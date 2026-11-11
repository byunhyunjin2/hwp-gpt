"""열린 한글 문서를 읽고, 바꾸고, 형광펜으로 표시한다. 문서를 저장하지 않는다.

연결은 ROT의 `!HwpObject*` 항목으로만 한다 — GetActiveObject는 사용자가 연 한글도 못 찾고,
Dispatch는 숨은 새 한글을 띄운다 (docs/spike-results.md, MISTAKES M-003).
"""
from typing import Callable

from .com_worker import ComWorker
from .rules import Edit, same_kind_neighbor, strip_unit

YELLOW = (255, 240, 0)   # 바꾼 곳
RED = (255, 120, 120)    # 안 바꿈·확인
SHAPE = ("AlignType", "LeftMargin", "RightMargin", "Indentation")  # 이웃 문단에 맞출 문단 모양


MM = 283.465  # 1mm = HWPUNIT
ALIGN = {"justify": 0, "left": 1, "right": 2, "center": 3, "distribute": 4}  # HParaShape.AlignType
PAGE_NUM = {"top_left": 1, "top_center": 2, "top_right": 3, "bottom_left": 4, "bottom_center": 5, "bottom_right": 6}
MEMO = "%%me"  # 한글 메모 컨트롤 ID (2026-11-11 시험)
# 새 컨트롤을 지우면 되돌아가는 넣기 → 그 컨트롤 ID (2026-11-11 시험. 각주는 안에 'atno'도 생기고, 같은 문단의 뒤 컨트롤은 자리가 밀림)
UNDO_BY_CTRL = {"picture": "gso", "memo": "%%me", "footnote": "fn", "header": "head", "footer": "foot", "page_number": "pgnp"}


class HwpNotAvailable(Exception):
    """한글이 없거나 연결이 끊김."""


def _replace_nths(text: str, find: str, replace: str, nths: set[int]) -> str:
    """text 속 find의 nths번째(0부터)들만 replace로 — apply 결과가 맞는지 비교할 기준."""
    parts = text.split(find)
    return "".join(p + ((replace if k in nths else find) if k < len(parts) - 1 else "") for k, p in enumerate(parts))


def bmp_to_png(bmp: bytes) -> bytes:
    """한글 CreatePageImage가 만드는 24비트 BMP → PNG (표준 라이브러리만). ChatGPT는 BMP를 받지 않는다."""
    import struct
    import zlib

    (off,) = struct.unpack_from("<I", bmp, 10)
    w, hgt = struct.unpack_from("<ii", bmp, 18)
    (bits,) = struct.unpack_from("<H", bmp, 28)
    if bits != 24:
        raise ValueError(f"{bits}비트 BMP는 지원하지 않음")
    stride = (w * 3 + 3) & ~3
    raw = bytearray()
    for r in (range(hgt - 1, -1, -1) if hgt > 0 else range(-hgt)):  # 양수 높이 = 아래 줄부터 저장됨
        row = bmp[off + r * stride: off + r * stride + w * 3]
        rgb = bytearray(row)
        rgb[0::3], rgb[2::3] = row[2::3], row[0::3]  # BGR → RGB
        raw += b"\0" + rgb

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, abs(hgt), 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def attach_running_hwp():
    """사용자가 연 한글에 붙는다. 없으면 None. 새 창을 띄우지 않는다."""
    import pythoncom
    import win32com.client

    ctx = pythoncom.CreateBindCtx(0)
    rot = pythoncom.GetRunningObjectTable()
    for mk in rot.EnumRunning():
        if mk.GetDisplayName(ctx, None).startswith("!HwpObject"):
            obj = rot.GetObject(mk).QueryInterface(pythoncom.IID_IDispatch)
            return win32com.client.Dispatch(obj)
    return None


class HwpBridge:
    def __init__(self, worker: ComWorker, attach: Callable = attach_running_hwp) -> None:
        self._w = worker
        self._attach = attach
        self._h = None
        self._marks: dict[str, tuple] = {}    # 패널이 형광펜 칠한 글자 → 색 (지우기용)
        self._cleared: dict[str, tuple] = {}  # 지운 표시 (다시 보기용)
        self.undo_spec: list[dict] | None = None  # 마지막 표·넣기 작업을 되돌리는 방법 (도구 서버 → 패널 ↶)
        self.table_width_before = 0  # 마지막 열 작업 전 표 폭 (열 넣기 되돌릴 때 원래 폭으로)

    # --- 내부 ---
    def _call(self, fn):
        import pywintypes

        def guarded():
            if self._h is None:
                raise HwpNotAvailable("한글 문서를 열어 주세요")
            try:
                return fn(self._h)
            except pywintypes.com_error as e:
                self._h = None
                raise HwpNotAvailable(f"한글 연결이 끊어짐: {e}") from e

        return self._w.call(guarded)

    @staticmethod
    def _find(h, text: str, from_start: bool) -> bool:
        """text를 찾아 선택. from_start면 문서 처음부터."""
        if from_start:
            h.HAction.Run("MoveDocBegin")
        p = h.HParameterSet.HFindReplace
        h.HAction.GetDefault("RepeatFind", p.HSet)
        p.FindString, p.FindRegExp, p.IgnoreMessage, p.Direction = text, 0, 1, 0
        p.FindType = 1  # 끝에서 처음으로 돌아가지 않음
        return bool(h.HAction.Execute("RepeatFind", p.HSet))

    @staticmethod
    def _insert(h, text: str) -> None:
        p = h.HParameterSet.HInsertText
        h.HAction.GetDefault("InsertText", p.HSet)
        p.Text = text
        h.HAction.Execute("InsertText", p.HSet)

    @staticmethod
    def _markpen(h, rgb) -> None:
        p = h.HParameterSet.HMarkpenShape
        h.HAction.GetDefault("MarkPenShape", p.HSet)
        p.Color = h.RGBColor(*rgb)
        h.HAction.Execute("MarkPenShape", p.HSet)

    @staticmethod
    def _para_text(h, lst: int, para: int) -> str | None:
        """그 문단의 글. 없는 문단이면 None."""
        if not h.SetPos(lst, para, 0) or tuple(h.GetPos())[:2] != (lst, para):
            return None
        h.HAction.Run("MoveSelParaEnd")
        t = (h.GetTextFile("UNICODE", "saveblock") or "").rstrip("\r\n")  # 빈 문단은 선택이 없어 None
        h.HAction.Run("Cancel")
        return t

    def _tidy(self, h, paras) -> None:
        """고친 문단을 주위에 맞춘다: 같은 글머리 종류의 가장 가까운 이웃(앞뒤 3문단, 같은 표 칸 안)과
        정렬·여백·들여쓰기를 같게 하고, 한글 줄 나눔을 어절 단위로(단어가 줄 끝에서 갈라지지 않게)."""
        for lst, para in sorted(paras):
            text = self._para_text(h, lst, para)
            if text is None:
                continue
            near = []
            for d in (1, -1, 2, -2, 3, -3):  # 가까운 순, 앞 문단 먼저
                t = self._para_text(h, lst, para - d) if para - d >= 0 else None
                if t is not None:
                    near.append((para - d, t))
            src = same_kind_neighbor(text, near)
            shape = {}
            if src is not None:
                h.SetPos(lst, src, 0)
                s = h.HParameterSet.HParaShape
                h.HAction.GetDefault("ParagraphShape", s.HSet)
                shape = {k: getattr(s, k) for k in SHAPE}
            h.SetPos(lst, para, 0)
            p = h.HParameterSet.HParaShape
            h.HAction.GetDefault("ParagraphShape", p.HSet)
            for k, v in shape.items():
                setattr(p, k, v)
            p.BreakNonLatinWord = 0  # 0 = 어절, 1 = 글자(한글 기본값) — 2026-10-25 시험으로 확인
            h.HAction.Execute("ParagraphShape", p.HSet)

    def _mark_all(self, h, text: str, rgb, limit: int) -> int:
        n = 0
        found = self._find(h, text, from_start=True)
        while found and n < limit:
            self._markpen(h, rgb)
            n += 1
            h.HAction.Run("Cancel")  # 선택 해제, 커서는 찾은 곳 뒤
            found = self._find(h, text, from_start=False)
        return n

    # --- 공개 ---
    def connect(self) -> bool:
        def do():
            self._h = self._attach()
            return self._h is not None

        return self._w.call(do)

    def read_text(self) -> str:
        return self._call(lambda h: h.GetTextFile("UNICODE", ""))

    def title(self) -> str:
        import win32gui

        return self._call(lambda h: win32gui.GetWindowText(h.XHwpWindows.Item(0).WindowHandle))

    def is_modified(self) -> bool:
        """저장 안 된 변경이 있는지. True→False로 바뀌면 사용자가 저장한 것."""
        return self._call(lambda h: bool(h.XHwpDocuments.Active_XHwpDocument.Modified))

    def target_name(self) -> str:
        """지금 수정 대상인 문서 경로 (새 문서면 빈 문자열)."""
        return self._call(lambda h: h.Path)

    def apply(self, edits: list[Edit]) -> list[tuple[Edit, int, list]]:
        """수정안을 적용하고 바꾼 곳을 노랑으로 표시. e.nths가 있으면 그 번째 것만, 없으면 문서 전체.
        (수정안, 바꾼 수, 바꾼 자리들[(list, para, pos)]) — 자리는 되돌리기(undo)에 쓴다."""

        def do(h):
            out = []
            for e in edits:
                before = h.GetTextFile("UNICODE", "")
                limit = before.count(e.find)
                want = None if e.nths is None else set(e.nths)
                k, pos = 0, []
                found = self._find(h, e.find, from_start=True)
                while found and k < limit:
                    if want is None or k in want:
                        self._insert(h, e.replace)  # 선택 영역을 바꿈
                        end = h.GetPos()  # 바꾼 글 뒤 — 다음 찾기는 여기부터 (바꾼 글 속의 find를 다시 찾지 않게)
                        for _ in range(len(e.replace)):
                            h.HAction.Run("MoveSelLeft")
                        pos.append(list(h.GetPos()))  # 바꾼 글자의 시작 자리
                        self._markpen(h, YELLOW)
                        h.HAction.Run("Cancel")
                        h.SetPos(*end)
                    else:
                        h.HAction.Run("Cancel")
                    k += 1
                    found = self._find(h, e.find, from_start=False)
                if want is not None and pos and h.GetTextFile("UNICODE", "") != _replace_nths(before, e.find, e.replace, want):
                    # 한글 찾기 순서가 본문 글 순서와 달라(글상자·머리말 등) 다른 자리를 바꿈 → 되돌리고 바꾸지 않음
                    self._revert(h, [{"find": e.find, "replace": e.replace, "pos": pos}])
                    pos = []
                if pos:
                    self._marks[e.replace] = YELLOW
                out.append((e, len(pos), pos))
            self._tidy(h, {(lst, para) for _, _, ps in out for lst, para, _ in ps})
            return out

        return self._call(do)

    def undo(self, applied: list[dict]) -> tuple[int, int]:
        """apply가 바꾼 자리를 거꾸로(마지막 것부터) 원래 글로 되돌린다. 그사이 사용자가 고친 자리는 건너뛴다.
        applied = [{"find", "replace", "pos": [[list, para, pos], ...]}]. (되돌린 수, 건너뛴 수)"""

        return self._call(lambda h: self._revert(h, applied))

    def _revert(self, h, applied: list[dict]) -> tuple[int, int]:
        """undo 본문 — 기록한 자리를 거꾸로 원래 글로 (apply가 잘못 바꾼 것을 되돌릴 때도). (되돌린 수, 건너뛴 수)"""
        ok = skipped = 0
        for a in reversed(applied):
            for lst, para, p in reversed(a.get("pos") or []):
                h.SetPos(lst, para, p)
                for _ in range(len(a["replace"])):
                    h.HAction.Run("MoveSelRight")
                if h.GetTextFile("UNICODE", "saveblock").rstrip("\r\n") != a["replace"]:
                    h.HAction.Run("Cancel")
                    skipped += 1
                    continue
                self._insert(h, a["find"])  # 선택 영역을 원래 글로 (MarkPenDelete는 선택을 풀어서 나중에)
                for _ in range(len(a["find"])):
                    h.HAction.Run("MoveSelLeft")
                if a["find"]:
                    h.HAction.Run("MarkPenDelete")  # 노랑을 이어받았으면 지움
                h.HAction.Run("Cancel")
                ok += 1
            self._marks.pop(a["replace"], None)
        return ok, skipped

    def redo(self, applied: list[dict]) -> tuple[int, int]:
        """undo한 것을 다시 적용(노랑 표시 포함). 자리는 apply 때 순서대로 기록됐으니 앞에서부터.
        그사이 사용자가 고친 자리는 건너뛴다. (다시 바꾼 수, 건너뛴 수)"""

        def do(h):
            ok = skipped = 0
            for a in applied:
                before = ok
                for lst, para, p in a.get("pos") or []:
                    h.SetPos(lst, para, p)
                    for _ in range(len(a["find"])):
                        h.HAction.Run("MoveSelRight")
                    if h.GetTextFile("UNICODE", "saveblock").rstrip("\r\n") != a["find"]:
                        h.HAction.Run("Cancel")
                        skipped += 1
                        continue
                    self._insert(h, a["replace"])
                    for _ in range(len(a["replace"])):
                        h.HAction.Run("MoveSelLeft")
                    self._markpen(h, YELLOW)
                    h.HAction.Run("Cancel")
                    ok += 1
                if ok > before:
                    self._marks[a["replace"]] = YELLOW
            return ok, skipped

        return self._call(do)

    def unmark(self, texts: list[str]) -> None:
        """이 글자들에 칠한 형광펜을 지운다 (되돌릴 때 그 요청의 확인 표시 정리)."""

        def do(h):
            for text in dict.fromkeys(texts):
                limit = h.GetTextFile("UNICODE", "").count(text)
                k, found = 0, self._find(h, text, from_start=True)
                while found and k < limit:
                    h.HAction.Run("MarkPenDelete")
                    h.HAction.Run("Cancel")
                    k += 1
                    found = self._find(h, text, from_start=False)
                self._marks.pop(text, None)

        self._call(do)

    def mark_check(self, text: str, nth: int | None = None) -> bool:
        def do(h):
            for t in filter(None, (text, strip_unit(text))):  # 표 칸의 '원'이 떨어져 있으면 숫자만으로
                if nth is not None:
                    if self._seek(h, t, nth):
                        self._markpen(h, RED)
                        h.HAction.Run("Cancel")
                        self._marks[t] = RED
                        return True
                elif self._mark_all(h, t, RED, h.GetTextFile("UNICODE", "").count(t)):
                    self._marks[t] = RED
                    return True
            return False

        return self._call(do)

    def goto(self, text: str, nth: int = 0) -> bool:
        """text의 nth번째(0부터)를 선택. 못 찾으면(긴 문장이 줄바꿈 등으로 끊김) 앞부분 낱말 4·3·2개, 가장 긴 낱말 순으로."""
        words = text.split()
        tries = [(text, nth)] + [(strip_unit(text), nth)] * bool(strip_unit(text))
        tries += [(" ".join(words[:k]), 0) for k in (4, 3, 2) if len(words) > k]
        tries += [(max(words, key=len), 0)] if words else []

        def do(h):
            for t, k in tries:
                found = bool(t) and self._find(h, t, from_start=True)
                for _ in range(k):
                    found = found and self._find(h, t, from_start=False)
                if found:
                    return True
            return False

        return self._call(do)

    def clear_marks(self) -> int:
        """패널이 칠한 글자만 다시 찾아 형광펜 제거 (사용자 형광펜은 보존)."""

        def do(h):
            n = 0
            for text in self._marks:
                limit = h.GetTextFile("UNICODE", "").count(text)
                found = self._find(h, text, from_start=True)
                k = 0
                while found and k < limit:
                    h.HAction.Run("MarkPenDelete")
                    h.HAction.Run("Cancel")
                    n += 1
                    k += 1
                    found = self._find(h, text, from_start=False)
            self._cleared = dict(self._marks)
            self._marks.clear()
            return n

        return self._call(do)

    def clear_all_marks(self) -> int:
        """문서의 형광펜을 모두 지운다 (패널이 칠한 것 + 남은 것 + 사용자가 칠한 것). 지운 표시 수.
        본문은 전체 선택, 표는 표마다 모든 칸을 선택해서 지운다 (본문 전체 선택은 표 칸 안까지는 지우지 못함).
        메모는 delete_memos로 따로 (app이 함께 부름)."""

        def count(h) -> int:
            return h.GetTextFile("HWPML2X", "").count("<MARKPENBEGIN")

        def do(h):
            before = count(h)
            h.HAction.Run("MoveDocBegin")
            h.HAction.Run("SelectAll")
            h.HAction.Run("MarkPenDelete")
            h.HAction.Run("Cancel")
            c = h.HeadCtrl
            while c:
                if c.CtrlID == "tbl":
                    h.SetPosBySet(c.GetAnchorPos(0))
                    h.FindCtrl()
                    h.HAction.Run("ShapeObjTableSelCell")
                    h.HAction.Run("TableCellBlockExtend")
                    h.HAction.Run("TableCellBlockExtend")  # 표 전체 칸 선택
                    h.HAction.Run("MarkPenDelete")
                    h.HAction.Run("Cancel")
                c = c.Next
            h.HAction.Run("MoveDocBegin")
            self._marks.clear()
            self._cleared = {}
            return before - count(h)

        return self._call(do)

    @staticmethod
    def _cell_row(h) -> int:
        """커서가 있는 표 칸의 줄 번호(1부터) — 상태 표시줄의 칸 주소 "(A3): …"."""
        import re

        m = re.search(r"\(([A-Z]+)(\d+)\)", str(h.KeyIndicator()[-1]))
        return int(m.group(2)) if m else 0

    def _goto_cell(self, h, text: str, nth: int) -> int | None:
        """text(nth번째)가 든 표 칸으로 가서 그 줄 번호(1부터). 표 칸이 아니면 None."""
        found = self._find(h, text, from_start=True)
        for _ in range(nth):
            found = found and self._find(h, text, from_start=False)
        if not found:
            return None
        h.HAction.Run("Cancel")
        if not (h.ParentCtrl and h.ParentCtrl.CtrlID == "tbl"):
            return None
        return self._cell_row(h)

    def table_rows(self, action: str, find: str, nth: int = 0, count: int = 1,
                   until: str = "", until_nth: int = 0, to_end: bool = False) -> str | None:
        """find(nth번째)가 든 표 칸의 줄을 지우거나(delete) 그 아래에 빈 줄을 넣는다(insert_below). 안 되면 이유.
        until: delete에서 마지막으로 지울 줄의 칸 글, to_end: 표 마지막 줄까지 — 줄 수는 칸 주소로 직접 센다
        (AI가 세거나 마지막 줄을 고르면 틀림, 2026-10-25 실제 ChatGPT 시험)."""
        run = {"delete": "TableDeleteRow", "insert_below": "TableInsertLowerRow"}.get(action)
        if not run:
            return f"모르는 작업: {action}"

        def do(h):
            if until:
                last = self._goto_cell(h, until, until_nth)
                if not last:
                    return "until 글이 든 표 칸을 찾지 못함"
            row = self._goto_cell(h, find, nth)
            if row is None:
                return "표 칸 안의 글을 찾지 못함"
            n = count
            if to_end and action == "delete":
                h.HAction.Run("TableColPageDown")  # 이 열의 맨 아래 칸
                last = self._cell_row(h)
                row = self._goto_cell(h, find, nth)
                n = last - row + 1
            elif until:
                if last < row:
                    return "until이 find보다 위에 있음"
                n = last - row + 1
            for _ in range(max(1, n)):
                if not h.HAction.Run(run):
                    return "한글이 줄 작업을 거부함"
            return None

        return self._call(do)

    def has_marks(self) -> bool:
        return bool(self._marks)

    def restore_marks(self) -> int:
        """[표시 모두 지우기]로 지운 표시를 같은 색으로 다시 칠한다."""

        def do(h):
            n = 0
            for text, rgb in self._cleared.items():
                k = self._mark_all(h, text, rgb, h.GetTextFile("UNICODE", "").count(text))
                if k:
                    self._marks[text] = rgb
                n += k
            self._cleared = {}
            return n

        return self._call(do)

    def can_restore(self) -> bool:
        return bool(self._cleared)

    def remember_marks(self, texts: list[str], rgb: tuple = YELLOW) -> None:
        """다른 프로세스(도구 서버)가 칠한 형광펜 글자를 지우기 목록에 추가."""
        for t in texts:
            if t:
                self._marks[t] = rgb
        if texts:
            self._cleared = {}  # 새 표시가 생기면 예전 '다시 보기'는 의미 없음

    # --- 서식·표·넣기·검토 (2026-11-11, 한컴 2022 시험으로 확인한 액션만) ---
    def _seek(self, h, text: str, nth: int = 0) -> bool:
        """문서 처음부터 text의 nth번째(0부터)를 선택."""
        found = self._find(h, text, from_start=True)
        for _ in range(nth):
            found = found and self._find(h, text, from_start=False)
        return found

    def _mark_back(self, h, n: int) -> None:
        """방금 넣은 글 n자를 노랑으로 (커서는 넣은 글 뒤)."""
        end = h.GetPos()
        for _ in range(n):
            h.HAction.Run("MoveSelLeft")
        self._markpen(h, YELLOW)
        h.HAction.Run("Cancel")
        h.SetPos(*end)

    def _type_lines(self, h, text: str, mark: bool = True) -> list[list[int]]:
        """여러 줄 글: 줄마다 문단을 나눠 넣고 노랑 표시. 줄마다 [list, para] (되돌리기용)."""
        spots = []
        for i, line in enumerate(text.splitlines() or [""]):
            if i:
                h.HAction.Run("BreakPara")
            spots.append(list(h.GetPos())[:2])
            if line:
                self._insert(h, line)
                if mark:
                    self._mark_back(h, len(line))
                    self._marks[line] = YELLOW
        return spots

    def shapes_of(self, find: str, nths, char_keys, para_keys) -> list:
        """format_text 되돌리기용: find의 각 번째 자리의 지금 모양 [[k, 글자 모양, 문단 모양], ...]."""

        def do(h):
            out, k = [], 0
            limit = h.GetTextFile("UNICODE", "").count(find)
            want = None if nths is None else set(nths)
            found = self._find(h, find, from_start=True)
            while found and k < limit:
                if want is None or k in want:
                    c, p = h.HParameterSet.HCharShape, h.HParameterSet.HParaShape
                    h.HAction.GetDefault("CharShape", c.HSet)
                    h.HAction.GetDefault("ParagraphShape", p.HSet)
                    ch = {key: getattr(c, key) for key in char_keys}
                    if "TextColor" in ch:  # 한글 색 값은 0x00BBGGRR → format_text가 받는 (r, g, b)
                        v = ch["TextColor"]
                        ch["TextColor"] = [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF]
                    out.append([k, ch, {key: getattr(p, key) for key in para_keys}])
                h.HAction.Run("Cancel")
                k += 1
                found = self._find(h, find, from_start=False)
            return out

        return self._call(do)

    def format_text(self, find: str, nths, char: dict, para: dict) -> int:
        """find(nths번째들, None이면 전부)에 글자 모양(char)·그 문단에 문단 모양(para)을 입힌다. 바꾼 수."""

        def do(h):
            limit = h.GetTextFile("UNICODE", "").count(find)
            want = None if nths is None else set(nths)
            k = n = 0
            found = self._find(h, find, from_start=True)
            while found and k < limit:
                if want is None or k in want:
                    if char:
                        c = h.HParameterSet.HCharShape
                        h.HAction.GetDefault("CharShape", c.HSet)
                        for key, v in char.items():
                            setattr(c, key, h.RGBColor(*v) if key == "TextColor" else v)
                        h.HAction.Execute("CharShape", c.HSet)
                    if para:
                        p = h.HParameterSet.HParaShape
                        h.HAction.GetDefault("ParagraphShape", p.HSet)
                        for key, v in para.items():
                            setattr(p, key, v)
                        h.HAction.Execute("ParagraphShape", p.HSet)
                    n += 1
                h.HAction.Run("Cancel")
                k += 1
                found = self._find(h, find, from_start=False)
            return n

        return self._call(do)

    @staticmethod
    def _cell_addr(h) -> str:
        """커서가 있는 표 칸 주소 (예: B3)."""
        import re

        m = re.search(r"\(([A-Z]+\d+)\)", str(h.KeyIndicator()[-1]))
        return m.group(1) if m else ""

    @staticmethod
    def _cell_text(h) -> str:
        h.HAction.Run("MoveListBegin")
        h.HAction.Run("Select")
        h.HAction.Run("MoveListEnd")
        t = h.GetTextFile("UNICODE", "saveblock") or ""
        h.HAction.Run("Cancel")
        return t.rstrip("\r\n")

    def _walk_cells(self, h, anchor: str, nth: int, visit) -> str | None:
        """anchor(nth번째)가 든 표의 칸을 A1부터 차례로 visit(주소) — visit가 True면 거기서 멈춤. 안 되면 이유."""
        if self._goto_cell(h, anchor, nth) is None:
            return "표 칸 안의 글을 찾지 못함"
        h.HAction.Run("TableColBegin")
        h.HAction.Run("TableColPageUp")
        seen = set()
        for _ in range(3000):
            addr = self._cell_addr(h)
            if addr in seen or visit(addr):
                return None
            seen.add(addr)
            if not h.HAction.Run("TableRightCell"):
                return None
        return None

    def read_table(self, anchor: str, nth: int = 0) -> dict:
        """anchor가 든 표 전체: {"cells": [[주소, 글], ...]} 또는 {"error"}."""

        def do(h):
            cells = []
            why = self._walk_cells(h, anchor, nth, lambda a: cells.append([a, self._cell_text(h)]))
            return {"error": why} if why else {"cells": cells}

        return self._call(do)

    def _goto_addr(self, h, anchor: str, nth: int, addr: str) -> str | None:
        """anchor가 든 표의 addr 칸으로. 안 되면 이유."""
        why = self._walk_cells(h, anchor, nth, lambda a: a == addr.upper())
        if why:
            return why
        return None if self._cell_addr(h) == addr.upper() else f"{addr} 칸이 없음"

    def cell_text(self, anchor: str, nth: int, addr: str) -> str | None:
        def do(h):
            return None if self._goto_addr(h, anchor, nth, addr) else self._cell_text(h)

        return self._call(do)

    def _make_table(self, h, rows: list) -> str | None:
        """커서가 있는 문단 아래에 rows 표를 새로 만들고 칸을 채운다. undo_spec = 그 표 지우기."""
        cols = max(len(r) for r in rows)
        h.HAction.Run("MoveParaEnd")
        h.HAction.Run("BreakPara")
        t = h.HParameterSet.HTableCreation
        h.HAction.GetDefault("TableCreate", t.HSet)
        t.Rows, t.Cols = len(rows), cols
        t.WidthType = 0  # 0 = 본문(단) 폭에 맞춤. 기본값이면 열마다 21.6mm로 좁게 만들어짐 (2026-11-11 시험)
        lst, para, _ = h.GetPos()
        at_end = self._para_text(h, lst, para + 1) is None  # 문서 끝에 표를 넣으면 한글이 뒤에 빈 문단을 더 만듦
        h.SetPos(lst, para, 0)
        if not h.HAction.Execute("TableCreate", t.HSet):
            return "한글이 표 만들기를 거부함"
        self.undo_spec = [{"op": "delete_ctrl_at", "args": ["tbl", *self._anchor(h.ParentCtrl), 2 if at_end else 1]}]
        cells = [str(v) for r in rows for v in list(r) + [""] * (cols - len(r))]
        for i, v in enumerate(cells):
            self._type_lines(h, v)
            if i < len(cells) - 1:
                h.HAction.Run("TableRightCell")
        return None

    def append_table(self, title: str, rows: list) -> str | None:
        """문서 맨 끝에 제목 문단 + 표 (신구대조표). undo_spec = 표 지우기 → 제목 문단 지우기."""
        self.undo_spec = None

        def do(h):
            h.HAction.Run("Cancel")
            h.HAction.Run("MoveDocEnd")  # 본문 맨 끝 (표 칸 안이 아님)
            h.HAction.Run("BreakPara")
            spots = self._type_lines(h, title)
            why = self._make_table(h, rows)
            if why is None:
                self.undo_spec = self.undo_spec + [{"op": "delete_para_at", "args": [*spots[0], title]}]
            return why

        return self._call(do)

    def table_op(self, op: dict, nth: int = 0) -> str | None:
        """표 작업 하나. op = {"action", "find"(표 칸 글), "cell", "text", "to", "rows"}. 안 되면 이유.
        set_cell · insert_col_left · insert_col_right · delete_col · merge(cell~to) · create(find 문단 아래에 rows 표)."""
        a, find = op.get("action"), op.get("find", "")
        self.undo_spec = None  # 되돌릴 수 있는 작업이면 do 안에서 채움 (도구 서버가 읽어 패널 ↶에 씀)

        def do(h):
            if a == "create":
                rows = op.get("rows") or []
                if not rows or not any(rows) or not self._seek(h, find, nth):
                    return "rows가 비었거나 find 문단을 찾지 못함"
                h.HAction.Run("Cancel")
                return self._make_table(h, rows)
            why = self._goto_addr(h, find, nth, op.get("cell", "A1"))
            if why:
                return why
            if a == "set_cell":
                h.HAction.Run("MoveListBegin")
                h.HAction.Run("Select")
                h.HAction.Run("MoveListEnd")
                if (h.GetTextFile("UNICODE", "saveblock") or "").strip("\r\n"):
                    h.HAction.Run("Delete")
                else:
                    h.HAction.Run("Cancel")
                self._type_lines(h, str(op.get("text", "")), mark=op.get("mark", True))
                return None
            if a == "merge":
                import re

                m1 = re.fullmatch(r"([A-Z]+)(\d+)", str(op.get("cell", "")).upper())
                m2 = re.fullmatch(r"([A-Z]+)(\d+)", str(op.get("to", "")).upper())
                if not m1 or not m2:
                    return "cell과 to에 칸 주소(예: A1, B2)가 필요함"
                (c1, r1), (c2, r2) = m1.groups(), m2.groups()
                col = lambda s: sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(s)))  # noqa: E731
                if col(c2) < col(c1) or int(r2) < int(r1):
                    return "to는 cell보다 오른쪽·아래여야 함"
                h.HAction.Run("TableCellBlock")
                h.HAction.Run("TableCellBlockExtend")
                for _ in range(col(c2) - col(c1)):
                    h.HAction.Run("TableRightCell")
                for _ in range(int(r2) - int(r1)):
                    h.HAction.Run("TableLowerCell")
                ok = h.HAction.Run("TableMergeCell")
                h.HAction.Run("Cancel")
                return None if ok else "한글이 칸 합치기를 거부함"
            run = {"insert_col_left": "TableInsertLeftColumn", "insert_col_right": "TableInsertRightColumn",
                   "delete_col": "TableDeleteColumn"}.get(a)
            if not run:
                return f"모르는 작업: {a}"
            self.table_width_before = h.CellShape.Item("Width")  # 커서가 칸에 있으면 표 전체 폭 (2026-11-11 시험)
            if not h.HAction.Run(run):
                return "한글이 열 작업을 거부함"
            if a.startswith("insert_col"):  # 한글은 열을 넣으면 표가 넓어져 본문 밖으로 나감 → 본문 폭 안으로
                self._resize_table(h, "TableResizeLeft", lambda w: w > self._text_width(h))
            elif op.get("width"):  # 열 넣기를 되돌릴 때: 줄였던 표를 원래 폭으로
                self._resize_table(h, "TableResizeRight", lambda w: w < op["width"])
            return None

        return self._call(do)

    def paragraph_of(self, find: str, nth: int = 0) -> str | None:
        """find가 든 문단의 글 (지우기 전 보호 검사용). 표 칸 안이면 None."""

        def do(h):
            if not self._seek(h, find, nth):
                return None
            h.HAction.Run("Cancel")
            if h.ParentCtrl and h.ParentCtrl.CtrlID == "tbl":
                return None
            lst, para, _ = h.GetPos()
            return self._para_text(h, lst, para)

        return self._call(do)

    def insert(self, item: dict, nth: int = 0, picture: str = "") -> str | None:
        """넣기·지우기 하나. item = {"kind", "find", "text", "position", "width_mm"}. 안 되면 이유.
        paragraph(find 문단 아래 새 문단) · delete_paragraph · page_break(find 문단 뒤) · picture(find 문단 아래)
        · footnote(find 글 뒤) · memo(find 문단에 메모) · header · footer · page_number(position)
        · picture(in_cell: 기준 글이 든 표 칸 안에, cell: find가 든 표의 그 주소 칸 안에) · replace_picture(picture_no번째 그림을 같은 폭으로 바꿈)."""
        kind, find, text = item.get("kind"), item.get("find", ""), str(item.get("text", ""))
        self.undo_spec = None

        def do(h):
            before = self._ctrls(h)
            why = body(h)
            if why is None and kind in UNDO_BY_CTRL:  # 그 종류의 새 컨트롤이 딱 하나면 그것을 지우는 게 되돌리기
                new = [c for c in self._ctrls(h) - before if c[0] == UNDO_BY_CTRL[kind]]
                if len(new) == 1:
                    # 그림은 새 문단을 만들어 넣으므로 그 빈 문단까지 지워야 원래대로 (안 지우면 아래 표 자리가 밀림)
                    self.undo_spec = [{"op": "delete_ctrl_at", "args": [*new[0], kind == "picture"]}]
            return why

        def body(h):
            A = h.HAction
            if kind in ("header", "footer"):
                s = h.HParameterSet.HHeaderFooter
                A.GetDefault("HeaderFooter", s.HSet)
                # 머리말/꼬리말은 HeaderFooterCtrlType(0/1). Type은 양쪽·홀수·짝수 쪽이라 Type=1로는 꼬리말이 안 생기고
                # 머리말에 들어갔음 (2026-11-11 시험으로 발견)
                s.HSet.SetItem("HeaderFooterCtrlType", 0 if kind == "header" else 1)
                if not A.Execute("HeaderFooter", s.HSet):
                    return "한글이 머리말·꼬리말을 거부함"
                self._insert(h, text)
                A.Run("CloseEx")
                return None
            if kind == "page_number":
                s = h.HParameterSet.HPageNumPos
                A.GetDefault("PageNumPos", s.HSet)
                s.DrawPos = PAGE_NUM.get(item.get("position", "bottom_center"), 5)
                return None if A.Execute("PageNumPos", s.HSet) else "한글이 쪽 번호를 거부함"
            if kind == "picture" and item.get("cell"):  # 빈 칸은 가리킬 글이 없으니 표의 아무 칸 글 + 칸 주소로
                if not picture:
                    return "첨부한 그림 파일만 넣을 수 있음"
                why = self._goto_addr(h, find, nth, str(item["cell"]))
                if why:
                    return why
                has_text = bool(self._cell_text(h))
                A.Run("MoveListEnd")
                if has_text:
                    A.Run("BreakPara")
                return self._put_picture(h, picture, item.get("width_mm"), in_cell=True)
            if kind == "replace_picture":
                if not picture:
                    return "첨부한 그림 파일만 넣을 수 있음"
                pics = self._pictures(h)
                try:
                    no = int(item.get("picture_no") or 0)
                except (ValueError, TypeError):
                    no = 0
                if not 1 <= no <= len(pics):
                    return f"picture_no는 1~{len(pics)} (문서의 그림 {len(pics)}개, 문서 순서)"
                old = pics[no - 1]
                width = old.Properties.Item("Width")  # 원래 그림 폭 그대로, 높이는 새 그림 비율로
                h.SetPosBySet(old.GetAnchorPos(0))
                h.DeleteCtrl(old)
                return self._put_picture(h, picture, width / MM)
            if not find or not self._seek(h, find, nth):
                return "find 글을 찾지 못함"
            A.Run("Cancel")  # 커서는 찾은 글 뒤
            if kind == "memo":
                # 메모는 선택한 글을 필드로 감싸고, 메모 경계를 걸치는 글은 한글 찾기로 못 찾는다 (2026-11-11 시험).
                # 문단 전체에 달면 경계가 문단 처음·끝이라 문단 안의 어떤 글도 계속 찾을 수 있다
                A.Run("MoveParaBegin")
                A.Run("MoveSelParaEnd")
                A.Run("InsertFieldMemo")
                self._insert(h, text)
                A.Run("CloseEx")
                return None
            if kind == "footnote":
                A.Run("InsertFootnote")
                self._insert(h, text)
                A.Run("CloseEx")
                return None
            if kind == "delete_paragraph":
                if h.ParentCtrl and h.ParentCtrl.CtrlID == "tbl":
                    return "표 칸 안의 문단은 지우지 않음 (표 작업으로)"
                A.Run("MoveParaBegin")
                A.Run("MoveSelParaEnd")
                A.Run("MoveSelRight")  # 문단 끝 줄바꿈까지
                A.Run("Delete")
                return None
            in_cell = kind == "picture" and item.get("in_cell") and h.ParentCtrl and h.ParentCtrl.CtrlID == "tbl"
            while not in_cell and h.ParentCtrl and h.ParentCtrl.CtrlID == "tbl":  # 표 칸 글이 기준이면 표 바로 뒤에
                h.SetPosBySet(h.ParentCtrl.GetAnchorPos(0))
            A.Run("MoveParaEnd")
            if kind == "page_break":
                A.Run("BreakPage")
                return None
            A.Run("BreakPara")
            if kind == "paragraph":
                spots = self._type_lines(h, text)
                self.undo_spec = [{"op": "delete_para_at", "args": [*spot, line]}
                                  for spot, line in reversed(list(zip(spots, text.splitlines() or [""])))]
                return None
            if kind == "picture":
                if not picture:
                    return "첨부한 그림 파일만 넣을 수 있음"
                return self._put_picture(h, picture, item.get("width_mm"), in_cell=bool(in_cell))
            return f"모르는 종류: {kind}"

        return self._call(do)

    @staticmethod
    def _text_width(h) -> int:
        """본문 폭 (HWPUNIT)."""
        sd = h.HParameterSet.HSecDef
        h.HAction.GetDefault("PageSetup", sd.HSet)
        pd = sd.PageDef
        return pd.PaperWidth - pd.LeftMargin - pd.RightMargin

    @staticmethod
    def _resize_table(h, action: str, more) -> None:
        """커서가 든 표의 모든 칸을 골라 action(칸마다 약 1mm씩 줄이기·늘리기)을 more(표 폭)가 참인 동안 되풀이.
        ponytail: 1mm씩 — 표 폭을 한 번에 정하는 COM 방법을 못 찾음 (TablePropertyDialog Width는 무시됨, 2026-11-11)."""
        h.HAction.Run("TableCellBlock")
        h.HAction.Run("TableCellBlockExtend")
        h.HAction.Run("TableCellBlockExtend")
        for _ in range(400):
            if not more(h.CellShape.Item("Width")) or not h.HAction.Run(action):
                break
        h.HAction.Run("Cancel")

    @staticmethod
    def _pictures(h) -> list:
        """문서의 그림 컨트롤 (표 안 포함, 문서 순서). 글상자·도형은 뺀다."""
        out, c = [], h.HeadCtrl
        while c:
            if c.CtrlID == "gso" and c.UserDesc == "그림":
                out.append(c)
            c = c.Next
        return out

    def _put_picture(self, h, path: str, width_mm=None, in_cell: bool = False) -> str | None:
        """커서 자리에 그림(문서에 포함). 폭은 width_mm·본문 폭(칸 안이면 칸 폭)을 넘지 않게, 높이는 원래 비율."""
        pic = h.InsertPicture(path, True, 0, False, False, 0, 0, 0)  # 원래 크기 — 원래 비율을 알려고
        if pic is None:
            return "한글이 그림 넣기를 거부함"
        w, hgt = pic.Properties.Item("Width"), pic.Properties.Item("Height")
        if in_cell:  # '칸 크기에 맞춤'(2)으로 칸 폭을 알아낸 뒤 높이만 원래 비율로 (그대로 두면 칸 높이로 납작해짐)
            pos = pic.GetAnchorPos(0)
            h.DeleteCtrl(pic)
            h.SetPosBySet(pos)
            pic = h.InsertPicture(path, True, 2, False, False, 0, 0, 0)
            limit = pic.Properties.Item("Width")
        else:
            limit = self._text_width(h)
        try:
            w_mm = float(str(width_mm).rstrip("mM ")) if width_mm is not None else 1e9
        except (ValueError, TypeError):
            w_mm = 1e9
        want = min(max(1, int(w_mm * MM)), limit)
        if (in_cell or w > want) and w > 0:
            ps = pic.Properties
            ps.SetItem("Width", want)
            ps.SetItem("Height", max(1, int(hgt * want / w)))
            pic.Properties = ps
        return None

    @staticmethod
    def _anchor(c) -> list[int]:
        s = c.GetAnchorPos(0)
        return [s.Item("List"), s.Item("Para"), s.Item("Pos")]

    def _ctrls(self, h) -> set[tuple]:
        """문서의 컨트롤 (ID, list, para, pos) — 넣기 전후를 비교해 새 컨트롤을 찾는다."""
        out, c = set(), h.HeadCtrl
        while c:
            out.add((c.CtrlID, *self._anchor(c)))
            c = c.Next
        return out

    def delete_ctrl_at(self, ctrl_id: str, lst: int, para: int, pos: int, drop_empty_para: int = 0) -> bool:
        """그 자리의 컨트롤(표·그림·메모·각주·머리말·쪽 번호)을 지운다. 자리가 바뀌었으면 False.
        drop_empty_para: 1 = 지운 뒤 그 문단이 비면 앞 문단과 합침 (표·그림을 넣으며 만든 빈 문단),
        2 = 그 뒤 문서 끝의 빈 문단도 (문서 끝에 표를 넣으면 한글이 하나 더 만듦)."""

        def do(h):
            same, c = [], h.HeadCtrl
            while c:
                if c.CtrlID == ctrl_id and self._anchor(c)[:2] == [lst, para]:
                    same.append(c)
                c = c.Next
            # 같은 문단에 나중에 넣은 것 때문에 자리(pos)가 밀렸을 수 있음 → 정확히 맞는 것, 없으면 그 문단에 하나뿐인 것
            hit = [c for c in same if self._anchor(c)[2] == pos] or (same if len(same) == 1 else [])
            for c in hit[:1]:
                h.DeleteCtrl(c)
                if drop_empty_para and para > 0 and self._para_text(h, lst, para) == "":
                    if (drop_empty_para == 2 and self._para_text(h, lst, para + 1) == ""
                            and self._para_text(h, lst, para + 2) is None):
                        h.SetPos(lst, para + 1, 0)
                        h.HAction.Run("DeleteBack")
                    h.SetPos(lst, para, 0)
                    h.HAction.Run("DeleteBack")
                return True
            return False

        return self._call(do)

    def delete_para_at(self, lst: int, para: int, text: str) -> bool:
        """새로 넣은 문단을 지운다 (앞 문단 끝의 나눔부터 이 문단 끝까지). 글이 바뀌었으면 False."""

        def do(h):
            if para < 1 or self._para_text(h, lst, para) != text:
                return False
            h.SetPos(lst, para - 1, 0)
            h.HAction.Run("MoveParaEnd")  # 앞 문단 끝 (표 같은 컨트롤이 있어도)
            h.HAction.Run("MoveSelRight")
            h.HAction.Run("MoveSelParaEnd")
            h.HAction.Run("Delete")
            return True

        return self._call(do)

    def fields(self) -> dict[str, str]:
        """누름틀 이름 → 지금 글."""

        def do(h):
            names = [n for n in str(h.GetFieldList(0, 0) or "").split("\x02") if n]
            return {n: h.GetFieldText(n) for n in dict.fromkeys(names)}

        return self._call(do)

    def put_field(self, name: str, text: str) -> None:
        self._call(lambda h: h.PutFieldText(name, text))

    def page_png(self, page: int, folder) -> bytes:
        """page쪽(1부터)을 그림으로 → PNG 바이트. BMP는 folder에 잠깐 만들고 지운다."""
        from pathlib import Path

        bmp = Path(folder).resolve() / f"page{page}.bmp"  # 상대 경로면 한글이 대화상자를 띄우고 멈춤 (2026-11-11)

        def do(h):
            if not 1 <= page <= h.PageCount:
                raise ValueError(f"쪽 번호는 1~{h.PageCount}")
            h.HAction.Run("Cancel")
            h.SetPos(0, 0, 0)  # 커서가 표 칸·머리말 안이면 그 칸만 그려짐 (2026-11-11 시험: 68×14 그림)
            h.CreatePageImage(str(bmp), page - 1, 80, 24, "bmp")
            return bmp.read_bytes()

        try:
            return bmp_to_png(self._call(do))
        finally:
            bmp.unlink(missing_ok=True)

    def delete_memos(self) -> int:
        """문서의 한글 메모를 모두 지운다. 지운 수."""

        def do(h):
            n, c = 0, h.HeadCtrl
            while c:
                nxt = c.Next
                if c.CtrlID == MEMO and h.DeleteCtrl(c):
                    n += 1
                c = nxt
            return n

        return self._call(do)

    # --- 테스트 전용 ---
    def _type_at_start(self, text: str) -> None:
        def do(h):
            h.HAction.Run("MoveDocBegin")
            self._insert(h, text)

        self._call(do)

    def _user_markpen(self, text: str) -> None:
        def do(h):
            assert self._find(h, text, from_start=True)
            self._markpen(h, (120, 200, 255))
            h.HAction.Run("Cancel")

        self._call(do)

    def _path(self) -> str:
        return self._call(lambda h: h.Path)

    def _is_modified(self) -> bool:
        return self._call(lambda h: bool(h.XHwpDocuments.Item(0).Modified))

    def _close_without_saving(self) -> None:
        def do(h):
            h.XHwpDocuments.Item(0).Close(isDirty=False)
            h.Quit()

        try:
            self._call(do)
        except HwpNotAvailable:
            pass
