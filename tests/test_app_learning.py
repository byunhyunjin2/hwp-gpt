import threading

import hwpgpt.learn as learn
from hwpgpt.app import Api
from hwpgpt.memory import MemoryStore


class Doc:
    def __init__(self, text):
        self.text, self.modified = text, False

    def read_text(self):
        return self.text

    def is_modified(self):
        return self.modified


def bare_api(tmp_path, doc):
    a = Api.__new__(Api)  # 생성자의 ComWorker·Codex 확인은 건너뜀
    a._memory = MemoryStore(tmp_path)
    a._bridge = doc
    a._doc_type = None
    a._snapshot = None
    a._prev_modified = None
    a._candidates = []
    a._learning = threading.Lock()
    a._busy = threading.Lock()
    return a


def test_first_request_gets_all_rules_labeled(tmp_path):
    a = bare_api(tmp_path, Doc(""))
    a._memory.add("공문", "끝. 표기 유지")
    a._memory.add("앵커사업 운영계획서", "책임교원 이름 유지")
    assert set(a._rules_for_prompt()) == {"[공문] 끝. 표기 유지", "[앵커사업 운영계획서] 책임교원 이름 유지"}
    a._doc_type = "공문"
    assert a._rules_for_prompt() == ["끝. 표기 유지"]


def test_manual_edit_becomes_candidate_not_saved(tmp_path, monkeypatch):
    doc = Doc("교육 기간: 2027. 11. 6.(토)")
    a = bare_api(tmp_path, doc)
    a._doc_type = "앵커사업 운영계획서"
    a._snapshot = doc.text  # AI 수정 직후
    doc.text = "교육 기간: 2027. 10. 30.(토)"  # 사용자가 직접 고침
    monkeypatch.setattr(learn, "propose_rules", lambda t, ch: ["축제은 10월 마지막 토요일"])
    a._learn_now()
    assert a._pop_candidates() == [{"docType": "앵커사업 운영계획서", "rule": "축제은 10월 마지막 토요일"}]
    assert a._memory.rules("앵커사업 운영계획서") == []  # 묻기 전엔 저장 안 함
    assert a._snapshot == doc.text


def test_typo_only_gives_no_candidate(tmp_path, monkeypatch):
    doc = Doc("추진 배겅")
    a = bare_api(tmp_path, doc)
    a._doc_type = "공문"
    a._snapshot = doc.text
    doc.text = "추진 배경"
    called = []
    monkeypatch.setattr(learn, "propose_rules", lambda t, ch: called.append(ch) or ["x"])
    a._learn_now()
    assert a._pop_candidates() == [] and called == []


def test_switching_document_resets_context(tmp_path):
    doc = Doc("A 문서")
    doc._marks = {"2027학년도": (255, 240, 0)}
    a = bare_api(tmp_path, doc)
    a._target = "a.hwp"
    a._thread_id, a._doc_type, a._snapshot = "T1", "공문", "A 문서"
    a._sync_target("a.hwp")  # 같은 문서면 유지
    assert a._thread_id == "T1"
    a._sync_target("b.hwp")  # 다른 문서로 바뀜
    assert (a._thread_id, a._doc_type, a._snapshot, a._prev_modified) == (None, None, None, None)
    assert doc._marks == {} and a._target == "b.hwp"


def test_set_mode_flags_switch_and_validates(tmp_path):
    a = bare_api(tmp_path, Doc(""))
    a._mode, a._mode_changed = "dock", threading.Event()
    assert a.set_mode("embed") == "embed" and a._mode_changed.is_set()
    a._mode_changed.clear()
    assert a.set_mode("dock") == "dock" and a._mode_changed.is_set()
    a._mode_changed.clear()
    assert a.set_mode("이상한값") == "dock" and not a._mode_changed.is_set()


def test_settings_saved_and_reloaded(tmp_path, monkeypatch):
    import hwpgpt.app as app

    monkeypatch.setenv("APPDATA", str(tmp_path))
    a = bare_api(tmp_path, Doc(""))
    a._settings = {}
    a.set_setting("theme", "light")
    a.set_setting("model", "gpt-test")
    a.set_setting("이상한키", "x")
    assert app._load_settings() == {"theme": "light", "model": "gpt-test"}


def test_save_transition_triggers_learning(tmp_path, monkeypatch):
    doc = Doc("a")
    a = bare_api(tmp_path, doc)
    hits = []
    monkeypatch.setattr(Api, "_learn_now", lambda self: hits.append(1))
    doc.modified = True
    a._watch_save()
    doc.modified = False  # 사용자가 저장
    a._watch_save()
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon:
            t.join(1)
    assert hits == [1]


def test_leftover_year_after_turn_is_marked_and_listed(tmp_path, fake_bridge):
    fake_bridge.text = "2027학년도 계획\r\n2026년 실적\r\n신청일 2026년 9월 1일"
    a = bare_api(tmp_path, fake_bridge)
    out = a._leftover_checks([{"find": "2026학년도", "replace": "2027학년도", "count": 1}],
                             [{"text": "2026년 실적", "note": "전년도"}])
    assert [(c["text"], c["nth"]) for c in out] == [("2026년", 1)]
    assert fake_bridge.red == ["2026년"]


def test_progress_never_goes_back():
    a = Api.__new__(Api)
    a._progress = {"pct": 0, "step": "", "start": 0.0}
    a._on_progress(45, "정하는 중")
    a._on_progress(25, "찾는 중")
    assert a.progress()["pct"] == 45 and a.progress()["step"] == "정하는 중"


def test_final_checks_drop_stale_and_recheck_budget(tmp_path, fake_bridge):
    fake_bridge.text = "사업 예산 2,000,000원\r\n합계 1,500,000원\r\n신청일 2026년  9월  1일"
    a = bare_api(tmp_path, fake_bridge)
    out = a._final_checks([
        {"text": "2,345,670원", "note": "합계 2,345,670원이 사업 예산 2,000,000원과 다름"},  # 그사이 바뀐 금액
        {"text": "2026년 9월 1일", "note": "신청일"},
        {"text": "2026년 9월 1일", "note": "신청일 확인"},
    ])
    assert [c["text"] for c in out] == ["2026년 9월 1일", "1,500,000"]
    assert out[0]["note"] == "신청일 확인"


def test_dropped_files_takes_real_paths_only():
    from hwpgpt.app import dropped_files

    e = {"dataTransfer": {"files": [{"name": "a.hwp", "pywebviewFullPath": r"C:\예시\a.hwp"},
                                    {"name": "b.png"}]}}  # 경로를 못 받은 항목은 뺀다
    assert dropped_files(e) == [{"path": r"C:\예시\a.hwp", "name": "a.hwp"}]
    assert dropped_files({}) == []


def test_undo_last_restores_and_tells_ai_next_time(tmp_path, fake_bridge):
    from hwpgpt.tools_server import Tools

    fake_bridge.text = "참여시간\r\n6\r\n만족도\r\n4.0"
    before = fake_bridge.text
    out = Tools(fake_bridge, tmp_path / "s.jsonl").apply_edits(
        [{"find": "6", "replace": "8", "lines": [2]}, {"find": "4.0", "replace": "5.0", "lines": [4]}])
    a = bare_api(tmp_path, fake_bridge)
    a._last, a._undone, a._thread_id = {"applied": out["applied"], "checks": ["8"]}, False, "t1"
    assert a.undo_last() == {"restored": 2, "skipped": 0}
    assert fake_bridge.text == before and fake_bridge.unmarked == ["8"] and a.undo_last()["error"]
    assert a._with_undo_note("다시 해줘").startswith("[참고: 바로 앞 요청에서 고친 것은 사용자가 모두 되돌렸음]")
    assert a._with_undo_note("또") == "또"  # 한 번만
