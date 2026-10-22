"""한글이 설치된 PC에서만: pytest -m hwp

시험은 이 테스트 전용 한글 인스턴스(Dispatch)의 경로 없는 새 문서에서만 한다 (MISTAKES M-004).
"""
import pytest

from hwpgpt.com_worker import ComWorker
from hwpgpt.hwp_bridge import HwpBridge
from hwpgpt.rules import Edit

pytestmark = pytest.mark.hwp

SAMPLE = "2026년 행사, 학번 202699001"


def _test_instance():
    """테스트 전용 한글. 경로 있는 문서가 보이면 중단."""
    import win32com.client

    h = win32com.client.Dispatch("HWPFrame.HwpObject")
    docs = h.XHwpDocuments
    for i in range(docs.Count):
        assert not docs.Item(i).FullName, f"실제 문서가 열려 있어 중단: {docs.Item(i).FullName}"
    h.XHwpWindows.Item(0).Visible = True
    return h


@pytest.fixture
def worker():
    w = ComWorker()
    yield w
    w.stop()


@pytest.fixture
def bridge(worker):
    b = HwpBridge(worker, attach=_test_instance)
    assert b.connect()
    b._type_at_start(SAMPLE)
    yield b
    b._close_without_saving()


def test_apply_counts_and_marks(bridge):
    res = bridge.apply([Edit("2026년", "2027년", "연도")])
    assert res[0][1] == 1
    t = bridge.read_text()
    assert "2027년" in t and "202699001" in t
    assert bridge.has_marks()


def test_clear_marks_after_user_typing(bridge):
    bridge.apply([Edit("2026년", "2027년", "연도")])
    bridge.mark_check("202699001")
    bridge._type_at_start("메모 ")  # 사용자 수정 흉내
    assert bridge.clear_marks() >= 2 and not bridge.has_marks()


def _markpen_count_via_save(bridge) -> int:
    """시험 문서만 임시 hwpx로 저장해 형광펜 수를 센다 (HWPML2X엔 형광펜이 안 나옴)."""
    import os
    import re
    import tempfile
    import zipfile

    def do(h):
        assert not h.Path, "경로 있는 문서에서는 저장 시험 금지"
        p = os.path.join(tempfile.mkdtemp(prefix="hwpgpt-"), "count.hwpx")
        h.SaveAs(p, "HWPX", "")
        with zipfile.ZipFile(p) as z:
            return len(re.findall(r"<hp:markpenBegin", z.read("Contents/section0.xml").decode("utf-8")))

    return bridge._call(do)


def test_clear_marks_keeps_user_markpen(bridge):
    bridge._user_markpen("행사")  # 사용자가 원래 칠해 둔 형광펜
    bridge.apply([Edit("2026년", "2027년", "연도")])
    bridge.clear_marks()
    assert _markpen_count_via_save(bridge) == 1


def test_goto_finds_text(bridge):
    assert bridge.goto("202699001") and not bridge.goto("없는 문장")


def test_never_saves(bridge):
    p = bridge._path()
    bridge.apply([Edit("2026년", "2027년", "연도")])
    assert bridge._path() == p == "" and bridge._is_modified()


def test_connect_false_when_no_hwp_running(worker):
    b = HwpBridge(worker)  # 기본 attach = ROT
    if worker.call(lambda: __import__("hwpgpt.hwp_bridge", fromlist=["x"]).attach_running_hwp()):
        pytest.skip("한글이 켜져 있음 — 모두 닫고 실행")
    assert b.connect() is False


def test_goto_nth_and_first_word_fallback(bridge):
    bridge._type_at_start("행사A ")  # 문서: "행사A 2026년 행사, ..."
    pos = lambda: bridge._call(lambda h: h.GetPos()[2])
    assert bridge.goto("행사", 0)
    first = pos()
    assert bridge.goto("행사", 1) and pos() > first
    assert bridge.goto("2026년  띄어쓰기가 다른 긴 문장")  # 못 찾으면 첫 낱말로


def test_restore_marks_after_clear(bridge):
    bridge.apply([Edit("2026년", "2027년", "연도")])
    bridge.mark_check("202699001")
    bridge.clear_marks()
    assert bridge.can_restore() and not bridge.has_marks()
    assert bridge.restore_marks() == 2 and bridge.has_marks() and not bridge.can_restore()
    assert bridge._marks == {"2027년": (255, 240, 0), "202699001": (255, 120, 120)}
