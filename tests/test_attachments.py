"""첨부 파일 글 뽑기. 시험 파일은 가짜 내용으로 코드에서 만든다."""
import struct
import zipfile

from hwpgpt import attachments as at

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
HP = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)
    return path


def test_docx_paragraphs_and_table_cells(tmp_path):
    xml = (f'<w:document {W}><w:body><w:p><w:r><w:t>2026학년도 </w:t></w:r><w:r><w:t>계획</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>홍길동</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    p = _zip(tmp_path / "a.docx", {"word/document.xml": xml})
    assert at.extract_text(p) == "2026학년도 계획\n홍길동"


def test_pptx_slides_in_number_order(tmp_path):
    slide = lambda t: f'<p:sld xmlns:p="x" {A}><a:p><a:r><a:t>{t}</a:t></a:r></a:p></p:sld>'
    p = _zip(tmp_path / "a.pptx", {"ppt/slides/slide10.xml": slide("열"), "ppt/slides/slide2.xml": slide("둘")})
    assert at.extract_text(p) == "둘\n열"


def test_hwpx_nested_table_paragraph_is_its_own_line(tmp_path):
    xml = (f'<hs:sec xmlns:hs="s" {HP}><hp:p><hp:run><hp:t>예산</hp:t><hp:tbl><hp:tc><hp:p><hp:run><hp:t>합계</hp:t>'
           '</hp:run></hp:p></hp:tc></hp:tbl></hp:run></hp:p></hs:sec>')
    p = _zip(tmp_path / "a.hwpx", {"Contents/section0.xml": xml})
    assert at.extract_text(p) == "예산\n합계"


def test_hwp_record_text_skips_controls():
    # 탭(8칸) → \t, 표 제어(11, 8칸)는 건너뜀, 문단 끝(13)
    units = [ord(c) for c in "연도"] + [9] + [0] * 7 + [11] + [0] * 7 + [ord("끝"), 13]
    body = struct.pack(f"<{len(units)}H", *units)
    rec = struct.pack("<I", 67 | (len(body) << 20)) + body
    other = struct.pack("<I", 66 | (4 << 20)) + b"\0" * 4  # 다른 레코드는 무시
    assert at.hwp_record_text(other + rec) == "연도\t끝"


def test_prepare_splits_images_docs_and_reports_problems(tmp_path):
    img = tmp_path / "사진.PNG"
    img.write_bytes(b"\x89PNG")
    txt = tmp_path / "메모.txt"
    txt.write_text("가" * (at.LIMIT + 10), encoding="utf-8")
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"zz")
    images, block, notes = at.prepare([str(img), str(txt), str(bad)])
    assert images == [str(img)]
    assert block.startswith("[첨부 파일: 메모.txt]\n") and len(block) < at.LIMIT + 40
    assert any("앞부분" in n for n in notes) and any("x.zip" in n for n in notes)
