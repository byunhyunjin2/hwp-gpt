"""열린 한글 문서를 읽고, 바꾸고, 형광펜으로 표시한다. 문서를 저장하지 않는다.

연결은 ROT의 `!HwpObject*` 항목으로만 한다 — GetActiveObject는 사용자가 연 한글도 못 찾고,
Dispatch는 숨은 새 한글을 띄운다 (docs/spike-results.md, MISTAKES M-003).
"""
from typing import Callable

from .com_worker import ComWorker
from .rules import Edit, strip_unit

YELLOW = (255, 240, 0)   # 바꾼 곳
RED = (255, 120, 120)    # 안 바꿈·확인


class HwpNotAvailable(Exception):
    """한글이 없거나 연결이 끊김."""


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
                limit = h.GetTextFile("UNICODE", "").count(e.find)
                want = None if e.nths is None else set(e.nths)
                k, pos = 0, []
                found = self._find(h, e.find, from_start=True)
                while found and k < limit:
                    if want is None or k in want:
                        self._insert(h, e.replace)  # 선택 영역을 바꿈
                        for _ in range(len(e.replace)):
                            h.HAction.Run("MoveSelLeft")
                        pos.append(list(h.GetPos()))  # 바꾼 글자의 시작 자리
                        self._markpen(h, YELLOW)
                    h.HAction.Run("Cancel")
                    k += 1
                    found = self._find(h, e.find, from_start=False)
                if pos:
                    self._marks[e.replace] = YELLOW
                out.append((e, len(pos), pos))
            return out

        return self._call(do)

    def undo(self, applied: list[dict]) -> tuple[int, int]:
        """apply가 바꾼 자리를 거꾸로(마지막 것부터) 원래 글로 되돌린다. 그사이 사용자가 고친 자리는 건너뛴다.
        applied = [{"find", "replace", "pos": [[list, para, pos], ...]}]. (되돌린 수, 건너뛴 수)"""

        def do(h):
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

        return self._call(do)

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

    def mark_check(self, text: str) -> bool:
        def do(h):
            for t in filter(None, (text, strip_unit(text))):  # 표 칸의 '원'이 떨어져 있으면 숫자만으로
                if self._mark_all(h, t, RED, h.GetTextFile("UNICODE", "").count(t)):
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
