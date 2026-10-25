"""번들 Codex CLI를 ChatGPT 로그인으로 실행해 한 번의 요청을 처리한다. API 키는 쓰지 않는다.

실행 방법은 docs/spike-results.md에서 확정: 빈 stdin, read-only 샌드박스, 도구 자동 승인, 전용 CODEX_HOME.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from . import paths, session

PKG = Path(__file__).resolve().parent
REPO = PKG.parent.parent
CODEX_NAMES = ("codex-x86_64-pc-windows-msvc.exe", "codex.exe")
INSTRUCTIONS = PKG / "assets" / "AGENTS.md"
# 문서 편집에 쓰지 않는 Codex 기본 도구들. 도구 정의가 매 호출마다 수천 토큰씩 들어가므로 끈다.
DISABLED_FEATURES = (
    "shell_tool", "unified_exec", "shell_snapshot", "view_image", "image_generation",
    "browser_use", "browser_use_external", "computer_use", "in_app_browser", "multi_agent",
    "apps", "plugins", "remote_plugin", "goals", "skill_search", "tool_suggest", "sleep_tool",
)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _default_bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "codex"
    return REPO / "spike" / "bin"  # 개발 중: 확인 시험 때 받은 공식 Codex


def find_codex(bundle_dir: Path | None = None) -> Path | None:
    """HWPGPT_CODEX → 설치본 동봉 → Codex 앱(해시 폴더 중 최신) 순. 경로를 하드코딩하지 않는다."""
    if os.environ.get("HWPGPT_CODEX"):
        return Path(os.environ["HWPGPT_CODEX"])
    b = bundle_dir or _default_bundle_dir()
    for name in CODEX_NAMES:
        if (b / name).is_file():
            return b / name
    apps = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    found = sorted(apps.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def codex_env() -> dict[str, str]:
    env = dict(os.environ)
    for k in ("OPENAI_API_KEY", "CODEX_API_KEY"):  # 키가 있으면 Codex가 API 과금으로 넘어감
        env.pop(k, None)
    env["CODEX_HOME"] = str(paths.codex_home())
    return env


def login_status(codex: Path | None = None) -> Literal["ok", "logged_out", "missing"]:
    codex = codex or find_codex()
    if not codex:
        return "missing"
    r = subprocess.run([str(codex), "login", "status"], env=codex_env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW, timeout=60)
    return "ok" if "Logged in using ChatGPT" in (r.stdout + r.stderr) else "logged_out"


def start_login(codex: Path | None = None) -> subprocess.Popen:
    """브라우저에서 ChatGPT 로그인을 연다. 끝나면 프로세스가 종료된다. 출력은 %APPDATA%\\HWP_GPT\\login.log"""
    log = open(paths.app_dir() / "login.log", "w", encoding="utf-8")
    return subprocess.Popen([str(codex or find_codex()), "login"], env=codex_env(),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=NO_WINDOW)


def tools_server_cmd() -> tuple[list[str], dict[str, str]]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).parent / "hwpgpt-tools.exe")], {}
    return [sys.executable, "-m", "hwpgpt.tools_server"], {"PYTHONPATH": str(PKG.parent)}


def _toml(v) -> str:
    """JSON 문자열·배열은 그대로 TOML 문법이 된다."""
    return json.dumps(v, ensure_ascii=False)


def list_models(home: Path | None = None) -> list[dict]:
    """ChatGPT 로그인으로 쓸 수 있는 모델 (Codex가 받아 둔 models_cache.json, 목록에 보이는 것만)."""
    try:
        data = json.loads(((Path(home) if home else paths.codex_home()) / "models_cache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"slug": m["slug"], "name": m.get("display_name") or m["slug"]}
            for m in data.get("models", []) if m.get("visibility") == "list" and m.get("slug")]


def build_command(codex: Path, prompt: str, server_cmd: list[str], server_env: dict[str, str],
                  thread_id: str | None = None, model: str | None = None, images: list[str] = ()) -> list[str]:
    env = {"PYTHONIOENCODING": "utf-8", **server_env}
    env_toml = "{" + ",".join(f"{k}={_toml(v)}" for k, v in env.items()) + "}"
    cmd = [
        str(codex), "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
        # 토큰 절약: Codex 기본(코딩용) 긴 지침 대신 문서 편집 지침만, 웹 검색 끔
        "-c", f"model_instructions_file={_toml(str(INSTRUCTIONS))}",
        "-c", 'web_search="disabled"',
        "-c", f"mcp_servers.hwpgpt.command={_toml(server_cmd[0])}",
        "-c", f"mcp_servers.hwpgpt.args={_toml(server_cmd[1:])}",
        "-c", 'mcp_servers.hwpgpt.default_tools_approval_mode="approve"',
        "-c", f"mcp_servers.hwpgpt.env={env_toml}",
    ]
    for f in DISABLED_FEATURES:
        cmd += ["--disable", f]
    if model:
        cmd += ["-m", model]
    # 첨부 그림: 새 대화는 exec의, 이어지는 대화는 resume의 --image (값을 하나씩 붙여 다음 인자를 먹지 않게)
    img = [f"--image={p}" for p in images]
    return cmd + (["resume", *img, thread_id, prompt] if thread_id else [*img, prompt])


@dataclass
class Events:
    reply: str = ""
    usage: dict = field(default_factory=dict)
    error: str | None = None  # "login" | "limit" | 기타 메시지
    thread_id: str | None = None


def _classify(msg: str) -> str:
    m = msg.lower()
    if any(k in m for k in ("401", "unauthorized", "not logged in", "login")):
        return "login"
    if any(k in m for k in ("usage limit", "rate limit", "429", "quota")):
        return "limit"
    return msg


def parse_events(lines: Iterable[str]) -> Events:
    ev = Events()
    for line in lines:
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        t = e.get("type")
        if t == "thread.started":
            ev.thread_id = e.get("thread_id")
        elif t == "item.completed" and e.get("item", {}).get("type") == "agent_message":
            ev.reply = e["item"].get("text", "").strip()
        elif t == "turn.completed":
            ev.usage = e.get("usage", {})
        elif t in ("error", "turn.failed"):
            msg = e.get("message") or e.get("error", {}).get("message", "") or json.dumps(e)
            ev.error = _classify(msg)
    return ev


@dataclass
class TurnResult:
    reply: str
    applied: list[dict]
    checks: list[dict]
    doc_type: str | None
    usage: dict
    error: str | None
    thread_id: str | None = None


def _find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            if (found := _find_key(v, key)) is not None:
                return found
    return None


def read_rate_limits(thread_id: str | None = None, home: Path | None = None) -> dict | None:
    """Codex 세션 기록의 마지막 사용 한도 → 남은 % (5시간 창, 주간 창). 기록이 없으면 None."""
    files = sorted((Path(home) if home else paths.codex_home()).glob("sessions/**/rollout-*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if thread_id:
        files = [p for p in files if thread_id in p.name] + [p for p in files if thread_id not in p.name]
    for p in files[:5]:
        for line in reversed(p.read_text(encoding="utf-8", errors="replace").splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                rl = _find_key(json.loads(line), "rate_limits")
            except json.JSONDecodeError:
                continue
            if rl and rl.get("primary") and rl.get("secondary"):
                return {"five_hour_left": round(100 - rl["primary"]["used_percent"]),
                        "weekly_left": round(100 - rl["secondary"]["used_percent"]),
                        "plan": rl.get("plan_type")}
    return None


# 진행률: Codex --json 이벤트 → (%, 단계). 뒤로 가지 않게 호출하는 쪽이 max를 쓴다.
READ_TOOLS = ("find_lines", "read_document")


def progress_of(e: dict) -> tuple[int, str] | None:
    t, item = e.get("type"), e.get("item") or {}
    tool, kind = item.get("tool", ""), item.get("type")
    if t in ("thread.started", "turn.started"):
        return 10, "요청을 이해하는 중"
    if kind == "mcp_tool_call" and tool in READ_TOOLS:
        return (25, "문서에서 고칠 곳 찾는 중") if t == "item.started" else (45, "고칠 내용 정하는 중")
    if kind == "mcp_tool_call" and tool == "apply_edits":
        return (60, "한글 문서 고치는 중") if t == "item.started" else (85, "고친 결과 확인하는 중")
    if kind == "agent_message" or t == "turn.completed":
        return 95, "답변 정리 중"
    return None


PERSONAL_ASK = "[[개인정보 확인]]"  # AI가 개인정보 수정 요청을 받으면 고치지 않고 이것만 답함 → 패널이 사용자에게 확인
PERSONAL_OK = "[개인정보 수정 허용] 사용자가 패널에서 확인함: 이번 요청에 한해 요청한 개인정보(이름·학번·연락처 등)를 고친다. 요청하지 않은 개인정보는 그대로 둔다."


def compose_prompt(user_text: str, memory_rules: list[str], attached: str = "", scoped: bool = False,
                   personal: bool = False) -> str:
    if not memory_rules and not attached and not scoped and not personal:
        return user_text
    parts = [PERSONAL_OK] if personal else []
    if scoped:  # 그림 첨부 = 고칠 범위 (사용자 결정 2026-10-22). 도구 서버도 위치 없는 수정을 거부한다
        parts.append("[범위] 첨부한 그림에 보이는 부분만 고친다. 문서의 다른 곳은 같은 글이 있어도 바꾸지 않는다. 수정마다 그 부분의 줄 번호(lines)를 준다.")
    if memory_rules:
        parts.append("[이 사용자가 이 문서 종류에서 지켜 온 규칙]\n" + "\n".join(f"- {r}" for r in memory_rules))
    if attached:  # 참고 자료일 뿐, 고칠 대상은 열린 한글 문서
        parts.append("[사용자가 첨부한 참고 자료 — 고칠 대상은 열린 한글 문서]\n" + attached)
    return "\n\n".join(parts) + f"\n\n[요청]\n{user_text}"


def _prepare_work_dir() -> Path:
    """지침은 model_instructions_file로 넘기므로 작업 폴더의 AGENTS.md는 지운다 (같은 지침이 두 번 들어가지 않게)."""
    w = paths.work_dir()
    (w / "AGENTS.md").unlink(missing_ok=True)
    return w


def _stream(cmd: list[str], timeout: int, on_event) -> tuple[list[str], str, int | None]:
    """Codex를 실행하며 stdout JSON 줄을 하나씩 on_event로 넘긴다. (stdout 줄, stderr, 종료 코드 / 시간 초과 None)"""
    lines: list[str] = []
    with tempfile.TemporaryFile() as err:  # stderr를 파이프로 받으면 두 파이프가 서로 막힐 수 있음
        p = subprocess.Popen(cmd, cwd=_prepare_work_dir(), env=codex_env(), stdout=subprocess.PIPE, stderr=err,
                             stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                             creationflags=NO_WINDOW)
        timer = threading.Timer(timeout, p.kill)
        timer.start()
        try:
            for line in p.stdout:
                lines.append(line)
                try:
                    on_event(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    pass
            code = p.wait()
        finally:
            timed_out = not timer.is_alive()
            timer.cancel()
        err.seek(0)
        return lines, err.read().decode("utf-8", "replace"), None if timed_out else code


def run_turn(user_text: str, memory_rules: list[str], thread_id: str | None = None,
             timeout: int = 600, on_progress=lambda pct, step: None, model: str | None = None,
             images: list[str] = (), attached: str = "", personal: bool = False) -> TurnResult:
    codex = find_codex()
    if not codex:
        return TurnResult("", [], [], None, {}, "missing")
    sess = paths.session_dir() / f"{uuid.uuid4().hex}.jsonl"
    server_cmd, server_env = tools_server_cmd()
    flags = {"HWPGPT_SCOPED": "1"} if images else {}
    if personal:  # 이번 요청만: 다음 요청의 도구 서버는 이 값 없이 다시 뜬다
        flags["HWPGPT_PERSONAL"] = "1"
    cmd = build_command(codex, compose_prompt(user_text, memory_rules, attached, bool(images), personal), server_cmd,
                        {**server_env, "HWPGPT_SESSION": str(sess), **flags}, thread_id, model, images)
    def on_event(e: dict) -> None:
        if pr := progress_of(e):
            on_progress(*pr)

    on_progress(5, "ChatGPT에 요청 보내는 중")
    out, err, code = _stream(cmd, timeout, on_event)
    if code is None:
        ev = Events(error="시간 초과")
    else:
        ev = parse_events(out)
        if not ev.reply and not ev.error and code:
            ev.error = _classify(err[-500:] or f"Codex 종료 코드 {code}")
    rows = session.read(sess)
    doc_types = [x["data"]["name"] for x in rows if x["kind"] == "doc_type"]
    return TurnResult(
        reply=ev.reply,
        applied=[x["data"] for x in rows if x["kind"] == "applied"],
        checks=[x["data"] for x in rows if x["kind"] == "check"],
        doc_type=doc_types[-1] if doc_types else None,  # 여러 번 기록하면 마지막 값
        usage=ev.usage, error=ev.error, thread_id=ev.thread_id or thread_id,
    )
