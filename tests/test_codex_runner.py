import os
from pathlib import Path

from hwpgpt import codex_runner as cr

FIX = Path(__file__).parent / "fixtures" / "codex_events.jsonl"


def test_env_strips_keys_and_isolates_home(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("CODEX_API_KEY", "sk-y")
    env = cr.codex_env()
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
    assert env["CODEX_HOME"].endswith(r"HWP_GPT\codex")


def test_find_codex_picks_newest_hash_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("HWPGPT_CODEX", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    old = tmp_path / "OpenAI/Codex/bin/aaa/codex.exe"
    new = tmp_path / "OpenAI/Codex/bin/bbb/codex.exe"
    for p, t in [(old, 1000), (new, 2000)]:
        p.parent.mkdir(parents=True)
        p.write_bytes(b"")
        os.utime(p, (t, t))
    assert cr.find_codex(bundle_dir=tmp_path / "none") == new


def test_find_codex_prefers_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("HWPGPT_CODEX", raising=False)
    b = tmp_path / "bin"
    b.mkdir()
    (b / "codex-x86_64-pc-windows-msvc.exe").write_bytes(b"")
    assert cr.find_codex(bundle_dir=b) == b / "codex-x86_64-pc-windows-msvc.exe"


def test_parse_events_from_fixture():
    with open(FIX, encoding="utf-8") as f:
        ev = cr.parse_events(f)
    assert ev.reply == "- 제목: 2026학년도 → 2027학년도"
    assert ev.thread_id.endswith("0001") and ev.error is None
    assert ev.usage["input_tokens"] == 66718


def test_parse_events_detects_login_and_limit():
    assert cr.parse_events(['{"type":"error","message":"401 Unauthorized"}']).error == "login"
    assert cr.parse_events(['{"type":"error","message":"You\'ve hit your usage limit"}']).error == "limit"
    assert cr.parse_events(["not json line"]).error is None


def _rollout(dirpath, name, used5, usedw, mtime):
    p = dirpath / "sessions" / "2026" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    rl = {"primary": {"used_percent": used5, "window_minutes": 300},
          "secondary": {"used_percent": usedw, "window_minutes": 10080}, "plan_type": "plus"}
    p.write_text('{"type":"session_meta"}\n'
                 + '{"type":"event_msg","payload":{"type":"token_count","rate_limits":' + __import__("json").dumps(rl) + "}}\n",
                 encoding="utf-8")
    os.utime(p, (mtime, mtime))
    return p


def test_read_rate_limits_from_newest_session(tmp_path):
    _rollout(tmp_path, "rollout-a-OLD.jsonl", 50.0, 70.0, 1000)
    _rollout(tmp_path, "rollout-b-NEW.jsonl", 6.0, 22.0, 2000)
    assert cr.read_rate_limits(home=tmp_path) == {"five_hour_left": 94, "weekly_left": 78, "plan": "plus"}
    assert cr.read_rate_limits(thread_id="OLD", home=tmp_path)["five_hour_left"] == 50


def test_read_rate_limits_none_when_no_sessions(tmp_path):
    assert cr.read_rate_limits(home=tmp_path) is None


def test_memory_rules_in_prompt():
    p = cr.compose_prompt("올해 걸로", ["책임교원 이름은 유지"])
    assert "책임교원 이름은 유지" in p and p.rstrip().endswith("올해 걸로")


def test_build_command_flags_and_resume():
    cmd = cr.build_command(Path("codex.exe"), "요청", ["py", "-m", "hwpgpt.tools_server"],
                           {"HWPGPT_SESSION": r"C:\s\a.jsonl"}, thread_id="T1")
    s = " ".join(cmd)
    for flag in ["exec", "--skip-git-repo-check", "--sandbox", "read-only", "--json",
                 'mcp_servers.hwpgpt.default_tools_approval_mode="approve"']:
        assert flag in s
    assert cmd[-3:] == ["resume", "T1", "요청"]
    # 토큰 절약: Codex 기본(코딩용) 지침 대신 우리 지침, 웹 검색 끔
    assert any(c.startswith("model_instructions_file=") and "AGENTS.md" in c for c in cmd)
    assert 'web_search="disabled"' in cmd
    for feat in ("shell_tool", "unified_exec", "image_generation", "browser_use", "computer_use", "multi_agent"):
        i = cmd.index(feat)
        assert cmd[i - 1] == "--disable"
    assert cmd.index("resume") > cmd.index("multi_agent")  # 옵션은 resume 앞에
    assert 'HWPGPT_SESSION="C:\\\\s\\\\a.jsonl"' in s  # TOML 문자열로 이스케이프


def test_progress_from_fixture_only_goes_up_to_95():
    import json
    from pathlib import Path

    from hwpgpt.codex_runner import progress_of

    events = [json.loads(l) for l in (Path(__file__).parent / "fixtures" / "codex_events.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pcts = [p[0] for e in events if (p := progress_of(e))]
    assert pcts[0] == 10 and 25 in pcts and 45 in pcts and max(pcts) == 95


def test_stream_passes_events_and_times_out(tmp_path, monkeypatch):
    import sys

    from hwpgpt import codex_runner as cr

    monkeypatch.setattr(cr, "_prepare_work_dir", lambda: tmp_path)
    seen = []
    code = 'import json;print(json.dumps({"type":"thread.started","thread_id":"t"}),flush=True)'
    lines, _, rc = cr._stream([sys.executable, "-c", code], 30, seen.append)
    assert rc == 0 and seen == [{"type": "thread.started", "thread_id": "t"}] and len(lines) == 1
    _, _, rc = cr._stream([sys.executable, "-c", "import time;time.sleep(30)"], 1, seen.append)
    assert rc is None


def test_list_models_and_model_flag(tmp_path):
    import json
    from pathlib import Path

    from hwpgpt import codex_runner as cr

    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-a", "display_name": "GPT-A", "visibility": "list"},
        {"slug": "hidden", "visibility": "hide"}]}), encoding="utf-8")
    assert cr.list_models(tmp_path) == [{"slug": "gpt-a", "name": "GPT-A"}]
    assert cr.list_models(tmp_path / "없음") == []
    cmd = cr.build_command(Path("codex.exe"), "요청", ["py"], {}, "t1", model="gpt-a")
    assert cmd[cmd.index("-m") + 1] == "gpt-a" and cmd[-3:] == ["resume", "t1", "요청"]
    assert "-m" not in cr.build_command(Path("codex.exe"), "요청", ["py"], {})


def test_images_go_where_exec_and_resume_expect_them():
    from pathlib import Path

    from hwpgpt import codex_runner as cr

    new = cr.build_command(Path("codex.exe"), "요청", ["py"], {}, images=["a.png", "b.jpg"])
    assert new[-3:] == ["--image=a.png", "--image=b.jpg", "요청"]
    cont = cr.build_command(Path("codex.exe"), "요청", ["py"], {}, "t1", images=["a.png"])
    assert cont[-4:] == ["resume", "--image=a.png", "t1", "요청"]


def test_attached_text_is_marked_as_reference():
    from hwpgpt.codex_runner import compose_prompt

    p = compose_prompt("이걸로 고쳐줘", [], "[첨부 파일: a.docx]\n내용")
    assert "고칠 대상은 열린 한글 문서" in p and p.endswith("[요청]\n이걸로 고쳐줘")
    assert compose_prompt("그냥", []) == "그냥"


def test_personal_permission_is_told_to_ai_and_tool_server_per_request(monkeypatch, tmp_path):
    import hwpgpt.codex_runner as cr

    assert cr.compose_prompt("명단 고쳐줘", [], personal=True).startswith("[보호 해제 허용]")
    assert cr.compose_prompt("명단 고쳐줘", []) == "명단 고쳐줘"
