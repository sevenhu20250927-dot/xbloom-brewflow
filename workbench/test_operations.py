import unittest

from operations import calculate_roast_metrics, format_seconds, parse_time_to_seconds


class RoastCalculationTests(unittest.TestCase):
    def test_parse_time_to_seconds_accepts_mmss_and_seconds(self):
        self.assertEqual(parse_time_to_seconds("3:53"), 233)
        self.assertEqual(parse_time_to_seconds("03:05"), 185)
        self.assertEqual(parse_time_to_seconds("245"), 245)
        self.assertEqual(format_seconds(233), "3:53")

    def test_calculate_weight_loss_development_and_dtr(self):
        metrics = calculate_roast_metrics(
            batch_weight_g=100,
            roasted_weight_g=86,
            yellow_time_sec=190,
            first_crack_time_sec=245,
            drop_time_sec=300,
        )

        self.assertEqual(metrics["weight_loss_g"], 14)
        self.assertEqual(metrics["weight_loss_pct"], 14)
        self.assertEqual(metrics["development_time_sec"], 55)
        self.assertEqual(metrics["dtr_pct"], 18.33)
        self.assertEqual(metrics["drying_time_sec"], 190)
        self.assertEqual(metrics["maillard_time_sec"], 55)

    def test_time_order_validation(self):
        with self.assertRaisesRegex(ValueError, "黄点时间必须早于一爆时间"):
            calculate_roast_metrics(
                batch_weight_g=100,
                yellow_time_sec=200,
                first_crack_time_sec=200,
            )

        with self.assertRaisesRegex(ValueError, "一爆时间必须早于下豆时间"):
            calculate_roast_metrics(
                batch_weight_g=100,
                first_crack_time_sec=260,
                drop_time_sec=250,
            )



class InventoryTotalWeightTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import schema
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch = patch.object(schema, "DB_PATH", Path(self.temp.name) / "stock.db")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        schema.init_db()
        self.payload = dict(name="测试批次", roaster="测试", country="危地马拉", producer="庄园",
                            process="水洗", roast_date="2026-08-15", net_weight=70,
                            total_weight=100, price_total=140)

    def test_original_weight_survives_consumption_and_old_client_edit(self):
        from operations import create_item, deduct_item, adjust_item, update_item, get_item
        item = create_item(self.payload)
        item = deduct_item(item["id"], 15, 0)
        self.assertEqual((item["total_weight"], item["net_weight"]), (100, 55))
        old_payload = dict(self.payload, net_weight=55)
        del old_payload["total_weight"]
        item = update_item(item["id"], old_payload)
        self.assertEqual(item["total_weight"], 100)
        with self.assertRaisesRegex(ValueError, "剩余克数不能超过"):
            update_item(item["id"], dict(self.payload, total_weight=20))
        self.assertEqual(get_item(item["id"])["net_weight"], 55)
        item = adjust_item(item["id"], 100, 200)
        self.assertEqual((item["total_weight"], item["net_weight"]), (200, 155))
        item = deduct_item(item["id"], 155, 0)
        self.assertEqual((item["total_weight"], item["net_weight"]), (200, 0))

    def test_capacity_backfill_once_unknown_stays_unknown(self):
        import json
        import schema
        from operations import create_item, get_item, update_item
        ids = []
        for capacity in ("100", ""):
            item = create_item(self.payload)
            ids.append(item["id"])
            with schema.get_db_connection() as db:
                db.execute("UPDATE beans SET import_json=? WHERE id=?",
                           (json.dumps({"id": str(item["id"]), "capacity": capacity}), item["id"]))
        with schema.get_db_connection() as db:
            db.execute("ALTER TABLE beans DROP COLUMN total_weight")
        schema.init_db()
        self.assertEqual(get_item(ids[0])["total_weight"], 100)
        self.assertIsNone(get_item(ids[1])["total_weight"])
        update_item(ids[0], dict(self.payload, total_weight=120))
        schema.init_db()
        self.assertEqual(get_item(ids[0])["total_weight"], 120)
        for bad in (-1, 20.5, True, float("nan")):
            with self.assertRaises(ValueError):
                update_item(ids[0], dict(self.payload, total_weight=bad))


if __name__ == "__main__":
    unittest.main()
