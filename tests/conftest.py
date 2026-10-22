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

    def unmark(self, texts):
        self.unmarked = list(texts)

    def mark_check(self, text: str) -> bool:
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
