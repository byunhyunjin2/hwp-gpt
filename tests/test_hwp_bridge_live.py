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
    import faulthandler
    import sys

    w = ComWorker()
    yield w
    # 한글을 끝낸 뒤 CoUninitialize가 남은 COM 대리 객체를 풀며 RPC 실패(0x800706be)를 COM 안에서 처리한다.
    # 처리된 예외인데 pytest의 faulthandler가 'Windows fatal exception'으로 찍어서, 이 정리 동안만 끈다 (2026-11-11)
    was = faulthandler.is_enabled()
    faulthandler.disable()
    try:
        w.stop()
    finally:
        if was:
            faulthandler.enable(file=sys.__stderr__)


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


def test_mark_check_nth_marks_only_target_occurrence(bridge):
    """leftover_years가 준 nth번째 자리만 빨간 형광펜을 칠하고 학번 속 같은 숫자는 건드리지 않음 (2026-11-11)."""
    assert bridge.mark_check("2026", nth=0)  # SAMPLE 앞쪽 '2026년'의 2026만, 뒤쪽 학번 '202699001'은 안 칠함
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


def _new_para(bridge, text):
    def do(h):
        h.HAction.Run("MoveDocEnd")
        h.HAction.Run("BreakPara")
        bridge._insert(h, text)

    bridge._call(do)


def test_apply_when_replace_contains_find(bridge):
    """'예산'→'사업 예산': 바꾼 글 속 '예산'을 다시 찾아 같은 자리를 여러 번 바꾸던 버그 (2026-11-11)."""
    _new_para(bridge, "예산A 예산B 예산C")
    res = bridge.apply([Edit("예산", "사업 예산", "")])
    assert res[0][1] == 3 and "사업 예산A 사업 예산B 사업 예산C" in bridge.read_text()
    res = bridge.apply([Edit("사업 예산", "사업 예산 총액", "", nths=(1,))])
    assert res[0][1] == 1 and "사업 예산A 사업 예산 총액B 사업 예산C" in bridge.read_text()


def test_format_text_char_and_para(bridge):
    _new_para(bridge, "추진 배경 문단")
    assert bridge.format_text("추진 배경", None, {"Bold": 1, "TextColor": (255, 0, 0), "Height": 1500},
                              {"AlignType": 3, "LineSpacingType": 0, "LineSpacing": 180}) == 1

    def shape(h):
        assert bridge._seek(h, "추진 배경")
        c, p = h.HParameterSet.HCharShape, h.HParameterSet.HParaShape
        h.HAction.GetDefault("CharShape", c.HSet)
        h.HAction.GetDefault("ParagraphShape", p.HSet)
        h.HAction.Run("Cancel")
        return c.Bold, c.Height, c.TextColor, p.AlignType, p.LineSpacing

    assert bridge._call(shape) == (1, 1500, 255, 3, 180)


def test_table_read_set_cols_merge_create(bridge):
    assert bridge.table_op({"action": "create", "find": "2026년", "rows": [["항목", "수량"], ["볼펜", "2"], ["합계", ""]]}) is None
    cells = bridge.read_table("항목")["cells"]
    assert cells == [["A1", "항목"], ["B1", "수량"], ["A2", "볼펜"], ["B2", "2"], ["A3", "합계"], ["B3", ""]]
    assert bridge.table_op({"action": "set_cell", "find": "항목", "cell": "B2", "text": "5"}) is None
    assert bridge.cell_text("항목", 0, "B2") == "5"
    assert bridge.table_op({"action": "insert_col_right", "find": "항목", "cell": "B1"}) is None
    assert bridge.table_op({"action": "set_cell", "find": "항목", "cell": "C1", "text": "비고"}) is None
    assert [a for a, _ in bridge.read_table("항목")["cells"]][:3] == ["A1", "B1", "C1"]
    assert bridge.table_op({"action": "delete_col", "find": "항목", "cell": "C1"}) is None
    assert "비고" not in bridge.read_text()
    assert bridge.table_op({"action": "merge", "find": "항목", "cell": "A3", "to": "B3"}) is None
    assert len(bridge.read_table("항목")["cells"]) == 5  # 마지막 줄 두 칸이 하나로
    assert bridge.table_op({"action": "merge", "find": "항목", "cell": "A1"})  # to가 없으면 예외 대신 오류 문구
    assert bridge.table_op({"action": "set_cell", "find": "항목", "cell": "Z9", "text": "x"})  # 없는 칸은 이유


def test_insert_kinds(bridge, tmp_path):
    _new_para(bridge, "기준 문단")
    assert bridge.insert({"kind": "paragraph", "find": "기준 문단", "text": "새 첫째\n새 둘째"}) is None
    t = bridge.read_text()
    assert t.index("기준 문단") < t.index("새 첫째") < t.index("새 둘째")
    assert bridge.insert({"kind": "delete_paragraph", "find": "새 첫째"}) is None
    assert "새 첫째" not in bridge.read_text() and "새 둘째" in bridge.read_text()
    assert bridge.insert({"kind": "footnote", "find": "기준 문단", "text": "각주 글"}) is None
    assert bridge.insert({"kind": "header", "text": "머리말 글"}) is None
    assert bridge.insert({"kind": "page_number", "position": "top_right"}) is None
    pages = bridge._call(lambda h: h.PageCount)
    assert bridge.insert({"kind": "page_break", "find": "기준 문단"}) is None
    assert bridge._call(lambda h: h.PageCount) == pages + 1
    png = tmp_path / "p.png"
    png.write_bytes(bridge.page_png(1, tmp_path))  # 쪽 그림을 그대로 '첨부 그림'으로 씀
    assert bridge.insert({"kind": "picture", "find": "기준 문단", "width_mm": 40}, picture=str(png)) is None
    assert bridge.insert({"kind": "memo", "find": "기준", "text": "메모 글"}) is None  # 메모는 찾은 글을 감쌈 → 마지막에
    x = bridge._call(lambda h: h.GetTextFile("HWPML2X", ""))
    assert "메모 글" in x and "머리말 글" in x and "각주 글" in x and 'Pos="TopRight"' in x
    assert bridge.delete_memos() == 1 and "메모 글" not in bridge._call(lambda h: h.GetTextFile("HWPML2X", ""))


def test_fields_and_page_png(bridge, tmp_path):
    bridge._call(lambda h: h.CreateField("이름", "", "성명"))
    assert bridge.fields() == {"성명": ""}
    bridge.put_field("성명", "홍길동")
    assert bridge.fields() == {"성명": "홍길동"}
    png = bridge.page_png(1, tmp_path)
    assert png.startswith(b"\x89PNG") and not list(tmp_path.glob("*.bmp"))


def test_paragraph_after_table_cell_goes_below_table_and_page_png_is_full_page(bridge, tmp_path):
    """표 칸 글을 기준으로 새 문단을 넣으면 칸 안이 아니라 표 뒤에 (2026-11-11 실제 ChatGPT 시험에서 칸 안에 들어감).
    커서가 표 칸에 있어도 쪽 그림은 쪽 전체 (칸만 그려졌음)."""
    assert bridge.table_op({"action": "create", "find": "2026년", "rows": [["항목", "금액"], ["합계", "100,000"]]}) is None
    assert bridge.insert({"kind": "paragraph", "find": "100,000", "text": "표 다음 문단"}) is None
    assert bridge.cell_text("항목", 0, "B2") == "100,000"
    assert bridge.read_text().rstrip().endswith("표 다음 문단")
    bridge.table_op({"action": "set_cell", "find": "항목", "cell": "B2", "text": "200,000"})  # 커서를 표 칸에 둠
    import struct

    png = bridge.page_png(1, tmp_path)
    assert struct.unpack(">II", png[16:24])[0] > 500  # A4 폭 80dpi ≈ 661px


def _left_px(png: bytes) -> int:
    """쪽 그림(80dpi)에서 글자가 시작하는 가장 왼쪽 x — 그림 라이브러리 없이 PNG를 직접 풂."""
    import struct
    import zlib

    w, h = struct.unpack(">II", png[16:24])
    data, i = b"", 8
    while i < len(png):
        n, t = struct.unpack(">I4s", png[i:i + 8])
        if t == b"IDAT":
            data += png[i + 8:i + 8 + n]
        i += 12 + n
    raw, row = zlib.decompress(data), w * 3 + 1
    return min(x for y in range(h) for x in range(w) if raw[y * row + 1 + x * 3] < 128)


def test_margin_mm_moves_text_by_real_millimetres(bridge, tmp_path):
    """여백 10mm → 쪽 그림에서 약 31px(80dpi) 이동. 홀수 값은 다른 단위라 짝수로 넣는다 (2026-11-11)."""
    from hwpgpt.tools_server import shapes

    base = _left_px(bridge.page_png(1, tmp_path))
    _, para = shapes({"left_margin_mm": 10})
    assert bridge.format_text("2026년", None, {}, para) == 1
    moved = _left_px(bridge.page_png(1, tmp_path)) - base
    assert 28 <= moved <= 35, moved


def test_new_table_full_width_and_paragraph_after_table_adds_one_paragraph(bridge):
    assert bridge.table_op({"action": "create", "find": "2026년", "rows": [["가", "나"], ["다", "라"]]}) is None
    assert bridge._call(lambda h: (bridge._goto_cell(h, "가", 0), round(h.CellShape.Item("Width") / 283.465))[1]) >= 140
    before = bridge.read_text()
    assert bridge.insert({"kind": "paragraph", "find": "라", "text": "표 뒤 문단"}) is None
    after = bridge.read_text()
    assert after.replace("표 뒤 문단\r\n", "", 1) == before  # 빈 문단 없이 이 문단 하나만 늘어남
    assert after.index("라") < after.index("표 뒤 문단")


def test_memo_on_whole_paragraph_keeps_text_findable(bridge):
    _new_para(bridge, "메모 달 문단 가나다")
    assert bridge.insert({"kind": "memo", "find": "달 문단", "text": "확인 메모"}) is None
    assert bridge._call(lambda h: bridge._seek(h, "메모 달 문단 가나다"))  # 메모 경계를 걸치지 않음
    assert bridge.apply([Edit("가나다", "라마바", "")])[0][1] == 1


def test_picture_in_cell_and_replace_picture(bridge, tmp_path):
    import struct
    import zlib

    def png(path, w, h):  # 단색 PNG (표준 라이브러리)
        raw = b"".join(b"\0" + b"\x20\x80\xe0" * w for _ in range(h))
        chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))  # noqa: E731
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        return str(path)

    wide, square = png(tmp_path / "wide.png", 1200, 600), png(tmp_path / "sq.png", 400, 400)
    assert bridge.table_op({"action": "create", "find": "2026년", "rows": [["사진", "설명"], ["칸", "글"]]}) is None
    assert bridge.insert({"kind": "picture", "find": "칸", "in_cell": True}, picture=wide) is None

    def sizes(h):
        return [(round(p.Properties.Item("Width") / 283.465), round(p.Properties.Item("Height") / 283.465))
                for p in bridge._pictures(h)]

    (w, hgt), = bridge._call(sizes)
    assert 60 <= w <= 80 and abs(w - 2 * hgt) <= 1  # 칸 폭(본문 폭 표 2열 ≈ 74mm)에 맞추고 비율 2:1 유지
    assert bridge.cell_text("사진", 0, "A2") == "칸"  # 칸 글은 그대로, 그림은 그 칸 안
    assert bridge.insert({"kind": "replace_picture", "picture_no": 1}, picture=square) is None
    (w2, h2), = bridge._call(sizes)
    assert w2 == w and abs(w2 - h2) <= 1  # 같은 폭, 새 그림 비율(1:1)
    assert "picture_no는 1~1" in bridge.insert({"kind": "replace_picture", "picture_no": 5}, picture=square)
    # 빈 칸(B1에 글 없음)은 표의 아무 칸 글 + 칸 주소로
    assert bridge.table_op({"action": "set_cell", "find": "사진", "cell": "B1", "text": ""}) is None
    assert bridge.insert({"kind": "picture", "find": "사진", "cell": "B1"}, picture=square) is None
    assert len(bridge._call(sizes)) == 2 and bridge.cell_text("사진", 0, "A1") == "사진"


def _run(bridge, ops):
    """패널 Api._run_ops와 같은 방식으로 기록된 작업 실행 → 모두 됐는지."""
    from hwpgpt.app import UNDO_OPS

    results = [getattr(bridge, o["op"])(*o["args"]) for o in ops if o["op"] in UNDO_OPS]
    return len(results) == len(ops) and not any(isinstance(r, str) or r is False or r == 0 for r in results)


def test_structural_undo_redo_restores_document(bridge, tmp_path):
    """서식·표·문단·그림·메모·각주·머리말·쪽 번호를 ↶하면 넣기 전 본문(HWPML)으로, ↷하면 다시 (2026-11-11)."""
    from hwpgpt import session
    from hwpgpt.tools_server import Tools

    def body():
        import re

        x = bridge._call(lambda h: h.GetTextFile("HWPML2X", ""))
        x = x[x.find("<BODY"):x.find("</BODY>")]
        # 다시 넣으면 한글 내부 번호(개체 ID·쌓는 순서·머리말 일련번호·메모 시각)만 새로 붙음 — 내용 비교에서 뺌
        x = re.sub(r'(InstI[dD]|ZOrder|SeriesNum)="\d+"|MEMO/\d+/\d+/\d+/\d+', "", x)
        x = re.sub(r"<MARKPEN[^>]*>|</MARKPEN[^>]*>|MARKPEN\w*", "", x)  # 노랑 표시는 따로 지움
        # 서식을 되돌리면 같은 글자 모양의 글이 두 덩어리로 남음(모양 ID는 원래와 같음) → 이어 붙여 비교
        while (y := re.sub(r'(<TEXT CharShape="(\d+)">(?:(?!</TEXT>).)*?)</CHAR></TEXT><TEXT CharShape="\2"><CHAR>', r"\1", x)) != x:
            x = y
        return x

    _new_para(bridge, "기준 문단 하나")
    png = tmp_path / "p.png"
    png.write_bytes(bridge.page_png(1, tmp_path))
    t = Tools(bridge, tmp_path / "s.jsonl", files=[str(png)])
    start = body()
    t.format_text([{"find": "기준 문단", "bold": True, "color": "#ff0000", "align": "center", "left_margin_mm": 5}])
    t.edit_table([{"action": "create", "find": "기준 문단", "rows": [["가", "나"], ["다", "라"]]}])
    t.edit_table([{"action": "set_cell", "find": "가", "cell": "B2", "text": "새 글"},
                  {"action": "insert_col_right", "find": "가", "cell": "A1"}])
    t.insert_content([{"kind": "paragraph", "find": "기준 문단", "text": "새 문단 1\n새 문단 2"},
                      {"kind": "picture", "find": "새 문단 2", "width_mm": 30},
                      {"kind": "memo", "find": "하나", "text": "메모"},
                      {"kind": "footnote", "find": "기준 문단", "text": "각주"},
                      {"kind": "header", "text": "머리말"},
                      {"kind": "footer", "text": "꼬리말"},
                      {"kind": "page_number", "position": "bottom_center"}])
    done = [x["data"] for x in session.read(tmp_path / "s.jsonl") if x["kind"] == "done"]
    assert len(done) == 11 and all(d.get("undo") for d in done), [d["label"] for d in done if not d.get("undo")]
    after = body()
    assert "<FOOTER" in after and "<HEADER" in after  # 꼬리말이 머리말로 들어가던 버그 (2026-11-11)
    for d in reversed(done):  # 패널에서 아래 항목부터 ↶
        assert _run(bridge, d["undo"]), d["label"]
    assert body() == start
    for d in done:  # ↷ 다시 적용 (새 자리를 다음 ↶에 씀)
        bridge.undo_spec = None
        assert _run(bridge, d["redo"]), d["label"]
        if bridge.undo_spec:
            d["undo"] = bridge.undo_spec
    assert body() == after
    for d in reversed(done):
        assert _run(bridge, d["undo"]), d["label"]
    assert body() == start


def test_insert_column_keeps_table_inside_text_width_and_undo_restores_width(bridge):
    """한글은 열을 넣으면 표가 본문 밖으로 넓어짐 → 본문 폭 안으로 줄이고, 되돌리면 원래 폭 (2026-11-11)."""
    def width(h):
        bridge._goto_cell(h, "가", 0)
        return h.CellShape.Item("Width")

    assert bridge.table_op({"action": "create", "find": "2026년", "rows": [["가", "나"], ["다", "라"]]}) is None
    before = bridge._call(width)
    text_w = bridge._call(bridge._text_width)
    assert bridge.table_op({"action": "insert_col_right", "find": "가", "cell": "A1"}) is None
    assert before - 1000 <= bridge._call(width) <= text_w
    assert bridge.table_op({"action": "delete_col", "find": "가", "cell": "B1", "width": before}) is None
    assert abs(bridge._call(width) - before) < 600  # 1mm 단위로 늘려서 1mm 안쪽


def test_append_change_table_at_end_and_undo_redo(bridge):
    """신구대조표: 문서 끝에 제목+표, ↶로 제목·표 모두 빠져 원래 글로, ↷로 다시 (2026-11-11)."""
    before = bridge.read_text()
    rows = [["연번", "수정 전", "수정 후", "곳"], ["1", "2026년", "2027년", "1"]]
    assert bridge.append_table("변경 신구대조표 (시험)", rows) is None
    after = bridge.read_text()
    assert "변경 신구대조표 (시험)" in after and "수정 전" in after and after.index("변경 신구대조표") > after.index(SAMPLE[:5])
    assert bridge.cell_text("수정 전", 0, "C2") == "2027년"
    undo = bridge.undo_spec
    assert [o["op"] for o in undo] == ["delete_ctrl_at", "delete_para_at"]
    assert _run(bridge, undo)
    assert bridge.read_text().strip() == before.strip()
    assert bridge.append_table("변경 신구대조표 (시험)", rows) is None and "수정 후" in bridge.read_text()


def test_change_table_starts_new_page_and_delete_removes_all(bridge):
    """신구대조표는 새 쪽에서 시작, [대조표 지우기]는 여러 개를 제목과 함께 모두 지워 원래대로 (2026-11-13)."""
    before = bridge.read_text()
    pages = bridge._call(lambda h: h.PageCount)
    rows = [["연번", "수정 전", "수정 후", "곳"], ["1", "2026년", "2027년", "1"]]
    assert bridge.append_table("변경 신구대조표 (시험)", rows) is None
    assert bridge._call(lambda h: h.PageCount) == pages + 1
    assert bridge.append_table("변경 신구대조표 (시험2)", rows) is None
    assert bridge.delete_titled_tables("변경 신구대조표") == 2
    assert bridge.read_text().strip() == before.strip()
    assert bridge._call(lambda h: h.PageCount) == pages


def test_same_text_in_header_does_not_skip_or_cancel_body_edits(bridge):
    """머리말에도 같은 글이 있으면: 전부 바꾸기는 본문 마지막 것을 빠뜨렸고, 번째(nths) 수정은 통째로 되돌려졌음 (2026-11-13)."""
    bridge._call(lambda h: (h.HAction.Run("MoveDocEnd"), bridge._insert(h, "\r\n가 2025학년도\r\n나 2025학년도\r\n다 2025학년도")))
    assert bridge.insert({"kind": "header", "text": "2025학년도 사업단"}) is None
    res = bridge.apply([Edit("2025학년도", "2026학년도", "연도", (0, 2))])
    assert res[0][1] == 2
    assert bridge.read_text().endswith("가 2026학년도\r\n나 2025학년도\r\n다 2026학년도")
    bridge.apply([Edit("2025학년도", "2026학년도", "연도")])
    assert "2025학년도" not in bridge.read_text()


def test_replace_containing_find_changes_each_spot_once(bridge):
    """한글 찾기는 문서 끝에서 처음으로 돌아감 — '2026년'→'2026년도'처럼 바꾼 글에 find가 들어 있어도 한 번씩만 (2026-11-13)."""
    res = bridge.apply([Edit("2026년", "2026년도", "표기")])
    assert res[0][1] == 1 and bridge.read_text().startswith("2026년도 행사,")
    res = bridge.apply([Edit("2026년", "2026년도", "표기", (0,))])
    assert res[0][1] == 1 and bridge.read_text().startswith("2026년도도 행사,")
