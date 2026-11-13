"""한글 없이 도는 hwp_bridge 순수 함수."""
import struct
import zlib

from hwpgpt.hwp_bridge import _replace_nths, bmp_to_png


def test_replace_nths_only_chosen():
    assert _replace_nths("가 가 가", "가", "나", {1}) == "가 나 가"
    assert _replace_nths("예산A 예산B", "예산", "사업 예산", {0, 1}) == "사업 예산A 사업 예산B"


def test_bmp_to_png_bottom_up_bgr():
    w, h = 2, 2  # 아래 줄(파랑, 초록) 위 줄(빨강, 흰색) — BMP는 아래 줄부터, BGR, 줄마다 4바이트 맞춤
    rows = [bytes([255, 0, 0, 0, 255, 0]) + b"\0\0", bytes([0, 0, 255, 255, 255, 255]) + b"\0\0"]
    bmp = b"BM" + struct.pack("<I4xI", 54 + 16, 54) + struct.pack("<IiiHHI", 40, w, h, 1, 24, 0) + b"\0" * 20 + b"".join(rows)
    png = bmp_to_png(bmp)
    assert png.startswith(b"\x89PNG") and struct.unpack(">II", png[16:24]) == (2, 2)
    idat = png[png.index(b"IDAT") + 4: png.index(b"IEND") - 8]
    raw = zlib.decompress(idat)
    assert raw == b"\0" + bytes([255, 0, 0, 255, 255, 255]) + b"\0" + bytes([0, 0, 255, 0, 255, 0])


def test_changed_spot_finds_which_body_spot_changed():
    from hwpgpt.hwp_bridge import _changed_spot

    before = "가 2025학년도 나 2025학년도"
    left = [[2, 0], [12, 1]]
    assert _changed_spot(before, "가 2026학년도 나 2025학년도", "2025학년도", "2026학년도", left) == 0
    assert _changed_spot(before, "가 2025학년도 나 2026학년도", "2025학년도", "2026학년도", left) == 1
    assert _changed_spot(before, before, "2025학년도", "2026학년도", left) is None  # 머리말 등 본문 밖


def test_wrapped_when_find_comes_back_in_same_list():
    from hwpgpt.hwp_bridge import _wrapped

    last = {0: (3, 10), 7: (0, 2)}
    assert _wrapped(last, (0, 0, 5)) and _wrapped(last, (0, 3, 10)) and _wrapped(last, (7, 0, 1))
    assert not _wrapped(last, (0, 3, 11)) and not _wrapped(last, (9, 0, 0))
