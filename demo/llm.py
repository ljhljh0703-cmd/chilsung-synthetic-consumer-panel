"""언어모델 호출을 한 곳에 모은다. 키 없이 구독 계정 로그인으로 돌릴 수 있다.

LLM_BACKEND (.env 또는 환경 변수)
  codex  (기본) ChatGPT 구독으로 로그인한 Codex CLI (`codex login` 한 번)
  claude        Claude 구독으로 로그인한 Claude Code CLI (`claude` 로그인 한 번)
  api           OpenAI API 키 (OPENAI_API_KEY)
LLM_MODEL      비우면 각 도구의 기본 모델. 예) codex: gpt-5-mini, claude: haiku
LLM_EFFORT     codex 생각 깊이 (기본 low: 빠르고 사용량을 덜 씀)

CLI 는 빈 임시 폴더에서 돌린다. 이 폴더의 정답지(config/outcomes.json)를 볼 수 없게 하기 위해서다.
"""
import json, os, shutil, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).parent
NO_TOOLS = "도구나 명령을 쓰지 말고, 파일을 열지 말고, 아래 내용만 보고 바로 답하세요.\n\n"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def backend():
    load_env()
    return os.environ.get("LLM_BACKEND", "codex")


def model_name():
    b = backend()
    return f"{b}:{os.environ.get('LLM_MODEL') or ('gpt-5-mini' if b == 'api' else 'default')}"


def check():
    """돌리기 전 점검. 문제가 있으면 사람이 읽을 문장을 돌려준다."""
    b = backend()
    if b == "api":
        return None if os.environ.get("OPENAI_API_KEY") else "OPENAI_API_KEY 가 없습니다."
    exe = "codex" if b == "codex" else "claude"
    if not shutil.which(exe):
        return f"{exe} 명령이 없습니다. 설치 후 로그인하세요."
    if b == "codex":
        r = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
        if r.returncode != 0 or "not logged" in (r.stdout + r.stderr).lower():
            return "Codex 로그인이 안 돼 있습니다. 터미널에서 codex login 을 한 번 하세요."
    return None


def record_model(log):
    """codex 실행 머리말의 「model: ...」「reasoning effort: ...」 줄을 results/model_used.json 에 남긴다."""
    info = {}
    for line in log.splitlines():
        s = line.strip().lower()
        for key in ("model:", "reasoning effort:", "provider:"):
            if s.startswith(key):
                info[key.rstrip(":")] = line.split(":", 1)[1].strip()
    if not info.get("model"):
        return
    f = ROOT / "results" / "model_used.json"
    try:
        seen = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
    except ValueError:
        seen = []
    if info not in seen:
        seen.append(info)
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")


def ask_json(system, user, schema, timeout=600):
    b = backend()
    model = os.environ.get("LLM_MODEL", "")
    if b == "api":
        from openai import OpenAI
        r = OpenAI().chat.completions.create(
            model=model or "gpt-5-mini",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "out", "strict": True, "schema": schema}})
        return json.loads(r.choices[0].message.content)

    with tempfile.TemporaryDirectory(prefix="persona-") as tmp:
        tmp = Path(tmp)
        prompt = NO_TOOLS + system + "\n\n" + user
        if b == "codex":
            (tmp / "schema.json").write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                   "-C", str(tmp), "--output-schema", str(tmp / "schema.json"), "-o", str(tmp / "out.json"),
                   "-c", f'model_reasoning_effort="{os.environ.get("LLM_EFFORT", "low")}"', "-c", 'web_search="disabled"', "--color", "never"]
            if model:
                cmd += ["-m", model]
            r = subprocess.run(cmd + ["-"], input=prompt, capture_output=True, text=True, cwd=tmp, timeout=timeout)
            record_model(r.stderr + r.stdout)
            out = tmp / "out.json"
            if not out.exists() or not out.read_text(encoding="utf-8").strip():
                raise RuntimeError(f"codex 응답 없음: {(r.stderr or r.stdout)[-400:]}")
            return json.loads(out.read_text(encoding="utf-8"))
        if b == "claude":
            cmd = ["claude", "-p", "--tools", "", "--output-format", "json", "--no-session-persistence",
                   "--json-schema", json.dumps(schema, ensure_ascii=False)]
            if model:
                cmd += ["--model", model]
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=tmp, timeout=timeout)
            if r.returncode != 0:
                raise RuntimeError(f"claude 실패: {(r.stderr or r.stdout)[-400:]}")
            o = json.loads(r.stdout)
            if isinstance(o.get("structured_output"), dict):
                return o["structured_output"]
            txt = o.get("result", "").strip().removeprefix("```json").removesuffix("```").strip()
            return json.loads(txt)
    raise ValueError(f"모르는 LLM_BACKEND: {b}")
