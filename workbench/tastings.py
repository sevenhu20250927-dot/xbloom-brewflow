"""Personal feedback on a shared brew, including the project's archived xBloom cups."""
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from schema import get_db_connection

ARCHIVES = Path(__file__).resolve().parent
SCORES = ("overall", "sweetness", "acidity", "aroma")


class TastingConflict(ValueError):
    pass


def cup_catalog(connection):
    cups = [dict(row) for row in connection.execute("""
        SELECT 'brew-' || r.id AS id, r.brew_date AS date, r.bean_id,
               COALESCE(b.bean_name, '原库存条目已移除') AS name
        FROM brew_records r LEFT JOIN beans b ON b.id = r.bean_id
        ORDER BY r.brew_date DESC, r.id DESC
    """)]
    for path in ARCHIVES.glob("BREW_RECORD_*.md"):
        match = re.fullmatch(r"BREW_RECORD_(\d{4}-\d{2}-\d{2})_([A-Z0-9_-]+)\.md", path.name)
        if match and path.is_file() and not path.is_symlink():
            with path.open(encoding="utf-8") as f:
                title = f.readline().strip().lstrip("# ").strip()
            cups.append({"id": path.stem, "date": match[1], "name": title, "archive": True})
    return sorted(cups, key=lambda c: c["date"], reverse=True)


def workspace():
    with get_db_connection() as db:
        return {"cups": cup_catalog(db),
                "inventory": [dict(r) for r in db.execute(
                    "SELECT id,bean_name AS name,net_weight FROM beans "
                    "WHERE net_weight IS NULL OR net_weight > 0 ORDER BY id DESC")],
                "people": [dict(r) for r in db.execute("SELECT id,name FROM tasters ORDER BY id")],
                "notes": [dict(r) | {"feedback": json.loads(r["feedback"])} for r in db.execute(
                    "SELECT person_id,cup,feedback,revision FROM personal_tastings ORDER BY rowid DESC")]}


def add_person(data):
    if not isinstance(data, dict) or set(data) != {"name"} or not isinstance(data["name"], str):
        raise ValueError("请输入品饮者姓名")
    name = unicodedata.normalize("NFKC", data["name"]).strip()
    if not 1 <= len(name) <= 40 or any(not c.isprintable() for c in name):
        raise ValueError("姓名需要 1 至 40 个可显示字符")
    with get_db_connection() as db:
        try:
            cursor = db.execute("INSERT INTO tasters(name) VALUES (?)", (name,))
        except sqlite3.IntegrityError as exc:
            raise TastingConflict("已有同名档案，请选择该档案或使用不同昵称") from exc
        return {"id": cursor.lastrowid, "name": name}


def save_feedback(data):
    if not isinstance(data, dict) or set(data) != {"person_id", "cup", "feedback", "revision"}:
        raise ValueError("反馈请求缺少或多出了字段")
    person, cup, rev, note = (data[k] for k in ("person_id", "cup", "revision", "feedback"))
    if type(person) is not int or not 0 < person < 2**63 or type(rev) is not int or rev < 0:
        raise ValueError("品饮者或记录版本无效")
    if not isinstance(cup, str) or not isinstance(note, dict) or set(note) - {*SCORES, "taste", "next"}:
        raise ValueError("冲煮或反馈字段无效")
    clean = {}
    for key, value in note.items():
        if key in SCORES:
            if type(value) not in (int, float) or not 0 <= value <= 10:
                raise ValueError("评分请填 0 到 10 之间的数字")
            clean[key] = value
        elif not isinstance(value, str) or len(value) > 2000:
            raise ValueError("品饮文字每项最多 2000 字")
        elif value.strip():
            clean[key] = value.strip()
    if not clean:
        raise ValueError("请至少填写一项评分或感受")
    with get_db_connection() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM tasters WHERE id=?", (person,)).fetchone():
            raise KeyError("品饮者不存在")
        if not any(item["id"] == cup for item in cup_catalog(db)):
            raise KeyError("冲煮记录不存在")
        old = db.execute("SELECT revision,feedback FROM personal_tastings WHERE person_id=? AND cup=?",
                         (person, cup)).fetchone()
        if old and json.loads(old["feedback"]) == clean:
            return {"revision": old["revision"]}
        if (old["revision"] if old else 0) != rev:
            raise TastingConflict("这条评价已在别处更新，请复制当前草稿后刷新核对")
        db.execute("""INSERT INTO personal_tastings(person_id,cup,feedback,revision) VALUES (?,?,?,?)
                      ON CONFLICT(person_id,cup) DO UPDATE SET feedback=excluded.feedback, revision=excluded.revision""",
                   (person, cup, json.dumps(clean, ensure_ascii=False), rev + 1))
        return {"revision": rev + 1}
