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


def test_apply_only_chosen_occurrence_then_undo_restores_exactly(bridge):
    bridge._type_at_start("참여 6시간 6 끝 ")  # 문서: "참여 6시간 6 끝 2026년 행사, 학번 202699001"
    before = bridge.read_text()
    (_, n1, pos1), = bridge.apply([Edit("6", "8", "", nths=(1,))])  # 0번째 = "6시간"의 6, 1번째 = 홀로 있는 6
    assert n1 == 1 and "참여 6시간 8 끝" in bridge.read_text()
    (_, n2, pos2), = bridge.apply([Edit("2026년", "2027학년도", "")])  # 길이가 다른 수정도 섞어서
    assert n2 == 1
    done = [{"find": "6", "replace": "8", "pos": pos1}, {"find": "2026년", "replace": "2027학년도", "pos": pos2}]
    after = bridge.read_text()
    assert bridge.undo(done) == (2, 0)
    assert bridge.read_text() == before
    assert bridge.redo(done) == (2, 0)  # [↷] 다시 적용 → 수정 뒤 글과 같아짐
    assert bridge.read_text() == after
    assert bridge.undo(done) == (2, 0) and bridge.read_text() == before  # 몇 번이든 오갈 수 있음


def test_undo_skips_spot_user_changed(bridge):
    (_, n, pos), = bridge.apply([Edit("2026년", "2027년", "")])
    bridge._type_at_start("x")  # 같은 문단 앞에 글자가 생겨 자리가 밀림 → 엉뚱한 곳을 바꾸지 않고 건너뜀
    assert bridge.undo([{"find": "2026년", "replace": "2027년", "pos": pos}]) == (0, 1)
    assert "2027년" in bridge.read_text()


def _shape(bridge, para):
    def do(h):
        h.SetPos(0, para, 0)
        p = h.HParameterSet.HParaShape
        h.HAction.GetDefault("ParagraphShape", p.HSet)
        return p.AlignType, p.LeftMargin, p.Indentation, p.BreakNonLatinWord
    return bridge._call(do)


def test_edit_matches_neighbor_bullet_shape_and_breaks_by_word(bridge):
    bridge._type_at_start(" ○ 일시: 2027년\r\n ○ 장소: OO구\r\n")  # 문단 0, 1 + 원래 SAMPLE이 문단 2

    def indent_first(h):  # 이웃(문단 0)은 들여쓰기·양쪽 정렬, 고칠 문단(1)은 기본값
        h.SetPos(0, 0, 0)
        p = h.HParameterSet.HParaShape
        h.HAction.GetDefault("ParagraphShape", p.HSet)
        p.LeftMargin, p.Indentation = 2000, -1000
        h.HAction.Execute("ParagraphShape", p.HSet)
    bridge._call(indent_first)
    before = _shape(bridge, 0)
    assert bridge.apply([Edit("OO구", "OO구 평생학습관", "")])[0][1] == 1
    assert _shape(bridge, 1) == before[:3] + (0,)  # 이웃과 같은 모양, 어절 단위 줄 나눔
    assert _shape(bridge, 2)[1:3] == (0, 0)  # 안 고친 문단은 그대로


def _make_table(bridge, cells, cols=2):
    def do(h):
        h.HAction.Run("MoveDocEnd")
        bridge._insert(h, "\r\n")
        t = h.HParameterSet.HTableCreation
        h.HAction.GetDefault("TableCreate", t.HSet)
        t.Rows, t.Cols = len(cells) // cols, cols
        h.HAction.Execute("TableCreate", t.HSet)
        for c in cells:
            bridge._insert(h, c)
            h.HAction.Run("TableRightCell")
        h.HAction.Run("MoveDocEnd")
    bridge._call(do)


def test_table_rows_delete_and_insert(bridge):
    _make_table(bridge, ["이름", "번호", "홍길동", "1", "김철수", "2", "이영희", "3", "박민수", "4"])
    assert bridge.table_rows("delete", "김철수", count=2) is None  # 김철수·이영희 줄
    text = bridge.read_text()
    assert "홍길동" in text and "박민수" in text and "김철수" not in text and "이영희" not in text
    assert bridge.table_rows("insert_below", "홍길동") is None
    assert bridge.read_text().count("\r\n") == text.count("\r\n") + 2  # 빈 칸 2개(한 줄)
    assert bridge.table_rows("delete", "2026년") == "표 칸 안의 글을 찾지 못함"  # 본문 글은 거부


def test_table_rows_delete_until_counts_rows_itself(bridge):
    _make_table(bridge, ["이름", "번호", "홍길동", "1", "김철수", "2", "이영희", "3", "박민수", "4", "최수진", "5"])
    assert bridge.table_rows("delete", "이영희", until="최수진") is None  # 3줄 — 줄 수는 칸 주소로 셈
    text = bridge.read_text()
    assert "김철수" in text and not any(n in text for n in ("이영희", "박민수", "최수진"))


def test_table_rows_delete_to_end(bridge):
    _make_table(bridge, ["이름", "번호", "홍길동", "1", "김철수", "2", "이영희", "3", "박민수", "4"])
    assert bridge.table_rows("delete", "김철수", to_end=True) is None
    text = bridge.read_text()
    assert "홍길동" in text and not any(n in text for n in ("김철수", "이영희", "박민수"))


def test_clear_all_marks_body_and_every_table(bridge):
    _make_table(bridge, ["항목", "금액", "재료비", "100"])
    _make_table(bridge, ["이름", "번호", "홍길동", "1"])
    def marks():
        return bridge._call(lambda h: h.GetTextFile("HWPML2X", "").count("<MARKPENBEGIN"))
    for w in ("재료비", "홍길동"):  # 표 두 개의 칸 (본문 전체 선택으로는 표 칸까지 안 지워짐)
        bridge._user_markpen(w)
    assert marks() == 2
    assert bridge.clear_all_marks() == 2 and marks() == 0
