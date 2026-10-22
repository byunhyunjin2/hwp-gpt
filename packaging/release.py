"""배포 한 번에: 버전 올리기 → 테스트 → 설치 파일 → latest.json → README·CHANGELOG → 커밋·태그·푸시 → GitHub 릴리스.

    python packaging/release.py --notes notes.md --codex <Codex 폴더> [--version 1.0.1] [--python <python.exe>]

notes.md: 사용자에게 보일 짧은 변경 목록 (예: "- 표 금액 점검\n- 업데이트 버튼"). 패널 업데이트 알림에도 그대로 나온다.
버전 규칙: 자리마다 0~9 (1.0.9 다음 1.1.0) — hwpgpt.updater.next_version
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from hwpgpt import __version__  # noqa: E402
from hwpgpt.updater import REPO, next_version  # noqa: E402


def run(*cmd: str) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notes", required=True, type=Path)
    ap.add_argument("--codex", required=True, help="공식 Codex를 푼 폴더 (서명 확인)")
    ap.add_argument("--version", help="지정하지 않으면 다음 버전")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()

    notes = a.notes.read_text(encoding="utf-8").strip()
    new = a.version or next_version(__version__)
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        sys.exit("커밋 안 된 변경이 있습니다. 먼저 커밋하세요.")
    run(a.python, "-m", "pytest", "-q")

    init = ROOT / "src" / "hwpgpt" / "__init__.py"
    init.write_text(re.sub(r'__version__ = ".*"', f'__version__ = "{new}"', init.read_text(encoding="utf-8")), encoding="utf-8")
    readme = ROOT / "README.md"
    block = f"<!-- latest -->\n현재 버전: **v{new}** — [설치 파일 받기](https://github.com/{REPO}/releases/latest)\n\n{notes}\n<!-- /latest -->"
    readme.write_text(re.sub(r"<!-- latest -->.*?<!-- /latest -->", lambda m: block, readme.read_text(encoding="utf-8"), flags=re.S),
                      encoding="utf-8")
    log = ROOT / "CHANGELOG.md"
    s = log.read_text(encoding="utf-8")
    i = s.index("\n## ")
    log.write_text(f"{s[:i]}\n## {datetime.date.today()} — v{new} 배포\n\n{notes}\n{s[i:]}", encoding="utf-8")

    run("powershell", "-ExecutionPolicy", "Bypass", "-File", "packaging\\build.ps1", "-CodexDir", a.codex, "-Python", a.python)
    setup = ROOT / "dist" / f"HWP_GPT-Setup-{new}.exe"
    latest = {"version": new, "notes": notes, "setup": setup.name,
              "sha256": hashlib.sha256(setup.read_bytes()).hexdigest()}
    (ROOT / "dist" / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    run("git", "add", "-A")
    run("git", "commit", "-m", f"release: v{new}")
    run("git", "tag", f"v{new}")
    run("git", "push", "origin", "HEAD", f"v{new}")
    run("gh", "release", "create", f"v{new}", str(setup), str(ROOT / "dist" / "latest.json"), "-R", REPO,
        "--title", f"HWP_GPT v{new}", "--notes-file", str(a.notes))
    print(f"배포 완료: https://github.com/{REPO}/releases/tag/v{new}")


if __name__ == "__main__":
    main()
