"""AI job lifecycle checks with retained temporary files and mocked providers."""
import json
from datetime import datetime
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from coffee_product.ai_settings import AISettings
from coffee_product.ai_planning import AiPlanningError, AiOutputError
from coffee_product.server import AIRecipeRunner
from coffee_product.deepseek_billing import receipt, price_period
from coffee_product.store import ProductError


class AIJobs(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="coffee-ai-jobs-test-"))
        class ReadOnlyStore:
            db_path = self.root / "synthetic.db"
            def state(self):
                return {"synthetic": True}
        self.settings = AISettings(self.root / "settings.json", codex_config_path=self.root / "absent.toml")
        self.runner = AIRecipeRunner(ReadOnlyStore(), self.settings, self.root / "jobs")
        self.request = {"request_id": "synthetic-request", "bean_id": 1, "mode": "xbloom", "goal": "更甜"}
        self.context = patch("coffee_product.server.ai_planning.build_context", return_value={"synthetic": True})
        self.context.start()
        self.addCleanup(self.context.stop)

    def finish(self, runner=None):
        runner = runner or self.runner
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = runner.get(self.request["request_id"])
            if result["status"] != "running":
                return result
            time.sleep(0.01)
        self.fail("Mocked AI job did not finish")

    def test_request_replay_and_reload_do_not_repeat_model(self):
        release = threading.Event()
        def slow(*args, **kwargs):
            release.wait(2)
            return {"title": "模拟方案，不是模型产物"}
        with patch("coffee_product.server.ai_planning.call_codex", side_effect=slow) as model:
            self.runner.start(self.request)
            self.assertEqual(self.runner.start(self.request)["id"], self.request["request_id"])
            with self.assertRaises(ProductError):
                self.runner.start(dict(self.request, goal="改了请求内容"))
            release.set()
            result = self.finish()
            self.assertEqual(result["status"], "completed")
            self.assertEqual(model.call_count, 1)
        reloaded = AIRecipeRunner(self.runner.store, self.settings, self.root / "jobs")
        self.assertEqual(reloaded.start(self.request)["result"], result["result"])

    def test_call_failure_uses_configured_backup_and_records_reason(self):
        with patch("coffee_product.server.ai_planning.call_codex", side_effect=AiPlanningError("模拟登录失败")), \
             patch("coffee_product.server.ai_planning.call_deepseek", return_value={"title": "模拟备用结果"}) as backup:
            self.runner.start(self.request)
            result = self.finish()
            self.assertEqual((result["status"], result["provider"]), ("completed", "deepseek"))
            self.assertEqual(result["attempts"][0]["error"], "模拟登录失败")
            self.assertEqual(backup.call_count, 1)

    def test_invalid_output_fails_without_silent_fallback(self):
        with patch("coffee_product.server.ai_planning.call_codex", side_effect=AiOutputError("模拟不合法研磨")), \
             patch("coffee_product.server.ai_planning.call_deepseek") as backup:
            self.runner.start(self.request)
            result = self.finish()
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("result", result)
            backup.assert_not_called()

    def test_changed_displayed_model_blocks_recipe_and_recommendation_before_dispatch(self):
        stale = {"provider": "codex", "model": "old-displayed-model"}
        with patch.object(self.runner.store, "state", side_effect=AssertionError("must reject before planning")):
            for kind, data in (("recipe", self.request),
                               ("recommendation", {"person_id": 1, "request_id": "stale-menu"})):
                with self.subTest(kind=kind), self.assertRaises(ProductError) as caught:
                    self.runner.start(dict(data, expected_ai=stale), kind=kind)
                self.assertEqual(caught.exception.status, 409)
                self.assertFalse(self.runner._directory(data["request_id"]).exists())

    def test_revision_references_the_reviewed_draft_and_keeps_people_separate(self):
        self.runner._save({"id": "first", "status": "completed", "kind": "recipe",
                           "bean_id": 1, "person_id": 2, "mode": "xbloom",
                           "result": {"rationale": ["先观察干净度"]}, "review_notes": ["保留研磨"]})
        payload = {"cupType": "xdripper", "doseGrams": 15, "recipe": {
            "rpm": 60, "grinderSize": 51, "grandWater": 225, "pours": [
                {"volume": 225, "temperature": 91, "flowRate": 3, "pattern": 1,
                 "pausing": 0, "vibBefore": False, "vibAfter": False}]}}
        revision = {"prior_job_id": "first", "payload_json": json.dumps(payload), "note": "减少水量"}
        with patch("coffee_product.server.ai_planning.call_codex", return_value={"title": "模拟修方"}) as model:
            for different in ({"person_id": 1}, {"bean_id": 2, "person_id": 2}):
                with self.assertRaises(ValueError):
                    self.runner.start(dict(self.request, revision=revision, **different))
            model.assert_not_called()
            self.runner.start(dict(self.request, revision=revision, person_id=2))
            self.assertEqual(self.finish()["review_notes"], ["保留研磨", "减少水量"])
            self.assertEqual(model.call_args.args[0]["revision"], {
                "current_payload": payload, "note": "减少水量",
                "previous_notes": ["保留研磨"], "previous_rationale": ["先观察干净度"]})

    def test_deepseek_primary_uses_configuration_and_missing_key_reports_failure(self):
        config = self.settings.load()
        config.update(primary="deepseek", fallback=None)
        config["deepseek"].update(model="configured-model", api_key_env="SYNTHETIC_COFFEE_KEY")
        self.settings.save(config)
        with patch("coffee_product.server.ai_planning.call_deepseek", side_effect=AiPlanningError("模拟未配置密钥")) as model:
            self.runner.start(dict(self.request, expected_ai={"provider": "deepseek", "model": "configured-model"}))
            result = self.finish()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["attempts"][0]["error"], "模拟未配置密钥")
            self.assertEqual(model.call_args.kwargs["api_key_env"], "SYNTHETIC_COFFEE_KEY")
            self.assertEqual(model.call_args.kwargs["model"], "configured-model")
            self.assertNotIn("result", result)

    def test_restart_marks_unfinished_job_interrupted_without_dispatch(self):
        self.runner._save({"id": "synthetic-request", "status": "running", "_digest": "synthetic"})
        with patch("coffee_product.server.ai_planning.call_codex") as model:
            self.assertEqual(self.runner.get("synthetic-request")["status"], "interrupted")
            model.assert_not_called()

    def test_deepseek_usage_survives_invalid_recipe_replay_and_service_restart(self):
        config = self.settings.load()
        config.update(primary="deepseek", fallback=None)
        self.settings.save(config)
        raw = dict(model="deepseek-flash", created=1795693754, usage={
            "prompt_tokens":63134, "prompt_cache_hit_tokens":1024, "prompt_cache_miss_tokens":62110,
            "completion_tokens":11123, "total_tokens":74257,
            "completion_tokens_details":{"reasoning_tokens":9594}})
        def invalid(*args, work_dir, **kwargs):
            work_dir.mkdir()
            (work_dir / "deepseek-response.json").write_text(json.dumps(raw))
            raise AiOutputError("模拟配方校验失败")
        with patch("coffee_product.server.ai_planning.call_deepseek", side_effect=invalid) as model:
            self.runner.start(self.request)
            result = self.finish()
            self.assertEqual(result["status"], "failed")
            usage = result["attempts"][0]["usage"]
            self.assertEqual((usage["total_tokens"], usage["min_cny"], usage["max_cny"]),
                             (74257, 0.10662248, 0.10662248))
            self.assertEqual(self.runner.start(self.request)["attempts"][0]["usage"], usage)
            model.assert_called_once()
        new = AIRecipeRunner(self.runner.store, self.settings, self.root / "jobs")
        self.assertEqual([row["usage"] for row in new.deepseek_history()], [usage])
        older = new._read(result["id"])
        del older["attempts"][0]["usage"]
        new._save(older)
        self.assertEqual(new.get(result["id"])["attempts"][0]["usage"], usage)
        self.assertNotIn("usage", new._read(result["id"])["attempts"][0])

    def test_deepseek_missing_cache_custom_endpoint_and_price_periods(self):
        path = self.root / "response.json"
        self.assertIsNone(receipt(path, ""))
        raw = dict(model="deepseek-v4-pro", created=1795693754,
                   usage={"prompt_tokens":1000000, "completion_tokens":1000000})
        path.write_text(json.dumps(raw))
        usage = receipt(path, "https://api.deepseek.com")
        self.assertEqual((usage["min_cny"], usage["max_cny"]), (13.65, 18))
        self.assertNotIn("min_cny", receipt(path, "https://other.example"))
        raw["model"] = "unknown"
        path.write_text(json.dumps(raw))
        self.assertNotIn("max_cny", receipt(path, "https://api.deepseek.com"))
        for iso, expected in (("2026-11-26T09:00","peak"), ("2026-11-26T12:00","off_peak"),
                              ("2026-11-26T14:00","peak"), ("2026-11-26T18:00","off_peak"),
                              ("2026-11-28T09:00","off_peak"), ("2026-10-01T09:00","off_peak"),
                              ("2035-11-26T09:00", None)):
            self.assertEqual(price_period(int(datetime.fromisoformat(iso+"+08:00").timestamp())), expected)


if __name__ == "__main__":
    unittest.main()
