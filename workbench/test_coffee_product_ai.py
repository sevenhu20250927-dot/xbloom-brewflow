"""Offline synthetic contexts and fake provider responses; never invoke a model."""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coffee_product import ai_planning as ai
import test_coffee_product_store as store_fixtures


class AiPlanningTests(unittest.TestCase):
    def setUp(self):
        self.payload = {"cupType": "xdripper", "doseGrams": 15, "recipe": {
            "grinderSize": 51, "rpm": 60, "grandWater": 225,
            "pours": [{"volume": water, "temperature": 93, "flowRate": 3.5, "pattern": 2,
                       "pausing": 12 if i < 3 else 0, "vibBefore": False, "vibAfter": False}
                      for i, water in enumerate([45, 60, 60, 60])]}}
        self.state = {
            "beans": [{"id": 1, "name": "同名模拟豆", "process": "水洗", "roast_level": None},
                      {"id": 2, "name": "同名模拟豆", "source_notes": "OTHER_BEAN_SECRET"}],
            "people": [{"id": 1, "name": "模拟甲"}, {"id": 2, "name": "模拟乙"}],
            "recipes": [{"id": 1, "bean_id": 1, "mode": "xbloom", "payload": self.payload},
                        {"id": 2, "bean_id": 2, "mode": "xbloom", "payload": self.payload}],
            "brews": [{"id": 10, "bean_id": 1, "recipe_id": 1, "status": "completed", "observations": {"screen_seconds": None}},
                      {"id": 11, "bean_id": 1, "recipe_id": 1, "status": "completed", "observations": {}},
                      {"id": 20, "bean_id": 2, "status": "completed", "observations": {"note": "OTHER_BEAN_SECRET"}},
                      {"id": 21, "bean_id": 1, "status": "cancelled"}],
            "feedback": [{"person_id": 1, "cup": "brew-10", "revision": 2, "feedback": {"taste": "模拟甲中温甜但稍苦"}},
                         {"person_id": 2, "cup": "brew-11", "revision": 1, "feedback": {"taste": "模拟乙中温偏淡"}},
                         {"person_id": 1, "cup": "brew-20", "revision": 1, "feedback": {"taste": "OTHER_BEAN_SECRET"}}],
            "experiences": [{"id": 1, "bean_id": 1, "source_brew_id": 10, "source_person_id": 1,
                             "condition": "模拟条件", "action": "降温", "expected": "减苦",
                             "evaluations": [{"brew_id": 10, "person_id": 1, "verdict": "support", "notes": "模拟支持"},
                                             {"brew_id": 11, "person_id": 2, "verdict": "counterexample", "notes": "模拟反例"}]},
                            {"id": 2, "bean_id": 2, "condition": "OTHER_BEAN_SECRET"}]}
        titles = {source_id: {"title": source_id} for source_id in ai.REFERENCE_IDS}
        self.references = patch.dict(ai.planning.SOURCES, titles)
        self.read = patch.object(ai.planning, "read_source", return_value="用于离线测试的一一原文样例。降低温度可能同时降低甜感。")
        self.references.start()
        self.read.start()
        self.addCleanup(self.references.stop)
        self.addCleanup(self.read.stop)
        self.context = ai.build_context(self.state, bean_id=1, person_id=1)

    def output(self, context=None):
        context = context or self.context
        citations = [{"source_id": source_id, "quote": context["sources"][source_id]["content"][:80]}
                     for source_id in context["required_citations"] + [ai.REFERENCE_IDS[2]]]
        return {"bean_id": 1, "title": "离线模拟配方", "mode": context["request"]["mode"],
                "goal": context["request"]["goal"], "payload": copy.deepcopy(self.payload),
                "rationale": ["模拟假设：降温尝试减少苦感"], "risks": ["模拟风险：可能降低甜感"], "citations": citations}

    def test_context_keeps_same_bean_raw_feedback_people_and_counterexamples_separate(self):
        original = copy.deepcopy(self.state)
        context = ai.build_context(self.state, bean_id=1, person_id=1)
        self.assertEqual(self.state, original)
        self.assertEqual(context["request"]["target_person"], {"id": 1, "name": "模拟甲"})
        self.assertEqual(context["history"]["same_bean_brew_count"], 2)
        self.assertEqual(context["history"]["same_bean_feedback_count"], 2)
        self.assertEqual(context["required_citations"], ["bean:1", "feedback:10:1"])
        self.assertIn("模拟甲中温甜但稍苦", context["sources"]["feedback:10:1"]["content"])
        self.assertIn("模拟乙中温偏淡", context["sources"]["feedback:11:2"]["content"])
        self.assertIn("counterexample", context["sources"]["experience:1"]["content"])
        self.assertIn("support", context["sources"]["experience:1"]["content"])
        self.assertNotIn("OTHER_BEAN_SECRET", ai.build_prompt(context))
        self.assertNotIn("brew:21", context["sources"])
        self.assertTrue(all(source_id in context["sources"] for source_id in ai.REFERENCE_IDS))

    def test_first_cup_stays_without_history_and_cross_bean_base_is_rejected(self):
        state = dict(self.state, brews=[], feedback=[], experiences=[])
        context = ai.build_context(state, bean_id=1)
        self.assertIn("没有同豆冲煮", context["history"]["note"])
        self.assertEqual(context["required_citations"], ["bean:1"])
        with self.assertRaises(ai.AiPlanningError):
            ai.build_context(self.state, bean_id=1, base_recipe_id=2)
        with self.assertRaises(ai.AiPlanningError):
            ai.build_context(self.state, bean_id=1, base_recipe_id=1, mode="manual")

    def test_arbitrary_goal_and_five_pours_are_validated_without_four_pour_template(self):
        context = ai.build_context(self.state, bean_id=1, goal="中低温更清晰，保留甜感")
        output = self.output(context)
        output["payload"]["recipe"]["pours"] = [dict(self.payload["recipe"]["pours"][0], volume=45) for _ in range(5)]
        result = ai.validate_output(json.dumps(output), context)
        self.assertEqual(len(result["payload"]["recipe"]["pours"]), 5)
        self.assertTrue(any("yiyi-experience-library" in item["title"] for item in result["evidence"]))
        self.assertTrue(result["execution_supported"])

    def test_validated_result_saves_with_provider_evidence_and_bounded_risks(self):
        fixture = store_fixtures.ProductDataFlow("test_default_suggestion_order_to_feedback_keeps_inventory_until_confirmation")
        fixture.validation_root = Path(tempfile.mkdtemp(prefix="coffee-ai-store-contract-"))
        fixture.setUp()
        context = ai.build_context(self.state, bean_id=1, mode="manual")
        output = self.output(context)
        output["risks"] = ["离线样例风险"] * 98
        result = ai.validate_output(json.dumps(output), context, provider="ollama", model="offline:27b")
        data = {key: result[key] for key in ("title", "mode", "goal", "payload", "rationale", "evidence", "risks")}
        saved = fixture.store.create_recipe(dict(data, bean_id=1, request_id="offline-ai-contract"))
        self.assertEqual(len(saved["risks"]), 100)
        self.assertIn("Ollama · offline:27b", saved["evidence"][-1]["excerpt"])
        print(f"\nRetained AI-to-store synthetic fixture: {fixture.validation_root}")

    def test_rejects_wrong_identity_machine_parameters_and_invented_evidence(self):
        for mutate in (
            lambda output: output.update(bean_id=2),
            lambda output: output.update(mode="manual"),
            lambda output: output.update(goal="偷偷换目标"),
            lambda output: output["payload"]["recipe"].update(rpm=100),
            lambda output: output["payload"]["recipe"].update(grandWater=224),
            lambda output: output["payload"].update(bypassMl=20),
            lambda output: output["citations"][0].update(source_id="bean:2"),
            lambda output: output["citations"][0].update(quote="编造的原文"),
            lambda output: output.update(citations=output["citations"][:1]),
        ):
            output = self.output()
            mutate(output)
            with self.subTest(output=output), self.assertRaises(ai.AiOutputError):
                ai.validate_output(json.dumps(output), self.context)

    def test_rejects_duplicate_keys_and_decimal_rounding_before_encoding(self):
        raw = json.dumps(self.output())
        for bad in (raw.replace('"bean_id": 1', '"bean_id": 1, "bean_id": 1', 1),
                    raw.replace('"rpm": 60', '"rpm": 60, "rpm": 60', 1),
                    raw.replace('"flowRate": 3.5', '"flowRate": 3.5000000000000001', 1)):
            with self.subTest(raw=bad), self.assertRaises(ai.AiOutputError):
                ai.validate_output(bad, self.context)

    def test_selected_dose_is_bound_to_model_schema_and_validated_result(self):
        for dose in (12, 15, 18):
            with self.subTest(dose=dose):
                context = ai.build_context(self.state, bean_id=1, dose_grams=dose)
                for branch in ai.output_schema(context)["properties"]["payload"]["anyOf"]:
                    self.assertEqual(branch["properties"]["doseGrams"]["enum"], [dose])
                output = self.output(context)
                output["payload"] = ai.planning.suggest(self.state["beans"][0], dose_grams=dose)["payload"]
                self.assertEqual(ai.validate_output(json.dumps(output), context)["payload"]["doseGrams"], dose)
                output["payload"] = self.payload
                if dose != 15:
                    with self.assertRaisesRegex(ai.AiOutputError, f"本杯选择 {dose} g"):
                        ai.validate_output(json.dumps(output), context)

    def test_native_bypass_available_to_ai_and_preserved_by_validation(self):
        payload_schema = ai.output_schema(self.context)["properties"]["payload"]
        output = self.output()
        payload = output["payload"]
        payload["recipe"]["grandWater"] = 210
        payload["recipe"]["pours"][-1]["volume"] -= 15
        self.assertTrue(any(set(branch["required"]) == set(payload) for branch in payload_schema["anyOf"]))
        payload.update(bypassMl=40, bypassTempC=92)
        self.assertTrue(any(set(branch["required"]) == set(payload) for branch in payload_schema["anyOf"]))
        self.assertIn("过粉水加旁通水", ai.build_prompt(self.context))
        checked = ai.validate_output(json.dumps(output), self.context, provider="deepseek")
        self.assertEqual(checked["payload"], payload)

    def test_error_identifies_the_quote_that_lost_its_markdown_formatting(self):
        output = self.output()
        last = output["citations"][-1]
        self.context["sources"][last["source_id"]]["content"] = "**触发可以用单杯判读**：是否切③"
        last["quote"] = "触发可以用单杯判读：是否切③"
        with self.assertRaisesRegex(ai.AiOutputError, f"第 {len(output['citations'])} 条引用.*逐字核对"):
            ai.validate_output(json.dumps(output), self.context)

    def test_codex_uses_stdin_isolated_directory_no_tools_and_checks_returned_file(self):
        def fake_run(command, **kwargs):
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ephemeral", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("features.shell_tool=false", command)
            self.assertIn('web_search="disabled"', command)
            self.assertIn("project_doc_max_bytes=0", command)
            self.assertIn('model_provider="workbench_https"', command)
            self.assertIn("model_providers.workbench_https.requires_openai_auth=true", command)
            self.assertIn("model_providers.workbench_https.supports_websockets=false", command)
            self.assertFalse(any("base_url=" in value for value in command))
            self.assertIn("模拟甲中温甜但稍苦", kwargs["input"])
            self.assertEqual(command[-1], "-")
            Path(command[command.index("-o") + 1]).write_text(json.dumps(self.output()), encoding="utf-8")
            return SimpleNamespace(returncode=0)
        result = ai.call_codex(self.context, model="offline-fixture", run=fake_run)
        self.assertIn("offline-fixture", result["provenance"])
        self.assertEqual(result["payload"], self.payload)

    def test_default_cli_uses_desktop_when_installed_and_honors_explicit_command(self):
        with patch.object(ai.os, "access", return_value=True):
            self.assertEqual(ai.build_command(None, ".")[0], str(ai.BUNDLED_CODEX))
            self.assertEqual(ai.build_command("/custom/codex", ".")[0], "/custom/codex")
        with patch.object(ai.os, "access", return_value=False):
            self.assertEqual(ai.build_command(None, ".")[0], "codex")

    def test_multiline_goal_is_checked_locally_not_embedded_in_strict_schema(self):
        self.context["request"]["goal"] = "保留甜感\n减轻苦涩"
        self.assertEqual(ai.output_schema(self.context)["properties"]["goal"], {"type":"string"})
        response = self.output()
        ai.validate_output(json.dumps(response), self.context)
        response["goal"] = "另一个目标"
        with self.assertRaisesRegex(ValueError, "目标"):
            ai.validate_output(json.dumps(response), self.context)

    def test_installed_codex_parses_command_flags_without_running_a_model(self):
        executable = shutil.which("codex")
        if not executable:
            self.skipTest("本机未安装Codex；仅跳过CLI参数解析检查")
        with tempfile.TemporaryDirectory(prefix="coffee-codex-help-") as temporary:
            directory = Path(temporary)
            (directory / "schema.json").write_text(json.dumps(ai.output_schema(self.context)), encoding="utf-8")
            command = ai.build_command(executable, directory, model="gpt-6.2-sol", reasoning_effort="high", service_tier="priority")
            self.assertIn('service_tier="priority"', command)
            self.assertIn('model_reasoning_effort="high"', command)
            result = subprocess.run(command[:-1] + ["--help"], cwd=directory, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--output-schema", result.stdout)

    def test_provider_errors_do_not_create_rule_fallback_or_leak_stderr(self):
        result = SimpleNamespace(returncode=1, stderr="SECRET_PROVIDER_TOKEN")
        with self.assertRaises(ai.AiPlanningError) as caught:
            ai.call_codex(self.context, run=lambda *args, **kwargs: result)
        self.assertNotIn("SECRET_PROVIDER_TOKEN", str(caught.exception))
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("offline-fixture", 1)
        with self.assertRaisesRegex(ai.AiPlanningError, "超时"):
            ai.call_codex(self.context, run=timeout)

    def test_ollama_uses_exact_model_and_shared_schema_without_download(self):
        calls = []
        def fake_open(request, **kwargs):
            calls.append(request.full_url)
            body = json.loads(request.data)
            self.assertEqual(body["model"], "offline:27b")
            self.assertFalse(body["stream"])
            self.assertFalse(body["think"])
            self.assertEqual(body["options"]["num_ctx"], 65536)
            self.assertEqual(body["options"]["num_predict"], 8192)
            self.assertEqual(body["format"], ai.output_schema(self.context))
            response = {"message": {"content": json.dumps(self.output())}}
            return io.BytesIO(json.dumps(response).encode("utf-8"))
        result = ai.call_ollama(self.context, model="offline:27b", open_url=fake_open)
        self.assertEqual(calls, ["http://127.0.0.1:11434/api/chat"])
        self.assertIn("Ollama · offline:27b", result["provenance"])

    def test_ollama_sends_configured_thinking_and_output_limit(self):
        def fake_open(request, **kwargs):
            body = json.loads(request.data)
            self.assertEqual(body["think"], "low")
            self.assertEqual(body["options"]["num_predict"], 4096)
            return io.BytesIO(json.dumps({"message": {"content": json.dumps(self.output())}}).encode("utf-8"))
        result = ai.call_ollama(self.context, think="low", num_predict=4096, open_url=fake_open)
        self.assertEqual(result["payload"], self.payload)

    def test_bad_recommendation_is_output_error_for_both_providers_not_transport_error(self):
        from coffee_product import recommendations
        context = recommendations.build_context(self.state, person_id=1)
        malformed = json.dumps({"person_id": 999, "items": []})
        def fake_run(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_text(malformed, encoding="utf-8")
            return SimpleNamespace(returncode=0)
        def fake_open(*args, **kwargs):
            return io.BytesIO(json.dumps({"message": {"content": malformed}}).encode("utf-8"))
        for invoke in (lambda: ai.call_codex(context, run=fake_run),
                       lambda: ai.call_ollama(context, open_url=fake_open)):
            with self.subTest(provider=invoke), self.assertRaises(ai.AiOutputError) as caught:
                invoke()
            self.assertIn("推荐品饮人和请求不一致", str(caught.exception))
        original = ai.AiOutputError("已分类的输出错误")
        def classified(*args, **kwargs):
            raise original
        with self.assertRaises(ai.AiOutputError) as caught:
            ai._validate_result(classified, malformed, context, provider="codex", model=None)
        self.assertIs(caught.exception, original)

    def test_oversized_codex_result_is_an_output_error(self):
        def fake_run(command, **kwargs):
            Path(command[command.index("-o") + 1]).write_bytes(b"x" * (256 * 1024 + 1))
            return SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(ai.AiOutputError, "输出过大"):
            ai.call_codex(self.context, run=fake_run)

    def test_deepseek_recipe_uses_same_validator_and_keeps_key_out_of_artifacts(self):
        directory = Path(tempfile.mkdtemp(prefix="coffee-deepseek-offline-"))
        def fake_open(request, **kwargs):
            self.assertEqual(request.full_url, "https://gateway.example.invalid/v1/chat/completions")
            self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-test-token")
            body = json.loads(request.data)
            self.assertEqual(body["model"], "synthetic-deepseek")
            self.assertEqual(body["response_format"], {"type": "json_object"})
            self.assertEqual(body["max_tokens"], 8192)
            self.assertNotIn("tools", body)
            self.assertIn("输出 JSON schema", body["messages"][0]["content"])
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(self.output())}}]}).encode())
        with patch.dict(ai.os.environ, {"SYNTHETIC_COFFEE_KEY": "synthetic-test-token"}):
            result = ai.call_deepseek(self.context, base_url="https://gateway.example.invalid/v1",
                model="synthetic-deepseek", api_key_env="SYNTHETIC_COFFEE_KEY", max_tokens=8192,
                open_url=fake_open, work_dir=directory)
        self.assertEqual(result["payload"], self.payload)
        self.assertIn("DeepSeek · synthetic-deepseek", result["provenance"])
        for file in directory.iterdir():
            self.assertNotIn("synthetic-test-token", file.read_text())

    def test_deepseek_missing_key_does_not_send_and_http_error_does_not_echo_key(self):
        def denied(request, **kwargs):
            raise ai.urlerror.HTTPError(request.full_url, 401, "synthetic-test-token", {},
                                       io.BytesIO(b"synthetic-test-token"))
        with patch.dict(ai.os.environ, {"SYNTHETIC_COFFEE_KEY": ""}), patch.object(ai.urlrequest, "build_opener") as transport:
            with self.assertRaisesRegex(ai.AiPlanningError, "尚未配置密钥"):
                ai.call_deepseek(self.context, api_key_env="SYNTHETIC_COFFEE_KEY")
            transport.assert_not_called()
        directory = Path(tempfile.mkdtemp(prefix="coffee-deepseek-offline-error-"))
        with patch.dict(ai.os.environ, {"SYNTHETIC_COFFEE_KEY": "synthetic-test-token"}):
            with self.assertRaises(ai.AiPlanningError) as caught:
                ai.call_deepseek(self.context, api_key_env="SYNTHETIC_COFFEE_KEY", open_url=denied, work_dir=directory)
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn("synthetic-test-token", str(caught.exception))
        for file in directory.iterdir():
            self.assertNotIn("synthetic-test-token", file.read_text())

    def test_deepseek_empty_truncated_and_bad_recipe_are_rejected(self):
        bad = self.output()
        bad["payload"]["recipe"]["rpm"] = 100
        for finish, content in (("stop", " "), ("length", json.dumps(self.output())),
                                ("stop", "not json"), ("stop", json.dumps(bad))):
            def response(*args, **kwargs):
                return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish,
                    "message": {"content": content}}]}).encode())
            with self.subTest(finish=finish, content=content), \
                 patch.dict(ai.os.environ, {"SYNTHETIC_COFFEE_KEY": "synthetic-test-token"}), \
                 self.assertRaises(ai.AiOutputError):
                ai.call_deepseek(self.context, api_key_env="SYNTHETIC_COFFEE_KEY", open_url=response)

    def test_deepseek_recommendation_reuses_person_identity_check(self):
        from coffee_product import recommendations
        context = recommendations.build_context(self.state, person_id=1)
        def response(person_id):
            return lambda *a, **kw: io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop",
                "message": {"content": json.dumps({"person_id": person_id, "items": []})}}]}).encode())
        with patch.dict(ai.os.environ, {"SYNTHETIC_COFFEE_KEY": "synthetic-test-token"}):
            result = ai.call_deepseek(context, api_key_env="SYNTHETIC_COFFEE_KEY", open_url=response(1))
            self.assertEqual(result["items"], [])  # Synthetic fixture has no orderable stock.
            self.assertIn("DeepSeek", result["provenance"])
            with self.assertRaisesRegex(ai.AiOutputError, "品饮人和请求不一致"):
                ai.call_deepseek(context, api_key_env="SYNTHETIC_COFFEE_KEY", open_url=response(2))

    def test_deepseek_does_not_redirect_credentials(self):
        request = ai.urlrequest.Request("https://example.invalid/chat/completions",
                                        headers={"Authorization": "Bearer synthetic-test-token"})
        self.assertIsNone(ai._NoCredentialRedirect().redirect_request(
            request, None, 302, "redirect", {}, "https://other.invalid"))

    def test_deepseek_uses_ui_saved_key_without_persisting_it_in_job_artifacts(self):
        from coffee_product.ai_settings import AICredentials
        root = Path(tempfile.mkdtemp(prefix="coffee-deepseek-private-key-"))
        credentials = AICredentials(root / "private" / "key")
        credentials.update({"api_key": "synthetic-ui-saved-key"})
        def response(request, **kwargs):
            self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-ui-saved-key")
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps(self.output())}}]}).encode())
        with patch.dict(ai.os.environ, {"SYNTHETIC_KEY": "synthetic-old-environment-key"}):
            result = ai.call_deepseek(self.context, api_key_env="SYNTHETIC_KEY", credentials=credentials,
                                     open_url=response, work_dir=root / "job")
        self.assertEqual(result["payload"], self.payload)
        for file in (root / "job").iterdir():
            self.assertNotIn("synthetic-ui-saved-key", file.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
