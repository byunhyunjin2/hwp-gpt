"""%APPDATA%\\HWP_GPT 아래 경로를 한곳에서 정한다."""
import os
from pathlib import Path


def app_dir() -> Path:
    p = Path(os.environ.get("APPDATA") or Path.home()) / "HWP_GPT"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sub(name: str) -> Path:
    p = app_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def codex_home() -> Path:
    return _sub("codex")


def memory_dir() -> Path:
    return _sub("memory")


def work_dir() -> Path:
    return _sub("work")


def session_dir() -> Path:
    return _sub("sessions")


def pasted_dir() -> Path:
    """붙여넣은 스크린샷을 첨부용 파일로 두는 곳 (패널을 켤 때 비움)."""
    return _sub("pasted")
