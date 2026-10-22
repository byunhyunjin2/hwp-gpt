"""요청 1회의 결과(바꾼 곳·확인 항목·문서 종류)를 JSONL로 남긴다. 도구 서버가 쓰고 패널이 읽는다."""
import json
from pathlib import Path
from typing import Literal

Kind = Literal["applied", "check", "doc_type"]


def write(path: Path, kind: Kind, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "data": data}, ensure_ascii=False) + "\n")


def read(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
