"""앱 아이콘(문서 위 병아리) 만들기: src/hwpgpt/assets/hwpgpt.ico (16~256px). 개발 PC에서 한 번 실행, 결과 .ico는 레포에 둔다.

    python packaging/make_icon.py      (Pillow 필요)
그림은 64칸 격자 기준 좌표를 16배로 키워 그리고 줄여서 매끈하게 만든다.
"""
from pathlib import Path

from PIL import Image, ImageDraw

S = 16  # 64칸 → 1024px
OUT = Path(__file__).resolve().parent.parent / "src" / "hwpgpt" / "assets" / "hwpgpt.ico"


def p(*xy):
    return [v * S for v in xy]


def draw() -> Image.Image:
    im = Image.new("RGBA", (64 * S, 64 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    blue, line_blue, paper = "#185FA5", "#85B7EB", "#E6F1FB"
    # 문서 (오른쪽 위 접힌 종이)
    page = [(12, 6), (40, 6), (52, 18), (52, 60), (10, 60), (10, 6)]
    d.polygon([v * S for pt in page for v in pt], fill=paper, outline=blue, width=int(2.5 * S))
    d.line(p(40, 6, 40, 18, 52, 18), fill=blue, width=int(2.5 * S), joint="curve")
    # 글줄
    for x2, y in ((33, 22), (39, 29)):
        d.line(p(17, y, x2, y), fill=line_blue, width=3 * S)
        for cx in (17, x2):
            d.ellipse(p(cx - 1.5, y - 1.5, cx + 1.5, y + 1.5), fill=line_blue)
    # 병아리
    d.ellipse(p(21, 34, 47, 60), fill="#FAC775", outline="#BA7517", width=int(2.2 * S))
    for ex in (29, 39):
        d.ellipse(p(ex - 2.4, 42.6, ex + 2.4, 47.4), fill="#2C2C2A")
    d.polygon(p(31, 50, 37, 50, 34, 53), fill="#D85A30", outline="#993C1D", width=int(1.2 * S))
    return im


if __name__ == "__main__":
    big = draw()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.resize((256, 256), Image.LANCZOS).save(OUT, sizes=[(s, s) for s in sizes])
    print("만듦:", OUT)
