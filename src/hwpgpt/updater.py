"""새 버전 확인·설치. 공개 레포 GitHub Releases의 latest.json을 본다.

GitHub API(분당·시간당 제한, 학교는 여러 PC가 같은 IP)를 쓰지 않고 릴리스 다운로드 주소만 쓴다.
release 자산: HWP_GPT-Setup-<버전>.exe, latest.json {"version", "notes", "setup", "sha256"}
"""
import hashlib
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__

REPO = "byunhyunjin2/hwp-gpt"
LATEST = f"https://github.com/{REPO}/releases/latest/download/latest.json"


def parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))


def next_version(v: str) -> str:
    """자리마다 0~9: 1.0.8 → 1.0.9 → 1.1.0, 1.9.9 → 2.0.0."""
    a, b, c = parse(v)
    c += 1
    if c > 9:
        b, c = b + 1, 0
    if b > 9:
        a, b = a + 1, 0
    return f"{a}.{b}.{c}"


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"HWP_GPT/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(current: str = __version__, timeout: float = 5) -> dict:
    """{"current", "latest", "notes", "available"}. 인터넷이 안 되면 available=False, error에 이유."""
    try:
        info = json.loads(_get(LATEST, timeout))
    except Exception as e:  # 오프라인·차단·릴리스 없음: 패널은 그대로 쓰게
        return {"current": current, "available": False, "error": str(e)}
    return {"current": current, "latest": info["version"], "notes": info.get("notes", ""),
            "available": parse(info["version"]) > parse(current), "_info": info}


def download(info: dict, on_progress: Callable[[int], None] = lambda pct: None) -> Path:
    """설치 파일을 임시 폴더에 받고 SHA256을 latest.json 값과 대조한다. 다르면 지우고 예외."""
    url = f"https://github.com/{REPO}/releases/download/v{info['version']}/{info['setup']}"
    path = Path(tempfile.gettempdir()) / info["setup"]
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": f"HWP_GPT/{__version__}"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if total:
                on_progress(int(done * 100 / total))
    if h.hexdigest().lower() != info["sha256"].lower():
        path.unlink(missing_ok=True)
        raise ValueError("받은 설치 파일이 릴리스와 다릅니다 (SHA256 불일치)")
    return path


def run_installer(setup: Path) -> None:
    """조용히 설치하고 끝나면 패널을 다시 띄운다(설치 파일의 [Run]). 패널은 이 직후 스스로 닫는다."""
    subprocess.Popen([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | NEW_PROCESS_GROUP
