import sqlite3
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "coffee_inventory.db"


def get_db_connection():
    """Create a SQLite connection with rows addressable by column name."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    """Create and migrate the local database schema.

    Data model:
    - beans: coffee-bean identity and inventory state. This is the bean's
      relatively stable "DNA": name, roaster, origin hierarchy, process,
      roast date, storage state, current weight, and current value.
    - brew_records: brewing logs linked to one bean. The mutable log body is
      stored as JSON so the brew template can evolve without adding a column
      for every tasting or recipe field.

    Migration policy:
    The app is intentionally lightweight and runs without Alembic or another
    migration tool. Each new column is added idempotently after inspecting
    PRAGMA table_info, then legacy columns are copied into the newer fields.
    """
    with get_db_connection() as connection:
        # Bean identity plus inventory counters. origin/estate/plot/batch are
        # legacy compatibility fields; country/region/producer/lot_info are the
        # canonical fields used by the current UI and API payloads.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS beans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bean_name TEXT NOT NULL,
                roaster TEXT NOT NULL,
                origin TEXT NOT NULL DEFAULT '',
                estate TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                producer TEXT NOT NULL DEFAULT '',
                lot_info TEXT NOT NULL DEFAULT '',
                variety_name TEXT NOT NULL DEFAULT '',
                roaster_recommendation TEXT NOT NULL DEFAULT '',
                roast_date TEXT NOT NULL DEFAULT '',
                storage_state TEXT NOT NULL DEFAULT '常温',
                process TEXT NOT NULL,
                plot TEXT NOT NULL,
                batch TEXT NOT NULL,
                net_weight INTEGER CHECK(net_weight >= 0),
                price_total REAL CHECK(price_total >= 0),
                created_at TEXT NOT NULL
            )
            """
        )
        # Brew logs keep relational identity (bean_id/date/timestamps) in
        # columns, while detailed brew/tasting data lives in data_json.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS brew_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bean_id INTEGER NOT NULL,
                brew_date TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (bean_id) REFERENCES beans(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS green_beans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                origin TEXT NOT NULL DEFAULT '',
                crop_season TEXT NOT NULL DEFAULT '',
                region TEXT NOT NULL DEFAULT '',
                bean_type TEXT NOT NULL DEFAULT '',
                estate TEXT NOT NULL DEFAULT '',
                variety_name TEXT NOT NULL DEFAULT '',
                plot TEXT NOT NULL DEFAULT '',
                batch TEXT NOT NULL DEFAULT '',
                flavor_notes TEXT NOT NULL DEFAULT '',
                supplier TEXT NOT NULL DEFAULT '',
                process TEXT NOT NULL DEFAULT '',
                moisture_pct REAL NULL,
                density REAL NULL,
                purchase_weight_g REAL NULL,
                remaining_green_weight_g REAL NULL,
                notes TEXT NOT NULL DEFAULT '',
                total_weight INTEGER NOT NULL CHECK(total_weight >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("""CREATE TABLE IF NOT EXISTS tasters (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS personal_tastings (
            person_id INTEGER NOT NULL REFERENCES tasters(id), cup TEXT NOT NULL,
            feedback TEXT NOT NULL, revision INTEGER NOT NULL,
            PRIMARY KEY (person_id, cup)
        )""")
        green_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(green_beans)").fetchall()
        }
        if "name" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        if "origin" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
        if "moisture_pct" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN moisture_pct REAL NULL")
        if "density" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN density REAL NULL")
        if "purchase_weight_g" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN purchase_weight_g REAL NULL")
        if "remaining_green_weight_g" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN remaining_green_weight_g REAL NULL")
        if "notes" not in green_columns:
            connection.execute("ALTER TABLE green_beans ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        connection.execute(
            """
            UPDATE green_beans
            SET name = TRIM(
                CASE
                    WHEN TRIM(COALESCE(crop_season, '')) <> ''
                        THEN crop_season || ' · ' || region || ' · ' || estate || ' · ' || COALESCE(NULLIF(variety_name, ''), bean_type)
                    ELSE region || ' · ' || estate || ' · ' || COALESCE(NULLIF(variety_name, ''), bean_type)
                END
            )
            WHERE TRIM(COALESCE(name, '')) = ''
            """
        )
        connection.execute(
            """
            UPDATE green_beans
            SET origin = TRIM(
                CASE
                    WHEN TRIM(COALESCE(region, '')) <> '' AND TRIM(COALESCE(estate, '')) <> ''
                        THEN region || ' / ' || estate
                    WHEN TRIM(COALESCE(region, '')) <> ''
                        THEN region
                    ELSE estate
                END
            )
            WHERE TRIM(COALESCE(origin, '')) = ''
            """
        )
        connection.execute(
            """
            UPDATE green_beans
            SET purchase_weight_g = total_weight
            WHERE purchase_weight_g IS NULL
            """
        )
        connection.execute(
            """
            UPDATE green_beans
            SET remaining_green_weight_g = total_weight
            WHERE remaining_green_weight_g IS NULL
            """
        )
        connection.execute(
            """
            UPDATE green_beans
            SET notes = flavor_notes
            WHERE TRIM(COALESCE(notes, '')) = '' AND TRIM(COALESCE(flavor_notes, '')) <> ''
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roast_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roast_date TEXT NOT NULL,
                bean_id INTEGER NULL,
                bean_batch_id INTEGER NULL,
                roasted_bean_id INTEGER NULL,
                bean_name_snapshot TEXT NOT NULL,
                bean_origin TEXT NULL,
                bean_process TEXT NULL,
                bean_variety TEXT NULL,
                roaster_model TEXT DEFAULT 'Santoker Cube10',
                roast_label TEXT NULL,
                batch_weight_g REAL NOT NULL,
                roasted_weight_g REAL NULL,
                cupping_reserved_g REAL DEFAULT 8.25,
                drinkable_weight_g REAL NULL,
                weight_loss_g REAL NULL,
                weight_loss_pct REAL NULL,
                profile_name TEXT NULL,
                charge_temp_c REAL NULL,
                preheat_temp_c REAL NULL,
                ambient_temp_c REAL NULL,
                fan_start INTEGER NULL,
                heat_start INTEGER NULL,
                operation_plan TEXT NULL,
                plan_yellow_time_s INTEGER NULL,
                plan_yellow_temp_c REAL NULL,
                plan_first_crack_time_s INTEGER NULL,
                plan_first_crack_temp_c REAL NULL,
                plan_drop_time_s INTEGER NULL,
                plan_drop_temp_c REAL NULL,
                plan_note TEXT NULL,
                yellow_time_sec INTEGER NULL,
                yellow_temp_c REAL NULL,
                first_crack_time_sec INTEGER NULL,
                first_crack_temp_c REAL NULL,
                drop_time_sec INTEGER NULL,
                drop_temp_c REAL NULL,
                actual_yellow_time_s INTEGER NULL,
                actual_yellow_temp_c REAL NULL,
                actual_first_crack_time_s INTEGER NULL,
                actual_first_crack_temp_c REAL NULL,
                actual_drop_time_s INTEGER NULL,
                actual_drop_temp_c REAL NULL,
                control_log TEXT NULL,
                roast_notes TEXT NULL,
                drying_time_sec INTEGER NULL,
                maillard_time_sec INTEGER NULL,
                development_time_sec INTEGER NULL,
                dtr_pct REAL NULL,
                yellow_to_fc_sec INTEGER NULL,
                fc_to_drop_temp_rise_c REAL NULL,
                experiment_goal TEXT NULL,
                changed_variable TEXT NULL,
                hypothesis TEXT NULL,
                result_summary TEXT NULL,
                next_adjustment TEXT NULL,
                roast_level TEXT NULL,
                color_note TEXT NULL,
                aroma_note TEXT NULL,
                defect_flags TEXT NULL,
                general_notes TEXT NULL,
                learning_note TEXT NULL,
                cupping_date TEXT NULL,
                cupping_score INTEGER NULL,
                cupping_notes TEXT NULL,
                defects TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (bean_id) REFERENCES green_beans(id),
                FOREIGN KEY (roasted_bean_id) REFERENCES beans(id)
            )
            """
        )
        roast_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(roast_batches)").fetchall()
        }
        roast_column_defaults = {
            "bean_batch_id": "INTEGER NULL",
            "roast_label": "TEXT NULL",
            "plan_yellow_time_s": "INTEGER NULL",
            "plan_yellow_temp_c": "REAL NULL",
            "plan_first_crack_time_s": "INTEGER NULL",
            "plan_first_crack_temp_c": "REAL NULL",
            "plan_drop_time_s": "INTEGER NULL",
            "plan_drop_temp_c": "REAL NULL",
            "plan_note": "TEXT NULL",
            "actual_yellow_time_s": "INTEGER NULL",
            "actual_yellow_temp_c": "REAL NULL",
            "actual_first_crack_time_s": "INTEGER NULL",
            "actual_first_crack_temp_c": "REAL NULL",
            "actual_drop_time_s": "INTEGER NULL",
            "actual_drop_temp_c": "REAL NULL",
            "control_log": "TEXT NULL",
            "roast_notes": "TEXT NULL",
            "cupping_date": "TEXT NULL",
            "cupping_score": "INTEGER NULL",
            "cupping_notes": "TEXT NULL",
            "defects": "TEXT NULL",
        }
        for column_name, column_type in roast_column_defaults.items():
            if column_name not in roast_columns:
                connection.execute(f"ALTER TABLE roast_batches ADD COLUMN {column_name} {column_type}")
        if "learning_note" not in roast_columns:
            connection.execute("ALTER TABLE roast_batches ADD COLUMN learning_note TEXT NULL")
        connection.execute(
            """
            UPDATE roast_batches
            SET bean_batch_id = bean_id
            WHERE bean_batch_id IS NULL AND bean_id IS NOT NULL
            """
        )
        orphan_roast = connection.execute(
            """
            SELECT id
            FROM roast_batches
            WHERE bean_batch_id IS NULL
            LIMIT 1
            """
        ).fetchone()
        if orphan_roast is not None:
            uncategorized_batch = connection.execute(
                """
                SELECT id
                FROM green_beans
                WHERE name = '未分类生豆批次'
                ORDER BY id
                LIMIT 1
                """
            ).fetchone()
            if uncategorized_batch is None:
                cursor = connection.execute(
                    """
                    INSERT INTO green_beans (
                        name, origin, crop_season, region, bean_type, estate, variety_name,
                        plot, batch, flavor_notes, supplier, process, purchase_weight_g,
                        remaining_green_weight_g, notes, total_weight, created_at, updated_at
                    )
                    VALUES ('未分类生豆批次', '', '', '', '', '', '', '', '', '', '', '', NULL, 0, '旧烘焙记录无法识别生豆批次时自动归档', 0, DATETIME('now'), DATETIME('now'))
                    """
                )
                uncategorized_id = cursor.lastrowid
            else:
                uncategorized_id = uncategorized_batch["id"]
            connection.execute(
                """
                UPDATE roast_batches
                SET bean_batch_id = ?, bean_id = COALESCE(bean_id, ?)
                WHERE bean_batch_id IS NULL
                """,
                (uncategorized_id, uncategorized_id),
            )
        connection.execute(
            """
            UPDATE roast_batches
            SET roast_label = profile_name
            WHERE TRIM(COALESCE(roast_label, '')) = '' AND TRIM(COALESCE(profile_name, '')) <> ''
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_yellow_time_s = yellow_time_sec
            WHERE actual_yellow_time_s IS NULL AND yellow_time_sec IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_yellow_temp_c = yellow_temp_c
            WHERE actual_yellow_temp_c IS NULL AND yellow_temp_c IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_first_crack_time_s = first_crack_time_sec
            WHERE actual_first_crack_time_s IS NULL AND first_crack_time_sec IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_first_crack_temp_c = first_crack_temp_c
            WHERE actual_first_crack_temp_c IS NULL AND first_crack_temp_c IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_drop_time_s = drop_time_sec
            WHERE actual_drop_time_s IS NULL AND drop_time_sec IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET actual_drop_temp_c = drop_temp_c
            WHERE actual_drop_temp_c IS NULL AND drop_temp_c IS NOT NULL
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET control_log = operation_plan
            WHERE TRIM(COALESCE(control_log, '')) = '' AND TRIM(COALESCE(operation_plan, '')) <> ''
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET roast_notes = general_notes
            WHERE TRIM(COALESCE(roast_notes, '')) = '' AND TRIM(COALESCE(general_notes, '')) <> ''
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roast_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roast_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                time_sec INTEGER NULL,
                temp_c REAL NULL,
                heat_setting INTEGER NULL,
                fan_setting INTEGER NULL,
                note TEXT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (roast_id) REFERENCES roast_batches(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roast_curve_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roast_id INTEGER NOT NULL,
                time_sec INTEGER NOT NULL,
                bean_temp_c REAL NULL,
                environment_temp_c REAL NULL,
                ror_c_per_min REAL NULL,
                heat_setting INTEGER NULL,
                fan_setting INTEGER NULL,
                FOREIGN KEY (roast_id) REFERENCES roast_batches(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cupping_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roast_id INTEGER NOT NULL,
                cupping_date TEXT NOT NULL,
                rest_hours REAL NULL,
                dose_g REAL DEFAULT 8.25,
                water_ml REAL DEFAULT 150,
                water_temp_c REAL DEFAULT 93,
                grind_setting TEXT NULL,
                grinder TEXT NULL,
                dry_aroma INTEGER NULL,
                wet_aroma INTEGER NULL,
                acidity INTEGER NULL,
                sweetness INTEGER NULL,
                bitterness INTEGER NULL,
                body INTEGER NULL,
                clarity INTEGER NULL,
                aftertaste INTEGER NULL,
                balance INTEGER NULL,
                overall INTEGER NULL,
                flavor_notes TEXT NULL,
                defect_notes TEXT NULL,
                conclusion TEXT NULL,
                next_roast_adjustment TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (roast_id) REFERENCES roast_batches(id)
            )
            """
        )
        connection.execute(
            """
            UPDATE roast_batches
            SET cupping_date = (
                    SELECT cupping_date
                    FROM cupping_records
                    WHERE cupping_records.roast_id = roast_batches.id
                    ORDER BY cupping_date DESC, id DESC
                    LIMIT 1
                ),
                cupping_score = (
                    SELECT overall
                    FROM cupping_records
                    WHERE cupping_records.roast_id = roast_batches.id
                    ORDER BY cupping_date DESC, id DESC
                    LIMIT 1
                ),
                cupping_notes = (
                    SELECT COALESCE(NULLIF(flavor_notes, ''), conclusion)
                    FROM cupping_records
                    WHERE cupping_records.roast_id = roast_batches.id
                    ORDER BY cupping_date DESC, id DESC
                    LIMIT 1
                ),
                defects = (
                    SELECT defect_notes
                    FROM cupping_records
                    WHERE cupping_records.roast_id = roast_batches.id
                    ORDER BY cupping_date DESC, id DESC
                    LIMIT 1
                )
            WHERE cupping_date IS NULL
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roast_inventory_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                roast_id INTEGER NULL,
                bean_id INTEGER NULL,
                transaction_type TEXT NOT NULL,
                weight_g REAL NOT NULL,
                note TEXT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (roast_id) REFERENCES roast_batches(id)
            )
            """
        )

        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(beans)").fetchall()
        }

        # Idempotent column migrations for databases created by older versions
        # of the app. Defaults are chosen so existing rows remain valid.
        if "origin" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN origin TEXT NOT NULL DEFAULT ''")
        if "estate" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN estate TEXT NOT NULL DEFAULT ''")
        if "country" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN country TEXT NOT NULL DEFAULT ''")
        if "region" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN region TEXT NOT NULL DEFAULT ''")
        if "producer" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN producer TEXT NOT NULL DEFAULT ''")
        if "lot_info" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN lot_info TEXT NOT NULL DEFAULT ''")
        if "variety_name" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN variety_name TEXT NOT NULL DEFAULT ''")
        if "roaster_recommendation" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN roaster_recommendation TEXT NOT NULL DEFAULT ''")
        if "roast_date" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN roast_date TEXT NOT NULL DEFAULT ''")
        if "storage_state" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN storage_state TEXT NOT NULL DEFAULT '常温'")

        if "import_json" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN import_json TEXT")
        if "total_weight" not in columns:
            connection.execute("ALTER TABLE beans ADD COLUMN total_weight INTEGER CHECK(total_weight >= 0)")
            # Only imported package capacity establishes an original amount.
            for row in connection.execute("SELECT id,net_weight,import_json FROM beans WHERE import_json IS NOT NULL").fetchall():
                capacity = json.loads(row["import_json"]).get("capacity")
                if (isinstance(capacity, str) and capacity.isascii() and capacity.isdecimal()
                        and (row["net_weight"] is None or int(capacity) >= row["net_weight"])):
                    connection.execute("UPDATE beans SET total_weight=? WHERE id=?", (int(capacity), row["id"]))
        connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS beans_source_id
                              ON beans(json_extract(import_json,'$.id')) WHERE import_json IS NOT NULL""")
        # Older inventories required numbers. A photographed bag can have no known weight or price.
        for field, kind in (("net_weight", "INTEGER"), ("price_total", "REAL")):
            info = {r["name"]: r for r in connection.execute("PRAGMA table_info(beans)")}
            if info[field]["notnull"]:
                connection.execute(f"ALTER TABLE beans ADD COLUMN new_{field} {kind} CHECK(new_{field} >= 0)")
                connection.execute(f"UPDATE beans SET new_{field} = {field}")
                connection.execute(f"ALTER TABLE beans DROP COLUMN {field}")
                connection.execute(f"ALTER TABLE beans RENAME COLUMN new_{field} TO {field}")

        # Backfill legacy origin/estate values into the newer canonical fields.
        if "origin" in columns:
            connection.execute(
                """
                UPDATE beans
                SET estate = origin
                WHERE TRIM(COALESCE(estate, '')) = '' AND import_json IS NULL
                """
            )
            connection.execute(
                """
                UPDATE beans
                SET origin = estate
                WHERE TRIM(COALESCE(origin, '')) = ''
                """
            )

        # Normalize derived fields that older rows may not have populated.
        connection.execute(
            """
            UPDATE beans
            SET country = origin
            WHERE TRIM(COALESCE(country, '')) = '' AND TRIM(COALESCE(origin, '')) <> ''
            """
        )
        connection.execute(
            """
            UPDATE beans
            SET producer = estate
            WHERE TRIM(COALESCE(producer, '')) = '' AND TRIM(COALESCE(estate, '')) <> ''
            """
        )
        connection.execute(
            """
            UPDATE beans
            SET lot_info = TRIM(
                CASE
                    WHEN TRIM(COALESCE(plot, '')) <> '' AND TRIM(COALESCE(batch, '')) <> ''
                        THEN plot || ' / ' || batch
                    WHEN TRIM(COALESCE(plot, '')) <> ''
                        THEN plot
                    ELSE batch
                END
            )
            WHERE TRIM(COALESCE(lot_info, '')) = ''
            """
        )
        connection.execute(
            """
            UPDATE beans
            SET roast_date = COALESCE(NULLIF(SUBSTR(created_at, 1, 10), ''), DATE('now'))
            WHERE TRIM(COALESCE(roast_date, '')) = '' AND import_json IS NULL
            """
        )
        connection.commit()
