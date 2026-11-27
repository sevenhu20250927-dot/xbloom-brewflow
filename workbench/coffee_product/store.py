"""One existing SQLite authority; no device access or implicit database creation."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from xbloom_bridge.protocol import ProtocolError, parse_recipe
from xbloom_bridge.recording import recipe_digest


class ProductError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


MODES = {"xbloom", "manual", "grind_own"}
SCORES = {"overall", "sweetness", "acidity", "aroma"}


def _now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ProductError(400, "请求必须是有限数值组成的 JSON") from exc


def _fields(data, required, optional=()):
    if type(data) is not dict or set(data) - set(required) - set(optional) or set(required) - set(data):
        raise ProductError(400, "请求缺少字段或含未知字段")


def _text(value, name, *, empty=False, limit=4000):
    if type(value) is not str or len(value) > limit or (not empty and not value.strip()):
        raise ProductError(400, f"{name} 必须是{'可空' if empty else '非空'}文字（最多 {limit} 字）")
    return value


def _id(value, name="id"):
    if type(value) is not int or not 0 < value < 2**63:
        raise ProductError(400, f"{name} 必须是正整数")
    return value


def _number(value, name, maximum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum)
    except OverflowError:
        valid = False
    if not valid:
        raise ProductError(400, f"{name} 必须是范围内的非负有限数值")
    return value


def _mode(value):
    if type(value) is not str or value not in MODES:
        raise ProductError(400, "制作模式必须是 xbloom/manual/grind_own")
    return value


def _text_list(value, name):
    if type(value) is not list or len(value) > 100:
        raise ProductError(400, f"{name} 必须是文字列表")
    for item in value:
        _text(item, name)


def _observations(value):
    names = {"note", "screen_seconds", "beverage_g", "brewer", "grinder", "grind_setting"}
    _fields(value, (), names)
    for key, item in value.items():
        if item is None:
            continue
        if key in {"screen_seconds", "beverage_g"}:
            _number(item, key)
        elif key == "grind_setting" and type(item) in (int, float):
            _number(item, key)
        else:
            _text(item, key, empty=True)
    return value


class Store:
    def __init__(self, db_path, recipe_root=None):
        self.db_path = Path(db_path).expanduser().resolve()
        if not self.db_path.is_file():
            raise ProductError(503, "必须指定已有主数据库；不会创建备用库存")
        self.recipe_root = Path(recipe_root).resolve() if recipe_root is not None else None
        self.capture_owner = uuid.uuid4().hex

    @contextmanager
    def _connection(self, *, write=False, begin=True):
        connection = None
        try:
            connection = sqlite3.connect(self.db_path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                                         uri=True, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            if not write:
                connection.execute("PRAGMA query_only=ON")
            if begin:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ProductError(409, "关联或唯一性冲突；请刷新核对") from exc
        except sqlite3.OperationalError as exc:
            raise ProductError(503, "主数据库不可用、繁忙或尚未初始化工作台") from exc
        finally:
            if connection is not None:
                try:
                    if connection.in_transaction:
                        connection.rollback()
                finally:
                    connection.close()

    def connect(self):
        """Legacy HTTP operations retain control of BEGIN; all use this same file."""
        return self._connection(write=True, begin=False)

    def init_schema(self):
        """The caller backs up first. Only the new product tables are created."""
        statements = [
            """CREATE TABLE IF NOT EXISTS product_preferences (
                person_id INTEGER PRIMARY KEY REFERENCES tasters(id),
                preference_text TEXT NOT NULL, revision INTEGER NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS product_recipes (
                id INTEGER PRIMARY KEY, bean_id INTEGER NOT NULL REFERENCES beans(id),
                parent_id INTEGER REFERENCES product_recipes(id), mode TEXT NOT NULL,
                sha256 TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS product_orders (
                id INTEGER PRIMARY KEY, bean_id INTEGER NOT NULL REFERENCES beans(id),
                person_id INTEGER NOT NULL REFERENCES tasters(id), mode TEXT NOT NULL,
                note TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                recipe_id INTEGER REFERENCES product_recipes(id))""",
            """CREATE TABLE IF NOT EXISTS product_brews (
                brew_id INTEGER PRIMARY KEY REFERENCES brew_records(id),
                order_id INTEGER UNIQUE REFERENCES product_orders(id),
                recipe_id INTEGER NOT NULL REFERENCES product_recipes(id), mode TEXT NOT NULL,
                status TEXT NOT NULL, observations TEXT NOT NULL DEFAULT '{}',
                capture_owner TEXT, capture_state TEXT, start_request_id TEXT,
                journal TEXT, report TEXT, capture_error TEXT)""",
            """CREATE TABLE IF NOT EXISTS product_consumption (
                brew_id INTEGER PRIMARY KEY REFERENCES product_brews(brew_id),
                grams REAL NOT NULL CHECK(grams >= 0), confirmed_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS product_experiences (
                id INTEGER PRIMARY KEY, bean_id INTEGER NOT NULL REFERENCES beans(id),
                condition TEXT NOT NULL, action TEXT NOT NULL, expected TEXT NOT NULL,
                source_brew_id INTEGER NOT NULL REFERENCES brew_records(id),
                source_person_id INTEGER NOT NULL REFERENCES tasters(id),
                feedback_revision INTEGER NOT NULL, feedback_snapshot TEXT NOT NULL,
                notes TEXT NOT NULL, created_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS product_evaluations (
                id INTEGER PRIMARY KEY, experience_id INTEGER NOT NULL REFERENCES product_experiences(id),
                brew_id INTEGER NOT NULL REFERENCES brew_records(id),
                person_id INTEGER NOT NULL REFERENCES tasters(id), verdict TEXT NOT NULL,
                feedback_revision INTEGER NOT NULL, feedback_snapshot TEXT NOT NULL,
                notes TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(experience_id, brew_id, person_id))""",
            """CREATE TABLE IF NOT EXISTS product_requests (
                request_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                response TEXT NOT NULL, created_at TEXT NOT NULL)""",
        ]
        with self._connection(write=True) as db:
            existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"beans", "brew_records", "tasters", "personal_tastings"} <= existing:
                raise ProductError(409, "所选数据库不是具备库存、冲煮和品鉴表的现有主库")
            for statement in statements:
                db.execute(statement)

    def _write(self, scope, data, action):
        request_id = _text(data["request_id"], "request_id", limit=200)
        digest = hashlib.sha256(_json([scope, data]).encode()).hexdigest()
        with self._connection(write=True) as db:
            previous = db.execute("SELECT digest,response FROM product_requests WHERE request_id=?",
                                  (request_id,)).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise ProductError(409, "同一 request_id 已用于不同内容")
                return json.loads(previous["response"]), True
            result = action(db)
            db.execute("INSERT INTO product_requests(request_id,digest,response,created_at) VALUES (?,?,?,?)",
                       (request_id, digest, _json(result), _now()))
            return result, False

    def _bean(self, db, bean_id):
        row = db.execute("""SELECT id,bean_name AS name,roaster,country,process,variety_name,
            roast_date,storage_state,net_weight,total_weight,
            json_extract(import_json,'$.flavor') AS source_flavor,
            json_extract(import_json,'$.notes') AS source_notes,
            json_extract(import_json,'$.roastLevel') AS roast_level
            FROM beans WHERE id=?""", (bean_id,)).fetchone()
        if row is None:
            raise ProductError(404, "豆子不存在")
        bean = dict(row)
        bean["source_flavor"] = json.loads(bean["source_flavor"]) if bean["source_flavor"] else []
        return bean

    def get_bean(self, bean_id):
        _id(bean_id, "bean_id")
        with self._connection() as db:
            return self._bean(db, bean_id)

    def _recipe(self, db, recipe_id):
        row = db.execute("SELECT * FROM product_recipes WHERE id=?", (recipe_id,)).fetchone()
        if row is None:
            raise ProductError(404, "配方版本不存在")
        recipe = dict(row)
        recipe.update(json.loads(recipe.pop("document")))
        return recipe

    def get_recipe(self, recipe_id):
        _id(recipe_id, "recipe_id")
        with self._connection() as db:
            return self._recipe(db, recipe_id)

    def _order(self, db, order_id):
        row = db.execute("SELECT * FROM product_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise ProductError(404, "订单不存在")
        order = dict(row)
        if order["status"] == "running":
            capture = db.execute("SELECT capture_owner,capture_state FROM product_brews WHERE order_id=?", (order_id,)).fetchone()
            if capture and capture["capture_state"] == "running" and capture["capture_owner"] != self.capture_owner:
                order["status"] = "needs_review"
        return order

    def _brew(self, db, brew_id):
        row = db.execute("""SELECT r.id,r.bean_id,r.created_at,r.brew_date,r.data_json,
            p.order_id,p.recipe_id,p.mode,p.status,p.observations,
            p.capture_owner,p.capture_state,p.journal,p.report,p.capture_error,c.grams AS consumption_g
            FROM brew_records r LEFT JOIN product_brews p ON p.brew_id=r.id
            LEFT JOIN product_consumption c ON c.brew_id=r.id WHERE r.id=?""", (brew_id,)).fetchone()
        if row is None:
            raise ProductError(404, "冲煮记录不存在")
        brew = dict(row)
        original = json.loads(brew.pop("data_json") or "{}")
        if brew["recipe_id"] is None:
            brew["legacy_data"] = original
        owner = brew.pop("capture_owner")
        capture_state = brew.get("capture_state")
        if capture_state == "running" and owner != self.capture_owner:
            brew["capture_state"] = "needs_review"
            if brew["status"] == "running":
                brew["status"] = "needs_review"
        brew["observations"] = json.loads(brew["observations"]) if brew["observations"] else {}
        # Manual status never substitutes for a machine completion observation.
        brew["machine_completion"] = "unconfirmed" if capture_state else None
        return brew

    def get_brew(self, brew_id):
        _id(brew_id, "brew_id")
        with self._connection() as db:
            return self._brew(db, brew_id)

    def _experience(self, db, experience_id):
        row = db.execute("SELECT * FROM product_experiences WHERE id=?", (experience_id,)).fetchone()
        if row is None:
            raise ProductError(404, "经验候选不存在")
        experience = dict(row)
        experience["feedback_snapshot"] = json.loads(experience["feedback_snapshot"])
        experience["evaluations"] = [dict(item) for item in db.execute(
            "SELECT id,brew_id,person_id,verdict,notes,created_at,feedback_revision,feedback_snapshot FROM product_evaluations "
            "WHERE experience_id=? ORDER BY id", (experience_id,))]
        for evaluation in experience["evaluations"]:
            evaluation["feedback_snapshot"] = json.loads(evaluation["feedback_snapshot"])
        return experience

    def state(self):
        with self._connection() as db:
            return {
                "beans": [self._bean(db, r[0]) for r in db.execute("SELECT id FROM beans ORDER BY id DESC").fetchall()],
                "people": [dict(r) for r in db.execute("SELECT id,name FROM tasters ORDER BY id")],
                "preferences": [dict(r) for r in db.execute(
                    "SELECT person_id,preference_text,revision FROM product_preferences ORDER BY person_id")],
                "recipes": [self._recipe(db, r[0]) for r in db.execute("SELECT id FROM product_recipes ORDER BY id DESC").fetchall()],
                "orders": [self._order(db, r[0]) for r in db.execute("SELECT id FROM product_orders WHERE status != 'deleted' ORDER BY id DESC").fetchall()],
                "brews": [self._brew(db, r[0]) for r in db.execute("SELECT id FROM brew_records ORDER BY id DESC").fetchall()],
                "experiences": [self._experience(db, r[0]) for r in db.execute("SELECT id FROM product_experiences ORDER BY id DESC").fetchall()],
                "feedback": [dict(r) | {"feedback": json.loads(r["feedback"])} for r in db.execute(
                    "SELECT person_id,cup,feedback,revision FROM personal_tastings ORDER BY person_id,cup")],
                "capabilities": {"modes": sorted(MODES), "automatic_modes": ["xbloom"],
                                 "machine_completion_verified": False},
            }

    def save_preference(self, data):
        _fields(data, {"request_id", "person_id", "preference_text", "expected_revision"})
        _id(data["person_id"], "person_id")
        _text(data["preference_text"], "preference_text", empty=True)
        if type(data["expected_revision"]) is not int or not 0 <= data["expected_revision"] < 2**63 - 1:
            raise ProductError(400, "expected_revision 必须是非负整数")

        def action(db):
            self._person(db, data["person_id"])
            old = db.execute("SELECT revision FROM product_preferences WHERE person_id=?",
                             (data["person_id"],)).fetchone()
            if (old["revision"] if old else 0) != data["expected_revision"]:
                raise ProductError(409, "口味档案已更新，请保留输入并刷新核对")
            result = {"person_id": data["person_id"], "preference_text": data["preference_text"].strip(),
                      "revision": data["expected_revision"] + 1}
            db.execute("""INSERT INTO product_preferences(person_id,preference_text,revision) VALUES (?,?,?)
                ON CONFLICT(person_id) DO UPDATE SET preference_text=excluded.preference_text,revision=excluded.revision""",
                       (result["person_id"], result["preference_text"], result["revision"]))
            return result
        return self._write(f"preference:{data['person_id']}", data, action)[0]

    def create_recipe(self, data):
        _fields(data, {"request_id", "bean_id", "title", "mode", "goal", "payload", "rationale", "evidence", "risks"}, {"parent_id"})
        _id(data["bean_id"], "bean_id")
        if data.get("parent_id") is not None:
            _id(data["parent_id"], "parent_id")
        _mode(data["mode"])
        _text(data["title"], "title", limit=200)
        _text(data["goal"], "goal", empty=True)
        _text_list(data["rationale"], "rationale")
        _text_list(data["risks"], "risks")
        if type(data["evidence"]) is not list or len(data["evidence"]) > 100:
            raise ProductError(400, "evidence 必须是证据列表")
        for evidence in data["evidence"]:
            _fields(evidence, {"source", "title", "excerpt"})
            for key, value in evidence.items():
                _text(value, key, empty=key == "excerpt")
        try:
            payload = parse_recipe(_json(data["payload"]).encode())
        except ProtocolError as exc:
            raise ProductError(400, str(exc)) from exc
        document = {key: data[key] for key in ("title", "goal", "rationale", "evidence", "risks")}
        document["payload"] = payload

        def action(db):
            self._bean(db, data["bean_id"])
            if data.get("parent_id") is not None and self._recipe(db, data["parent_id"])["bean_id"] != data["bean_id"]:
                raise ProductError(409, "修方父版本必须属于同一豆子")
            cursor = db.execute("INSERT INTO product_recipes(bean_id,parent_id,mode,sha256,document,created_at) VALUES (?,?,?,?,?,?)",
                                (data["bean_id"], data.get("parent_id"), data["mode"], recipe_digest(payload), _json(document), _now()))
            return self._recipe(db, cursor.lastrowid)
        return self._write("recipe", data, action)[0]

    def create_order(self, data):
        _fields(data, {"request_id", "bean_id", "person_id", "mode", "note"})
        _id(data["bean_id"], "bean_id")
        _id(data["person_id"], "person_id")
        _mode(data["mode"])
        _text(data["note"], "note", empty=True)

        def action(db):
            bean = self._bean(db, data["bean_id"])
            if bean["net_weight"] is None or bean["net_weight"] < 15:
                raise ProductError(409, "余量不足一份 15g 或尚未确认，请刷新豆单或先核对库存")
            self._person(db, data["person_id"])
            existing = self._pending_order(db, data["bean_id"], data["person_id"], data["mode"])
            if existing:
                if existing["note"] != data["note"]:
                    raise ProductError(409, f"已有未完成订单 #{existing['id']}，请在订单中修改备注")
                return existing
            cursor = db.execute("INSERT INTO product_orders(bean_id,person_id,mode,note,status,created_at) VALUES (?,?,?,?,?,?)",
                                (data["bean_id"], data["person_id"], data["mode"], data["note"], "ordered", _now()))
            return self._order(db, cursor.lastrowid)
        return self._write("order", data, action)[0]

    def _pending_order(self, db, bean_id, person_id, mode, exclude_id=None):
        row = db.execute("""SELECT id FROM product_orders
            WHERE bean_id=? AND person_id=? AND mode=?
              AND status IN ('ordered','prepared','starting','running','needs_review','unconfirmed')
              AND (? IS NULL OR id != ?) ORDER BY id LIMIT 1""",
                         (bean_id, person_id, mode, exclude_id, exclude_id)).fetchone()
        return self._order(db, row["id"]) if row else None

    def _checked_order(self, db, order_id, expected):
        _fields(expected, {"bean_id", "person_id", "mode", "note", "status"})
        order = self._order(db, order_id)
        if any(order[key] != value for key, value in expected.items()):
            raise ProductError(409, "订单已变化，请保留修改内容并刷新核对")
        return order

    def update_order(self, order_id, data):
        _id(order_id, "order_id")
        _fields(data, {"request_id", "expected", "bean_id", "person_id", "mode", "note"})
        _id(data["bean_id"], "bean_id")
        _id(data["person_id"], "person_id")
        _mode(data["mode"])
        _text(data["note"], "note", empty=True)

        def action(db):
            order = self._checked_order(db, order_id, data["expected"])
            linked = db.execute("SELECT 1 FROM product_brews WHERE order_id=?", (order_id,)).fetchone()
            if order["status"] != "ordered" or linked:
                raise ProductError(409, "只能修改尚未建立制作记录的待制作订单")
            bean = self._bean(db, data["bean_id"])
            if bean["net_weight"] is None or bean["net_weight"] < 15:
                raise ProductError(409, "余量不足一份 15g 或尚未确认，请先核对库存")
            self._person(db, data["person_id"])
            existing = self._pending_order(db, data["bean_id"], data["person_id"], data["mode"], order_id)
            if existing:
                raise ProductError(409, f"相同豆子和制作方式已有未完成订单 #{existing['id']}")
            db.execute("UPDATE product_orders SET bean_id=?,person_id=?,mode=?,note=? WHERE id=?",
                       (data["bean_id"], data["person_id"], data["mode"], data["note"], order_id))
            return self._order(db, order_id)
        return self._write(f"order-update:{order_id}", data, action)[0]

    def cancel_order(self, order_id, data):
        _id(order_id, "order_id")
        _fields(data, {"request_id", "expected"})

        def action(db):
            order = self._checked_order(db, order_id, data["expected"])
            if order["status"] not in {"ordered", "prepared"}:
                raise ProductError(409, "只能取消尚未开始的订单；已执行的杯请核对并记录结果")
            brew = db.execute("""SELECT p.brew_id,p.status,p.capture_state,p.start_request_id,
                p.journal,p.report,p.observations,c.grams
                FROM product_brews p LEFT JOIN product_consumption c ON c.brew_id=p.brew_id
                WHERE p.order_id=?""", (order_id,)).fetchone()
            if brew:
                if (brew["status"] != "prepared" or any(brew[key] is not None for key in
                    ("capture_state", "start_request_id", "journal", "report", "grams"))
                        or json.loads(brew["observations"]) != {}):
                    raise ProductError(409, "本杯已有开始或执行记录，不能按未制作取消")
                db.execute("UPDATE product_brews SET status='cancelled' WHERE brew_id=?", (brew["brew_id"],))
            db.execute("UPDATE product_orders SET status='cancelled' WHERE id=?", (order_id,))
            return self._order(db, order_id)
        return self._write(f"order-cancel:{order_id}", data, action)[0]

    def delete_order(self, order_id, data):
        _id(order_id, "order_id")
        _fields(data, {"request_id", "expected"})

        def action(db):
            order = self._checked_order(db, order_id, data["expected"])
            linked = db.execute("SELECT 1 FROM product_brews WHERE order_id=?", (order_id,)).fetchone()
            if order["status"] not in {"ordered", "cancelled"} or linked:
                raise ProductError(409, "已有制作记录的订单不能删除；尚未开始时可取消并保留关联")
            # Keep its identity for saved request receipts; SQLite must not reuse it.
            db.execute("UPDATE product_orders SET status='deleted' WHERE id=?", (order_id,))
            return self._order(db, order_id)
        return self._write(f"order-delete:{order_id}", data, action)[0]

    def create_brew(self, data):
        _fields(data, {"request_id", "bean_id", "recipe_id", "mode"}, {"order_id"})
        _id(data["bean_id"], "bean_id")
        _id(data["recipe_id"], "recipe_id")
        if data.get("order_id") is not None:
            _id(data["order_id"], "order_id")
        _mode(data["mode"])

        def action(db):
            bean = self._bean(db, data["bean_id"])
            recipe = self._recipe(db, data["recipe_id"])
            if recipe["bean_id"] != data["bean_id"] or recipe["mode"] != data["mode"]:
                raise ProductError(409, "配方的豆子或制作模式不一致")
            if data.get("order_id") is not None:
                order = self._order(db, data["order_id"])
                if order["bean_id"] != data["bean_id"] or order["mode"] != data["mode"]:
                    raise ProductError(409, "订单的豆子或制作模式不一致")
                if order["status"] != "ordered":
                    raise ProductError(409, "此订单已有制作记录")
            payload, now = recipe["payload"], _now()
            detail = {"bean_context": {}, "technique": {
                "dose": payload["doseGrams"], "ratio": payload["recipe"]["grandWater"] / payload["doseGrams"],
                "water_temperature": payload["recipe"]["pours"][0]["temperature"],
                "grind_size": payload["recipe"]["grinderSize"]}, "tasting": {}, "improvement": {},
                "recipe_snapshot": {"id": recipe["id"], "sha256": recipe["sha256"], "payload": payload}}
            cursor = db.execute("INSERT INTO brew_records(bean_id,brew_date,data_json,created_at,updated_at) VALUES (?,?,?,?,?)",
                                (bean["id"], now[:10], _json(detail), now, now))
            brew_id = cursor.lastrowid
            db.execute("INSERT INTO product_brews(brew_id,order_id,recipe_id,mode,status) VALUES (?,?,?,?,?)",
                       (brew_id, data.get("order_id"), recipe["id"], data["mode"], "prepared"))
            if data.get("order_id") is not None:
                db.execute("UPDATE product_orders SET status='prepared',recipe_id=? WHERE id=?",
                           (recipe["id"], data["order_id"]))
            return self._brew(db, brew_id)
        return self._write("brew", data, action)[0]

    def record_brew(self, brew_id, data):
        _id(brew_id, "brew_id")
        _fields(data, {"request_id", "status"}, {"observations", "consumption_g"})
        if type(data["status"]) is not str or data["status"] not in {"completed", "failed", "unconfirmed"}:
            raise ProductError(400, "人工结果必须是 completed/failed/unconfirmed")
        if "observations" in data:
            _observations(data["observations"])
        if data.get("consumption_g") is not None:
            _number(data["consumption_g"], "consumption_g")

        def action(db):
            brew = self._brew(db, brew_id)
            if brew["recipe_id"] is None:
                raise ProductError(409, "历史杯只能填写品鉴，不能通过新工作台补扣耗豆")
            if brew["status"] == "cancelled":
                raise ProductError(409, "本杯已取消，不能记录制作结果或扣豆；请另建订单")
            if brew["capture_state"] == "running":
                raise ProductError(409, "本杯仍在采集执行中，先核对机器与采集状态，再记录结果或扣量")
            observations = data.get("observations", brew["observations"])
            grams = data.get("consumption_g")
            if (grams is None and data["status"] == "completed" and brew["status"] != "completed"
                    and brew["consumption_g"] is None):
                grams = self._recipe(db, brew["recipe_id"])["payload"]["doseGrams"]
            if grams is not None:
                old = db.execute("SELECT grams FROM product_consumption WHERE brew_id=?", (brew_id,)).fetchone()
                if old and Decimal(str(old["grams"])) != Decimal(str(grams)):
                    raise ProductError(409, "此杯耗豆已确认，改量需单独人工补正")
                if old is None:
                    row = db.execute("SELECT net_weight,price_total FROM beans WHERE id=?", (brew["bean_id"],)).fetchone()
                    if row["net_weight"] is None:
                        raise ProductError(409, "库存余量未知，不能确认扣量")
                    balance = Decimal(str(row["net_weight"])) - Decimal(str(grams))
                    if balance < 0:
                        raise ProductError(409, "库存余量不足，不会夹断或扣成负数")
                    price = row["price_total"]
                    if price is not None:
                        price = round(price * float(balance) / row["net_weight"], 2) if row["net_weight"] else 0
                    db.execute("UPDATE beans SET net_weight=?,price_total=? WHERE id=?",
                               (float(balance), price, brew["bean_id"]))
                    db.execute("INSERT INTO product_consumption(brew_id,grams,confirmed_at) VALUES (?,?,?)", (brew_id, grams, _now()))
            db.execute("UPDATE product_brews SET status=?,observations=? WHERE brew_id=?",
                       (data["status"], _json(observations), brew_id))
            if brew["order_id"] is not None:
                db.execute("UPDATE product_orders SET status=? WHERE id=?", (data["status"], brew["order_id"]))
            row = db.execute("SELECT data_json FROM brew_records WHERE id=?", (brew_id,)).fetchone()
            detail = json.loads(row["data_json"])
            technique = detail.setdefault("technique", {})
            mapping = {"screen_seconds": "total_time", "beverage_g": "yield", "grinder": "grinder",
                       "grind_setting": "grind_size", "note": "extraction_notes"}
            for key, target in mapping.items():
                if key in data.get("observations", {}):
                    technique[target] = observations[key]
            db.execute("UPDATE brew_records SET data_json=?,updated_at=? WHERE id=?", (_json(detail), _now(), brew_id))
            return self._brew(db, brew_id)
        return self._write(f"record:{brew_id}", data, action)[0]

    def _person(self, db, person_id):
        if db.execute("SELECT 1 FROM tasters WHERE id=?", (person_id,)).fetchone() is None:
            raise ProductError(404, "品鉴人不存在")

    def save_feedback(self, data):
        _fields(data, {"person_id", "cup", "feedback", "revision"})
        _id(data["person_id"], "person_id")
        if type(data["cup"]) is not str or not re.fullmatch(r"brew-[1-9][0-9]{0,18}", data["cup"]):
            raise ProductError(400, "cup 必须引用 brew-N")
        brew_id = _id(int(data["cup"][5:]), "brew_id")
        if type(data["revision"]) is not int or not 0 <= data["revision"] < 2**63 - 1:
            raise ProductError(400, "revision 必须是非负整数")
        _fields(data["feedback"], (), SCORES | {"taste", "next"})
        clean = {}
        for key, value in data["feedback"].items():
            if key in SCORES:
                clean[key] = _number(value, key, 10)
            else:
                _text(value, key, empty=True, limit=2000)
                if value.strip():
                    clean[key] = value.strip()
        if not clean:
            raise ProductError(400, "请至少填写一项评分或原话")
        with self._connection(write=True) as db:
            self._person(db, data["person_id"])
            self._brew(db, brew_id)
            old = db.execute("SELECT feedback,revision FROM personal_tastings WHERE person_id=? AND cup=?",
                             (data["person_id"], data["cup"])).fetchone()
            if old and json.loads(old["feedback"]) == clean:
                return {"person_id": data["person_id"], "cup": data["cup"], "feedback": clean, "revision": old["revision"]}
            if (old["revision"] if old else 0) != data["revision"]:
                raise ProductError(409, "这条评价已更新，请保留草稿并刷新核对")
            revision = data["revision"] + 1
            db.execute("""INSERT INTO personal_tastings(person_id,cup,feedback,revision) VALUES (?,?,?,?)
                ON CONFLICT(person_id,cup) DO UPDATE SET feedback=excluded.feedback,revision=excluded.revision""",
                       (data["person_id"], data["cup"], _json(clean), revision))
            return {"person_id": data["person_id"], "cup": data["cup"], "feedback": clean, "revision": revision}

    def _feedback_evidence(self, db, bean_id, brew_id, person_id):
        brew = self._brew(db, brew_id)
        if brew["bean_id"] != bean_id:
            raise ProductError(409, "经验引用必须属于同一豆子")
        self._person(db, person_id)
        row = db.execute("SELECT feedback,revision FROM personal_tastings WHERE person_id=? AND cup=?",
                         (person_id, f"brew-{brew_id}")).fetchone()
        if row is None or not json.loads(row["feedback"]):
            raise ProductError(409, "此人在所引杯次没有反馈，不能生成经验结论")
        return row["revision"], row["feedback"]

    def create_experience(self, data):
        _fields(data, {"request_id", "bean_id", "condition", "action", "expected", "source_brew_id", "source_person_id", "notes"})
        for key in ("bean_id", "source_brew_id", "source_person_id"):
            _id(data[key], key)
        for key in ("condition", "action", "expected", "notes"):
            _text(data[key], key, empty=key == "notes")

        def action(db):
            revision, snapshot = self._feedback_evidence(db, data["bean_id"], data["source_brew_id"], data["source_person_id"])
            cursor = db.execute("""INSERT INTO product_experiences
                (bean_id,condition,action,expected,source_brew_id,source_person_id,notes,created_at,feedback_revision,feedback_snapshot)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", tuple(data[key] for key in (
                    "bean_id", "condition", "action", "expected", "source_brew_id", "source_person_id", "notes")) + (_now(), revision, snapshot))
            return self._experience(db, cursor.lastrowid)
        return self._write("experience", data, action)[0]

    def evaluate_experience(self, experience_id, data):
        _id(experience_id, "experience_id")
        _fields(data, {"request_id", "brew_id", "person_id", "verdict", "notes"})
        _id(data["brew_id"], "brew_id")
        _id(data["person_id"], "person_id")
        if type(data["verdict"]) is not str or data["verdict"] not in {"support", "counterexample", "insufficient"}:
            raise ProductError(400, "verdict 必须是 support/counterexample/insufficient")
        _text(data["notes"], "notes", empty=True)

        def action(db):
            experience = self._experience(db, experience_id)
            if data["brew_id"] == experience["source_brew_id"]:
                raise ProductError(409, "后续观察不能重复使用经验来源杯")
            revision, snapshot = self._feedback_evidence(db, experience["bean_id"], data["brew_id"], data["person_id"])
            db.execute("""INSERT INTO product_evaluations(experience_id,brew_id,person_id,verdict,notes,created_at,feedback_revision,feedback_snapshot)
                VALUES (?,?,?,?,?,?,?,?)""", (experience_id, data["brew_id"], data["person_id"], data["verdict"], data["notes"], _now(), revision, snapshot))
            return self._experience(db, experience_id)
        return self._write(f"evaluate:{experience_id}", data, action)[0]

    def claim_start(self, brew_id, data, *, retry_proof=None):
        _id(brew_id, "brew_id")
        _fields(data, {"request_id", "reviewed_sha256", "confirm_start", "address", "brewer"}, {"retry_of"})
        if data["confirm_start"] is not True:
            raise ProductError(400, "本杯必须明确授权开始")
        if type(data["reviewed_sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", data["reviewed_sha256"]):
            raise ProductError(400, "需要审核配方的 sha256")
        _text(data["address"], "address", limit=200)
        _text(data["brewer"], "brewer", limit=200)

        def action(db):
            brew = self._brew(db, brew_id)
            if brew["mode"] != "xbloom" or brew["recipe_id"] is None:
                raise ProductError(409, "自动执行首版仅支持全机器磨冲")
            if "retry_of" in data:
                if (brew["status"] != "needs_review" or brew["capture_state"] != "finished"
                        or not brew["journal"] or brew["consumption_g"] is not None or not retry_proof
                        or data["retry_of"] != Path(brew["journal"]).name
                        or data["retry_of"] != retry_proof["token"]
                        or any(data[k] != retry_proof[k] for k in ("reviewed_sha256", "address", "brewer"))):
                    raise ProductError(409, "这次失败已处理，或日志无法确认启动前失败。请同步当杯记录。")
            elif brew["status"] != "prepared" or brew["capture_state"] is not None:
                raise ProductError(409, "此杯已记录或已尝试开始，不会重新派发")
            pending = db.execute("""SELECT brew_id FROM product_brews
                WHERE brew_id<>? AND capture_state IS NOT NULL AND status IN ('running','needs_review') LIMIT 1""",
                (brew_id,)).fetchone()
            if pending:
                raise ProductError(409, f"第 {pending['brew_id']} 杯执行仍待人工核对，不能派发另一杯")
            recipe = self._recipe(db, brew["recipe_id"])
            if recipe["sha256"] != data["reviewed_sha256"]:
                raise ProductError(409, "审核摘要与本杯配方不一致")
            db.execute("""UPDATE product_brews SET status='running',capture_state='running',
                capture_owner=?,start_request_id=?,journal=NULL,report=NULL,capture_error=NULL WHERE brew_id=?""",
                       (self.capture_owner, data["request_id"], brew_id))
            if brew["order_id"] is not None:
                db.execute("UPDATE product_orders SET status='running' WHERE id=?", (brew["order_id"],))
            return {"dispatch": True, "brew": self._brew(db, brew_id)}
        result, replayed = self._write(f"start:{brew_id}", data, action)
        if replayed:
            return {"dispatch": False, "brew": self.get_brew(brew_id)}
        return result

    def finish_capture(self, brew_id, journal, report, error=None):
        """Attach evidence after capture, never assert machine completion or debit beans."""
        _id(brew_id, "brew_id")
        for name, value in (("journal", journal), ("report", report), ("error", error)):
            if value is not None:
                _text(value, name, empty=True, limit=16000)
        with self._connection(write=True) as db:
            brew = self._brew(db, brew_id)
            row = db.execute("SELECT capture_owner,capture_state FROM product_brews WHERE brew_id=?", (brew_id,)).fetchone()
            if row is None or row["capture_state"] is None:
                raise ProductError(409, "本杯没有开始意图，不能附加执行完成回执")
            if row["capture_state"] == "finished":
                if (brew["journal"], brew["report"], brew["capture_error"]) != (journal, report, error):
                    raise ProductError(409, "执行证据已保存，不能覆盖")
                return brew
            if row["capture_owner"] != self.capture_owner:
                raise ProductError(409, "这是上次进程的执行，需人工核对，不能冒充当前回执")
            status = "needs_review" if brew["status"] == "running" else brew["status"]
            db.execute("""UPDATE product_brews SET capture_state='finished',status=?,journal=?,report=?,capture_error=?
                WHERE brew_id=?""", (status, journal, report, error, brew_id))
            if brew["order_id"] is not None:
                db.execute("UPDATE product_orders SET status=? WHERE id=?", (status, brew["order_id"]))
            return self._brew(db, brew_id)
