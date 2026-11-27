"""Run the local workspace against an explicitly selected existing SQLite database.

python -m coffee_product.server --db /absolute/path/coffee_inventory.db
Starting the web server never connects to a coffee machine.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import lru_cache
import hashlib
import html
from http import HTTPStatus
from http.server import ThreadingHTTPServer
import importlib.util
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import operations
import schema
import tastings
from coffeeSys import CoffeeInventoryHandler, RecipeRequestError
from ui import INDEX_HTML
from xbloom_bridge import protocol
from xbloom_bridge.recording import recipe_digest
from xbloom_bridge.report import generate_report, render_recipe_context
from . import planning, ai_planning, recommendations
from .deepseek_billing import receipt as deepseek_receipt
from .live_brew import LiveBrew
from .ai_settings import AISettings, AICredentials, DEFAULT_KEY_FILE, provider_status
from .store import Store, ProductError

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
ZONE = ZoneInfo("Asia/Shanghai")


def exact_json(raw):
    """Keep the existing recipe boundary's duplicate-key and decimal checks."""
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=protocol._unique_object,
                       parse_float=protocol._json_float, parse_constant=protocol._reject_constant)
    if type(value) is not dict:
        raise ValueError("请求必须是 JSON 对象")
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


class AIRecipeRunner:
    """One persisted proposal per request; no inventory writes or device access."""

    def __init__(self, store, settings, output, codex_path=None, credentials=None):
        self.store, self.settings = store, settings
        self.codex_path = codex_path or ai_planning.default_codex_command()
        self.credentials = credentials if credentials is not None else AICredentials()
        database_key = hashlib.sha256(str(store.db_path).encode()).hexdigest()[:16]
        self.output = Path(output).resolve() / database_key
        self.active = set()
        self.lock = threading.RLock()

    def _directory(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id):
            raise ValueError("AI 请求编号格式无效")
        return self.output / job_id

    def _save(self, job):
        directory = self._directory(job["id"])
        directory.mkdir(parents=True, exist_ok=True)
        job["updated_at"] = datetime.now(ZONE).isoformat(timespec="seconds")
        temporary = directory / "job.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(directory / "job.json")

    def _read(self, job_id):
        path = self._directory(job_id) / "job.json"
        if not path.exists():
            raise ProductError(404, "未找到这次 AI 拟方任务")
        return json.loads(path.read_text(encoding="utf-8"))

    def _with_usage(self, job):
        for attempt in job.get("attempts", []):
            if attempt["provider"] != "deepseek" or "usage" in attempt:
                continue
            if attempt["status"] == "running" and job["status"] == "running" and job["id"] in self.active:
                continue
            path = self._directory(job["id"]) / "deepseek" / "deepseek-response.json"
            config = job.get("_settings", {}).get("deepseek", {})
            usage = deepseek_receipt(path, config.get("base_url"))
            if usage is not None:
                attempt["usage"] = usage

    def _public(self, job):
        self._with_usage(job)
        return json.loads(json.dumps({key: value for key, value in job.items() if not key.startswith("_")}, ensure_ascii=False))

    def deepseek_history(self):
        rows = []
        for path in self.output.glob("*/job.json"):
            job = self._read(path.parent.name)
            self._with_usage(job)
            for attempt in job.get("attempts", []):
                if attempt["provider"] == "deepseek":
                    status = attempt["status"]
                    if status == "running" and job["id"] not in self.active:
                        status = "interrupted"
                    rows.append({"id": job["id"], "kind": job["kind"], "bean_id": job.get("bean_id"),
                                 "revision": bool(job.get("review_notes")), "created_at": job["created_at"],
                                 "model": attempt["model"], "status": status, "usage": attempt.get("usage")})
        return sorted(rows, key=lambda row: (row["usage"] or {}).get("created") or
                      datetime.fromisoformat(row["created_at"]).timestamp(), reverse=True)

    def get(self, job_id):
        with self.lock:
            job = self._read(job_id)
            if job["status"] == "running" and job_id not in self.active:
                job.update(status="interrupted", error="本地服务重启，这次 AI 任务已中断。没有自动重发；可重新提出一次方案。")
                self._save(job)
            return self._public(job)

    def start(self, data, *, kind="recipe"):
        required = {"request_id", "person_id"} if kind == "recommendation" else {"request_id", "bean_id", "mode", "goal"}
        optional = set() if kind == "recommendation" else {"base_recipe_id", "person_id", "revision", "dose_grams"}
        if not required <= data.keys() or data.keys() - required - optional - {"expected_ai"}:
            raise ValueError("AI 请求字段不完整或包含未知字段")
        if "dose_grams" in data:
            planning.check_dose(data["dose_grams"])
        job_id = data["request_id"]
        directory = self._directory(job_id)
        digest = hashlib.sha256(json.dumps([kind, data], sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        with self.lock:
            if (directory / "job.json").exists():
                if self._read(job_id)["_digest"] != digest:
                    raise ProductError(409, "同一 AI 请求编号不能用于不同内容")
                return self.get(job_id)
            if self.active:
                raise ProductError(409, "已有 AI 拟方正在进行，请先等待当前结果")
            config = self.settings.load()
            primary = config["primary"]
            route = {"provider": primary, "model": config[primary]["model"]}
            expected = data.get("expected_ai")
            if primary == "codex" and isinstance(expected, dict) and ("service_tier" in expected or "reasoning_effort" in expected):
                route.update(reasoning_effort=config[primary]["reasoning_effort"], service_tier=config[primary]["service_tier"])
            if "expected_ai" in data and expected != route:
                raise ProductError(409, "主用 AI 设置已变更，请核对制作台的最新型号后再提交。")
            planner = recommendations if kind == "recommendation" else ai_planning
            context = planner.build_context(self.store.state(), **{key: value for key, value in data.items()
                                                                  if key not in ("request_id", "expected_ai", "revision")})
            if "revision" in data:
                revision = data["revision"]
                if not isinstance(revision, dict) or set(revision) not in (
                    {"note", "payload_json"}, {"note", "payload_json", "prior_job_id"}
                ):
                    raise ValueError("修方需要本次修改意见与当前草稿")
                note, raw = revision["note"], revision["payload_json"]
                if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
                    raise ValueError("请写下 1–2000 字的修改意见")
                if not isinstance(raw, str):
                    raise ValueError("当前草稿参数格式无效")
                payload = protocol.parse_recipe(raw.encode())
                notes = []
                context["revision"] = {"current_payload": payload, "note": note.strip()}
                if "prior_job_id" in revision:
                    previous = self._read(revision["prior_job_id"])
                    if (previous.get("kind") != "recipe" or previous.get("status") != "completed"
                            or any(previous.get(k) != data.get(k) for k in ("bean_id", "mode", "person_id"))):
                        raise ValueError("所选拟方记录与本次豆子、模式或品饮人不符")
                    notes = previous.get("review_notes", [])
                    context["revision"]["previous_rationale"] = previous["result"]["rationale"]
                context["revision"]["previous_notes"] = notes
            job = {"id": job_id, "kind": kind, "status": "running", "created_at": datetime.now(ZONE).isoformat(timespec="seconds"),
                   "bean_id": data.get("bean_id"), "mode": data.get("mode"), "goal": data.get("goal", ""),
                   "person_id": data.get("person_id"), "base_recipe_id": data.get("base_recipe_id"),
                   "attempts": [], "_digest": digest, "_settings": config}
            if "dose_grams" in data:
                job["dose_grams"] = data["dose_grams"]
            if "revision" in data:
                job["review_notes"] = [*notes, note.strip()]
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "context.json").write_text(json.dumps(context, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            self.active.add(job_id)
            self._save(job)
            try:
                threading.Thread(target=self._generate, args=(job, context), daemon=True).start()
            except Exception:
                self.active.discard(job_id)
                job.update(status="failed", error="AI 工作线程未能启动，请重新提交。")
                self._save(job)
                raise
            return self._public(job)

    def _generate(self, job, context):
        config = job["_settings"]
        providers = [config["primary"]] + ([config["fallback"]] if config["fallback"] else [])
        try:
            for provider in providers:
                options = config[provider]
                attempt = {"provider": provider, "model": options["model"], "status": "running"}
                with self.lock:
                    job.update(provider=provider, model=options["model"])
                    job["attempts"].append(attempt)
                    self._save(job)
                directory = self._directory(job["id"]) / provider
                try:
                    if provider == "codex":
                        result = ai_planning.call_codex(context, codex_path=self.codex_path,
                            model=options["model"], reasoning_effort=options["reasoning_effort"],
                            service_tier=options["service_tier"],
                            timeout=options["timeout_seconds"], work_dir=directory)
                    elif provider == "ollama":
                        result = ai_planning.call_ollama(context, base_url=options["base_url"],
                            model=options["model"], timeout=options["timeout_seconds"],
                            num_ctx=options["num_ctx"], think=options["think"],
                            num_predict=options["num_predict"], work_dir=directory)
                    elif provider == "deepseek":
                        result = ai_planning.call_deepseek(context, base_url=options["base_url"],
                            model=options["model"], api_key_env=options["api_key_env"],
                            timeout=options["timeout_seconds"], max_tokens=options["max_tokens"],
                            work_dir=directory, credentials=self.credentials)
                    else:
                        raise ai_planning.AiPlanningError("未支持的 AI 提供方")
                except ai_planning.AiOutputError as exc:
                    with self.lock:
                        attempt.update(status="failed", error=str(exc))
                        job.update(status="failed", error=f"{provider} 返回的 AI 结果未通过校验：{exc}；未替换成规则方案。")
                    break
                except Exception as exc:
                    # A transport/login/model availability failure may use the configured backup.
                    message = str(exc) if isinstance(exc, ai_planning.AiPlanningError) else "AI 调用出现内部错误，请检查本机服务日志。"
                    with self.lock:
                        attempt.update(status="failed", error=message)
                    continue
                with self.lock:
                    attempt["status"] = "completed"
                    job.update(status="completed", result=result)
                break
            else:
                job.update(status="failed", error="配置的 AI 路线均未成功。请检查登录、服务地址及模型名称；未生成替代配方。")
        finally:
            with self.lock:
                self._with_usage(job)
                self._save(job)
                self.active.discard(job["id"])


class BrewProgress:
    """Project complete journal lines into the current user-visible phase."""
    phases = {"connecting": "connecting", "connected": "connected", "load_observed": "loaded",
              "start_observed": "started", "observation_ended": "reporting"}
    device_phases = {40506: "grinding", 40510: "pouring", 40511: "stopped"}

    def __init__(self, *, collect_samples=False):
        self.offset = 0
        self.telemetry = LiveBrew() if collect_samples else None
        self.phase = "registered"
        self.started = False
        self.waiting_handshake = False
        self.tank_low = False
        self.state_low = False

    def accept(self, event):
        if self.telemetry is not None:
            self.telemetry.accept(event)
        kind = event.get("kind")
        if kind == "tx_intent":
            self.waiting_handshake = event.get("label") == "handshake"
        elif kind == "error" and self.waiting_handshake:
            if "No matching machine evidence within observation window" in str(event.get("error", "")):
                self.phase = "handshake_timeout"
        elif kind == "decoded" and isinstance(event.get("data"), dict):
            data = event["data"]
            if data.get("kind") == "machine_info":
                self.waiting_handshake = False
                if data.get("water_source") == "tank" and type(data.get("water_ok")) is bool:
                    self.tank_low = not data["water_ok"]
                elif data.get("water_source") == "plumbed":
                    self.tank_low = False
            elif data.get("kind") == "state":
                state = data.get("state")
                if state == "no_water":
                    self.state_low = True
                elif state in {"idle", "armed", "starting", "brewing", "ready", "complete"}:
                    if self.state_low:
                        self.tank_low = False
                    self.state_low = False
            if self.started:
                if data.get("kind") == "legacy_event" and self.phase != "end_signal":
                    self.phase = self.device_phases.get(data.get("code"), self.phase)
                elif data.get("kind") == "completion_candidate" and self.phase in ("pouring", "stopped"):
                    self.phase = "end_signal"
        elif kind in self.phases:
            self.phase = ("no_update" if kind == "observation_ended" and event.get("stop_reason") == "no_update"
                          else self.phases[kind])
            if kind == "start_observed":
                self.started = True

    def read(self, path):
        with path.open("rb") as stream:
            stream.seek(self.offset)
            for line in stream:
                if not line.endswith(b"\n"):
                    break
                self.offset += len(line)
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict):
                    self.accept(event)
        return "no_water" if self.tank_low or self.state_low else self.phase


@lru_cache(maxsize=256)
def finished_brew_phase(path, modified_ns, size):
    # Finished journals are immutable. A replacement or later append gets a fresh replay.
    return BrewProgress().read(path)


@lru_cache(maxsize=16)
def recorded_telemetry(path, modified_ns, size):
    progress = BrewProgress(collect_samples=True)
    progress.read(path)
    progress.telemetry.closed = True
    return progress.telemetry.snapshot()


@lru_cache(maxsize=128)
def prestart_retry(path, modified_ns, size):
    """A complete failed attempt can be repeated only before any possible start."""
    session, brewer, last = {}, None, None
    with path.open("rb") as stream:
        for seq, line in enumerate(stream):
            if not line.endswith(b"\n"):
                return None
            try:
                event = json.loads(line)
            except (ValueError, UnicodeError):
                return None
            if not isinstance(event, dict) or event.get("seq") != seq:
                return None
            last = event.get("kind")
            if seq == 0:
                if last != "session" or event.get("operation") != "brew":
                    return None
                session = event
            elif last == "session":
                return None
            if last == "report_context":
                brewer = event.get("brewer")
            if last in ("tx_intent", "tx_returned") and event.get("label") not in {"handshake", "dose", "bypass+dose", "cup", "recipe"}:
                return None
            if last in ("start_observed", "start_unconfirmed", "write_uncertain", "journal_damage"):
                return None
            if last == "decoded":
                data = event.get("data")
                if not isinstance(data, dict) or data.get("state") in ("brewing", "starting") or data.get("code") in (40506, 40510):
                    return None
    if last == "error" and session.get("recipe_sha256") and session.get("address") and brewer:
        return {"token": path.name, "reviewed_sha256": session["recipe_sha256"],
                "address": session["address"], "brewer": brewer}


class BrewRunner:
    """Persisted claim + one dispatch. Lost replies never cause a second brew."""

    def __init__(self, store, output, python, enabled):
        self.store = store
        self.output = Path(output).resolve()
        # Resolving a venv executable symlink selects the base Python's packages.
        self.python = str(Path(python).expanduser().absolute())
        self.enabled = enabled
        self.unavailable_reason = ""
        if self.enabled:
            try:
                probe = subprocess.run([self.python, "-B", "-c", "from bleak import BleakClient"],
                                       cwd=ROOT, capture_output=True, timeout=8)
                if probe.returncode:
                    self.unavailable_reason = "冲煮用 Python 无法加载蓝牙依赖 bleak，请检查 --brew-python。"
            except (OSError, subprocess.TimeoutExpired):
                self.unavailable_reason = "冲煮用 Python 启动失败或超时，请检查 --brew-python。"
            self.enabled = not self.unavailable_reason
        self.threads = set()
        self.live_journals = {}
        self.lock = threading.Lock()

    def capture_phase(self, brew):
        try:
            if brew.get("capture_state") == "running":
                with self.lock:
                    live = self.live_journals.get(brew["id"])
                    return live[1].read(live[0]) if live else "registered"
            if brew.get("journal"):
                path = Path(brew["journal"]).resolve()
                if path.is_relative_to(self.output) and path.suffix == ".jsonl":
                    stat = path.stat()
                    return finished_brew_phase(path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            return "unavailable"
        return None

    def retry_details(self, brew):
        if (brew.get("status") != "needs_review" or brew.get("capture_state") != "finished"
                or not brew.get("journal") or not brew.get("capture_error") or brew.get("consumption_g") is not None):
            return None
        try:
            path = Path(brew["journal"]).resolve()
            if path.suffix == ".jsonl" and path.is_relative_to(self.output / f"brew-{brew['id']}"):
                stat = path.stat()
                return prestart_retry(path, stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
        return None

    def telemetry(self, brew):
        if brew.get("capture_state") == "running":
            with self.lock:
                live = self.live_journals.get(brew["id"])
                if live:
                    live[1].read(live[0])
                    return live[1].telemetry.snapshot()
        elif brew.get("journal"):
            path = Path(brew["journal"]).resolve()
            if path.suffix == ".jsonl" and path.is_relative_to(self.output):
                stat = path.stat()
                return recorded_telemetry(path, stat.st_mtime_ns, stat.st_size)
        return None

    def attempt_journals(self, brew_id):
        root = self.output / f"brew-{brew_id}"
        paths = [*root.glob("*.jsonl"), *root.glob("retry-*/*.jsonl")]
        return {p.stem: p for p in sorted(paths, key=lambda p: p.name) if p.resolve().is_relative_to(root)}

    def start(self, brew_id, data, *, rinse=False):
        if not self.enabled:
            raise ProductError(409, self.unavailable_reason or "自动冲煮未启用；可记录人工制作，配置蓝牙解释器后再使用自动入口")
        address = data.get("address")
        if not isinstance(address, str) or not re.fullmatch(r"[0-9A-Fa-f:-]{17,36}", address):
            raise ValueError("请填写明确的 xBloom 蓝牙地址（Mac UUID 或设备地址）")
        # The claim validates the same reviewed digest and persists start intent
        # before either writing a recipe or constructing a machine subprocess.
        if rinse:
            claimed = self.store.claim_rinse(brew_id, data)
        else:
            proof = self.retry_details(self.store.get_brew(brew_id)) if "retry_of" in data else None
            claimed = self.store.claim_start(brew_id, data, retry_proof=proof)
        if claimed["dispatch"]:
            thread = threading.Thread(target=self._rinse if rinse else self._capture, args=(brew_id, data), daemon=True)
            with self.lock:
                self.threads.add(thread)
            try:
                thread.start()
            except BaseException as exc:
                with self.lock:
                    self.threads.discard(thread)
                if rinse:
                    self.store.finish_rinse(brew_id, str(exc))
                else:
                    self.store.finish_capture(brew_id, None, None, error=str(exc))
                raise
        return claimed["brew"]

    def _rinse(self, brew_id, data):
        error = None
        try:
            directory = self.output / "rinses" / f"brew-{brew_id}"
            directory.mkdir(parents=True, exist_ok=False)
            args = [self.python, "-m", "xbloom_bridge", "rinse", "--address", data["address"],
                    "--volume", str(data["volume_ml"]), "--confirm-rinse", "--output", str(directory)]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            if result.returncode:
                error = result.stderr.strip()[-2000:] or f"润纸进程退出码 {result.returncode}"
                try:
                    error = json.loads(error.splitlines()[-1])["error"] or error
                except (ValueError, KeyError, TypeError):
                    pass
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                self.store.finish_rinse(brew_id, error)
            finally:
                with self.lock:
                    self.threads.discard(threading.current_thread())

    def _capture(self, brew_id, data):
        journal = report = None
        error = None
        try:
            brew = self.store.get_brew(brew_id)
            recipe = self.store.get_recipe(brew["recipe_id"])
            if recipe_digest(recipe["payload"]) != data["reviewed_sha256"]:
                raise ValueError("保存的配方与本次审核指纹不一致，未连接机器")
            directory = self.output / f"brew-{brew_id}"
            if "retry_of" in data:
                directory = directory / ("retry-" + hashlib.sha256(data["request_id"].encode()).hexdigest())
            directory.mkdir(parents=True, exist_ok=False)
            recipe_path = directory / "recipe.json"
            recipe_path.write_text(json.dumps(recipe["payload"], ensure_ascii=False,
                                             indent=2, allow_nan=False), encoding="utf-8")
            args = [self.python, "-m", "xbloom_bridge", "brew", "--recipe", str(recipe_path),
                    "--address", data["address"], "--confirm-start", "--reviewed-sha256",
                    data["reviewed_sha256"], "--output", str(directory),
                    "--report-title", recipe["title"]]
            if data.get("brewer"):
                args += ["--brewer", data["brewer"]]
            # Rinse, when requested, ran separately before the user authorized this brew.
            with (directory / "capture.log").open("x", encoding="utf-8") as output:
                proc = subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, encoding="utf-8")
                for line in proc.stdout:
                    output.write(line)
                    output.flush()
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(event, dict):
                        continue
                    if "journal" in event and isinstance(event["journal"], str):
                        candidate = Path(event["journal"]).resolve()
                        if candidate.is_relative_to(directory) and candidate.suffix == ".jsonl":
                            journal = str(candidate)
                            with self.lock:
                                self.live_journals.setdefault(brew_id, (candidate, BrewProgress(collect_samples=True)))
                    if isinstance(event.get("report"), dict):
                        for key in ("html", "html_path"):
                            if isinstance(event["report"].get(key), str):
                                candidate = Path(event["report"][key]).resolve()
                                if candidate.is_relative_to(directory) and candidate.suffix == ".html":
                                    report = str(candidate)
                    if event.get("error") or event.get("report_error"):
                        error = str(event.get("error") or event.get("report_error"))[:2000]
                code = proc.wait()
                if code:
                    error = error or f"采集进程退出码 {code}；请核对机器，不自动重启"
            if journal and Path(journal).is_file():
                report = generate_report(journal, recipe_document=recipe)["html"]
        except BaseException as exc:
            error = error or f"{type(exc).__name__}: {exc}"
        finally:
            try:
                # Capture completion does not claim machine completion. The user
                # must separately record observed outcome and actual consumption.
                with self.lock:
                    self.live_journals.pop(brew_id, None)
                self.store.finish_capture(brew_id, journal, report, error=error)
            finally:
                with self.lock:
                    self.threads.discard(threading.current_thread())


class Handler(CoffeeInventoryHandler):
    store = None
    runner = None
    ai_runner = None
    database_label = "本机 SQLite"
    device_address = ""

    def _guard_host(self):
        host = urlparse("http://" + self.headers.get("Host", "")).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RecipeRequestError("请使用本机工作台地址访问", HTTPStatus.FORBIDDEN)

    def _error(self, exc):
        if isinstance(exc, ProductError):
            status = getattr(exc, "status", 400)
        elif isinstance(exc, RecipeRequestError):
            status = exc.status
        elif isinstance(exc, KeyError):
            status = 404
        elif isinstance(exc, sqlite3.IntegrityError):
            status = 409
        elif isinstance(exc, sqlite3.OperationalError):
            status = 503
        elif isinstance(exc, (ValueError, UnicodeError, RecursionError)):
            status = 400
        else:
            status = 500
        if isinstance(exc, sqlite3.IntegrityError):
            message = "记录已有业务关联或唯一键冲突，操作未提交"
        elif isinstance(exc, sqlite3.OperationalError):
            message = "数据库暂时不可用，请保留当前输入并核对记录后再继续"
        else:
            message = str(exc)
        self._send_json({"error": message}, status)

    def _json_body(self):
        return exact_json(self._read_xb_recipe_body())

    def _bytes(self, body, content_type, filename=None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _view_brew(self, brew):
        value = dict(brew)
        phase = self.runner.capture_phase(brew)
        if brew.get("capture_state") == "running" or phase in ("no_water", "handshake_timeout", "no_update"):
            value["capture_phase"] = phase
        retry = self.runner.retry_details(brew)
        if retry and self.runner.enabled:
            value["retry"] = retry
        if brew.get("capture_state") == "finished":
            attempts = self.runner.attempt_journals(brew["id"])
            previous = [name for name, p in attempts.items() if str(p) != brew.get("journal")]
            if previous:
                value["previous_journals"] = [f"/api/product/brews/{brew['id']}/attempts/{name}/journal" for name in previous]
        value["report"] = f"/api/product/brews/{brew['id']}/report"
        value["journal"] = f"/api/product/brews/{brew['id']}/journal" if brew.get("journal") else None
        return value

    def do_GET(self):
        try:
            self._guard_host()
            path = urlparse(self.path).path
            if path in ("/studio", "/menu", "/experiences"):
                self._bytes((WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
                return
            if path in ("/", "/inventory"):
                self._send_html(INDEX_HTML)
                return
            assets = {"/product-assets/app.js": "app.js", "/product-assets/brew-chart.js": "brew-chart.js",
                      "/product-assets/style.css": "style.css"}
            if path in assets:
                file = WEB / assets[path]
                mime = "text/javascript" if file.suffix == ".js" else "text/css"
                self._bytes(file.read_bytes(), mime + "; charset=utf-8")
                return
            if path == "/api/product/state":
                state = self.store.state()
                state["database_label"] = self.database_label
                state["brews"] = [self._view_brew(b) for b in state["brews"]]
                state["menu"] = daily_menu(state["beans"])
                state["capabilities"] = {"bluetooth_start": self.runner.enabled,
                                         "bluetooth_unavailable_reason": self.runner.unavailable_reason,
                                         "grind_own_start": False, "manual": True,
                                         "public_ordering": False, "scope": "local",
                                         "default_address": self.device_address,
                                         "bluetooth_verified_this_release": False}
                config = self.ai_runner.settings.load()
                state["capabilities"]["ai_recipe"] = {"enabled": True, "engine": "configured",
                                                        "checks_expected_ai": True,
                                                        "deepseek_model_list": True,
                                                        "primary": config["primary"], "fallback": config["fallback"]}
                self._send_json(state)
                return
            if path == "/api/product/ai/settings":
                self._send_json(self.ai_runner.settings.load())
                return
            if path == "/api/product/ai/status":
                self._send_json(provider_status(self.ai_runner.settings, self.ai_runner.credentials,
                                                self.ai_runner.codex_path))
                return
            if path == "/api/product/ai/deepseek/usage":
                self._send_json({"calls": self.ai_runner.deepseek_history()})
                return
            match = re.fullmatch(r"/api/product/ai/jobs/([A-Za-z0-9_-]{1,100})", path)
            if match:
                self._send_json(self.ai_runner.get(match[1]))
                return
            match = re.fullmatch(r"/api/product/recipes/([1-9][0-9]*)/download", path)
            if match:
                item = self.store.get_recipe(int(match[1]))
                body = (json.dumps(item["payload"], ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
                self._bytes(body, "application/json; charset=utf-8", f"recipe-{item['id']}.json")
                return
            match = re.fullmatch(r"/api/product/sources/([A-Za-z0-9_-]+)", path)
            if match:
                source = planning.SOURCES.get(match[1])
                if not source:
                    raise KeyError("来源不存在")
                self._bytes(Path(source["path"]).read_bytes(), "text/plain; charset=utf-8")
                return
            match = re.fullmatch(r"/api/product/brews/([1-9][0-9]*)/attempts/([0-9]{8}T[0-9]{6}Z-[0-9a-f]{12})/journal", path)
            if match:
                self.store.get_brew(int(match[1]))
                self._artifact(self.runner.attempt_journals(int(match[1])).get(match[2]), "application/x-ndjson; charset=utf-8")
                return
            match = re.fullmatch(r"/api/product/brews/([1-9][0-9]*)/live", path)
            if match:
                brew = self.store.get_brew(int(match[1]))
                self._send_json({"brew": self._view_brew(brew), "telemetry": self.runner.telemetry(brew)})
                return
            match = re.fullmatch(r"/api/product/brews/([1-9][0-9]*)/(report|journal)", path)
            if match:
                brew = self.store.get_brew(int(match[1]))
                if match[2] == "journal":
                    self._artifact(brew.get("journal"), "application/x-ndjson; charset=utf-8")
                elif brew.get("report"):
                    self._artifact(brew["report"], "text/html; charset=utf-8")
                else:
                    self._bytes(self._manual_report(brew), "text/html; charset=utf-8")
                return
            if path.startswith("/api/product/"):
                raise KeyError("接口不存在")
            super().do_GET()
        except Exception as exc:
            self._error(exc)

    def _artifact(self, filename, content_type):
        if not filename:
            raise KeyError("这杯没有原始机器记录")
        path = Path(filename).resolve()
        if not path.is_relative_to(self.runner.output) or not path.is_file():
            raise KeyError("报告文件不在本次记录目录中")
        self._bytes(path.read_bytes(), content_type)

    def _manual_report(self, brew):
        escape = lambda value: html.escape(str(value if value is not None else "未记录"))
        recipe = self.store.get_recipe(brew["recipe_id"]) if brew.get("recipe_id") else None
        state = self.store.state()
        bean = next((b for b in state["beans"] if b["id"] == brew["bean_id"]), {})
        title = f"{bean.get('roaster', '')} · {bean.get('name', '咖啡')} · 第 {brew['id']} 杯"
        observations = brew.get("observations") or {}
        facts = [("制作状态（人工记录）", brew.get("status")),
                 ("机器完成确认", "未确认，人工观察与机器信号分别记录"),
                 ("屏显秒数（人工观察）", observations.get("screen_seconds")),
                 ("实际液重 g（人工记录）", observations.get("beverage_g")),
                 ("已登记耗豆 g", brew.get("consumption_g")),
                 ("原始说明", observations.get("note"))]
        body = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in facts)
        parameters = ""
        if not recipe and brew.get("legacy_data"):
            original = json.dumps(brew["legacy_data"], ensure_ascii=False, indent=2)
            parameters = f"<details open><summary>已有历史记录原文</summary><pre>{escape(original)}</pre></details>"
        if recipe:
            payload = recipe["payload"]
            rec = payload["recipe"]
            water = f"{rec['grandWater']} ml"
            if payload.get("bypassMl"):
                water = (f"过粉 {water} ＋ 旁通 {payload['bypassMl']} ml（设定 {payload['bypassTempC']} ℃），"
                         f"合计 {rec['grandWater'] + payload['bypassMl']} ml")
            parameters = f"<p>配方版本 {recipe['id']} · {escape(payload['doseGrams'])} g / {escape(water)} · {escape(rec['grinderSize'])} 档 · {escape(rec['rpm'])} RPM</p>"
            parameters += "<table><tr><th>段</th><th>水量 ml</th><th>设定 ℃</th><th>流速 ml/s</th><th>驻留 s</th></tr>"
            for i, pour in enumerate(rec["pours"], 1):
                parameters += "<tr>" + "".join(f"<td>{escape(v)}</td>" for v in
                    (i, pour["volume"], pour["temperature"], pour["flowRate"], pour["pausing"])) + "</tr>"
            parameters += "</table>"
        notes = []
        for feedback in state.get("feedback", []):
            if feedback.get("cup") == f"brew-{brew['id']}":
                person = next((p["name"] for p in state["people"] if p["id"] == feedback["person_id"]), "未知品饮者")
                text = json.dumps(feedback["feedback"], ensure_ascii=False, indent=2)
                notes.append(f"<h3>{escape(person)}</h3><pre>{escape(text)}</pre>")
        content = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title>
<style>body{{font:16px/1.7 system-ui;margin:40px auto;padding:0 24px;max-width:850px;background:#fffbf5;color:#403127}}table{{width:100%;border-collapse:collapse;margin:24px 0}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #e5d6c5}}pre{{white-space:pre-wrap}}small{{color:#806c5d}}.recipe-context{{background:#f4ece0;padding:12px 20px;border-radius:8px}}.recipe-context dt{{font-weight:650}}.recipe-context dd{{margin:0 0 12px}}</style>
<h1>{escape(title)}</h1>{render_recipe_context(recipe)}<h2>冲煮数据</h2><small>本报告来自当杯配方快照与人工记录。未采集的曲线、最后一滴和实际温度不推算。</small>{parameters}<table>{body}</table><h2>分别记录的品鉴</h2>{''.join(notes) or '<p>尚无品鉴反馈。</p>'}<p><a href="/studio">返回工作台</a></p></html>"""
        return content.encode("utf-8")

    def do_POST(self):
        try:
            self._guard_host()
            path = urlparse(self.path).path
            if not path.startswith("/api/product/"):
                self._legacy_write_guard(path)
                return super().do_POST()
            self.close_connection = True
            data = self._json_body()
            if path == "/api/product/ai/settings":
                result = self.ai_runner.settings.save(data)
            elif path == "/api/product/ai/deepseek/models":
                if data:
                    raise ValueError("模型列表使用已保存的服务地址和凭据")
                config = self.ai_runner.settings.load()["deepseek"]
                result = ai_planning.deepseek_models(config, self.ai_runner.credentials)
            elif path == "/api/product/ai/credentials/deepseek":
                self.ai_runner.credentials.update(data)
                config = self.ai_runner.settings.load()
                result = dict(self.ai_runner.credentials.status(config["deepseek"]["api_key_env"]),
                              model=config["deepseek"]["model"])
            elif path == "/api/product/ai/suggest":
                result = self.ai_runner.start(data)
            elif path == "/api/product/ai/recommend":
                result = self.ai_runner.start(data, kind="recommendation")
            elif path == "/api/product/settings/rinse":
                result = self.store.save_rinse_setting(data)
            elif path == "/api/product/preferences":
                result = self.store.save_preference(data)
            elif path == "/api/product/suggest":
                if set(data) - {"bean_id", "mode", "goal", "base_recipe_id", "dose_grams"}:
                    raise ValueError("建议请求含未知字段")
                bean = self.store.get_bean(data.get("bean_id"))
                base = self.store.get_recipe(data["base_recipe_id"]) if data.get("base_recipe_id") else None
                state = self.store.state()
                result = planning.suggest(bean, mode=data.get("mode", "xbloom"),
                                          goal=data.get("goal", ""), base=base,
                                          experiences=state["experiences"],
                                          dose_grams=planning.check_dose(data["dose_grams"]) if "dose_grams" in data else None)
            elif path == "/api/product/recipes":
                if "payload_json" in data:
                    if "payload" in data or not isinstance(data["payload_json"], str):
                        raise ValueError("配方只提交一份原始 JSON 或参数对象")
                    data["payload"] = protocol.parse_recipe(data.pop("payload_json").encode("utf-8"))
                result = self.store.create_recipe(data)
            elif path == "/api/product/orders":
                result = self.store.create_order(data)
            elif match := re.fullmatch(r"/api/product/orders/([1-9][0-9]*)/(update|cancel|delete)", path):
                action = {"update": self.store.update_order, "cancel": self.store.cancel_order,
                          "delete": self.store.delete_order}[match[2]]
                result = action(int(match[1]), data)
            elif path == "/api/product/brews":
                result = self._view_brew(self.store.create_brew(data))
            elif path == "/api/product/feedback":
                result = self.store.save_feedback(data)
            elif path == "/api/product/experiences":
                result = self.store.create_experience(data)
            elif match := re.fullmatch(r"/api/product/brews/([1-9][0-9]*)/(start|rinse|record)", path):
                bid = int(match[1])
                if match[2] == "rinse":
                    result = self._view_brew(self.runner.start(bid, data, rinse=True))
                elif match[2] == "start":
                    result = self._view_brew(self.runner.start(bid, data))
                else:
                    result = self._view_brew(self.store.record_brew(bid, data))
            elif match := re.fullmatch(r"/api/product/experiences/([1-9][0-9]*)/evaluate", path):
                result = self.store.evaluate_experience(int(match[1]), data)
            else:
                raise KeyError("接口不存在")
            self._send_json(result)
        except Exception as exc:
            self._error(exc)

    def _legacy_write_guard(self, path):
        origins = self.headers.get_all("Origin", [])
        if origins and (len(origins) != 1 or origins[0] != f"http://{self.headers.get('Host')}"):
            raise RecipeRequestError("请在本机咖啡工作台修改数据", HTTPStatus.FORBIDDEN)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise RecipeRequestError("不接受跨站写入", HTTPStatus.FORBIDDEN)
        match = re.fullmatch(r"/api/brews/([1-9][0-9]*)", path)
        if match:
            brew = self.store.get_brew(int(match[1]))
            if brew.get("recipe_id"):
                raise ProductError(409, "这杯已关联审核配方，请在制作工作台记录结果，不可覆盖历史快照")

    def do_PUT(self):
        try:
            self._guard_host()
            self._legacy_write_guard(urlparse(self.path).path)
            super().do_PUT()
        except Exception as exc:
            self._error(exc)

    def do_DELETE(self):
        try:
            self._guard_host()
            self._legacy_write_guard(urlparse(self.path).path)
            super().do_DELETE()
        except Exception as exc:
            self._error(exc)


def backup_database(database, directory):
    """Consistent SQLite backup, including WAL, before additive schema changes."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ("before-coffee-product-" + datetime.now(ZONE).strftime("%Y%m%d-%H%M%S-%f") + ".db")
    source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--label", default="本机 SQLite", help="Display identity of this database, e.g. 试用副本")
    parser.add_argument("--device-address", default="", help="Previously selected machine; shown for review, never scanned automatically")
    parser.add_argument("--output", type=Path, default=ROOT / "ble_runs" / "product")
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "backups")
    parser.add_argument("--brew-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--ai-settings", type=Path, default=Path(__file__).resolve().parent / "ai-settings.local.json")
    parser.add_argument("--ai-output", type=Path, default=ROOT / "outputs" / "ai-recipes")
    parser.add_argument("--ai-key-file", type=Path, default=DEFAULT_KEY_FILE,
                        help="Private DeepSeek key file; never included in settings or job records")
    parser.add_argument("--codex-command", help="Local Codex executable; defaults to the macOS app CLI when available, then PATH")
    parser.add_argument("--enable-bluetooth", action="store_true",
                        help="Enable reviewed per-cup start endpoint; never connects on startup")
    args = parser.parse_args(argv)
    database = args.db.expanduser().resolve()
    if not database.is_file():
        parser.error("--db 必须指向现有库存数据库；不自动创建第二份库存")
    # Bind before any migration: an occupied port must not mutate the database.
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        store = Store(database)
        backup = backup_database(database, args.backup_dir.resolve())
        store.init_schema()
        # Legacy inventory operations share the same connection policy and DB.
        schema.DB_PATH = database
        schema.get_db_connection = store.connect
        operations.get_db_connection = store.connect
        tastings.get_db_connection = store.connect
        Handler.store = store
        Handler.database_label = args.label
        Handler.device_address = args.device_address
        Handler.runner = BrewRunner(store, args.output, args.brew_python, args.enable_bluetooth)
        Handler.ai_runner = AIRecipeRunner(store, AISettings(args.ai_settings), args.ai_output, args.codex_command,
                                          credentials=AICredentials(args.ai_key_file))
        print(f"备份：{backup}", flush=True)
        print(f"咖啡工作台：http://127.0.0.1:{args.port}/studio", flush=True)
        print(f"豆单：http://127.0.0.1:{args.port}/menu", flush=True)
        print(f"使用现有主库：{database}；启动不会连接机器", flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        print("网页服务停止；这不表示机器已经停止。", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
