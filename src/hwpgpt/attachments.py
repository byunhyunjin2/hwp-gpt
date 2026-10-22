"""채팅창 첨부 파일: 그림은 그대로 ChatGPT에 붙이고, 문서는 글만 뽑아 요청에 함께 넣는다.

지원: 그림(png·jpg·gif·webp·bmp), 워드(docx), 파워포인트(pptx), 한글(hwpx·hwp), 글(txt·md·csv).
문서 글은 파일마다 LIMIT 글자까지 (토큰 절약). 첨부 내용도 문서처럼 내 ChatGPT 계정으로 전송된다.
"""
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree

IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
DOCS = {".docx", ".pptx", ".hwpx", ".hwp", ".txt", ".md", ".csv"}
LIMIT = 15000
DIALOG_FILTER = ("첨부 파일 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.docx;*.pptx;*.hwpx;*.hwp;*.txt;*.md;*.csv)",
                 "모든 파일 (*.*)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraphs(xml: bytes) -> list[str]:
    """워드(w:p/w:t)·파워포인트(a:p/a:t)·한글(hp:p/hp:t) 모두 문단 p 안의 글 t. 표 속 문단은 따로 한 줄."""
    out: list[str] = []

    def walk(el, buf):
        for ch in el:
            name = _local(ch.tag)
            if name == "p":  # 자리를 먼저 잡아 문서 순서 유지 (표 속 문단이 바깥 문단보다 앞에 오지 않게)
                at, mine = len(out), []
                out.append("")
                walk(ch, mine)
                out[at] = "".join(mine)
            elif name == "t":
                buf.append(ch.text or "")
                walk(ch, buf)
            else:
                walk(ch, buf)

    walk(ElementTree.fromstring(xml), [])
    return [s for s in out if s.strip()]


def _zip_text(path: Path, pattern: str) -> str:
    """zip 안에서 pattern에 맞는 XML들을 번호 순서대로 (slide2 < slide10)."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(pattern, n)]
        names.sort(key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
        return "\n".join(line for n in names for line in _paragraphs(z.read(n)))


def hwp_record_text(data: bytes) -> str:
    """HWP 5 본문 레코드에서 문단 글(PARA_TEXT, 태그 67)만. 제어 문자는 건너뛴다 (표·그림 등은 8칸짜리)."""
    lines, i = [], 0
    while i + 4 <= len(data):
        head = struct.unpack_from("<I", data, i)[0]
        tag, size = head & 0x3FF, (head >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            size = struct.unpack_from("<I", data, i)[0]
            i += 4
        if tag == 67:
            chars = struct.unpack_from(f"<{size // 2}H", data, i)
            buf, k = [], 0
            while k < len(chars):
                c = chars[k]
                if c >= 32:
                    buf.append(chr(c))
                    k += 1
                elif c in (0, 10, 13) or 24 <= c <= 31:  # 한 칸짜리 제어 문자 (10 = 줄바꿈)
                    if c == 10:
                        buf.append("\n")
                    k += 1
                else:  # 8칸짜리 (9 = 탭)
                    if c == 9:
                        buf.append("\t")
                    k += 8
            if "".join(buf).strip():
                lines.append("".join(buf))
        i += size
    return "\n".join(lines)


def _hwp_text(path: Path) -> str:
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        flags = struct.unpack_from("<I", ole.openstream("FileHeader").read(), 36)[0]
        if flags & 0x2:
            raise ValueError("암호가 걸린 한글 파일은 읽을 수 없습니다")
        sections = sorted((s for s in ole.listdir() if s[0] == "BodyText"), key=lambda s: int(s[1][7:]))
        if not sections:
            raise ValueError("배포용(보기 전용) 한글 파일은 읽을 수 없습니다")
        out = []
        for s in sections:
            raw = ole.openstream(s).read()
            out.append(hwp_record_text(zlib.decompress(raw, -15) if flags & 0x1 else raw))
        return "\n".join(out)


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".txt", ".md", ".csv"):
        raw = path.read_bytes()
        try:
            return raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return raw.decode("cp949", errors="replace")  # 한글 Windows 메모장 기본
    if ext == ".docx":
        return _zip_text(path, r"word/document\.xml")
    if ext == ".pptx":
        return _zip_text(path, r"ppt/slides/slide\d+\.xml")
    if ext == ".hwpx":
        return _zip_text(path, r"Contents/section\d+\.xml")
    if ext == ".hwp":
        return _hwp_text(path)
    raise ValueError("지원하지 않는 파일 형식입니다")


def prepare(paths: list[str]) -> tuple[list[str], str, list[str]]:
    """(그림 경로들, 요청 앞에 붙일 문서 글, 사용자에게 알릴 말). 읽지 못한 파일은 알림에 이유를 남기고 뺀다."""
    images, blocks, notes = [], [], []
    for s in paths:
        p = Path(s)
        ext = p.suffix.lower()
        if ext in IMAGES:
            images.append(str(p))
            continue
        try:
            text = extract_text(p).strip()
        except Exception as e:  # 깨진 파일·암호·형식: 그 파일만 빼고 요청은 계속
            notes.append(f"{p.name}: {e}")
            continue
        if len(text) > LIMIT:
            notes.append(f"{p.name}: 앞부분 {LIMIT:,}자만 보냈습니다 (전체 {len(text):,}자)")
            text = text[:LIMIT]
        blocks.append(f"[첨부 파일: {p.name}]\n{text}")
    return images, "\n\n".join(blocks), notes
