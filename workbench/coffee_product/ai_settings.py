"""Local AI settings, private credentials and non-generating readiness checks."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from datetime import datetime
from pathlib import Path
import tempfile
import tomllib
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


PROVIDERS = {"codex", "ollama", "deepseek"}
DEEPSEEK_DEFAULTS = {"base_url": "https://api.deepseek.com", "model": "deepseek-flash",
                     "api_key_env": "DEEPSEEK_API_KEY", "timeout_seconds": 600,
                     "max_tokens": 16384}
DEFAULT_KEY_FILE = Path.home() / "Library/Application Support/xbloom-brewflow/deepseek-api-key"


def _fields(value, names, location):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(f"{location} 字段不完整或包含未知字段")


def _text(value, location):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{location} 必须是非空文字")
    return value.strip()


def _positive_int(value, location):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{location} 必须是正整数")
    return value


def _base_url(value, location):
    base_url = _text(value, location)
    try:
        url = urlsplit(base_url)
        port = url.port
        valid = (url.scheme in {"http", "https"} and bool(url.hostname)
                 and url.username is None and url.password is None
                 and not url.query and not url.fragment
                 and not any(char.isspace() or ord(char) < 32 for char in base_url)
                 and (port is None or port > 0))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{location} 必须是无凭据、查询参数或片段的 HTTP(S) 地址")
    return base_url.rstrip("/")


def validate(payload: dict) -> dict:
    """Read older settings without replacing their existing provider choices."""
    if type(payload) is dict and "deepseek" not in payload:
        payload = dict(payload, deepseek=dict(DEEPSEEK_DEFAULTS))
    _fields(payload, ("primary", "fallback", "codex", "ollama", "deepseek"), "AI 配置")
    primary, fallback = payload["primary"], payload["fallback"]
    if type(primary) is not str or primary not in PROVIDERS:
        raise ValueError("primary 必须是 codex、ollama 或 deepseek")
    if fallback is not None and (type(fallback) is not str or fallback not in PROVIDERS):
        raise ValueError("fallback 必须是 codex、ollama、deepseek 或 null")
    if primary == fallback:
        raise ValueError("主模型提供方和备用提供方不能相同")
    codex, ollama = payload["codex"], payload["ollama"]
    if isinstance(codex, dict):
        codex = {"service_tier": "default", **codex}
    _fields(codex, ("model", "reasoning_effort", "service_tier", "timeout_seconds"), "codex")
    if codex["service_tier"] not in ("default", "priority"):
        raise ValueError("Codex 速度请选择标准或 Fast")
    if type(ollama) is dict:
        ollama = {"think": False, "num_predict": 8192, **ollama}
    _fields(ollama, ("base_url", "model", "timeout_seconds", "num_ctx", "think", "num_predict"), "ollama")
    think = ollama["think"]
    if type(think) is not bool:
        think = _text(think, "ollama.think（布尔值或模型推理级别）")
    base_url = _base_url(ollama["base_url"], "ollama.base_url")
    deepseek = payload["deepseek"]
    _fields(deepseek, DEEPSEEK_DEFAULTS, "deepseek")
    deepseek_url = _base_url(deepseek["base_url"], "deepseek.base_url")
    address = urlsplit(deepseek_url)
    if address.scheme != "https" and address.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("DeepSeek 密钥只发送至 HTTPS 或本机接口")
    key_env = _text(deepseek["api_key_env"], "deepseek.api_key_env")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ValueError("api_key_env 请填写环境变量名，不填写密钥")
    max_tokens = _positive_int(deepseek["max_tokens"], "deepseek.max_tokens")
    if max_tokens > 393216:
        raise ValueError("deepseek.max_tokens 超过接口上限 393216")
    return {
        "primary": primary, "fallback": fallback,
        "codex": {
            "model": _text(codex["model"], "codex.model"),
            "service_tier": codex["service_tier"],
            "reasoning_effort": _text(codex["reasoning_effort"], "codex.reasoning_effort"),
            "timeout_seconds": _positive_int(codex["timeout_seconds"], "codex.timeout_seconds"),
        },
        "ollama": {
            "base_url": base_url.rstrip("/"),
            "model": _text(ollama["model"], "ollama.model"),
            "timeout_seconds": _positive_int(ollama["timeout_seconds"], "ollama.timeout_seconds"),
            "num_ctx": _positive_int(ollama["num_ctx"], "ollama.num_ctx"),
            "think": think,
            "num_predict": _positive_int(ollama["num_predict"], "ollama.num_predict"),
        },
        "deepseek": {"base_url": deepseek_url,
                     "model": _text(deepseek["model"], "deepseek.model"),
                     "api_key_env": key_env,
                     "timeout_seconds": _positive_int(deepseek["timeout_seconds"], "deepseek.timeout_seconds"),
                     "max_tokens": max_tokens},
    }


def _codex_preferences(path: Path) -> dict:
    """Read only top-level model/effort entries, never profiles or credentials."""
    allowed = {"model", "model_reasoning_effort"}
    values = {}
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.lstrip().startswith("["):
                    break
                key = line.partition("=")[0].strip()
                if key not in allowed:
                    continue
                try:
                    value = tomllib.loads(line).get(key)
                except tomllib.TOMLDecodeError:
                    continue
                if type(value) is str and value.strip():
                    values[key] = value.strip()
                if values.keys() == allowed:
                    break
    except (OSError, UnicodeError):
        pass
    return values


class AICredentials:
    """Private file for a UI-managed key; never included in public settings/jobs."""

    def __init__(self, path=None):
        self.path = Path(path).expanduser() if path is not None else DEFAULT_KEY_FILE

    @staticmethod
    def _key(value):
        if (type(value) is not str or not value.strip() or len(value.strip()) > 8192
                or any(ord(char) < 33 or ord(char) > 126 for char in value.strip())):
            raise ValueError("请填写有效的 API Key；不接受空值、空格或多行内容")
        return value.strip()

    def update(self, data):
        if type(data) is dict and set(data) == {"remove"} and data["remove"] is True:
            self.path.unlink(missing_ok=True)
            return
        _fields(data, ("api_key",), "密钥请求")
        key = self._key(data["api_key"])
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".deepseek-key-", delete=False) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), 0o600)
                stream.write(key)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def key(self, env_name):
        # A newly saved UI key takes effect even if the process has an old env key.
        try:
            return self._key(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            value = os.environ.get(env_name, "").strip()
            return self._key(value) if value else ""

    def status(self, env_name):
        environment = bool(os.environ.get(env_name, "").strip())
        try:
            saved = True
            info = self.path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
                return {"configured": False, "source": "saved", "saved_key": True,
                        "environment_key": environment, "state": "error",
                        "message": "本机密钥文件不可用，请重新保存或移除后使用环境配置"}
        except FileNotFoundError:
            saved = False
        except OSError:
            return {"configured": False, "source": "none", "saved_key": False,
                    "environment_key": environment, "state": "error",
                    "message": "无法检查本机保存的密钥，请检查文件访问权限"}
        source = "saved" if saved else "environment" if environment else "none"
        message = {"saved": "本机已保存 DeepSeek 密钥。",
                   "environment": "使用服务环境中的 DeepSeek 密钥。",
                   "none": "尚未配置密钥，可在此页面保存 API Key"}[source]
        return {"configured": source != "none", "source": source, "saved_key": saved,
                "environment_key": environment, "state": "configured" if source != "none" else "missing",
                "message": message}


def provider_status(settings, credentials, codex_path="codex", *, run=None, which=None):
    """Inspect local prerequisites only; no inference request or raw auth output."""
    config = settings.load()
    executable = (which or shutil.which)(str(codex_path))
    codex = {"installed": executable is not None, "logged_in": None,
             "state": "missing", "message": "未找到 Codex CLI，请先在这台 Mac 安装并登录",
             "model": config["codex"]["model"]}
    if executable is not None:
        try:
            result = (run or subprocess.run)([executable, "login", "status"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", timeout=8, check=False)
            # Only convert the CLI result into a state; never return its text.
            output = ((result.stdout or "") + (result.stderr or "")).lower()
            if "not logged in" in output:
                codex.update(logged_in=False, state="login_required", message="Codex 已安装，尚未登录；请在本机完成 Codex 登录")
            elif result.returncode == 0 and "logged in" in output:
                codex.update(logged_in=True, state="ready", message="Codex 已登录。制作台通过 HTTPS 流式调用，环境检查已完成。")
            else:
                codex.update(state="unknown", message="Codex 已安装，但未能确认登录状态；可重新检查")
        except (OSError, subprocess.SubprocessError):
            codex.update(state="unknown", message="Codex 登录状态检查失败或超时；可重新检查")
    deepseek = dict(credentials.status(config["deepseek"]["api_key_env"]), model=config["deepseek"]["model"])
    return {"primary": config["primary"], "fallback": config["fallback"],
            "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
            "scope": "environment", "generation_verified": False,
            "providers": {"codex": codex, "deepseek": deepseek}}


class AISettings:
    """Server-owned path; load returns defaults until a full config is saved.

    Saved JSON is authoritative; old Ollama objects may omit think/num_predict.
    All other fields must remain complete and valid. A broken
    saved file raises ValueError instead of silently switching model backends.
    An explicit codex_config_path imports model preferences for callers that request it.
    """

    def __init__(self, path, *, codex_config_path=None):
        self.path = Path(path).expanduser()
        self.codex_config_path = (Path(codex_config_path).expanduser()
                                  if codex_config_path is not None else None)

    def defaults(self) -> dict:
        preferences = _codex_preferences(self.codex_config_path) if self.codex_config_path else {}
        return {
            "primary": "codex", "fallback": "deepseek",
            "codex": {"model": preferences.get("model", "gpt-6.1-terra"),
                      "reasoning_effort": preferences.get("model_reasoning_effort", "high"),
                      "service_tier": "priority",
                      "timeout_seconds": 600},
            "ollama": {"base_url": "http://127.0.0.1:11434", "model": "qwen3.8:27b-mlx",
                       "timeout_seconds": 600, "num_ctx": 65536, "think": False, "num_predict": 8192},
            "deepseek": dict(DEEPSEEK_DEFAULTS),
        }

    def load(self) -> dict:
        try:
            with self.path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
        except FileNotFoundError:
            return self.defaults()
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("AI 配置文件不是有效的 UTF-8 JSON") from exc
        return validate(payload)

    def save(self, payload: dict) -> dict:
        settings = validate(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=f".{self.path.name}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(settings, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return settings
