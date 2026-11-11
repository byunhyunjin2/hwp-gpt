import pytest

from hwpgpt.hwp_bridge import HwpNotAvailable


class FakeBridge:
    """HwpBridge 대역: 문자열 문서 위에서 동작하고 호출을 기록한다."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.applied: list = []
        self.red: list[str] = []

    def connect(self) -> bool:
        return True

    def read_text(self) -> str:
        return self.text

    def apply(self, edits):
        """e.nths가 있으면 그 번째 것만. 자리는 [0, 0, 글자 위치]로 흉내."""
        import re

        out = []
        for e in edits:
            idxs = [m.start() for m in re.finditer(re.escape(e.find), self.text)]
            pick = [i for k, i in enumerate(idxs) if e.nths is None or k in e.nths]
            for i in reversed(pick):
                self.text = self.text[:i] + e.replace + self.text[i + len(e.find):]
            self.applied.append(e)
            out.append((e, len(pick), [[0, 0, i] for i in pick]))
        return out

    def undo(self, applied):
        ok = 0
        for a in reversed(applied):
            for _, _, i in reversed(a["pos"]):
                if self.text[i:i + len(a["replace"])] == a["replace"]:
                    self.text = self.text[:i] + a["find"] + self.text[i + len(a["replace"]):]
                    ok += 1
        return ok, 0

    def redo(self, applied):
        ok = 0
        for a in applied:
            for _, _, i in a["pos"]:
                if self.text[i:i + len(a["find"])] == a["find"]:
                    self.text = self.text[:i] + a["replace"] + self.text[i + len(a["find"]):]
                    ok += 1
        return ok, 0

    def table_rows(self, action, find, nth=0, count=1, until="", until_nth=0, to_end=False):
        self.rows = getattr(self, "rows", []) + [(action, find, until, to_end)]
        return None if find in self.text else "표 칸 안의 글을 찾지 못함"

    # 서식·표·넣기: 호출만 기록 (한글 동작은 test_hwp_bridge_live)
    undo_spec = None
    table_width_before = 40000

    def shapes_of(self, find, nths, char_keys, para_keys):
        return [[k, {key: 0 for key in char_keys}, {key: 0 for key in para_keys}] for k in (nths or [0])]

    def _log(self, *a):
        self.calls = getattr(self, "calls", []) + [a]

    def format_text(self, find, nths, char, para):
        self._log("format", find, nths, char, para)
        return self.text.count(find) if nths is None else len(nths)

    def read_table(self, anchor, nth=0):
        return {"cells": [["A1", "이름"], ["B1", "연락처"], ["A2", "홍길동"], ["B2", "010-0000-0000"]]}

    def cell_text(self, anchor, nth, addr):
        return dict(self.read_table(anchor)["cells"]).get(addr)

    def table_op(self, op, nth=0):
        self._log("table", op, nth)
        return None

    def paragraph_of(self, find, nth=0):
        return next((ln for ln in self.text.splitlines() if find in ln), None)

    def insert(self, item, nth=0, picture=""):
        self._log("insert", item, nth, picture)
        return None

    def fields(self):
        return getattr(self, "field_values", {})

    def put_field(self, name, text):
        self.field_values[name] = text

    def unmark(self, texts):
        self.unmarked = list(texts)

    def mark_check(self, text: str, nth: int | None = None) -> bool:
        self.red.append(text)
        return text in self.text


class DeadBridge:
    def __getattr__(self, name):
        def fail(*a, **k):
            raise HwpNotAvailable("한글 문서를 열어 주세요")

        return fail


@pytest.fixture
def fake_bridge():
    return FakeBridge()


@pytest.fixture
def dead_bridge():
    return DeadBridge()
