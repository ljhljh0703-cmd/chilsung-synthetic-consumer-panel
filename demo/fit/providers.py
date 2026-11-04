"""Exact-model, no-tools survey transports. Never print provider bodies."""
import json
import re
import shlex
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

TERRA = "gpt-6.1-terra"
HAIKU = "claude-haiku-5-5"
KEYS = Path.home() / ".config/lotte-ax/keys.env"
SPECS = {
    TERRA: ("https://api.openai.com/v1", "OPENAI_API_KEY", "responses"),
    HAIKU: ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "messages"),
}
SETTINGS = {
    TERRA: {"reasoning": {"effort": "none"}, "max_output_tokens": 1024, "store": False},
    HAIKU: {"thinking": {"type": "disabled"}, "output_config": {"effort": "low"}, "max_tokens": 1024},
}


class Stop(RuntimeError):
    pass


class Quota(Stop):
    pass


def is_quota(status, body):
    if status not in (402, 429, 400):
        return False
    try:
        error = json.loads(body).get("error", {})
        if not isinstance(error, dict):
            return False
    except (ValueError, AttributeError):
        return False
    code = str(error.get("code", "")).lower()
    message = str(error.get("message", "")).lower()
    return code in {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active", "credit_balance_too_low"} or any(
        term in message for term in ("credit balance is too low", "insufficient credits", "exceeded your current quota",
                                     "billing hard limit", "purchase credits", "spending limit", "payment required"))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def load_keys():
    try:
        lines = KEYS.read_text().splitlines()
    except OSError:
        raise Stop("지정 키 파일 읽기 실패") from None
    result = {}
    required = {s[1] for s in SPECS.values()}
    for line in lines:
        match = re.fullmatch(r"\s*(?:export\s+)?([A-Z_]+)\s*=\s*(.*)", line)
        if match and match[1] in required:
            try:
                parts = shlex.split(match[2], comments=True)
            except ValueError:
                raise Stop("지정 키 파일 형식 오류") from None
            if match[1] in result or len(parts) != 1 or not parts[0] or not parts[0].isascii() or any(c.isspace() for c in parts[0]):
                raise Stop("지정 키 파일 형식 오류")
            result[match[1]] = parts[0]
    if result.keys() != required:
        raise Stop("지정 키 파일에 두 키가 필요")
    return result


def request(model, action, keys, payload=None):
    base, key, endpoint = SPECS[model]
    path = f"models/{model}" if action == "model" else endpoint
    headers = ({"Authorization": "Bearer " + keys[key]} if model == TERRA else
               {"x-api-key": keys[key], "anthropic-version": "2023-06-01"})
    headers["Content-Type"] = "application/json"
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    try:
        with build_opener(NoRedirect).open(Request(f"{base}/{path}", data, headers), timeout=30) as response:
            value = json.load(response)
    except HTTPError as error:
        if is_quota(error.code, error.read(16_384)):
            raise Quota(f"{model} {action} 결제·크레딧 한도 (HTTP {error.code})") from None
        raise Stop(f"{model} {action} HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise Stop(f"{model} {action} 연결 실패 ({type(reason).__name__}, errno={getattr(reason, 'errno', None)})") from None
    except (UnicodeError, ValueError):
        raise Stop(f"{model} {action} API 응답 형식 오류") from None
    if not isinstance(value, dict):
        raise Stop(f"{model} {action} API 응답 형식 오류")
    return value


def actual_model(expected, value):
    # A provider may resolve the exact alias to a dated snapshot of the same model.
    if not isinstance(value, str) or not re.fullmatch(re.escape(expected) + r"(?:-\d{4}-?\d{2}-?\d{2})?", value):
        raise Stop(f"{expected} 요청과 반환 모델 불일치 또는 모델명 누락")
    return value


def preflight(model, keys):
    return actual_model(model, request(model, "model", keys).get("id"))


def answer(model, system, user, keys):
    payload = {"model": model, **SETTINGS[model]}
    if model == TERRA:
        payload.update(instructions=system, input=user)
    else:
        payload.update(system=system, messages=[{"role": "user", "content": user}])
    value = request(model, "survey", keys, payload)
    returned = actual_model(model, value.get("model"))
    if model == TERRA:
        if value.get("status") != "completed":
            return returned, ""
        blocks = [b for item in value.get("output", []) if item.get("type") == "message"
                  for b in item.get("content", [])]
        if any(b.get("type") == "refusal" for b in blocks):
            return returned, ""
        return returned, "".join(b.get("text", "") for b in blocks if b.get("type") == "output_text")
    if value.get("stop_reason") != "end_turn":
        return returned, ""
    return returned, "".join(b.get("text", "") for b in value.get("content", []) if b.get("type") == "text")


CLI_SETTINGS = {
    TERRA: {"model_reasoning_effort": "none", "web_search": "disabled", "shell_tool": False,
            "session_persistence": False, "api_store_false": "unavailable"},
    HAIKU: {"effort": "low", "thinking": {"type": "disabled"}, "tools": [], "session_persistence": False,
            "api_store_false": "unavailable"},
}


def cli_answer(model, system, user, _keys):
    exe = shutil.which("codex" if model == TERRA else "claude")
    if not exe:
        raise Stop(f"{model} 로그인 CLI 미설치")
    # Keep login credentials in their original store, never use inherited API keys.
    env = {k: os.environ[k] for k in ("HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME") if k in os.environ}
    with tempfile.TemporaryDirectory(prefix="lotte-fit-cli-") as cwd:
        if model == TERRA:
            cmd = [exe, "--ask-for-approval", "never", "exec", "--skip-git-repo-check", "--ephemeral",
                   "--ignore-user-config", "--sandbox", "read-only", "--disable", "shell_tool",
                   "--disable", "plugins", "-c", 'web_search="disabled"', "-c",
                   f'model_reasoning_effort="{CLI_SETTINGS[model]["model_reasoning_effort"]}"',
                   "-c", 'model_provider="openai"', "-m", model, "--color", "never", "-"]
        else:
            env["CLAUDE_CODE_EXTRA_BODY"] = json.dumps({"thinking": CLI_SETTINGS[model]["thinking"]})
            cmd = [exe, "-p", "--model", model, "--effort", "low", "--tools", "",
                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
                   "--output-format", "json"]
        prompt = system + "\n도구, 명령, 파일, 웹을 사용하지 마세요.\n\n" + user
        try:
            result = subprocess.run(cmd, input=prompt, text=True, capture_output=True, cwd=cwd, env=env, timeout=150)
        except (subprocess.TimeoutExpired, OSError):
            raise Stop(f"{model} 로그인 CLI 연결 실패") from None
        if result.returncode:
            raise Stop(f"{model} 로그인 CLI 실패 (exit {result.returncode})")
    if model == TERRA:
        # Only accept the runtime model banner; never synthesize it from -m.
        names = re.findall(r"^model: ([^\s]+)\s*$", result.stderr, re.M)
        return actual_model(model, names[0] if len(set(names)) == 1 else None), result.stdout.strip()
    try:
        payload = json.loads(result.stdout)
        names = [k for k in payload.get("modelUsage", {}) if k.startswith("claude-")]
    except (ValueError, AttributeError, TypeError):
        raise Stop(f"{model} 로그인 CLI 응답 메타데이터 없음") from None
    if payload.get("is_error"):
        raise Stop(f"{model} 로그인 CLI 오류")
    return actual_model(model, names[0] if len(names) == 1 else None), payload.get("result", "")


if __name__ == "__main__":
    try:
        keys = load_keys()
        for model in SPECS:
            print(preflight(model, keys), flush=True)
    except Stop as error:
        raise SystemExit(str(error)) from None
