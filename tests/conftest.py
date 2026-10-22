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
        out = []
        for e in edits:
            n = self.text.count(e.find)
            self.text = self.text.replace(e.find, e.replace)
            self.applied.append(e)
            out.append((e, n))
        return out

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
