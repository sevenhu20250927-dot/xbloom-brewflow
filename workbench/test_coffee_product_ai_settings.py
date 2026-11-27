"""Offline settings tests; all configuration paths are temporary fixtures."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coffee_product.ai_settings import AISettings, AICredentials, provider_status, validate


class AISettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="coffee-ai-settings-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.codex = self.root / "codex.toml"
        self.codex.write_text('model = "fixture-codex-model"\nmodel_reasoning_effort = "high"\n'
                              '[profiles.other]\nmodel = "never-inherit-this"\n', encoding="utf-8")
        self.path = self.root / "local" / "ai-settings.json"
        self.settings = AISettings(self.path, codex_config_path=self.codex)

    def test_defaults_read_only_two_top_level_codex_fields(self):
        before = self.codex.read_bytes()
        result = self.settings.load()
        self.assertEqual(result["primary"], "codex")
        self.assertEqual(result["fallback"], "deepseek")
        self.assertEqual(result["codex"], {"model": "fixture-codex-model", "reasoning_effort": "high", "service_tier": "priority", "timeout_seconds": 600})
        self.assertEqual(result["ollama"]["model"], "qwen3.8:27b-mlx")
        self.assertEqual(result["ollama"]["num_ctx"], 65536)
        self.assertEqual(result["ollama"]["timeout_seconds"], 600)
        self.assertIs(result["ollama"]["think"], False)
        self.assertEqual(result["ollama"]["num_predict"], 8192)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.codex.read_bytes(), before)
        self.codex.unlink()
        self.assertEqual(self.settings.load()["codex"]["model"], "gpt-6.1-terra")

    def test_save_reload_and_switch_provider_without_global_changes(self):
        before = self.codex.read_bytes()
        config = self.settings.load()
        config["codex"]["service_tier"] = "default"
        config.update(primary="ollama", fallback=None)
        config["ollama"].update(base_url="https://localhost:11434/", model="another-local-tag",
                                timeout_seconds=1200, num_ctx=131072, think="xhigh", num_predict=16384)
        config["codex"].update(model="chosen-codex-model", reasoning_effort="ultra", timeout_seconds=900)
        result = self.settings.save(config)
        reloaded = AISettings(self.path, codex_config_path=self.codex).load()
        self.assertEqual(reloaded, result)
        self.assertEqual(result["ollama"]["base_url"], "https://localhost:11434")
        self.assertEqual((reloaded["ollama"]["think"], reloaded["ollama"]["num_predict"]), ("xhigh", 16384))
        self.assertEqual(self.codex.read_bytes(), before)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), result)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        config["primary"], config["fallback"] = "ollama", "codex"
        self.assertEqual(self.settings.save(config)["fallback"], "codex")

    def test_invalid_types_fields_models_and_duplicate_backends_are_rejected(self):
        valid = self.settings.load()
        cases = []
        for key, value in (("primary", "other"), ("fallback", "codex"), ("fallback", False), ("unknown", "field")):
            case = copy.deepcopy(valid)
            case[key] = value
            cases.append(case)
        for provider, key, value in (("codex", "model", " "), ("codex", "reasoning_effort", ""),
                                     ("codex", "timeout_seconds", True), ("codex", "api_key", "forbidden"),
                                     ("ollama", "model", None), ("ollama", "num_ctx", 1.5),
                                     ("ollama", "num_ctx", 0), ("ollama", "timeout_seconds", -1),
                                     ("ollama", "think", 1), ("ollama", "think", " "),
                                     ("ollama", "think", None), ("ollama", "num_predict", True),
                                     ("ollama", "num_predict", 0), ("ollama", "num_predict", -1),
                                     ("ollama", "num_predict", 1.5), ("ollama", "unknown", "field")):
            case = copy.deepcopy(valid)
            case[provider][key] = value
            cases.append(case)
        incomplete = copy.deepcopy(valid)
        del incomplete["codex"]["model"]
        cases.append(incomplete)
        for case in cases:
            with self.subTest(config=case), self.assertRaises(ValueError):
                self.settings.save(case)
        self.assertFalse(self.path.parent.exists())

    def test_old_saved_ollama_config_gets_defaults_without_rewriting_file(self):
        old = self.settings.load()
        del old["ollama"]["think"]
        del old["ollama"]["num_predict"]
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(old), encoding="utf-8")
        before = self.path.read_bytes()
        loaded = self.settings.load()
        self.assertIs(loaded["ollama"]["think"], False)
        self.assertEqual(loaded["ollama"]["num_predict"], 8192)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.settings.save(old), loaded)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), loaded)

    def test_thinking_accepts_booleans_and_nonempty_model_level_without_coercion(self):
        config = self.settings.load()
        for think in (False, True, "low", "medium", "xhigh", "future-model-level"):
            with self.subTest(think=think):
                result = validate(dict(config, ollama=dict(config["ollama"], think=think)))
                self.assertEqual(result["ollama"]["think"], think)
                self.assertIs(type(result["ollama"]["think"]), type(think))

    def test_deepseek_config_and_old_file_preserve_provider_choices_without_storing_key(self):
        old = self.settings.load()
        del old["deepseek"]
        old.update(primary="codex", fallback="ollama")
        self.path.parent.mkdir()
        self.path.write_text(json.dumps(old), encoding="utf-8")
        before = self.path.read_bytes()
        loaded = self.settings.load()
        self.assertEqual(loaded["fallback"], "ollama")
        self.assertEqual(loaded["deepseek"]["api_key_env"], "DEEPSEEK_API_KEY")
        self.assertEqual(self.path.read_bytes(), before)
        loaded.update(primary="codex", fallback="deepseek")
        loaded["deepseek"].update(base_url="https://gateway.example.invalid/v1/", model="configured-model",
                                  api_key_env="COFFEE_DEEPSEEK_KEY", max_tokens=8192)
        saved = self.settings.save(loaded)
        self.assertEqual(saved["deepseek"]["base_url"], "https://gateway.example.invalid/v1")
        self.assertEqual(self.settings.load(), saved)
        self.assertNotIn('"api_key":', self.path.read_text())

    def test_deepseek_invalid_credentials_addresses_and_limits_rejected(self):
        config = self.settings.load()
        for key, value in (("api_key", "synthetic-token"), ("api_key_env", "sk-not-a-variable"),
                           ("api_key_env", ""), ("base_url", "http://remote.example.invalid"),
                           ("base_url", "https://user:secret@example.invalid"),
                           ("base_url", "https://example.invalid?key=secret"),
                           ("max_tokens", 0), ("max_tokens", True), ("max_tokens", 393217),
                           ("model", ""), ("timeout_seconds", -1)):
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                validate(dict(config, deepseek=dict(config["deepseek"], **{key: value})))

    def test_url_credentials_and_non_http_endpoints_are_rejected(self):
        config = self.settings.load()
        for url in ("file:///tmp/model", "ftp://localhost", "http://", "http://name:secret@localhost:11434",
                    "https://name@localhost", "https://localhost?token=secret", "https://localhost#token",
                    "http://local host:11434", "http://localhost:99999", "http://localhost:0"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate(dict(config, ollama=dict(config["ollama"], base_url=url)))
        for url in ("http://localhost:11434", "http://[::1]:11434", "https://example.invalid/ollama"):
            self.assertEqual(validate(dict(config, ollama=dict(config["ollama"], base_url=url)))["ollama"]["base_url"], url)

    def test_invalid_save_or_failed_replace_preserves_previous_file(self):
        config = self.settings.save(self.settings.load())
        original = self.path.read_bytes()
        invalid = copy.deepcopy(config)
        invalid["codex"]["model"] = ""
        with self.assertRaises(ValueError):
            self.settings.save(invalid)
        self.assertEqual(self.path.read_bytes(), original)
        modified = copy.deepcopy(config)
        modified["codex"]["model"] = "changed"
        with patch("coffee_product.ai_settings.os.replace", side_effect=OSError("fixture write failure")):
            with self.assertRaises(OSError):
                self.settings.save(modified)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.path.write_text("{broken-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.settings.load()

    def test_private_key_save_replace_remove_and_environment_precedence(self):
        credentials = AICredentials(self.root / "private" / "deepseek.key")
        with patch.dict("os.environ", {"SYNTHETIC_KEY": "synthetic-environment-key"}):
            status = credentials.status("SYNTHETIC_KEY")
            self.assertEqual(status["source"], "environment")
            credentials.update({"api_key": " synthetic-saved-key "})
            self.assertEqual(credentials.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(credentials.key("SYNTHETIC_KEY"), "synthetic-saved-key")
            self.assertEqual(credentials.status("SYNTHETIC_KEY")["source"], "saved")
            self.assertNotIn("synthetic-saved-key", json.dumps(credentials.status("SYNTHETIC_KEY")))
            credentials.update({"api_key": "synthetic-replacement-key"})
            self.assertEqual(credentials.key("SYNTHETIC_KEY"), "synthetic-replacement-key")
            credentials.update({"remove": True})
            self.assertEqual(credentials.key("SYNTHETIC_KEY"), "synthetic-environment-key")
            self.assertEqual(credentials.status("SYNTHETIC_KEY")["source"], "environment")
            self.assertFalse(credentials.path.exists())
        with patch.dict("os.environ", {"SYNTHETIC_KEY": ""}):
            self.assertFalse(credentials.status("SYNTHETIC_KEY")["configured"])
            self.assertEqual(credentials.key("SYNTHETIC_KEY"), "")
            credentials.update({"remove": True})  # Repeat removal is safe.
        credentials.path.write_text("")
        self.assertEqual(credentials.status("SYNTHETIC_KEY")["state"], "error")

    def test_invalid_key_request_keeps_previous_and_failed_write_is_atomic(self):
        credentials = AICredentials(self.root / "private" / "deepseek.key")
        credentials.update({"api_key": "synthetic-original"})
        for payload in ({"api_key": ""}, {"api_key": "line\nvalue"}, {"api_key": "a\0b"},
                        {"api_key": "含中文"}, {"api_key": "x", "extra": "value"},
                        {"remove": False}, {"remove": 1}, {}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                credentials.update(payload)
            self.assertEqual(credentials.key("SYNTHETIC_KEY"), "synthetic-original")
        with patch("coffee_product.ai_settings.os.replace", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                credentials.update({"api_key": "synthetic-replacement"})
        self.assertEqual(credentials.key("SYNTHETIC_KEY"), "synthetic-original")
        self.assertEqual(list(credentials.path.parent.glob(".deepseek-key-*")), [])

    def test_readiness_distinguishes_login_and_key_setup_without_exposing_auth_output(self):
        credentials = AICredentials(self.root / "private" / "deepseek.key")
        credentials.update({"api_key": "synthetic-private-key"})
        seen = []
        def logged_in(command, **kwargs):
            seen.append(command)
            return SimpleNamespace(returncode=0, stdout="", stderr="Logged in using an API key: synthetic-secret-output")
        status = provider_status(self.settings, credentials, run=logged_in, which=lambda path: "/fake/codex")
        self.assertEqual(seen, [["/fake/codex", "login", "status"]])
        self.assertEqual(status["providers"]["codex"]["state"], "ready")
        self.assertTrue(status["providers"]["codex"]["logged_in"])
        self.assertEqual(status["providers"]["deepseek"]["source"], "saved")
        self.assertFalse(status["generation_verified"])
        self.assertEqual(status["scope"], "environment")
        self.assertNotIn("synthetic-secret-output", json.dumps(status))
        self.assertNotIn("synthetic-private-key", json.dumps(status))
        self.assertNotIn("api_key", self.settings.load()["deepseek"])

    def test_readiness_handles_missing_unlogged_and_unknown_codex(self):
        credentials = AICredentials(self.root / "private" / "absent.key")
        with patch("coffee_product.ai_settings.subprocess.run") as execute:
            result = provider_status(self.settings, credentials, which=lambda path: None)
            self.assertEqual(result["providers"]["codex"]["state"], "missing")
            execute.assert_not_called()
        for code, output, expected in ((1, "Not logged in", "login_required"), (1, "unrecognized status", "unknown")):
            run = lambda *args, **kwargs: SimpleNamespace(returncode=code, stdout=output, stderr="")
            status = provider_status(self.settings, credentials, run=run, which=lambda path: "/fake/codex")
            self.assertEqual(status["providers"]["codex"]["state"], expected)
        def failed(*args, **kwargs):
            raise OSError("synthetic error with text that must not leak")
        status = provider_status(self.settings, credentials, run=failed, which=lambda path: "/fake/codex")
        self.assertEqual(status["providers"]["codex"]["state"], "unknown")
        self.assertNotIn("must not leak", json.dumps(status))


if __name__ == "__main__":
    unittest.main(verbosity=2)
