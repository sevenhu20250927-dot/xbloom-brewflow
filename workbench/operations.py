import json
import random
from datetime import date, datetime

from schema import get_db_connection


def validate_date(value, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD") from exc
    if parsed > date.today():
        raise ValueError(f"{field_name} 不能晚于今天")
    return parsed.isoformat()


def normalize_optional_date(value, field_name):
    text = str(value or "").strip()
    if not text:
        return None
    return validate_date(text, field_name)


def parse_time_to_seconds(value, field_name="时间"):
    """Parse seconds or mm:ss text into integer seconds."""
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) != 2:
            raise ValueError(f"{field_name} 必须是 mm:ss 或秒数")
        try:
            minutes = int(parts[0])
            seconds = int(parts[1])
        except ValueError as exc:
            raise ValueError(f"{field_name} 必须是 mm:ss 或秒数") from exc
        if minutes < 0 or seconds < 0 or seconds >= 60:
            raise ValueError(f"{field_name} 必须是合法 mm:ss")
        return minutes * 60 + seconds
    try:
        seconds = int(float(text))
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是 mm:ss 或秒数") from exc
    if seconds < 0:
        raise ValueError(f"{field_name} 不能小于 0")
    return seconds


def format_seconds(value):
    if value is None:
        return None
    seconds = int(value)
    return f"{seconds // 60}:{seconds % 60:02d}"


def validate_existing_bean_id(value):
    try:
        bean_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("咖啡豆不能为空") from exc
    with get_db_connection() as connection:
        row = connection.execute("SELECT id FROM beans WHERE id = ?", (bean_id,)).fetchone()
    if row is None:
        raise ValueError("咖啡豆不存在")
    return bean_id


def build_freshness(roast_date_text):
    if not roast_date_text:
        return {"resting_days": None, "label": "烘焙日待补", "hint": "未提供完整日期", "tone": ""}
    roast_day = datetime.strptime(roast_date_text, "%Y-%m-%d").date()
    resting_days = (date.today() - roast_day).days

    if resting_days < 10:
        return {
            "resting_days": resting_days,
            "label": "继续养豆",
            "hint": "继续养豆",
            "tone": "tone-early",
        }
    if resting_days < 20:
        return {
            "resting_days": resting_days,
            "label": "黄金赏味期",
            "hint": "黄金赏味期",
            "tone": "tone-golden",
        }
    if resting_days < 30:
        return {
            "resting_days": resting_days,
            "label": "抓紧喝或冷冻",
            "hint": "抓紧喝掉或者冷冻",
            "tone": "tone-brown",
        }
    if resting_days < 60:
        return {
            "resting_days": resting_days,
            "label": "过期",
            "hint": "过期",
            "tone": "tone-expired",
        }
    return {
        "resting_days": resting_days,
        "label": "扔掉",
        "hint": "扔掉",
        "tone": "tone-discard",
    }


def row_to_payload(row):
    net_weight = row["net_weight"]
    price_total = row["price_total"]
    cups = None if net_weight is None else net_weight // 15
    price_per_gram = None
    if net_weight is not None and price_total is not None:
        price_per_gram = round(price_total / net_weight, 2) if net_weight else 0
    roast_date = row["roast_date"]
    freshness = build_freshness(roast_date)
    return {
        "id": row["id"],
        "name": row["bean_name"],
        "bean_name": row["bean_name"],
        "roaster": row["roaster"],
        "country": row["country"],
        "region": row["region"],
        "producer": row["producer"],
        "lot_info": row["lot_info"],
        "variety_name": row["variety_name"],
        "roaster_recommendation": row["roaster_recommendation"],
        "roast_date": roast_date,
        "storage_state": row["storage_state"],
        "process": row["process"],
        "net_weight": net_weight,
        "total_weight": row["total_weight"],
        "cups": cups,
        "price_total": price_total,
        "source_notes": row["source_notes"],
        "source_flavor": json.loads(row["source_flavor"] or "[]"),
        "price_per_gram": price_per_gram,
        "resting_days": freshness["resting_days"],
        "freshness_label": freshness["label"],
        "freshness_hint": freshness["hint"],
        "freshness_tone": freshness["tone"],
        "created_at": row["created_at"],
    }


def fetch_inventory():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                bean_name,
                roaster,
                COALESCE(NULLIF(TRIM(country), ''), origin) AS country,
                region,
                COALESCE(NULLIF(TRIM(producer), ''), estate) AS producer,
                COALESCE(
                    NULLIF(TRIM(lot_info), ''),
                    TRIM(
                        CASE
                            WHEN TRIM(COALESCE(plot, '')) <> '' AND TRIM(COALESCE(batch, '')) <> ''
                                THEN plot || ' / ' || batch
                            WHEN TRIM(COALESCE(plot, '')) <> ''
                                THEN plot
                            ELSE batch
                        END
                    )
                ) AS lot_info,
                variety_name,
                roaster_recommendation,
                roast_date,
                storage_state,
                process,
                net_weight, total_weight, price_total, created_at,
                json_extract(import_json,'$.notes') AS source_notes,
                json_extract(import_json,'$.flavor') AS source_flavor
            FROM beans
            """
        ).fetchall()

    items = [row_to_payload(row) for row in rows]
    items.sort(
        key=lambda item: (
            -(item["price_per_gram"] or 0),
            -(item["resting_days"] or 0),
            -item["id"],
        )
    )
    summary = {
        "total_net_weight": sum(item["net_weight"] or 0 for item in items),
        "total_cups": sum(item["cups"] or 0 for item in items),
        "recommendation": None,
    }
    golden_items = [
        item for item in items if item["resting_days"] is not None and 10 <= item["resting_days"] < 20 and (item["net_weight"] or 0) > 0
    ]
    if golden_items:
        recommended = random.choice(golden_items)
        summary["recommendation"] = {
            "name": recommended["name"],
            "producer": recommended["producer"],
            "cups": recommended["cups"],
            "resting_days": recommended["resting_days"],
            "price_per_gram": recommended["price_per_gram"],
        }
    return {"items": items, "summary": summary}


def validate_text(value, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


def normalize_optional_text(value):
    return str(value or "").strip()


def validate_int(value, field_name):
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc
    if number < 0:
        raise ValueError(f"{field_name} 不能小于 0")
    return number


def validate_float(value, field_name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须是数字") from exc
    if number < 0:
        raise ValueError(f"{field_name} 不能小于 0")
    return round(number, 2)


def validate_positive_float(value, field_name):
    number = validate_float(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return number


def normalize_optional_float(value):
    if value is None or str(value).strip() == "":
        return None
    return validate_float(value, "数值")


def normalize_optional_int(value):
    if value is None or str(value).strip() == "":
        return None
    return validate_int(value, "数值")


def normalize_optional_time(value, field_name):
    return parse_time_to_seconds(value, field_name)


def normalize_optional_score(value, field_name):
    if value is None or str(value).strip() == "":
        return None
    score = validate_int(value, field_name)
    if score < 1 or score > 5:
        raise ValueError(f"{field_name} 必须是 1-5 分")
    return score


def clean_number(value):
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else round(number, 2)


def normalize_item_payload(payload, *, partial_label=False):
    def label_text(value, field_name):
        return normalize_optional_text(value) if partial_label else validate_text(value, field_name)

    def optional(parser, key, label):
        if partial_label and payload.get(key) in ("", None):
            return None
        return parser(payload.get(key), label)
    total_weight = payload.get("total_weight")
    if total_weight not in (None, ""):
        if (isinstance(total_weight, bool) or
                not str(total_weight).isascii() or not str(total_weight).isdecimal()):
            raise ValueError("总克数必须是非负整数")
        total_weight = int(total_weight)
        if total_weight >= 2**63:
            raise ValueError("总克数超出可保存范围")
    else:
        total_weight = None
    item = {
        "name": validate_text(payload.get("name") or payload.get("bean_name"), "名称"),
        "roaster": label_text(payload.get("roaster"), "烘焙商"),
        "country": label_text(payload.get("country"), "国家"),
        "region": normalize_optional_text(payload.get("region")),
        "producer": label_text(payload.get("producer") or payload.get("estate"), "庄园/生产者"),
        "lot_info": normalize_optional_text(payload.get("lot_info")),
        "variety_name": normalize_optional_text(payload.get("variety_name")),
        "roaster_recommendation": normalize_optional_text(payload.get("roaster_recommendation")),
        "roast_date": optional(validate_date, "roast_date", "烘焙日期") or "",
        "storage_state": validate_text(payload.get("storage_state") or "常温", "保存状态"),
        "process": label_text(payload.get("process"), "处理法"),
        "net_weight": optional(validate_int, "net_weight", "净含量"),
        "total_weight": total_weight,
        "price_total": optional(validate_float, "price_total", "总价格"),
    }
    if item["net_weight"] is not None and total_weight is not None and item["net_weight"] > total_weight:
        raise ValueError("剩余克数不能超过总克数")
    return item


def create_item(payload):
    item = normalize_item_payload(payload)
    created_at = datetime.now().isoformat(timespec="seconds")

    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO beans (
                bean_name, roaster, origin, estate, country, region, producer, lot_info, variety_name, roaster_recommendation, roast_date, storage_state, process, plot, batch,
                net_weight, total_weight, price_total, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                item["roaster"],
                item["country"],
                item["producer"],
                item["country"],
                item["region"],
                item["producer"],
                item["lot_info"],
                item["variety_name"],
                item["roaster_recommendation"],
                item["roast_date"],
                item["storage_state"],
                item["process"],
                "",
                "",
                item["net_weight"],
                item["total_weight"],
                item["price_total"],
                created_at,
            ),
        )
        connection.commit()
        item_id = cursor.lastrowid

    return get_item(item_id)


def get_item(item_id):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                bean_name,
                roaster,
                COALESCE(NULLIF(TRIM(country), ''), origin) AS country,
                region,
                COALESCE(NULLIF(TRIM(producer), ''), estate) AS producer,
                COALESCE(
                    NULLIF(TRIM(lot_info), ''),
                    TRIM(
                        CASE
                            WHEN TRIM(COALESCE(plot, '')) <> '' AND TRIM(COALESCE(batch, '')) <> ''
                                THEN plot || ' / ' || batch
                            WHEN TRIM(COALESCE(plot, '')) <> ''
                                THEN plot
                            ELSE batch
                        END
                    )
                ) AS lot_info,
                variety_name,
                roaster_recommendation,
                roast_date,
                storage_state,
                process,
                net_weight, total_weight, price_total, created_at,
                json_extract(import_json,'$.notes') AS source_notes,
                json_extract(import_json,'$.flavor') AS source_flavor
            FROM beans
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
    if row is None:
        raise KeyError("记录不存在")
    return row_to_payload(row)


def update_item(item_id, payload):
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT import_json IS NOT NULL AS imported,total_weight FROM beans WHERE id=?", (item_id,)).fetchone()
        if not existing:
            raise KeyError("记录不存在")
        item = normalize_item_payload({"total_weight": existing["total_weight"], **payload}, partial_label=bool(existing["imported"]))
        cursor = connection.execute(
            """
            UPDATE beans
            SET bean_name = ?, roaster = ?, origin = ?, estate = ?, country = ?, region = ?,
                producer = ?, lot_info = ?, variety_name = ?, roaster_recommendation = ?, roast_date = ?, storage_state = ?, process = ?,
                plot = ?, batch = ?, net_weight = ?, total_weight = ?, price_total = ?
            WHERE id = ?
            """,
            (
                item["name"],
                item["roaster"],
                item["country"],
                item["producer"],
                item["country"],
                item["region"],
                item["producer"],
                item["lot_info"],
                item["variety_name"],
                item["roaster_recommendation"],
                item["roast_date"],
                item["storage_state"],
                item["process"],
                "",
                "",
                item["net_weight"],
                item["total_weight"],
                item["price_total"],
                item_id,
            ),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("记录不存在")
    return get_item(item_id)


def adjust_item(item_id, delta_weight, delta_price):
    delta_weight = validate_int(delta_weight, "净含量变动")
    delta_price = validate_float(delta_price, "价格变动")

    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT net_weight, total_weight, price_total FROM beans WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise KeyError("记录不存在")

        if row["net_weight"] is None:
            raise ValueError("请先补录当前余量")
        new_weight = row["net_weight"] + delta_weight
        new_total = None if row["total_weight"] is None else row["total_weight"] + delta_weight
        new_price = None if row["price_total"] is None else round(row["price_total"] + delta_price, 2)
        connection.execute(
            "UPDATE beans SET net_weight = ?, total_weight = ?, price_total = ? WHERE id = ?",
            (new_weight, new_total, new_price, item_id),
        )
        connection.commit()

    return get_item(item_id)


def deduct_item(item_id, delta_weight, delta_price):
    delta_weight = validate_int(delta_weight, "净含量变动")

    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT net_weight, price_total FROM beans WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise KeyError("记录不存在")

        current_weight = row["net_weight"]
        if current_weight is None:
            raise ValueError("请先补录当前余量")
        new_weight = current_weight - delta_weight
        if new_weight < 0:
            raise ValueError("减少后净含量不能小于 0")
        price = row["price_total"]
        new_price = None if price is None or not current_weight else round(price * new_weight / current_weight, 2)
        if new_weight == 0:
            new_price = 0

        connection.execute(
            "UPDATE beans SET net_weight = ?, price_total = ? WHERE id = ?",
            (new_weight, new_price, item_id),
        )
        connection.commit()

    return get_item(item_id)


def delete_item(item_id):
    with get_db_connection() as connection:
        cursor = connection.execute("DELETE FROM beans WHERE id = ?", (item_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("记录不存在")


def row_to_green_payload(row):
    total_weight = clean_number(row["total_weight"])
    variety_label = "" if row["name"] else (row["bean_type"] or row["variety_name"])
    title_parts = [
        row["name"],
        row["crop_season"] if not row["name"] else "",
        row["region"] if not row["name"] else "",
        row["estate"] if not row["name"] else "",
        variety_label,
    ]
    display_name = " · ".join(part for part in title_parts if str(part or "").strip())
    return {
        "id": row["id"],
        "name": row["name"],
        "origin": row["origin"],
        "crop_season": row["crop_season"],
        "region": row["region"],
        "bean_type": row["bean_type"],
        "estate": row["estate"],
        "variety_name": row["variety_name"],
        "plot": row["plot"],
        "batch": row["batch"],
        "flavor_notes": row["flavor_notes"],
        "supplier": row["supplier"],
        "process": row["process"],
        "moisture_pct": clean_number(row["moisture_pct"]),
        "density": clean_number(row["density"]),
        "purchase_weight_g": clean_number(row["purchase_weight_g"]),
        "remaining_green_weight_g": clean_number(row["remaining_green_weight_g"]),
        "notes": row["notes"],
        "total_weight": total_weight,
        "display_name": display_name or f"生豆 #{row['id']}",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_green_inventory():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                name,
                origin,
                crop_season,
                region,
                bean_type,
                estate,
                variety_name,
                plot,
                batch,
                flavor_notes,
                supplier,
                process,
                moisture_pct,
                density,
                purchase_weight_g,
                remaining_green_weight_g,
                notes,
                total_weight,
                created_at,
                updated_at
            FROM green_beans
            ORDER BY total_weight DESC, id DESC
            """
        ).fetchall()
    items = [row_to_green_payload(row) for row in rows]
    return {
        "items": items,
        "summary": {
            "total_weight": sum(item["total_weight"] for item in items),
            "active_count": sum(1 for item in items if item["total_weight"] > 0),
        },
    }


def normalize_green_payload(payload):
    total_weight = validate_int(payload.get("total_weight"), "总量")
    name = normalize_optional_text(payload.get("name"))
    origin = normalize_optional_text(payload.get("origin"))
    region = normalize_optional_text(payload.get("region"))
    estate = normalize_optional_text(payload.get("estate"))
    bean_type = normalize_optional_text(payload.get("bean_type"))
    variety_name = normalize_optional_text(payload.get("variety_name"))
    if not name:
        name = " · ".join(part for part in (
            normalize_optional_text(payload.get("crop_season")),
            region,
            estate,
            variety_name or bean_type,
        ) if part) or "未命名生豆批次"
    if not origin:
        origin = " / ".join(part for part in (region, estate) if part)
    return {
        "name": name,
        "origin": origin,
        "crop_season": normalize_optional_text(payload.get("crop_season")),
        "region": region,
        "bean_type": bean_type,
        "estate": estate,
        "variety_name": variety_name,
        "plot": normalize_optional_text(payload.get("plot")),
        "batch": normalize_optional_text(payload.get("batch")),
        "flavor_notes": normalize_optional_text(payload.get("flavor_notes")),
        "supplier": normalize_optional_text(payload.get("supplier")),
        "process": normalize_optional_text(payload.get("process")),
        "moisture_pct": normalize_optional_float(payload.get("moisture_pct")),
        "density": normalize_optional_float(payload.get("density")),
        "purchase_weight_g": normalize_optional_float(payload.get("purchase_weight_g")),
        "remaining_green_weight_g": normalize_optional_float(payload.get("remaining_green_weight_g")) if payload.get("remaining_green_weight_g") not in (None, "") else total_weight,
        "notes": normalize_optional_text(payload.get("notes")),
        "total_weight": total_weight,
    }


def get_green_item(item_id):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                id,
                name,
                origin,
                crop_season,
                region,
                bean_type,
                estate,
                variety_name,
                plot,
                batch,
                flavor_notes,
                supplier,
                process,
                moisture_pct,
                density,
                purchase_weight_g,
                remaining_green_weight_g,
                notes,
                total_weight,
                created_at,
                updated_at
            FROM green_beans
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
    if row is None:
        raise KeyError("生豆记录不存在")
    return row_to_green_payload(row)


def create_green_item(payload):
    item = normalize_green_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO green_beans (
                name, origin, crop_season, region, bean_type, estate, variety_name, plot, batch,
                flavor_notes, supplier, process, moisture_pct, density, purchase_weight_g,
                remaining_green_weight_g, notes, total_weight, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                item["origin"],
                item["crop_season"],
                item["region"],
                item["bean_type"],
                item["estate"],
                item["variety_name"],
                item["plot"],
                item["batch"],
                item["flavor_notes"],
                item["supplier"],
                item["process"],
                item["moisture_pct"],
                item["density"],
                item["purchase_weight_g"],
                item["remaining_green_weight_g"],
                item["notes"],
                item["total_weight"],
                now,
                now,
            ),
        )
        connection.commit()
        item_id = cursor.lastrowid
    return get_green_item(item_id)


def update_green_item(item_id, payload):
    item = normalize_green_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE green_beans
            SET name = ?, origin = ?, crop_season = ?, region = ?, bean_type = ?, estate = ?, variety_name = ?,
                plot = ?, batch = ?, flavor_notes = ?, supplier = ?, process = ?,
                moisture_pct = ?, density = ?, purchase_weight_g = ?, remaining_green_weight_g = ?,
                notes = ?, total_weight = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                item["name"],
                item["origin"],
                item["crop_season"],
                item["region"],
                item["bean_type"],
                item["estate"],
                item["variety_name"],
                item["plot"],
                item["batch"],
                item["flavor_notes"],
                item["supplier"],
                item["process"],
                item["moisture_pct"],
                item["density"],
                item["purchase_weight_g"],
                item["remaining_green_weight_g"],
                item["notes"],
                item["total_weight"],
                now,
                item_id,
            ),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("生豆记录不存在")
    return get_green_item(item_id)


def adjust_green_item(item_id, delta_weight):
    delta_weight = validate_int(delta_weight, "总量变动")
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT total_weight FROM green_beans WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise KeyError("生豆记录不存在")

        new_weight = row["total_weight"] + delta_weight
        connection.execute(
            "UPDATE green_beans SET total_weight = ?, remaining_green_weight_g = ?, updated_at = ? WHERE id = ?",
            (new_weight, new_weight, datetime.now().isoformat(timespec="seconds"), item_id),
        )
        connection.commit()
    return get_green_item(item_id)


def deduct_green_item(item_id, delta_weight):
    delta_weight = validate_int(delta_weight, "总量变动")
    with get_db_connection() as connection:
        row = connection.execute(
            "SELECT total_weight FROM green_beans WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise KeyError("生豆记录不存在")

        new_weight = row["total_weight"] - delta_weight
        if new_weight < 0:
            raise ValueError("减少后总量不能小于 0")
        connection.execute(
            "UPDATE green_beans SET total_weight = ?, remaining_green_weight_g = ?, updated_at = ? WHERE id = ?",
            (new_weight, new_weight, datetime.now().isoformat(timespec="seconds"), item_id),
        )
        connection.commit()
    return get_green_item(item_id)


def delete_green_item(item_id):
    with get_db_connection() as connection:
        cursor = connection.execute("DELETE FROM green_beans WHERE id = ?", (item_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("生豆记录不存在")


def normalize_bean_batch_payload(payload):
    name = validate_text(payload.get("name"), "豆子名称")
    origin = normalize_optional_text(payload.get("origin"))
    process = normalize_optional_text(payload.get("process"))
    variety = normalize_optional_text(payload.get("variety") or payload.get("variety_name"))
    purchase_weight = normalize_optional_float(payload.get("purchase_weight_g"))
    remaining_weight = normalize_optional_float(payload.get("remaining_green_weight_g"))
    if remaining_weight is None:
        remaining_weight = purchase_weight or 0
    return {
        "name": name,
        "origin": origin,
        "process": process,
        "variety": variety,
        "purchase_weight_g": purchase_weight,
        "remaining_green_weight_g": remaining_weight,
        "notes": normalize_optional_text(payload.get("notes")),
    }


def row_to_bean_batch_payload(row):
    purchase_weight = clean_number(row["purchase_weight_g"])
    remaining_weight = clean_number(row["remaining_green_weight_g"])
    return {
        "id": row["id"],
        "name": row["name"] or green_display_name(row),
        "origin": row["origin"],
        "process": row["process"],
        "variety": row["variety_name"] or row["bean_type"],
        "purchase_weight_g": purchase_weight,
        "remaining_green_weight_g": remaining_weight if remaining_weight is not None else clean_number(row["total_weight"]),
        "notes": row["notes"],
        "green_item": row_to_green_payload(row),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_bean_batch_row(connection, batch_id):
    return connection.execute(
        """
        SELECT
            id, name, origin, crop_season, region, bean_type, estate, variety_name,
            plot, batch, flavor_notes, supplier, process, moisture_pct, density,
            purchase_weight_g, remaining_green_weight_g, notes, total_weight,
            created_at, updated_at
        FROM green_beans
        WHERE id = ?
        """,
        (batch_id,),
    ).fetchone()


def enrich_batch_with_roasts(batch, roasts):
    batch_roasts = [roast for roast in roasts if NumberSafe(roast.get("bean_batch_id")) == NumberSafe(batch["id"])]
    latest = batch_roasts[0] if batch_roasts else None
    batch["roast_count"] = len(batch_roasts)
    batch["latest_roast_date"] = latest["roast_date"] if latest else None
    batch["latest_dtr_pct"] = latest["dtr_pct"] if latest else None
    batch["latest_cupping_score"] = latest["cupping_score"] if latest else None
    return batch


def NumberSafe(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_bean_batches():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                id, name, origin, crop_season, region, bean_type, estate, variety_name,
                plot, batch, flavor_notes, supplier, process, moisture_pct, density,
                purchase_weight_g, remaining_green_weight_g, notes, total_weight,
                created_at, updated_at
            FROM green_beans
            ORDER BY COALESCE(remaining_green_weight_g, total_weight) DESC, id DESC
            """
        ).fetchall()
    roasts = fetch_roasts()["items"]
    items = [enrich_batch_with_roasts(row_to_bean_batch_payload(row), roasts) for row in rows]
    return {"items": items}


def get_bean_batch(batch_id):
    with get_db_connection() as connection:
        row = fetch_bean_batch_row(connection, batch_id)
    if row is None:
        raise KeyError("生豆批次不存在")
    batch = row_to_bean_batch_payload(row)
    roasts = fetch_roasts_for_bean_batch(batch_id)["items"]
    return {**enrich_batch_with_roasts(batch, roasts), "roasts": roasts}


def create_bean_batch(payload):
    item = normalize_bean_batch_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO green_beans (
                name, origin, crop_season, region, bean_type, estate, variety_name, plot,
                batch, flavor_notes, supplier, process, purchase_weight_g,
                remaining_green_weight_g, notes, total_weight, created_at, updated_at
            )
            VALUES (?, ?, '', ?, ?, '', ?, '', '', ?, '', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                item["origin"],
                item["origin"],
                item["variety"],
                item["variety"],
                item["notes"],
                item["process"],
                item["purchase_weight_g"],
                item["remaining_green_weight_g"],
                item["notes"],
                int(round(item["remaining_green_weight_g"])),
                now,
                now,
            ),
        )
        connection.commit()
        batch_id = cursor.lastrowid
    return get_bean_batch(batch_id)


ROAST_LEVELS = {"very_light", "light", "light_medium", "medium", "dark", "unknown", ""}
CHANGED_VARIABLES = {"load", "heat", "fan", "development", "bean", "profile", "other", ""}
ROAST_EVENT_TYPES = {
    "charge",
    "turning_point",
    "yellow",
    "first_crack_start",
    "first_crack_end",
    "drop",
    "heat_change",
    "fan_change",
    "note",
}
ROAST_BASE_COLUMNS = [
    "id",
    "roast_date",
    "bean_id",
    "bean_batch_id",
    "roasted_bean_id",
    "bean_name_snapshot",
    "bean_origin",
    "bean_process",
    "bean_variety",
    "roaster_model",
    "roast_label",
    "batch_weight_g",
    "roasted_weight_g",
    "cupping_reserved_g",
    "drinkable_weight_g",
    "weight_loss_g",
    "weight_loss_pct",
    "profile_name",
    "charge_temp_c",
    "preheat_temp_c",
    "ambient_temp_c",
    "fan_start",
    "heat_start",
    "operation_plan",
    "plan_yellow_time_s",
    "plan_yellow_temp_c",
    "plan_first_crack_time_s",
    "plan_first_crack_temp_c",
    "plan_drop_time_s",
    "plan_drop_temp_c",
    "plan_note",
    "yellow_time_sec",
    "yellow_temp_c",
    "first_crack_time_sec",
    "first_crack_temp_c",
    "drop_time_sec",
    "drop_temp_c",
    "actual_yellow_time_s",
    "actual_yellow_temp_c",
    "actual_first_crack_time_s",
    "actual_first_crack_temp_c",
    "actual_drop_time_s",
    "actual_drop_temp_c",
    "control_log",
    "roast_notes",
    "drying_time_sec",
    "maillard_time_sec",
    "development_time_sec",
    "dtr_pct",
    "yellow_to_fc_sec",
    "fc_to_drop_temp_rise_c",
    "experiment_goal",
    "changed_variable",
    "hypothesis",
    "result_summary",
    "next_adjustment",
    "roast_level",
    "color_note",
    "aroma_note",
    "defect_flags",
    "general_notes",
    "learning_note",
    "cupping_date",
    "cupping_score",
    "cupping_notes",
    "defects",
    "created_at",
    "updated_at",
]


def calculate_roast_metrics(
    batch_weight_g,
    roasted_weight_g=None,
    cupping_reserved_g=8.25,
    yellow_time_sec=None,
    first_crack_time_sec=None,
    drop_time_sec=None,
    first_crack_temp_c=None,
    drop_temp_c=None,
):
    """Calculate derived roast metrics from manually recorded events."""
    metrics = {
        "drinkable_weight_g": None,
        "weight_loss_g": None,
        "weight_loss_pct": None,
        "drying_time_sec": yellow_time_sec,
        "maillard_time_sec": None,
        "development_time_sec": None,
        "dtr_pct": None,
        "yellow_to_fc_sec": None,
        "fc_to_drop_temp_rise_c": None,
        "dehydration_duration_s": yellow_time_sec,
        "maillard_duration_s": None,
        "post_crack_duration_s": None,
    }

    if roasted_weight_g is not None:
        weight_loss_g = round(batch_weight_g - roasted_weight_g, 2)
        if weight_loss_g < 0:
            raise ValueError("熟豆重量不能大于载量")
        metrics["weight_loss_g"] = weight_loss_g
        metrics["weight_loss_pct"] = round(weight_loss_g / batch_weight_g * 100, 2)
        metrics["drinkable_weight_g"] = max(round(roasted_weight_g - cupping_reserved_g, 2), 0)

    if yellow_time_sec is not None and first_crack_time_sec is not None:
        if first_crack_time_sec <= yellow_time_sec:
            raise ValueError("黄点时间必须早于一爆时间")
        metrics["maillard_time_sec"] = first_crack_time_sec - yellow_time_sec
        metrics["yellow_to_fc_sec"] = metrics["maillard_time_sec"]
        metrics["maillard_duration_s"] = metrics["maillard_time_sec"]

    if first_crack_time_sec is not None and drop_time_sec is not None:
        if drop_time_sec <= first_crack_time_sec:
            raise ValueError("一爆时间必须早于下豆时间")
        metrics["development_time_sec"] = drop_time_sec - first_crack_time_sec
        metrics["post_crack_duration_s"] = metrics["development_time_sec"]
        if drop_time_sec > 0:
            metrics["dtr_pct"] = round(metrics["development_time_sec"] / drop_time_sec * 100, 2)

    if first_crack_temp_c is not None and drop_temp_c is not None:
        metrics["fc_to_drop_temp_rise_c"] = round(drop_temp_c - first_crack_temp_c, 2)

    return metrics


def green_display_name(row):
    if "name" in row.keys() and str(row["name"] or "").strip():
        return row["name"]
    parts = [row["crop_season"], row["region"], row["estate"], row["bean_type"] or row["variety_name"]]
    return " · ".join(part for part in parts if str(part or "").strip()) or f"生豆 #{row['id']}"


def fetch_green_row(connection, bean_id):
    return connection.execute(
        """
        SELECT id, name, origin, crop_season, region, bean_type, estate, variety_name, process, total_weight
        FROM green_beans
        WHERE id = ?
        """,
        (bean_id,),
    ).fetchone()


def validate_roast_time_order(yellow_time, first_crack_time, drop_time, prefix=""):
    label = f"{prefix}" if prefix else ""
    if yellow_time is not None and first_crack_time is not None and first_crack_time <= yellow_time:
        raise ValueError(f"{label}黄点时间必须早于一爆时间")
    if first_crack_time is not None and drop_time is not None and drop_time <= first_crack_time:
        raise ValueError(f"{label}一爆时间必须早于下豆时间")


def normalize_roast_payload(payload):
    bean_id = None
    green_row = None
    raw_bean_id = payload.get("bean_batch_id") or payload.get("bean_id")
    with get_db_connection() as connection:
        if raw_bean_id not in (None, ""):
            try:
                bean_id = int(raw_bean_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("生豆 ID 不合法") from exc
            green_row = fetch_green_row(connection, bean_id)
            if green_row is None:
                raise ValueError("生豆库存记录不存在")

    roast_level = normalize_optional_text(payload.get("roast_level") or "unknown")
    changed_variable = normalize_optional_text(payload.get("changed_variable"))
    if roast_level not in ROAST_LEVELS:
        raise ValueError("烘焙度不合法")
    if changed_variable not in CHANGED_VARIABLES:
        raise ValueError("改变变量不合法")

    batch_weight_g = validate_positive_float(payload.get("batch_weight_g"), "载量")
    roasted_weight_g = normalize_optional_float(payload.get("roasted_weight_g"))
    cupping_reserved_g = normalize_optional_float(payload.get("cupping_reserved_g"))
    if cupping_reserved_g is None:
        cupping_reserved_g = 8.25

    plan_yellow_time_s = normalize_optional_time(payload.get("plan_yellow_time_s"), "计划黄点时间")
    plan_first_crack_time_s = normalize_optional_time(payload.get("plan_first_crack_time_s"), "计划一爆时间")
    plan_drop_time_s = normalize_optional_time(payload.get("plan_drop_time_s"), "计划下豆时间")
    validate_roast_time_order(plan_yellow_time_s, plan_first_crack_time_s, plan_drop_time_s, "计划")

    actual_yellow_time_s = normalize_optional_time(
        payload.get("actual_yellow_time_s", payload.get("yellow_time_sec")),
        "实际黄点时间",
    )
    actual_first_crack_time_s = normalize_optional_time(
        payload.get("actual_first_crack_time_s", payload.get("first_crack_time_sec")),
        "实际一爆时间",
    )
    actual_drop_time_s = normalize_optional_time(
        payload.get("actual_drop_time_s", payload.get("drop_time_sec")),
        "实际下豆时间",
    )
    actual_first_crack_temp_c = normalize_optional_float(
        payload.get("actual_first_crack_temp_c", payload.get("first_crack_temp_c"))
    )
    actual_drop_temp_c = normalize_optional_float(
        payload.get("actual_drop_temp_c", payload.get("drop_temp_c"))
    )

    metrics = calculate_roast_metrics(
        batch_weight_g=batch_weight_g,
        roasted_weight_g=roasted_weight_g,
        cupping_reserved_g=cupping_reserved_g,
        yellow_time_sec=actual_yellow_time_s,
        first_crack_time_sec=actual_first_crack_time_s,
        drop_time_sec=actual_drop_time_s,
        first_crack_temp_c=actual_first_crack_temp_c,
        drop_temp_c=actual_drop_temp_c,
    )

    if green_row:
        snapshot = normalize_optional_text(payload.get("bean_name_snapshot")) or green_display_name(green_row)
        origin = normalize_optional_text(payload.get("bean_origin")) or green_row["region"]
        process = normalize_optional_text(payload.get("bean_process")) or green_row["process"]
        variety = normalize_optional_text(payload.get("bean_variety")) or green_row["variety_name"] or green_row["bean_type"]
    else:
        snapshot = validate_text(payload.get("bean_name_snapshot"), "豆子名称")
        origin = normalize_optional_text(payload.get("bean_origin"))
        process = normalize_optional_text(payload.get("bean_process"))
        variety = normalize_optional_text(payload.get("bean_variety"))

    item = {
        "roast_date": validate_date(payload.get("roast_date"), "烘焙日期"),
        "bean_id": bean_id,
        "bean_batch_id": bean_id,
        "bean_name_snapshot": snapshot,
        "bean_origin": origin,
        "bean_process": process,
        "bean_variety": variety,
        "roaster_model": normalize_optional_text(payload.get("machine") or payload.get("roaster_model")) or "Santoker Cube10",
        "roast_label": normalize_optional_text(payload.get("roast_label") or payload.get("profile_name")),
        "batch_weight_g": batch_weight_g,
        "roasted_weight_g": roasted_weight_g,
        "cupping_reserved_g": cupping_reserved_g,
        "profile_name": normalize_optional_text(payload.get("profile_name")),
        "charge_temp_c": normalize_optional_float(payload.get("charge_temp_c")),
        "preheat_temp_c": normalize_optional_float(payload.get("preheat_temp_c")),
        "ambient_temp_c": normalize_optional_float(payload.get("ambient_temp_c")),
        "fan_start": normalize_optional_int(payload.get("fan_start")),
        "heat_start": normalize_optional_int(payload.get("heat_start")),
        "operation_plan": normalize_optional_text(payload.get("operation_plan")),
        "plan_yellow_time_s": plan_yellow_time_s,
        "plan_yellow_temp_c": normalize_optional_float(payload.get("plan_yellow_temp_c")),
        "plan_first_crack_time_s": plan_first_crack_time_s,
        "plan_first_crack_temp_c": normalize_optional_float(payload.get("plan_first_crack_temp_c")),
        "plan_drop_time_s": plan_drop_time_s,
        "plan_drop_temp_c": normalize_optional_float(payload.get("plan_drop_temp_c")),
        "plan_note": normalize_optional_text(payload.get("plan_note")),
        "yellow_time_sec": actual_yellow_time_s,
        "yellow_temp_c": normalize_optional_float(payload.get("actual_yellow_temp_c", payload.get("yellow_temp_c"))),
        "first_crack_time_sec": actual_first_crack_time_s,
        "first_crack_temp_c": actual_first_crack_temp_c,
        "drop_time_sec": actual_drop_time_s,
        "drop_temp_c": actual_drop_temp_c,
        "actual_yellow_time_s": actual_yellow_time_s,
        "actual_yellow_temp_c": normalize_optional_float(payload.get("actual_yellow_temp_c", payload.get("yellow_temp_c"))),
        "actual_first_crack_time_s": actual_first_crack_time_s,
        "actual_first_crack_temp_c": actual_first_crack_temp_c,
        "actual_drop_time_s": actual_drop_time_s,
        "actual_drop_temp_c": actual_drop_temp_c,
        "control_log": normalize_optional_text(payload.get("control_log")),
        "roast_notes": normalize_optional_text(payload.get("roast_notes")),
        "experiment_goal": normalize_optional_text(payload.get("experiment_goal")),
        "changed_variable": changed_variable,
        "hypothesis": normalize_optional_text(payload.get("hypothesis")),
        "result_summary": normalize_optional_text(payload.get("result_summary")),
        "next_adjustment": normalize_optional_text(payload.get("next_adjustment")),
        "roast_level": roast_level,
        "color_note": normalize_optional_text(payload.get("color_note")),
        "aroma_note": normalize_optional_text(payload.get("aroma_note")),
        "defect_flags": normalize_optional_text(payload.get("defect_flags")),
        "general_notes": normalize_optional_text(payload.get("general_notes")),
        "learning_note": normalize_optional_text(payload.get("learning_note")),
        "cupping_date": normalize_optional_date(payload.get("cupping_date"), "杯测日期"),
        "cupping_score": normalize_optional_score(payload.get("cupping_score"), "杯测评分"),
        "cupping_notes": normalize_optional_text(payload.get("cupping_notes")),
        "defects": normalize_optional_text(payload.get("defects")),
        "create_roasted_batch": bool(payload.get("create_roasted_batch")),
        "events": normalize_roast_events(payload.get("events") or []),
        **metrics,
    }
    return item


def normalize_roast_events(events):
    normalized = []
    if not isinstance(events, list):
        raise ValueError("烘焙事件格式不合法")
    for event in events:
        event_type = normalize_optional_text(event.get("event_type"))
        has_content = any(
            normalize_optional_text(event.get(key)) for key in ("time_sec", "temp_c", "heat_setting", "fan_setting", "note")
        )
        if not event_type and not has_content:
            continue
        if event_type not in ROAST_EVENT_TYPES:
            raise ValueError("烘焙事件类型不合法")
        normalized.append(
            {
                "event_type": event_type,
                "time_sec": normalize_optional_time(event.get("time_sec"), "事件时间"),
                "temp_c": normalize_optional_float(event.get("temp_c")),
                "heat_setting": normalize_optional_int(event.get("heat_setting")),
                "fan_setting": normalize_optional_int(event.get("fan_setting")),
                "note": normalize_optional_text(event.get("note")),
            }
        )
    return normalized


def row_to_roast_payload(row):
    payload = {}
    for column in ROAST_BASE_COLUMNS:
        if column in row.keys():
            payload[column] = row[column]

    for key in (
        "batch_weight_g",
        "roasted_weight_g",
        "cupping_reserved_g",
        "drinkable_weight_g",
        "weight_loss_g",
        "weight_loss_pct",
        "charge_temp_c",
        "preheat_temp_c",
        "ambient_temp_c",
        "plan_yellow_temp_c",
        "plan_first_crack_temp_c",
        "plan_drop_temp_c",
        "yellow_temp_c",
        "first_crack_temp_c",
        "drop_temp_c",
        "actual_yellow_temp_c",
        "actual_first_crack_temp_c",
        "actual_drop_temp_c",
        "dtr_pct",
        "fc_to_drop_temp_rise_c",
    ):
        if key in payload:
            payload[key] = clean_number(payload[key])

    payload["bean_batch_id"] = payload.get("bean_batch_id") or payload.get("bean_id")
    payload["machine"] = payload.get("roaster_model")
    payload["actual_yellow_time_s"] = payload.get("actual_yellow_time_s") or payload.get("yellow_time_sec")
    payload["actual_yellow_temp_c"] = payload.get("actual_yellow_temp_c") if payload.get("actual_yellow_temp_c") is not None else payload.get("yellow_temp_c")
    payload["actual_first_crack_time_s"] = payload.get("actual_first_crack_time_s") or payload.get("first_crack_time_sec")
    payload["actual_first_crack_temp_c"] = payload.get("actual_first_crack_temp_c") if payload.get("actual_first_crack_temp_c") is not None else payload.get("first_crack_temp_c")
    payload["actual_drop_time_s"] = payload.get("actual_drop_time_s") or payload.get("drop_time_sec")
    payload["actual_drop_temp_c"] = payload.get("actual_drop_temp_c") if payload.get("actual_drop_temp_c") is not None else payload.get("drop_temp_c")
    payload["dehydration_duration_s"] = payload.get("drying_time_sec")
    payload["maillard_duration_s"] = payload.get("maillard_time_sec")
    payload["post_crack_duration_s"] = payload.get("development_time_sec")

    payload["latest_cupping"] = None
    if payload.get("cupping_score") is not None or payload.get("cupping_notes") or payload.get("cupping_date"):
        payload["latest_cupping"] = {
            "id": row["cupping_id"] if "cupping_id" in row.keys() else None,
            "cupping_date": payload.get("cupping_date"),
            "overall": payload.get("cupping_score"),
            "conclusion": payload.get("cupping_notes"),
            "defect_notes": payload.get("defects"),
            "next_roast_adjustment": payload.get("next_adjustment"),
        }
    elif "cupping_id" in row.keys() and row["cupping_id"] is not None:
        payload["latest_cupping"] = {
            "id": row["cupping_id"],
            "cupping_date": row["cupping_date"],
            "overall": row["overall"],
            "conclusion": row["conclusion"],
            "defect_notes": row["defect_notes"] if "defect_notes" in row.keys() else None,
            "next_roast_adjustment": row["next_roast_adjustment"] if "next_roast_adjustment" in row.keys() else None,
        }
    return payload


def roast_select_sql():
    return """
        SELECT
            roast_batches.*,
            latest_cupping.id AS cupping_id,
            latest_cupping.cupping_date,
            latest_cupping.overall,
            latest_cupping.conclusion,
            latest_cupping.defect_notes,
            latest_cupping.next_roast_adjustment
        FROM roast_batches
        LEFT JOIN cupping_records AS latest_cupping
            ON latest_cupping.id = (
                SELECT id
                FROM cupping_records
                WHERE cupping_records.roast_id = roast_batches.id
                ORDER BY cupping_date DESC, id DESC
                LIMIT 1
            )
    """


def fetch_roasts():
    with get_db_connection() as connection:
        rows = connection.execute(
            roast_select_sql()
            + """
            ORDER BY roast_date DESC, roast_batches.id DESC
            """
        ).fetchall()
    return {"items": [row_to_roast_payload(row) for row in rows]}


def fetch_roasts_for_bean_batch(batch_id):
    with get_db_connection() as connection:
        rows = connection.execute(
            roast_select_sql()
            + """
            WHERE COALESCE(roast_batches.bean_batch_id, roast_batches.bean_id) = ?
            ORDER BY roast_date DESC, roast_batches.id DESC
            """,
            (batch_id,),
        ).fetchall()
        roast_ids = [row["id"] for row in rows]
        cuppings_by_roast = {}
        if roast_ids:
            placeholders = ",".join("?" for _ in roast_ids)
            cupping_rows = connection.execute(
                f"""
                SELECT *
                FROM cupping_records
                WHERE roast_id IN ({placeholders})
                ORDER BY cupping_date DESC, COALESCE(rest_hours, -1) DESC, id DESC
                """,
                roast_ids,
            ).fetchall()
            for cupping in cupping_rows:
                cuppings_by_roast.setdefault(cupping["roast_id"], []).append(
                    row_to_cupping_payload(cupping)
                )

    items = []
    for row in rows:
        roast = row_to_roast_payload(row)
        roast["cuppings"] = cuppings_by_roast.get(roast["id"], [])
        items.append(roast)
    return {"items": items}


def get_roast(roast_id):
    with get_db_connection() as connection:
        row = connection.execute(
            roast_select_sql()
            + """
            WHERE roast_batches.id = ?
            """,
            (roast_id,),
        ).fetchone()
        if row is None:
            raise KeyError("烘焙记录不存在")
        events = connection.execute(
            """
            SELECT id, event_type, time_sec, temp_c, heat_setting, fan_setting, note, created_at
            FROM roast_events
            WHERE roast_id = ?
            ORDER BY COALESCE(time_sec, 999999), id
            """,
            (roast_id,),
        ).fetchall()
        cuppings = connection.execute(
            """
            SELECT *
            FROM cupping_records
            WHERE roast_id = ?
            ORDER BY cupping_date DESC, id DESC
            """,
            (roast_id,),
        ).fetchall()
        transactions = connection.execute(
            """
            SELECT id, roast_id, bean_id, transaction_type, weight_g, note, created_at
            FROM roast_inventory_transactions
            WHERE roast_id = ?
            ORDER BY id
            """,
            (roast_id,),
        ).fetchall()

    payload = row_to_roast_payload(row)
    payload["events"] = [row_to_roast_event(event) for event in events]
    payload["cuppings"] = [row_to_cupping_payload(cupping) for cupping in cuppings]
    payload["transactions"] = [row_to_transaction_payload(transaction) for transaction in transactions]
    return payload


def create_roast(payload):
    item = normalize_roast_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    roasted_bean_id = None
    if item["create_roasted_batch"] and (item["drinkable_weight_g"] is None or item["drinkable_weight_g"] <= 0):
        raise ValueError("生成熟豆库存批次需要填写熟豆重量，且扣除杯测预留后必须大于 0")
    with get_db_connection() as connection:
        try:
            connection.execute("BEGIN")
            if item["bean_id"] is not None:
                green_row = fetch_green_row(connection, item["bean_id"])
                if green_row is None:
                    raise ValueError("生豆库存记录不存在")
                current_weight = float(green_row["total_weight"])
                if current_weight < item["batch_weight_g"]:
                    raise ValueError("生豆库存不足，无法扣减本锅载量")
                connection.execute(
                    """
                    UPDATE green_beans
                    SET total_weight = ?, remaining_green_weight_g = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        round(current_weight - item["batch_weight_g"], 2),
                        round(current_weight - item["batch_weight_g"], 2),
                        now,
                        item["bean_id"],
                    ),
                )

            cursor = connection.execute(
                """
                INSERT INTO roast_batches (
                    roast_date, bean_id, bean_batch_id, bean_name_snapshot, bean_origin, bean_process, bean_variety,
                    roaster_model, roast_label, batch_weight_g, roasted_weight_g, cupping_reserved_g,
                    drinkable_weight_g, weight_loss_g, weight_loss_pct, profile_name,
                    charge_temp_c, preheat_temp_c, ambient_temp_c, fan_start, heat_start,
                    operation_plan, plan_yellow_time_s, plan_yellow_temp_c,
                    plan_first_crack_time_s, plan_first_crack_temp_c, plan_drop_time_s,
                    plan_drop_temp_c, plan_note, yellow_time_sec, yellow_temp_c, first_crack_time_sec,
                    first_crack_temp_c, drop_time_sec, drop_temp_c, drying_time_sec,
                    maillard_time_sec, development_time_sec, dtr_pct, yellow_to_fc_sec,
                    fc_to_drop_temp_rise_c, experiment_goal, changed_variable, hypothesis,
                    result_summary, next_adjustment, roast_level, color_note, aroma_note,
                    defect_flags, general_notes, learning_note, actual_yellow_time_s,
                    actual_yellow_temp_c, actual_first_crack_time_s, actual_first_crack_temp_c,
                    actual_drop_time_s, actual_drop_temp_c, control_log, roast_notes,
                    cupping_date, cupping_score, cupping_notes, defects, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["roast_date"],
                    item["bean_id"],
                    item["bean_batch_id"],
                    item["bean_name_snapshot"],
                    item["bean_origin"],
                    item["bean_process"],
                    item["bean_variety"],
                    item["roaster_model"],
                    item["roast_label"],
                    item["batch_weight_g"],
                    item["roasted_weight_g"],
                    item["cupping_reserved_g"],
                    item["drinkable_weight_g"],
                    item["weight_loss_g"],
                    item["weight_loss_pct"],
                    item["profile_name"],
                    item["charge_temp_c"],
                    item["preheat_temp_c"],
                    item["ambient_temp_c"],
                    item["fan_start"],
                    item["heat_start"],
                    item["operation_plan"],
                    item["plan_yellow_time_s"],
                    item["plan_yellow_temp_c"],
                    item["plan_first_crack_time_s"],
                    item["plan_first_crack_temp_c"],
                    item["plan_drop_time_s"],
                    item["plan_drop_temp_c"],
                    item["plan_note"],
                    item["yellow_time_sec"],
                    item["yellow_temp_c"],
                    item["first_crack_time_sec"],
                    item["first_crack_temp_c"],
                    item["drop_time_sec"],
                    item["drop_temp_c"],
                    item["drying_time_sec"],
                    item["maillard_time_sec"],
                    item["development_time_sec"],
                    item["dtr_pct"],
                    item["yellow_to_fc_sec"],
                    item["fc_to_drop_temp_rise_c"],
                    item["experiment_goal"],
                    item["changed_variable"],
                    item["hypothesis"],
                    item["result_summary"],
                    item["next_adjustment"],
                    item["roast_level"],
                    item["color_note"],
                    item["aroma_note"],
                    item["defect_flags"],
                    item["general_notes"],
                    item["learning_note"],
                    item["actual_yellow_time_s"],
                    item["actual_yellow_temp_c"],
                    item["actual_first_crack_time_s"],
                    item["actual_first_crack_temp_c"],
                    item["actual_drop_time_s"],
                    item["actual_drop_temp_c"],
                    item["control_log"],
                    item["roast_notes"],
                    item["cupping_date"],
                    item["cupping_score"],
                    item["cupping_notes"],
                    item["defects"],
                    now,
                    now,
                ),
            )
            roast_id = cursor.lastrowid

            if item["bean_id"] is not None:
                connection.execute(
                    """
                    INSERT INTO roast_inventory_transactions (roast_id, bean_id, transaction_type, weight_g, note, created_at)
                    VALUES (?, ?, 'green_used', ?, ?, ?)
                    """,
                    (roast_id, item["bean_id"], item["batch_weight_g"], "新建烘焙记录自动扣减生豆库存", now),
                )

            if item["create_roasted_batch"] and item["drinkable_weight_g"] is not None and item["drinkable_weight_g"] > 0:
                roasted_net_weight = int(round(item["drinkable_weight_g"]))
                roasted_cursor = connection.execute(
                    """
                    INSERT INTO beans (
                        bean_name, roaster, origin, estate, country, region, producer, lot_info,
                        variety_name, roaster_recommendation, roast_date, storage_state, process,
                        plot, batch, net_weight, price_total, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"{item['bean_name_snapshot']} #{roast_id}",
                        "自烘",
                        item["bean_origin"] or "",
                        item["bean_origin"] or "",
                        item["bean_origin"] or "",
                        "",
                        item["bean_origin"] or "",
                        f"烘焙批次 #{roast_id}",
                        item["bean_variety"] or "",
                        "",
                        item["roast_date"],
                        "常温",
                        item["bean_process"] or "",
                        "",
                        "",
                        roasted_net_weight,
                        0,
                        now,
                    ),
                )
                roasted_bean_id = roasted_cursor.lastrowid
                connection.execute(
                    "UPDATE roast_batches SET roasted_bean_id = ? WHERE id = ?",
                    (roasted_bean_id, roast_id),
                )
                connection.execute(
                    """
                    INSERT INTO roast_inventory_transactions (roast_id, bean_id, transaction_type, weight_g, note, created_at)
                    VALUES (?, ?, 'roasted_created', ?, ?, ?)
                    """,
                    (roast_id, roasted_bean_id, roasted_net_weight, "自动生成熟豆库存批次", now),
                )

            for event in item["events"]:
                connection.execute(
                    """
                    INSERT INTO roast_events (roast_id, event_type, time_sec, temp_c, heat_setting, fan_setting, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        roast_id,
                        event["event_type"],
                        event["time_sec"],
                        event["temp_c"],
                        event["heat_setting"],
                        event["fan_setting"],
                        event["note"],
                        now,
                    ),
                )

            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return get_roast(roast_id)


def create_roast_for_bean_batch(batch_id, payload):
    data = dict(payload)
    data["bean_batch_id"] = batch_id
    data["bean_id"] = batch_id
    return create_roast(data)


def update_roast(roast_id, payload):
    item = normalize_roast_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    if item["create_roasted_batch"] and (item["drinkable_weight_g"] is None or item["drinkable_weight_g"] <= 0):
        raise ValueError("生成熟豆库存批次需要填写熟豆重量，且扣除杯测预留后必须大于 0")

    with get_db_connection() as connection:
        try:
            connection.execute("BEGIN")
            old = connection.execute("SELECT * FROM roast_batches WHERE id = ?", (roast_id,)).fetchone()
            if old is None:
                raise KeyError("烘焙记录不存在")

            old_green_transaction = connection.execute(
                """
                SELECT id, bean_id, weight_g
                FROM roast_inventory_transactions
                WHERE roast_id = ? AND transaction_type = 'green_used'
                ORDER BY id DESC
                LIMIT 1
                """,
                (roast_id,),
            ).fetchone()
            old_green_id = old_green_transaction["bean_id"] if old_green_transaction else None
            old_green_weight = float(old_green_transaction["weight_g"]) if old_green_transaction else 0
            same_green_bean = old_green_id is not None and old_green_id == item["bean_id"]

            if same_green_bean:
                green_delta = round(item["batch_weight_g"] - old_green_weight, 2)
                if green_delta != 0:
                    green_row = fetch_green_row(connection, item["bean_id"])
                    if green_row is None:
                        raise ValueError("生豆库存记录不存在")
                    current_weight = float(green_row["total_weight"])
                    new_weight = round(current_weight - green_delta, 2)
                    if new_weight < 0:
                        raise ValueError("生豆库存不足，无法扣减本锅载量差额")
                    connection.execute(
                        """
                        UPDATE green_beans
                        SET total_weight = ?, remaining_green_weight_g = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (new_weight, new_weight, now, item["bean_id"]),
                    )
            elif item["bean_id"] is not None:
                green_row = fetch_green_row(connection, item["bean_id"])
                if green_row is None:
                    raise ValueError("生豆库存记录不存在")
                current_weight = float(green_row["total_weight"])
                if current_weight < item["batch_weight_g"]:
                    raise ValueError("生豆库存不足，无法扣减本锅载量")
                connection.execute(
                    """
                    UPDATE green_beans
                    SET total_weight = ?, remaining_green_weight_g = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        round(current_weight - item["batch_weight_g"], 2),
                        round(current_weight - item["batch_weight_g"], 2),
                        now,
                        item["bean_id"],
                    ),
                )

            connection.execute(
                """
                UPDATE roast_batches
                SET roast_date = ?, bean_id = ?, bean_batch_id = ?, bean_name_snapshot = ?, bean_origin = ?,
                    bean_process = ?, bean_variety = ?, roaster_model = ?, batch_weight_g = ?,
                    roasted_weight_g = ?, cupping_reserved_g = ?, drinkable_weight_g = ?,
                    weight_loss_g = ?, weight_loss_pct = ?, profile_name = ?, roast_label = ?, charge_temp_c = ?,
                    preheat_temp_c = ?, ambient_temp_c = ?, fan_start = ?, heat_start = ?,
                    operation_plan = ?, plan_yellow_time_s = ?, plan_yellow_temp_c = ?,
                    plan_first_crack_time_s = ?, plan_first_crack_temp_c = ?,
                    plan_drop_time_s = ?, plan_drop_temp_c = ?, plan_note = ?,
                    yellow_time_sec = ?, yellow_temp_c = ?,
                    first_crack_time_sec = ?, first_crack_temp_c = ?, drop_time_sec = ?,
                    drop_temp_c = ?, actual_yellow_time_s = ?, actual_yellow_temp_c = ?,
                    actual_first_crack_time_s = ?, actual_first_crack_temp_c = ?,
                    actual_drop_time_s = ?, actual_drop_temp_c = ?, control_log = ?,
                    roast_notes = ?, drying_time_sec = ?, maillard_time_sec = ?,
                    development_time_sec = ?, dtr_pct = ?, yellow_to_fc_sec = ?,
                    fc_to_drop_temp_rise_c = ?, experiment_goal = ?, changed_variable = ?,
                    hypothesis = ?, result_summary = ?, next_adjustment = ?, roast_level = ?,
                    color_note = ?, aroma_note = ?, defect_flags = ?, general_notes = ?,
                    learning_note = ?, cupping_date = ?, cupping_score = ?, cupping_notes = ?,
                    defects = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    item["roast_date"],
                    item["bean_id"],
                    item["bean_batch_id"],
                    item["bean_name_snapshot"],
                    item["bean_origin"],
                    item["bean_process"],
                    item["bean_variety"],
                    item["roaster_model"],
                    item["batch_weight_g"],
                    item["roasted_weight_g"],
                    item["cupping_reserved_g"],
                    item["drinkable_weight_g"],
                    item["weight_loss_g"],
                    item["weight_loss_pct"],
                    item["profile_name"],
                    item["roast_label"],
                    item["charge_temp_c"],
                    item["preheat_temp_c"],
                    item["ambient_temp_c"],
                    item["fan_start"],
                    item["heat_start"],
                    item["operation_plan"],
                    item["plan_yellow_time_s"],
                    item["plan_yellow_temp_c"],
                    item["plan_first_crack_time_s"],
                    item["plan_first_crack_temp_c"],
                    item["plan_drop_time_s"],
                    item["plan_drop_temp_c"],
                    item["plan_note"],
                    item["yellow_time_sec"],
                    item["yellow_temp_c"],
                    item["first_crack_time_sec"],
                    item["first_crack_temp_c"],
                    item["drop_time_sec"],
                    item["drop_temp_c"],
                    item["actual_yellow_time_s"],
                    item["actual_yellow_temp_c"],
                    item["actual_first_crack_time_s"],
                    item["actual_first_crack_temp_c"],
                    item["actual_drop_time_s"],
                    item["actual_drop_temp_c"],
                    item["control_log"],
                    item["roast_notes"],
                    item["drying_time_sec"],
                    item["maillard_time_sec"],
                    item["development_time_sec"],
                    item["dtr_pct"],
                    item["yellow_to_fc_sec"],
                    item["fc_to_drop_temp_rise_c"],
                    item["experiment_goal"],
                    item["changed_variable"],
                    item["hypothesis"],
                    item["result_summary"],
                    item["next_adjustment"],
                    item["roast_level"],
                    item["color_note"],
                    item["aroma_note"],
                    item["defect_flags"],
                    item["general_notes"],
                    item["learning_note"],
                    item["cupping_date"],
                    item["cupping_score"],
                    item["cupping_notes"],
                    item["defects"],
                    now,
                    roast_id,
                ),
            )

            connection.execute("DELETE FROM roast_events WHERE roast_id = ?", (roast_id,))
            for event in item["events"]:
                connection.execute(
                    """
                    INSERT INTO roast_events (roast_id, event_type, time_sec, temp_c, heat_setting, fan_setting, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        roast_id,
                        event["event_type"],
                        event["time_sec"],
                        event["temp_c"],
                        event["heat_setting"],
                        event["fan_setting"],
                        event["note"],
                        now,
                    ),
                )

            if old_green_transaction:
                connection.execute(
                    """
                    UPDATE roast_inventory_transactions
                    SET bean_id = ?, weight_g = ?, note = ?
                    WHERE id = ?
                    """,
                    (
                        item["bean_id"],
                        item["batch_weight_g"],
                        "修改烘焙记录后同步生豆扣减；换豆不回补原生豆",
                        old_green_transaction["id"],
                    ),
                )
            elif item["bean_id"] is not None:
                connection.execute(
                    """
                    INSERT INTO roast_inventory_transactions (roast_id, bean_id, transaction_type, weight_g, note, created_at)
                    VALUES (?, ?, 'green_used', ?, ?, ?)
                    """,
                    (roast_id, item["bean_id"], item["batch_weight_g"], "修改烘焙记录后新增生豆扣减", now),
                )

            roasted_bean_id = old["roasted_bean_id"]
            if item["create_roasted_batch"]:
                roasted_net_weight = int(round(item["drinkable_weight_g"]))
                if roasted_bean_id:
                    connection.execute(
                        """
                        UPDATE beans
                        SET bean_name = ?, origin = ?, estate = ?, country = ?, producer = ?,
                            lot_info = ?, variety_name = ?, roast_date = ?, process = ?, net_weight = ?
                        WHERE id = ?
                        """,
                        (
                            f"{item['bean_name_snapshot']} #{roast_id}",
                            item["bean_origin"] or "",
                            item["bean_origin"] or "",
                            item["bean_origin"] or "",
                            item["bean_origin"] or "",
                            f"烘焙批次 #{roast_id}",
                            item["bean_variety"] or "",
                            item["roast_date"],
                            item["bean_process"] or "",
                            roasted_net_weight,
                            roasted_bean_id,
                        ),
                    )
                else:
                    roasted_cursor = connection.execute(
                        """
                        INSERT INTO beans (
                            bean_name, roaster, origin, estate, country, region, producer, lot_info,
                            variety_name, roaster_recommendation, roast_date, storage_state, process,
                            plot, batch, net_weight, price_total, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{item['bean_name_snapshot']} #{roast_id}",
                            "自烘",
                            item["bean_origin"] or "",
                            item["bean_origin"] or "",
                            item["bean_origin"] or "",
                            "",
                            item["bean_origin"] or "",
                            f"烘焙批次 #{roast_id}",
                            item["bean_variety"] or "",
                            "",
                            item["roast_date"],
                            "常温",
                            item["bean_process"] or "",
                            "",
                            "",
                            roasted_net_weight,
                            0,
                            now,
                        ),
                    )
                    roasted_bean_id = roasted_cursor.lastrowid
                    connection.execute(
                        "UPDATE roast_batches SET roasted_bean_id = ? WHERE id = ?",
                        (roasted_bean_id, roast_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO roast_inventory_transactions (roast_id, bean_id, transaction_type, weight_g, note, created_at)
                        VALUES (?, ?, 'roasted_created', ?, ?, ?)
                        """,
                        (roast_id, roasted_bean_id, roasted_net_weight, "修改烘焙记录时自动生成熟豆库存批次", now),
                    )

            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return get_roast(roast_id)


def update_roast_learning_note(roast_id, payload):
    learning_note = normalize_optional_text(payload.get("learning_note"))
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE roast_batches
            SET learning_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (learning_note, now, roast_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("烘焙记录不存在")
    return get_roast(roast_id)


def row_to_roast_event(row):
    return {
        "id": row["id"],
        "event_type": row["event_type"],
        "time_sec": row["time_sec"],
        "temp_c": clean_number(row["temp_c"]),
        "heat_setting": row["heat_setting"],
        "fan_setting": row["fan_setting"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def row_to_transaction_payload(row):
    return {
        "id": row["id"],
        "roast_id": row["roast_id"],
        "bean_id": row["bean_id"],
        "transaction_type": row["transaction_type"],
        "weight_g": clean_number(row["weight_g"]),
        "note": row["note"],
        "created_at": row["created_at"],
    }


def normalize_cupping_payload(roast_id, payload):
    return {
        "roast_id": roast_id,
        "cupping_date": validate_date(payload.get("cupping_date"), "杯测日期"),
        "rest_hours": normalize_optional_float(payload.get("rest_hours")),
        "dose_g": normalize_optional_float(payload.get("dose_g")) or 8.25,
        "water_ml": normalize_optional_float(payload.get("water_ml")) or 150,
        "water_temp_c": normalize_optional_float(payload.get("water_temp_c")) or 93,
        "grind_setting": normalize_optional_text(payload.get("grind_setting")),
        "grinder": normalize_optional_text(payload.get("grinder")),
        "dry_aroma": normalize_optional_score(payload.get("dry_aroma"), "干香"),
        "wet_aroma": normalize_optional_score(payload.get("wet_aroma"), "湿香"),
        "acidity": normalize_optional_score(payload.get("acidity"), "酸质"),
        "sweetness": normalize_optional_score(payload.get("sweetness"), "甜感"),
        "bitterness": normalize_optional_score(payload.get("bitterness"), "苦感"),
        "body": normalize_optional_score(payload.get("body"), "醇厚"),
        "clarity": normalize_optional_score(payload.get("clarity"), "干净度"),
        "aftertaste": normalize_optional_score(payload.get("aftertaste"), "余韵"),
        "balance": normalize_optional_score(payload.get("balance"), "平衡"),
        "overall": normalize_optional_score(payload.get("overall"), "总评"),
        "flavor_notes": normalize_optional_text(payload.get("flavor_notes")),
        "defect_notes": normalize_optional_text(payload.get("defect_notes")),
        "conclusion": normalize_optional_text(payload.get("conclusion")),
        "next_roast_adjustment": normalize_optional_text(payload.get("next_roast_adjustment")),
    }


def create_cupping_record(roast_id, payload):
    with get_db_connection() as connection:
        roast = connection.execute("SELECT id FROM roast_batches WHERE id = ?", (roast_id,)).fetchone()
    if roast is None:
        raise KeyError("烘焙记录不存在")

    item = normalize_cupping_payload(roast_id, payload)
    now = datetime.now().isoformat(timespec="seconds")
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO cupping_records (
                roast_id, cupping_date, rest_hours, dose_g, water_ml, water_temp_c,
                grind_setting, grinder, dry_aroma, wet_aroma, acidity, sweetness,
                bitterness, body, clarity, aftertaste, balance, overall, flavor_notes,
                defect_notes, conclusion, next_roast_adjustment, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["roast_id"],
                item["cupping_date"],
                item["rest_hours"],
                item["dose_g"],
                item["water_ml"],
                item["water_temp_c"],
                item["grind_setting"],
                item["grinder"],
                item["dry_aroma"],
                item["wet_aroma"],
                item["acidity"],
                item["sweetness"],
                item["bitterness"],
                item["body"],
                item["clarity"],
                item["aftertaste"],
                item["balance"],
                item["overall"],
                item["flavor_notes"],
                item["defect_notes"],
                item["conclusion"],
                item["next_roast_adjustment"],
                now,
                now,
            ),
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET cupping_date = ?, cupping_score = ?, cupping_notes = ?, defects = ?,
                next_adjustment = COALESCE(NULLIF(?, ''), next_adjustment),
                updated_at = ?
            WHERE id = ?
            """,
            (
                item["cupping_date"],
                item["overall"],
                item["flavor_notes"] or item["conclusion"],
                item["defect_notes"],
                item["next_roast_adjustment"],
                now,
                roast_id,
            ),
        )
        connection.commit()
        cupping_id = cursor.lastrowid
    return get_cupping_record(cupping_id)


def get_cupping_record(cupping_id):
    with get_db_connection() as connection:
        row = connection.execute("SELECT * FROM cupping_records WHERE id = ?", (cupping_id,)).fetchone()
    if row is None:
        raise KeyError("杯测记录不存在")
    return row_to_cupping_payload(row)


def row_to_cupping_payload(row):
    payload = {key: row[key] for key in row.keys()}
    for key in ("rest_hours", "dose_g", "water_ml", "water_temp_c"):
        payload[key] = clean_number(payload[key])
    return payload


def fetch_roast_compare(ids):
    roast_ids = []
    for raw_id in ids:
        if raw_id in (None, ""):
            continue
        try:
            roast_ids.append(int(raw_id))
        except (TypeError, ValueError) as exc:
            raise ValueError("烘焙记录 ID 不合法") from exc
    if len(roast_ids) < 2 or len(roast_ids) > 4:
        raise ValueError("对比需要选择 2-4 锅")
    placeholders = ",".join("?" for _ in roast_ids)
    with get_db_connection() as connection:
        rows = connection.execute(
            roast_select_sql()
            + f"""
            WHERE roast_batches.id IN ({placeholders})
            ORDER BY roast_date DESC, roast_batches.id DESC
            """,
            roast_ids,
        ).fetchall()
    return {"items": [row_to_roast_payload(row) for row in rows]}


def normalize_brew_payload(payload):
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise ValueError("冲煮记录内容不合法")
    return {
        "bean_id": validate_existing_bean_id(payload.get("bean_id")),
        "brew_date": validate_date(payload.get("brew_date"), "冲煮日期"),
        "data": normalize_brew_data(data),
    }


def normalize_brew_data(data):
    if any(key in data for key in ("bean_context", "technique", "tasting", "improvement")):
        return {
            "bean_context": dict(data.get("bean_context") or {}),
            "technique": dict(data.get("technique") or {}),
            "tasting": dict(data.get("tasting") or {}),
            "improvement": dict(data.get("improvement") or {}),
        }

    return {
        "bean_context": {
            "roast_degree": data.get("roast_degree", ""),
            "warming_time": data.get("warming_time", ""),
        },
        "technique": {
            "water_type": data.get("water_type", ""),
            "water_tds": data.get("water_tds", ""),
            "water_mg_ca": data.get("water_mg_ca", ""),
            "grinder": data.get("grinder", ""),
            "dripper": data.get("dripper", ""),
            "filter_paper": data.get("filter_paper", ""),
            "kettle": data.get("kettle", ""),
            "dose": data.get("dose", ""),
            "yield": data.get("yield", ""),
            "ratio": data.get("ratio", ""),
            "grind_size": data.get("grind_size") or data.get("used_grind", ""),
            "water_temperature": data.get("water_temperature", ""),
            "roaster_recommended_grind": data.get("recommended_grind", ""),
            "flow_judgement": data.get("flow_judgement", []),
            "coffee_bed": data.get("coffee_bed", []),
            "grind_notes": data.get("grind_notes", ""),
            "bloom": data.get("bloom", ""),
            "pour_method": data.get("pour_method", ""),
            "total_time": data.get("total_time", ""),
            "extraction_observation": data.get("extraction_observation", []),
            "extraction_notes": data.get("extraction_notes", ""),
        },
        "tasting": {
            "acidity_style": data.get("acidity_style", ""),
            "sweetness_style": data.get("sweetness_style", ""),
            "clarity_style": data.get("clarity_style", ""),
            "finish_style": data.get("finish_style", ""),
            "score": data.get("score", ""),
            "flavor_direction": data.get("flavor_direction", []),
            "flavor_description": data.get("flavor_description", ""),
            "structure_acidity": data.get("structure_acidity", ""),
            "structure_sweetness": data.get("structure_sweetness", ""),
            "structure_body": data.get("structure_body", ""),
            "structure_cleanliness": data.get("structure_cleanliness", ""),
            "structure_clarity": data.get("structure_clarity", ""),
            "structure_balance": data.get("structure_balance", ""),
            "aftertaste_length": data.get("aftertaste_length", ""),
            "aftertaste_type": data.get("aftertaste_type", ""),
            "retronasal": data.get("retronasal", ""),
            "defects": data.get("defects", ""),
        },
        "improvement": {
            "next_adjustment": data.get("next_adjustment", ""),
        },
    }


def row_to_brew_payload(row):
    data = normalize_brew_data(json.loads(row["data_json"] or "{}"))
    bean = {
        "id": row["bean_id"],
        "name": row["bean_name"],
        "roaster": row["roaster"],
        "country": row["country"],
        "region": row["region"],
        "producer": row["producer"],
        "lot_info": row["lot_info"],
        "variety_name": row["variety_name"],
        "roaster_recommendation": row["roaster_recommendation"],
        "roast_date": row["roast_date"],
        "storage_state": row["storage_state"],
        "process": row["process"],
    }
    return {
        "id": row["id"],
        "bean_id": row["bean_id"],
        "brew_date": row["brew_date"],
        "data": data,
        "bean": bean,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_brew_records():
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                brew_records.id,
                brew_records.bean_id,
                brew_records.brew_date,
                brew_records.data_json,
                brew_records.created_at,
                brew_records.updated_at,
                beans.bean_name,
                beans.roaster,
                COALESCE(NULLIF(TRIM(beans.country), ''), beans.origin) AS country,
                beans.region,
                COALESCE(NULLIF(TRIM(beans.producer), ''), beans.estate) AS producer,
                COALESCE(
                    NULLIF(TRIM(beans.lot_info), ''),
                    TRIM(
                        CASE
                            WHEN TRIM(COALESCE(beans.plot, '')) <> '' AND TRIM(COALESCE(beans.batch, '')) <> ''
                                THEN beans.plot || ' / ' || beans.batch
                            WHEN TRIM(COALESCE(beans.plot, '')) <> ''
                                THEN beans.plot
                            ELSE beans.batch
                        END
                    )
                ) AS lot_info,
                beans.variety_name,
                beans.roaster_recommendation,
                beans.roast_date,
                beans.storage_state,
                beans.process
            FROM brew_records
            JOIN beans ON beans.id = brew_records.bean_id
            ORDER BY brew_records.brew_date DESC, brew_records.id DESC
            """
        ).fetchall()
    return {"items": [row_to_brew_payload(row) for row in rows]}


def get_brew_record(record_id):
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT
                brew_records.id,
                brew_records.bean_id,
                brew_records.brew_date,
                brew_records.data_json,
                brew_records.created_at,
                brew_records.updated_at,
                beans.bean_name,
                beans.roaster,
                COALESCE(NULLIF(TRIM(beans.country), ''), beans.origin) AS country,
                beans.region,
                COALESCE(NULLIF(TRIM(beans.producer), ''), beans.estate) AS producer,
                COALESCE(
                    NULLIF(TRIM(beans.lot_info), ''),
                    TRIM(
                        CASE
                            WHEN TRIM(COALESCE(beans.plot, '')) <> '' AND TRIM(COALESCE(beans.batch, '')) <> ''
                                THEN beans.plot || ' / ' || beans.batch
                            WHEN TRIM(COALESCE(beans.plot, '')) <> ''
                                THEN beans.plot
                            ELSE beans.batch
                        END
                    )
                ) AS lot_info,
                beans.variety_name,
                beans.roaster_recommendation,
                beans.roast_date,
                beans.storage_state,
                beans.process
            FROM brew_records
            JOIN beans ON beans.id = brew_records.bean_id
            WHERE brew_records.id = ?
            """,
            (record_id,),
        ).fetchone()
    if row is None:
        raise KeyError("冲煮记录不存在")
    return row_to_brew_payload(row)


def create_brew_record(payload):
    record = normalize_brew_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    data_json = json.dumps(record["data"], ensure_ascii=False)
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO brew_records (bean_id, brew_date, data_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (record["bean_id"], record["brew_date"], data_json, now, now),
        )
        connection.commit()
        record_id = cursor.lastrowid
    return get_brew_record(record_id)


def update_brew_record(record_id, payload):
    record = normalize_brew_payload(payload)
    now = datetime.now().isoformat(timespec="seconds")
    data_json = json.dumps(record["data"], ensure_ascii=False)
    with get_db_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE brew_records
            SET bean_id = ?, brew_date = ?, data_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (record["bean_id"], record["brew_date"], data_json, now, record_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("冲煮记录不存在")
    return get_brew_record(record_id)


def delete_brew_record(record_id):
    with get_db_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM personal_tastings WHERE cup=? LIMIT 1",
                              (f"brew-{record_id}",)).fetchone():
            raise ValueError("这杯已有个人品饮记录，不能删除")
        cursor = connection.execute("DELETE FROM brew_records WHERE id = ?", (record_id,))
        connection.commit()
    if cursor.rowcount == 0:
        raise KeyError("冲煮记录不存在")
