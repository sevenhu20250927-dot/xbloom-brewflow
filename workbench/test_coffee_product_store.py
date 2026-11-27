"""Synthetic business flows in retained temporary SQLite files only.

No production DB, schema.init_db(), network, model, Runner or device simulation.
claim_start tests only the persisted dispatch intent; nothing consumes it.
The user requested that temporary databases remain available for inspection.
"""

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from coffee_product import ai_planning, planning
from coffee_product.store import ProductError, Store


class ProductDataFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validation_root = Path(tempfile.mkdtemp(prefix="coffee-product-validation-"))

    @classmethod
    def tearDownClass(cls):
        print(f"\nRetained synthetic SQLite fixtures: {cls.validation_root}")

    def setUp(self):
        self.db_path = self.validation_root / f"{self._testMethodName}.sqlite"
        db = sqlite3.connect(self.db_path)
        try:
            db.executescript("""
                CREATE TABLE beans (
                    id INTEGER PRIMARY KEY, bean_name TEXT NOT NULL,
                    roaster TEXT NOT NULL, country TEXT, process TEXT NOT NULL,
                    variety_name TEXT, roast_date TEXT, storage_state TEXT,
                    net_weight REAL CHECK(net_weight >= 0), total_weight REAL,
                    price_total REAL, import_json TEXT NOT NULL);
                CREATE TABLE brew_records (
                    id INTEGER PRIMARY KEY, bean_id INTEGER NOT NULL REFERENCES beans(id),
                    brew_date TEXT NOT NULL, data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE tasters (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
                CREATE TABLE personal_tastings (
                    person_id INTEGER NOT NULL REFERENCES tasters(id), cup TEXT NOT NULL,
                    feedback TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(person_id,cup));
            """)
            for bean_id, process, roast_date in ((1, "水洗", "2026-11-01"), (2, "日晒", "2026-11-10")):
                db.execute("""INSERT INTO beans VALUES
                    (?, '同名测试豆', '测试烘焙商', '测试产国', ?, '测试品种', ?,
                     '常温', 100.0, 250.0, 40.0, ?)""",
                           (bean_id, process, roast_date, json.dumps({"flavor": ["测试香气"]})))
            db.executemany("INSERT INTO tasters VALUES (?,?)", ((1, "制作人样例"), (2, "客人样例")))
            db.commit()
        finally:
            db.close()
        self.store = Store(self.db_path)
        self.store.init_schema()
        self.sequence = 0

    def key(self):
        self.sequence += 1
        return f"fixture-{self.sequence}"

    def rows(self, sql, params=()):
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True)
        try:
            return db.execute(sql, params).fetchall()
        finally:
            db.close()

    def error(self, status, action, *args):
        with self.assertRaises(ProductError) as caught:
            action(*args)
        self.assertEqual(caught.exception.status, status)

    def recipe_data(self, bean_id=1, mode="xbloom", goal="保持", base=None):
        suggestion = planning.suggest(self.store.get_bean(bean_id), mode=mode, goal=goal, base=base)
        data = {key: suggestion[key] for key in
                ("title", "mode", "goal", "payload", "rationale", "evidence", "risks")}
        data.update(request_id=self.key(), bean_id=bean_id)
        if base is not None:
            data["parent_id"] = base["id"]
        return data

    def recipe(self, bean_id=1, mode="xbloom", goal="保持", base=None):
        return self.store.create_recipe(self.recipe_data(bean_id, mode, goal, base))

    def brew(self, recipe=None, order_id=None):
        recipe = recipe or self.recipe()
        data = dict(request_id=self.key(), bean_id=recipe["bean_id"],
                    recipe_id=recipe["id"], mode=recipe["mode"])
        if order_id is not None:
            data["order_id"] = order_id
        return self.store.create_brew(data)

    def record(self, brew, status="completed", grams=None):
        data = dict(request_id=self.key(), status=status,
                    observations={"note": "临时库人工结果样例，未运行设备", "screen_seconds": None})
        if grams is not None:
            data["consumption_g"] = grams
        return self.store.record_brew(brew["id"], data)

    def feedback(self, brew, person=1, score=7, revision=0, taste="中温反馈样例"):
        return self.store.save_feedback(dict(person_id=person, cup=f"brew-{brew['id']}",
                                              feedback={"overall": score, "taste": taste}, revision=revision))

    def experience_data(self, brew, person=1):
        return dict(request_id=self.key(), bean_id=brew["bean_id"], condition="同批豆、同设备的测试条件",
                    action="研磨细一格", expected="甜感改善且不增加涩感", source_brew_id=brew["id"],
                    source_person_id=person, notes="经验候选样例，不是实冲事实")

    def start_data(self, recipe):
        return dict(request_id=self.key(), reviewed_sha256=recipe["sha256"], confirm_start=True,
                    address="database-only-no-device", brewer="制作人样例")

    def test_prestart_retry_requires_complete_evidence_and_dispatches_once(self):
        from coffee_product.server import BrewRunner
        runner = BrewRunner(self.store, self.validation_root / self._testMethodName, "python3", False)
        recipe = self.recipe()
        order = self.store.create_order(self.order_data())
        bid = self.brew(recipe, order_id=order["id"])["id"]
        first = self.start_data(recipe)
        self.store.claim_start(bid, first)
        directory = runner.output / f"brew-{bid}"
        directory.mkdir(parents=True)
        path = directory / "20261125T075930Z-12300aa00000.jsonl"
        events = [dict(kind="session", operation="brew", recipe_sha256=recipe["sha256"], address=first["address"]),
                  dict(kind="report_context", brewer=first["brewer"]), dict(kind="tx_intent", label="handshake"),
                  dict(kind="disconnected", expected=True), dict(kind="error", error="No matching machine evidence within observation window")]
        def write(items):
            path.write_text("".join(json.dumps(dict(event, seq=i)) + "\n" for i, event in enumerate(items)))
        write(events)
        brew = self.store.finish_capture(bid, str(path), None, error="timeout")
        self.assertEqual(runner.capture_phase(brew), "handshake_timeout")
        for event in (dict(kind="tx_intent", label="start_commit"), dict(kind="start_unconfirmed"),
                      dict(kind="write_uncertain"), dict(kind="decoded", data={"kind":"state","state":"brewing"})):
            write(events[:3] + [event] + events[3:])
            self.assertIsNone(runner.retry_details(brew))
        write(events)
        with path.open("ab") as f:
            f.write(b'{"partial"')
        self.assertIsNone(runner.retry_details(brew))
        write(events)
        proof = runner.retry_details(brew)
        retry = dict(first, request_id=self.key(), retry_of=proof["token"])
        self.error(409, self.store.claim_start, bid, retry)
        self.assertTrue(self.store.claim_start(bid, retry, retry_proof=proof)["dispatch"])
        self.assertFalse(self.store.claim_start(bid, retry)["dispatch"])
        with self.assertRaises(ProductError):
            self.store.claim_start(bid, dict(retry, request_id=self.key()), retry_proof=proof)
        self.assertEqual(self.store.get_brew(bid)["order_id"], order["id"])
        self.assertIsNone(self.store.get_brew(bid)["consumption_g"])
        self.assertTrue(path.is_file())

    def test_water_indicators_are_visible_before_start_and_clear_on_recovery(self):
        from coffee_product.server import BrewProgress
        path = self.validation_root / "water-events.jsonl"
        progress = BrewProgress()
        for data, expected in [
            ({"kind":"legacy_event", "code":40522, "event_name":"no_water"}, "registered"),
            ({"kind":"machine_info", "water_source":"plumbed", "water_ok":False}, "registered"),
            ({"kind":"machine_info", "water_source":"tank", "water_ok":False}, "no_water"),
            ({"kind":"machine_info", "water_source":"tank", "water_ok":True}, "registered"),
            ({"kind":"state", "state":"no_water"}, "no_water"),
            ({"kind":"state", "state":"idle"}, "registered")]:
            with path.open("a") as f:
                f.write(json.dumps({"kind":"decoded", "data":data}) + "\n")
            self.assertEqual(progress.read(path), expected)

    def order_data(self, **changes):
        return dict(request_id=self.key(), bean_id=1, person_id=2, mode="xbloom", note="") | changes

    def order_action(self, order, **changes):
        expected = {key: order[key] for key in ("bean_id", "person_id", "mode", "note", "status")}
        return dict(request_id=self.key(), expected=expected) | changes

    def test_preferences_remain_personal_versioned_replayable_and_clearable(self):
        self.assertEqual(self.store.state()["preferences"], [])
        first = dict(request_id=self.key(), person_id=1, preference_text="喜欢轻盈", expected_revision=0)
        saved = self.store.save_preference(first)
        self.assertEqual(self.store.save_preference(first), saved)
        self.store.save_preference(dict(request_id=self.key(), person_id=2,
                                        preference_text="喜欢浓郁", expected_revision=0))
        self.error(409, self.store.save_preference, dict(first, request_id=self.key(), preference_text="旧页面改写"))
        self.error(404, self.store.save_preference, dict(first, request_id=self.key(), person_id=999))
        self.error(400, self.store.save_preference, dict(first, request_id=self.key(), expected_revision=True))
        cleared = self.store.save_preference(dict(first, request_id=self.key(), preference_text="", expected_revision=1))
        self.assertEqual(cleared, {"person_id": 1, "preference_text": "", "revision": 2})
        restarted = Store(self.db_path)
        self.assertEqual(restarted.state()["preferences"], [cleared, {"person_id": 2, "preference_text": "喜欢浓郁", "revision": 1}])
        self.assertEqual(restarted.state()["feedback"], [])
        self.assertEqual(restarted.get_bean(1)["net_weight"], 100)

    def test_concurrent_preference_edits_do_not_overwrite_each_other(self):
        requests = [dict(request_id=self.key(), person_id=1, preference_text=value, expected_revision=0)
                    for value in ("偏好样例甲", "偏好样例乙")]
        def save(data):
            try:
                return self.store.save_preference(data)
            except ProductError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(save, requests))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(results.count(409), 1)
        self.assertEqual(self.store.state()["preferences"][0]["revision"], 1)

    def test_ai_recipe_must_cite_selected_person_preference_without_turning_it_into_a_score(self):
        for person_id, preference in ((1, "偏好轻盈"), (2, "偏好浓郁")):
            self.store.save_preference(dict(request_id=self.key(), person_id=person_id,
                                            preference_text=preference, expected_revision=0))
        context = ai_planning.build_context(self.store.state(), bean_id=1, person_id=1)
        self.assertEqual(context["request"]["target_person"]["preference_source"], "preference:1")
        self.assertIn("preference:1", context["required_citations"])
        self.assertIn("非当杯评分", context["sources"]["preference:1"]["title"])
        self.assertNotIn("preference:2", context["sources"])
        self.assertEqual(context["history"]["same_bean_feedback_count"], 0)
        proposal = planning.suggest(self.store.get_bean(1))
        result = {key: proposal[key] for key in ("title", "mode", "goal", "payload", "rationale", "risks")}
        result["bean_id"] = 1
        source_ids = ["bean:1", "preference:1", "yiyi-experience-library"]
        catalog = ai_planning.citation_catalog(context)
        result["citations"] = [next(n for n, (source, _) in catalog.items() if source == source_id)
                               for source_id in source_ids]
        checked = ai_planning.validate_output(json.dumps(result), context)
        self.assertTrue(any("preference:1" in evidence["title"] for evidence in checked["evidence"]))
        result["citations"] = [n for n in result["citations"] if catalog[n][0] != "preference:1"]
        with self.assertRaises(ai_planning.AiOutputError):
            ai_planning.validate_output(json.dumps(result), context)

    def test_repeated_and_concurrent_clicks_keep_one_unfinished_order(self):
        requests = [self.order_data(), self.order_data()]
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(self.store.create_order, requests))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(len(self.store.state()["orders"]), 1)
        order = results[0]
        self.error(409, self.store.create_order, self.order_data(note="变更备注须修改订单"))
        brew = self.brew(order_id=order["id"])
        self.assertEqual(self.store.create_order(self.order_data())["id"], order["id"])
        self.record(brew)
        second = self.store.create_order(self.order_data())
        self.assertNotEqual(second["id"], order["id"])
        self.assertEqual(self.store.get_bean(1)["net_weight"], 85)

    def test_order_edit_rejects_stale_duplicate_and_prepared_changes(self):
        order = self.store.create_order(self.order_data())
        data = self.order_action(order, bean_id=2, person_id=1, mode="manual", note="换为手冲")
        changed = self.store.update_order(order["id"], data)
        self.assertEqual((changed["bean_id"], changed["person_id"], changed["mode"], changed["note"]),
                         (2, 1, "manual", "换为手冲"))
        self.assertEqual(self.store.update_order(order["id"], data), changed)
        self.error(409, self.store.update_order, order["id"], dict(data, request_id=self.key()))
        self.error(409, self.store.cancel_order, order["id"], self.order_action(order))
        self.error(409, self.store.delete_order, order["id"], self.order_action(order))
        other = self.store.create_order(self.order_data())
        self.error(409, self.store.update_order, other["id"],
                   self.order_action(other, bean_id=2, person_id=1, mode="manual", note=""))
        recipe = self.recipe(bean_id=2, mode="manual")
        self.brew(recipe, changed["id"])
        prepared = next(o for o in self.store.state()["orders"] if o["id"] == changed["id"])
        self.error(409, self.store.update_order, prepared["id"],
                   self.order_action(prepared, bean_id=1, person_id=1, mode="manual", note=""))

    def test_cancel_prepared_order_retains_links_and_prevents_start_or_debit(self):
        order = self.store.create_order(self.order_data())
        recipe = self.recipe()
        brew = self.brew(recipe, order["id"])
        prepared = self.store.state()["orders"][0]
        data = self.order_action(prepared)
        cancelled = self.store.cancel_order(order["id"], data)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.store.cancel_order(order["id"], data), cancelled)
        self.assertEqual(self.store.get_brew(brew["id"])["status"], "cancelled")
        self.error(409, self.store.claim_start, brew["id"], self.start_data(recipe))
        self.error(409, self.record, brew, "completed", 15)
        self.error(409, self.store.delete_order, order["id"], self.order_action(cancelled))
        self.error(409, self.brew, recipe, order["id"])
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        self.assertEqual(len(self.store.state()["brews"]), 1)
        self.assertNotEqual(self.store.create_order(self.order_data())["id"], order["id"])

    def test_started_and_manually_recorded_orders_cannot_be_cancelled_or_deleted(self):
        order = self.store.create_order(self.order_data())
        recipe = self.recipe()
        brew = self.brew(recipe, order["id"])
        self.store.claim_start(brew["id"], self.start_data(recipe))
        running = self.store.state()["orders"][0]
        self.error(409, self.store.cancel_order, order["id"], self.order_action(running))
        self.error(409, self.store.delete_order, order["id"], self.order_action(running))
        self.store.finish_capture(brew["id"], None, None, "仅测试数据库状态，没有运行设备")
        self.record(brew, "unconfirmed", 15)
        recorded = self.store.state()["orders"][0]
        self.error(409, self.store.cancel_order, order["id"], self.order_action(recorded))
        self.error(409, self.store.delete_order, order["id"], self.order_action(recorded))
        self.assertEqual(self.store.get_bean(1)["net_weight"], 85)

    def test_delete_unused_order_hides_it_without_reusing_identity(self):
        order = self.store.create_order(self.order_data())
        cancelled = self.store.cancel_order(order["id"], self.order_action(order))
        data = self.order_action(cancelled)
        deleted = self.store.delete_order(order["id"], data)
        self.assertEqual(deleted["status"], "deleted")
        self.assertEqual(self.store.delete_order(order["id"], data), deleted)
        self.assertEqual(self.store.state()["orders"], [])
        replacement = self.store.create_order(self.order_data())
        self.assertNotEqual(replacement["id"], order["id"])
        self.error(409, self.brew, self.recipe(), order["id"])
        self.assertEqual(self.rows("SELECT status FROM product_orders WHERE id=?", (order["id"],)),
                         [("deleted",)])
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)

    def test_default_suggestion_order_to_feedback_keeps_inventory_until_confirmation(self):
        data = self.recipe_data(goal="")
        recipe = self.store.create_recipe(data)
        self.assertEqual(recipe["goal"], "")
        self.assertEqual(recipe["payload"]["doseGrams"], 15)
        self.assertEqual(recipe["payload"]["recipe"]["grandWater"], 225)
        self.assertEqual(recipe["payload"]["recipe"]["rpm"], 60)
        order = self.store.create_order(dict(request_id=self.key(), bean_id=1, person_id=2,
                                             mode="xbloom", note="客人保留原话"))
        brew = self.brew(recipe, order["id"])
        self.assertEqual((brew["status"], brew["bean_id"]), ("prepared", 1))
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        self.assertEqual(self.record(brew)["consumption_g"], 15)
        self.assertEqual(self.store.get_bean(1)["net_weight"], 85)
        result = self.record(brew)
        self.feedback(result, 1, score=0)
        self.feedback(result, 2, score=8)
        state = self.store.state()
        self.assertEqual(state["orders"][0]["status"], "completed")
        self.assertEqual(state["orders"][0]["recipe_id"], recipe["id"])
        self.assertEqual({f["person_id"]: f["feedback"]["overall"] for f in state["feedback"]}, {1: 0, 2: 8})
        self.assertEqual(self.store.get_bean(1)["net_weight"], 85)
        self.assertEqual(self.store.get_bean(2)["net_weight"], 100)

    def test_same_name_batches_versions_and_brew_snapshot_do_not_mix(self):
        original = self.recipe()
        old_payload = copy.deepcopy(original["payload"])
        brew = self.brew(original)
        changed = self.recipe(goal="更甜", base=original)
        self.assertEqual(changed["parent_id"], original["id"])
        self.assertNotEqual(changed["sha256"], original["sha256"])
        self.assertEqual(self.store.get_recipe(original["id"])["payload"], old_payload)
        snapshot = json.loads(self.rows("SELECT data_json FROM brew_records WHERE id=?", (brew["id"],))[0][0])["recipe_snapshot"]
        self.assertEqual(snapshot, {"id": original["id"], "sha256": original["sha256"], "payload": old_payload})
        with self.assertRaises(ValueError):
            planning.suggest(self.store.get_bean(2), base=original)
        wrong_parent = self.recipe_data(bean_id=2)
        wrong_parent["parent_id"] = original["id"]
        self.error(409, self.store.create_recipe, wrong_parent)
        self.error(409, self.store.create_brew,
                   dict(request_id=self.key(), bean_id=2, recipe_id=original["id"], mode="xbloom"))
        self.error(409, self.store.create_brew,
                   dict(request_id=self.key(), bean_id=1, recipe_id=original["id"], mode="manual"))
        order = self.store.create_order(dict(request_id=self.key(), bean_id=2, person_id=2, mode="xbloom", note=""))
        self.error(409, self.store.create_brew,
                   dict(request_id=self.key(), bean_id=1, recipe_id=original["id"], mode="xbloom", order_id=order["id"]))
        self.assertEqual(len(self.store.state()["brews"]), 1)

    def test_unknown_fields_illegal_payload_and_missing_people_have_no_writes(self):
        original = self.recipe_data()
        bad_cases = []
        bad = copy.deepcopy(original)
        bad["undeclared"] = True
        bad_cases.append(bad)
        for field, value in (("grandWater", 224), ("grinderSize", True), ("rpm", 65)):
            bad = copy.deepcopy(original)
            bad["payload"]["recipe"][field] = value
            bad_cases.append(bad)
        bad = copy.deepcopy(original)
        bad["payload"]["bypassMl"] = 10
        bad_cases.append(bad)
        for bad in bad_cases:
            with self.subTest(payload=bad):
                self.error(400, self.store.create_recipe, bad)
        self.error(404, self.store.create_order,
                   dict(request_id=self.key(), bean_id=1, person_id=999, mode="xbloom", note=""))
        self.assertEqual(self.rows("SELECT count(*) FROM product_requests")[0][0], 0)
        self.assertEqual(self.store.state()["recipes"], [])

    def test_request_replay_and_consumption_are_once_only(self):
        data = self.recipe_data()
        recipe = self.store.create_recipe(data)
        self.assertEqual(self.store.create_recipe(data), recipe)
        self.error(409, self.store.create_recipe, dict(data, title="同键不同内容"))
        self.error(409, self.store.create_order, dict(request_id=data["request_id"], bean_id=1,
                                                    person_id=1, mode="xbloom", note="跨动作复用键"))
        brew_data = dict(request_id=self.key(), bean_id=1, recipe_id=recipe["id"], mode="xbloom")
        brew = self.store.create_brew(brew_data)
        self.assertEqual(self.store.create_brew(brew_data), brew)
        record = dict(request_id=self.key(), status="completed", observations={}, consumption_g=15.5)
        first = self.store.record_brew(brew["id"], record)
        self.assertEqual(self.store.record_brew(brew["id"], record), first)
        self.store.record_brew(brew["id"], dict(record, request_id=self.key()))
        self.error(409, self.store.record_brew, brew["id"], dict(record, request_id=self.key(), consumption_g=16))
        bean = self.store.get_bean(1)
        self.assertEqual((bean["net_weight"], bean["total_weight"]), (84.5, 250))
        self.assertEqual(self.rows("SELECT count(*) FROM product_consumption")[0][0], 1)
        self.assertEqual(len(self.store.state()["brews"]), 1)

    def test_old_completed_without_consumption_waits_for_manual_reconciliation(self):
        brew = self.brew()
        with self.store._connection(write=True) as db:
            db.execute("UPDATE product_brews SET status='completed' WHERE brew_id=?", (brew["id"],))
        self.assertIsNone(self.record(brew)["consumption_g"])
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        self.assertEqual(self.record(brew, grams=12)["consumption_g"], 12)
        self.assertEqual(self.store.get_bean(1)["net_weight"], 88)

    def test_excess_consumption_rolls_back_and_failed_cup_can_consume(self):
        brew = self.brew()
        data = dict(request_id=self.key(), status="completed", observations={"note": "超量样例"}, consumption_g=101)
        self.error(409, self.store.record_brew, brew["id"], data)
        self.assertEqual(self.store.get_brew(brew["id"])["status"], "prepared")
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        self.assertEqual(self.rows("SELECT count(*) FROM product_consumption")[0][0], 0)
        self.assertEqual(self.rows("SELECT count(*) FROM product_requests WHERE request_id=?", (data["request_id"],))[0][0], 0)
        failed = self.store.record_brew(brew["id"], dict(data, status="failed", consumption_g=15))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual((self.store.get_bean(1)["net_weight"], self.store.get_bean(1)["total_weight"]), (85, 250))

    def test_independent_feedback_keeps_missing_scores_and_rejects_stale_revision(self):
        brew = self.record(self.brew())
        first = self.feedback(brew, 1, score=0)
        other = self.feedback(brew, 2, score=8)
        self.assertEqual(self.feedback(brew, 1, score=0), first)
        revised = self.feedback(brew, 1, score=4, revision=1, taste="凉后评价修订")
        self.assertEqual(revised["revision"], 2)
        self.error(409, self.feedback, brew, 1, 6, 1)
        self.error(400, self.store.save_feedback, dict(person_id=1, cup=f"brew-{brew['id']}", feedback={}, revision=2))
        self.error(400, self.store.save_feedback, dict(person_id=1, cup=f"brew-{brew['id']}", feedback={"overall": True}, revision=2))
        state = {row["person_id"]: row for row in self.store.state()["feedback"]}
        self.assertEqual(state[2], other)
        self.assertNotIn("sweetness", state[1]["feedback"])
        self.assertEqual(state[1]["feedback"]["overall"], 4)

    def test_experience_requires_same_batch_feedback_and_freezes_source_revision(self):
        brew = self.record(self.brew())
        data = self.experience_data(brew)
        self.error(409, self.store.create_experience, data)
        original = self.feedback(brew, score=6)
        self.error(409, self.store.create_experience, dict(data, bean_id=2))
        self.error(409, self.store.create_experience, dict(data, source_person_id=2))
        experience = self.store.create_experience(data)
        self.feedback(brew, score=3, revision=1, taste="后来改分，不得改写当时引用")
        reread = self.store.state()["experiences"][0]
        self.assertEqual(reread["feedback_revision"], 1)
        self.assertEqual(reread["feedback_snapshot"], original["feedback"])
        self.assertEqual(reread["source_brew_id"], brew["id"])
        self.assertEqual(reread["source_person_id"], 1)
        self.assertEqual(self.store.create_experience(data)["id"], experience["id"])

    def test_support_and_counterexample_reference_later_cups_and_fixed_feedback(self):
        source = self.record(self.brew())
        self.feedback(source)
        experience = self.store.create_experience(self.experience_data(source))
        later = self.record(self.brew())
        original = self.feedback(later, score=8)
        self.feedback(later, person=2, score=2)
        data = dict(request_id=self.key(), brew_id=later["id"], person_id=1, verdict="support", notes="制作人支持样例")
        self.error(409, self.store.evaluate_experience, experience["id"], dict(data, brew_id=source["id"]))
        other_batch = self.record(self.brew(self.recipe(bean_id=2)))
        self.feedback(other_batch)
        self.error(409, self.store.evaluate_experience, experience["id"], dict(data, brew_id=other_batch["id"]))
        self.store.evaluate_experience(experience["id"], data)
        self.store.evaluate_experience(experience["id"], dict(data, request_id=self.key(), person_id=2,
                                                              verdict="counterexample", notes="客人反例样例"))
        self.feedback(later, score=5, revision=1)
        result = self.store.state()["experiences"][0]
        observations = {e["person_id"]: e for e in result["evaluations"]}
        self.assertEqual(observations[1]["feedback_snapshot"], original["feedback"])
        self.assertEqual(observations[1]["feedback_revision"], 1)
        self.assertEqual(observations[2]["verdict"], "counterexample")
        self.assertEqual(self.store.evaluate_experience(experience["id"], data)["id"], experience["id"])
        suggestion = planning.suggest(self.store.get_bean(1), experiences=[result])
        excerpt = next(e["excerpt"] for e in suggestion["evidence"] if e["source"] == "local-experience")
        self.assertIn("客人反例样例", excerpt)
        self.assertIn("不证明因果", excerpt)

    def test_start_needs_authorization_fingerprint_and_never_redispatches_after_restart(self):
        recipe = self.recipe()
        brew = self.brew(recipe)
        data = self.start_data(recipe)
        self.error(400, self.store.claim_start, brew["id"], dict(data, confirm_start=False))
        self.error(409, self.store.claim_start, brew["id"], dict(data, reviewed_sha256="0" * 64))
        self.assertEqual(self.store.get_brew(brew["id"])["status"], "prepared")
        self.assertTrue(self.store.claim_start(brew["id"], data)["dispatch"])
        self.assertFalse(self.store.claim_start(brew["id"], data)["dispatch"])
        self.error(409, self.store.claim_start, brew["id"], dict(data, request_id=self.key()))
        restarted = Store(self.db_path)
        replay = restarted.claim_start(brew["id"], data)
        self.assertFalse(replay["dispatch"])
        self.assertEqual(replay["brew"]["status"], "needs_review")
        self.assertEqual(replay["brew"]["machine_completion"], "unconfirmed")
        self.error(409, restarted.claim_start, brew["id"], dict(data, request_id=self.key()))
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        for mode in ("manual", "grind_own"):
            manual_recipe = self.recipe(mode=mode)
            manual = self.brew(manual_recipe)
            self.error(409, self.store.claim_start, manual["id"], self.start_data(manual_recipe))

    def test_active_capture_blocks_manual_result_and_receipt_never_confirms_machine(self):
        recipe = self.recipe()
        brew = self.brew(recipe)
        self.store.claim_start(brew["id"], self.start_data(recipe))
        self.error(409, self.record, brew, "completed", 15)
        self.assertEqual(self.store.get_bean(1)["net_weight"], 100)
        # Pure receipt metadata in SQLite; no log replay, fake BLE or Runner.
        captured = self.store.finish_capture(brew["id"], None, None, "数据库流程样例：没有执行设备")
        self.assertEqual(captured["status"], "needs_review")
        self.assertEqual(captured["machine_completion"], "unconfirmed")
        confirmed = self.record(brew, "completed", 15)
        self.assertEqual(confirmed["status"], "completed")
        self.assertEqual(confirmed["machine_completion"], "unconfirmed")

    def test_selected_dose_reaches_saved_recipe_and_brew_snapshot(self):
        bean = self.store.get_bean(1)
        for dose in range(5, 19):
            with self.subTest(dose=dose):
                data = self.recipe_data()
                data["payload"] = planning.suggest(bean, goal="1:16", dose_grams=dose)["payload"]
                saved = self.store.create_recipe(data)
                brew = self.brew(saved)
                raw, = self.rows("SELECT data_json FROM brew_records WHERE id=?", (brew["id"],))[0]
                payload = json.loads(raw)["recipe_snapshot"]["payload"]
                self.assertEqual(payload["doseGrams"], dose)
                self.assertEqual(sum(p["volume"] for p in payload["recipe"]["pours"]), dose * 16)
        for invalid in (4, 19, 12.5, True, "12"):
            with self.assertRaisesRegex(ValueError, "整数"):
                planning.suggest(bean, dose_grams=invalid)

    def test_planning_preserves_base_and_rejects_mapping_conflicts(self):
        recipe = self.recipe()
        kept = planning.suggest(self.store.get_bean(1), base=recipe)
        self.assertEqual(kept["payload"], recipe["payload"])
        # External contract: v1.9.4 workbench/ai_recipe.py TARGET_HINTS,
        # lines 228–240: sweetness/cleanliness keep ratio; concentration/
        # lightness keep grinder setting. These are source-based invariants.
        for goal in ("更甜", "更干净"):
            adjusted = planning.suggest(self.store.get_bean(1), goal=goal, base=recipe)
            self.assertEqual(adjusted["payload"]["recipe"]["grandWater"], 225)
            self.assertEqual(adjusted["payload"]["doseGrams"], 15)
        stronger = planning.suggest(self.store.get_bean(1), goal="更浓", base=recipe)
        self.assertEqual(stronger["payload"]["recipe"]["grandWater"], 210)
        self.assertEqual(stronger["payload"]["recipe"]["grinderSize"], recipe["payload"]["recipe"]["grinderSize"])
        low = copy.deepcopy(recipe)
        low["payload"]["recipe"]["grinderSize"] = 48
        with self.assertRaises(ValueError):
            planning.suggest(self.store.get_bean(1), goal="更甜", base=low)
        high = copy.deepcopy(recipe)
        high["payload"]["recipe"]["grinderSize"] = 55
        with self.assertRaises(ValueError):
            planning.suggest(self.store.get_bean(1), goal="更干净", base=high)
        lighter = planning.suggest(self.store.get_bean(1), goal="更清爽", base=recipe)
        self.assertEqual(lighter["payload"]["recipe"]["grandWater"], 240)
        self.assertEqual(lighter["payload"]["recipe"]["grinderSize"], recipe["payload"]["recipe"]["grinderSize"])
        fast = copy.deepcopy(recipe)
        fast["payload"]["recipe"]["rpm"] = 100
        with self.assertRaises(ValueError):
            planning.suggest(self.store.get_bean(1), base=fast)
        with self.assertRaises(ValueError):
            planning.read_source("../../schema.py")
        for mode in ("manual", "grind_own"):
            suggestion = planning.suggest(self.store.get_bean(1), mode=mode)
            self.assertFalse(suggestion["execution_supported"])
            self.assertEqual(suggestion["payload"], recipe["payload"])
        fresh = planning.suggest(self.store.get_bean(1))
        self.assertTrue(any("烘焙度数值未知" in risk for risk in fresh["risks"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
