from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib import error as urlerror, request as urlrequest
from . import recommendations

DISABLED_FEATURES = ("shell_tool", "apps", "plugins", "hooks", "browser_use",
                     "computer_use", "image_generation", "multi_agent",
                     "multi_agent_v2", "memories")


class AiPlanningError(ValueError):
    pass


class AiOutputError(AiPlanningError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def build_command(codex_path, directory, *, model=None, reasoning_effort=None):
    directory = Path(directory)
    command = [str(codex_path), "exec", "--ignore-user-config"]
    for feature in DISABLED_FEATURES:
        command.extend(["-c", f"features.{feature}=false"])
    command.extend(["-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0"])
    if model:
        command.extend(["-m", model])
    if reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort={json.dumps(reasoning_effort)}"])
    return command + ["--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check",
                      "-C", str(directory), "--output-schema", str(directory / "schema.json"),
                      "-o", str(directory / "result.json"), "-"]


@contextmanager
def _working_directory(work_dir):
    if work_dir is not None:
        directory = Path(work_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        yield directory
    else:
        with tempfile.TemporaryDirectory(prefix="coffee-ai-draft-") as temporary:
            yield Path(temporary)


def _validate_result(validate, raw, context, *, provider, model):
    try:
        return validate(raw, context, provider=provider, model=model)
    except AiOutputError:
        raise
    except ValueError as exc:
        raise AiOutputError(f"AI 任务结果未通过检查：{exc}") from exc


def call_codex(context, *, codex_path="codex", model=None, reasoning_effort=None,
               timeout=240, work_dir=None, run=None):
    """Single model invocation; no fallback, recipe save, database or device access."""
    run = run or subprocess.run
    schema_for, prompt_for, validate = recommendations.output_schema, recommendations.build_prompt, recommendations.validate_output
    with _working_directory(work_dir) as directory:
        (directory / "schema.json").write_text(_json(schema_for(context)), encoding="utf-8")
        prompt = prompt_for(context)
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        command = build_command(codex_path, directory, model=model, reasoning_effort=reasoning_effort)
        def keep_diagnostics(stderr):
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            (directory / "stderr.txt").write_text(stderr or "", encoding="utf-8")
        try:
            process = run(command, input=prompt, cwd=directory, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            keep_diagnostics(exc.stderr)
            diagnostic = f"；诊断保留于 {directory / 'stderr.txt'}" if work_dir is not None else ""
            raise AiPlanningError(f"本机 AI 任务超时；没有保存业务记录或执行设备动作{diagnostic}") from exc
        except OSError as exc:
            raise AiPlanningError("无法启动本机 Codex；请检查安装与登录状态") from exc
        keep_diagnostics(getattr(process, "stderr", None))
        if process.returncode:
            diagnostic = f"；诊断保留于 {directory / 'stderr.txt'}" if work_dir is not None else ""
            raise AiPlanningError(f"本机 Codex AI 任务失败（退出码 {process.returncode}）；没有回退到规则结果{diagnostic}")
        try:
            raw = (directory / "result.json").read_bytes()
        except OSError as exc:
            raise AiPlanningError("Codex 未返回 AI 任务结果文件；没有保存业务记录或执行设备动作") from exc
        if len(raw) > 256 * 1024:
            raise AiOutputError("AI 任务输出过大，未接受")
        return _validate_result(validate, raw, context, provider="codex", model=model)


class _NoCredentialRedirect(urlrequest.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _deepseek_headers(credentials, api_key_env):
    try:
        key = credentials.key(api_key_env) if credentials is not None else os.environ.get(api_key_env, "").strip()
    except (OSError, ValueError):
        raise AiPlanningError("本机保存的 DeepSeek 密钥无法读取，请在 AI 设置中重新保存") from None
    if not key:
        raise AiPlanningError("DeepSeek 尚未配置密钥：请在服务环境配置 DEEPSEEK_API_KEY")
    return {"Content-Type": "application/json", "Authorization": "Bearer " + key}


def call_deepseek(context, *, base_url="https://api.deepseek.com", model="deepseek-flash",
                  api_key_env="DEEPSEEK_API_KEY", timeout=600, max_tokens=16384,
                  work_dir=None, open_url=None, credentials=None):
    """Send one proposal request; credentials stay out of persisted job data."""
    headers = _deepseek_headers(credentials, api_key_env)
    schema_for, prompt_for, validate = recommendations.output_schema, recommendations.build_prompt, recommendations.validate_output
    schema = schema_for(context)
    prompt = prompt_for(context) + "\n输出 JSON schema：\n" + _json(schema)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "stream": False, "response_format": {"type": "json_object"}, "max_tokens": max_tokens}
    request = urlrequest.Request(base_url.rstrip("/") + "/chat/completions",
        data=_json(body).encode("utf-8"),
        headers=headers, method="POST")
    open_url = open_url or urlrequest.build_opener(_NoCredentialRedirect()).open
    with _working_directory(work_dir) as directory:
        (directory / "schema.json").write_text(_json(schema), encoding="utf-8")
        (directory / "prompt.txt").write_text(prompt, encoding="utf-8")
        try:
            with open_url(request, timeout=timeout) as response:
                raw = response.read(1024 * 1024 + 1)
        except urlerror.HTTPError as exc:
            # The remote error body can echo credentials. Keep only the status.
            exc.close()
            raise AiPlanningError(f"DeepSeek 调用失败（HTTP {exc.code}）；请核对地址、模型、密钥或额度") from None
        except (urlerror.URLError, OSError, TimeoutError):
            raise AiPlanningError("DeepSeek 连接失败或超时；尚未生成推荐") from None
        if len(raw) > 1024 * 1024:
            raise AiOutputError("DeepSeek 返回内容过大，未接受")
        (directory / "deepseek-response.json").write_bytes(raw)
        try:
            response = json.loads(raw)
            choice = response["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("incomplete completion")
            content = choice["message"]["content"]
            if type(content) is not str or not content.strip():
                raise ValueError("empty content")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise AiOutputError("DeepSeek 未返回完整 JSON 答案（可能为空、被截断或结构不符）") from None
        (directory / "result.json").write_text(content, encoding="utf-8")
        return _validate_result(validate, content, context, provider="deepseek", model=model)
