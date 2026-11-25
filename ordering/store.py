from contextlib import closing, contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
MODES = {"xbloom", "manual", "grind_own"}


class ProductError(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


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


def _mode(value):
    if type(value) is not str or value not in MODES:
        raise ProductError(400, "制作模式必须是 xbloom/manual/grind_own")
    return value


def daily_menu(beans):
    """Stable daily rotation with roaster variety; selection is not taste evidence."""
    day = datetime.now(ZONE).date().isoformat()
    available = [b for b in beans if type(b.get("net_weight")) in (int, float)
                 and b["net_weight"] >= 15]
    available.sort(key=lambda b: hashlib.sha256(f"{day}:{b['id']}".encode()).hexdigest())
    selected, rest, roasters = [], [], set()
    for bean in available:
        if bean.get("roaster") not in roasters and len(selected) < 5:
            selected.append(bean)
            roasters.add(bean.get("roaster"))
        else:
            rest.append(bean)
    selected.extend(rest[:5-len(selected)])
    result = []
    for bean in selected:
        flavor = bean.get("source_flavor") or []
        if isinstance(flavor, str):
            flavor = [flavor]
        story = " · ".join(str(bean.get(k) or "") for k in
                           ("country", "process", "variety_name") if bean.get(k))
        result.append(dict(bean, story=story or "产地与处理信息待补充",
                           source_label="豆袋／库存资料", menu_reason="在库可供 · 当日轮换",
                           source_flavor=flavor))
    return result


class Store:
    """A local order book. Only the owner imports inventory or adds customer profiles."""
    def __init__(self, path):
        self.db_path = Path(path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.db_path)) as db:
            existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existing and "menu_beans" not in existing:
                raise ProductError(409, "请指定点单专用数据库或新文件")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS menu_beans (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, roaster TEXT NOT NULL,
                    country TEXT NOT NULL, process TEXT NOT NULL, variety_name TEXT NOT NULL,
                    source_flavor TEXT NOT NULL, source_notes TEXT NOT NULL, net_weight REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasters (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS product_preferences (
                    person_id INTEGER PRIMARY KEY REFERENCES tasters(id), preference_text TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS product_orders (
                    id INTEGER PRIMARY KEY, bean_id INTEGER NOT NULL REFERENCES menu_beans(id),
                    person_id INTEGER NOT NULL REFERENCES tasters(id), mode TEXT NOT NULL, note TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS product_requests (
                    request_id TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL);
            """)

    def state(self):
        with self._connection() as db:
            return {key: [dict(row) for row in db.execute(query)] for key,query in {
                "beans":"SELECT * FROM menu_beans ORDER BY roaster,name",
                "people":"SELECT * FROM tasters ORDER BY id",
                "preferences":"SELECT * FROM product_preferences",
                "orders":"SELECT * FROM product_orders WHERE status != 'deleted' ORDER BY id DESC"
            }.items()}

    def _bean(self, db, bean_id):
        row = db.execute("SELECT * FROM menu_beans WHERE id=?", (bean_id,)).fetchone()
        if row is None:
            raise ProductError(404,"豆子不存在")
        return dict(row)

    def _order(self, db, order_id):
        row = db.execute("SELECT * FROM product_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise ProductError(404,"订单不存在")
        return dict(row)

    def transition(self, order_id, data, action):
        transitions = {"accept": ({"ordered"}, "accepted"), "finish": ({"accepted"}, "fulfilled"),
                       "cancel": ({"ordered"}, "cancelled"), "delete": ({"ordered", "cancelled"}, "deleted")}
        allowed, target = transitions[action]
        _fields(data, {"request_id","expected"})
        def apply(db):
            order = self._checked_order(db, order_id, data["expected"])
            if order["status"] not in allowed:
                raise ProductError(409, "订单状态已变化，请刷新核对")
            db.execute("UPDATE product_orders SET status=? WHERE id=?", (target, order_id))
            return self._order(db,order_id)
        return self._write(f"order-{action}:{order_id}",data,apply)[0]

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

    def _person(self, db, person_id):
        if db.execute("SELECT 1 FROM tasters WHERE id=?", (person_id,)).fetchone() is None:
            raise ProductError(404, "品鉴人不存在")

    def _checked_order(self, db, order_id, expected):
        _fields(expected, {"bean_id", "person_id", "mode", "note", "status"})
        order = self._order(db, order_id)
        if any(order[key] != value for key, value in expected.items()):
            raise ProductError(409, "订单已变化，请保留修改内容并刷新核对")
        return order

    def _pending_order(self, db, bean_id, person_id, mode, exclude_id=None):
        row = db.execute("""SELECT id FROM product_orders
            WHERE bean_id=? AND person_id=? AND mode=?
              AND status IN ('ordered','accepted')
              AND (? IS NULL OR id != ?) ORDER BY id LIMIT 1""",
                         (bean_id, person_id, mode, exclude_id, exclude_id)).fetchone()
        return self._order(db, row["id"]) if row else None

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

    def update_order(self, order_id, data):
        _id(order_id, "order_id")
        _fields(data, {"request_id", "expected", "bean_id", "person_id", "mode", "note"})
        _id(data["bean_id"], "bean_id")
        _id(data["person_id"], "person_id")
        _mode(data["mode"])
        _text(data["note"], "note", empty=True)

        def action(db):
            order = self._checked_order(db, order_id, data["expected"])
            if order["status"] != "ordered":
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
