from datetime import date

from hwpgpt.rules import Edit, check_budget, format_date, is_protected, parse_date, validate_edits


def test_date_formats_keep_style_and_fix_weekday():
    for src, new, want in [
        ("2026. 10. 31.(토)", date(2027, 10, 30), "2027. 10. 30.(토)"),
        ("2026.10.31(토)", date(2027, 10, 31), "2027.10.31(일)"),
        ("2026년 10월 31일(토)", date(2027, 10, 31), "2027년 10월 31일(일)"),
    ]:
        d, tpl = parse_date(src)
        assert d == date(2026, 10, 31) and format_date(new, tpl) == want


def test_parse_date_rejects_non_date():
    assert parse_date("202699001") is None


def test_year_inside_id_or_amount_is_protected():
    assert is_protected("202699001", "학번 202699001 홍길동")
    assert is_protected("2,026,000", "예산 2,026,000원") is None  # 금액은 고칠 수 있음


def test_plain_year_is_not_protected():
    assert is_protected("2026학년도", "2026학년도 운영계획서") is None


def test_personal_info_paragraph_is_protected():
    assert is_protected("010-1234-5678", "담당자 연락처 010-1234-5678")


def test_wrong_weekday_edit_rejected():
    ok, checks = validate_edits(
        "기간: 2026. 10. 31.(토)", [Edit("2026. 10. 31.(토)", "2027. 10. 31.(토)", "연도")]
    )
    assert ok == [] and "요일" in checks[0].note


def test_correct_weekday_edit_accepted():
    e = Edit("2026. 10. 31.(토)", "2027. 10. 31.(일)", "연도")
    ok, checks = validate_edits("기간: 2026. 10. 31.(토)", [e])
    assert ok == [e] and checks == []


def test_edit_touching_id_rejected():
    ok, checks = validate_edits("학번 202699001", [Edit("2026", "2027", "연도")])
    assert ok == [] and checks


def test_year_edit_skips_id_but_allowed_elsewhere_is_rejected_whole():
    # "2026"이 학번 안에도 있으면 전체 치환은 학번까지 바꾸므로 거부해야 한다
    ok, checks = validate_edits("2026학년도 / 학번 202699001", [Edit("2026", "2027", "연도")])
    assert ok == [] and checks


def test_edit_not_found_rejected():
    ok, checks = validate_edits("본문", [Edit("없는말", "x", "")])
    assert ok == [] and checks


def test_edit_inside_personal_paragraph_rejected():
    ok, checks = validate_edits(
        "담당자 연락처 010-1234-5678", [Edit("010-1234-5678", "010-0000-0000", "")]
    )
    assert ok == [] and checks


def test_amount_edit_allowed_whatever_reason():
    assert len(validate_edits("식비 450,000원", [Edit("450,000", "500,000", "")])[0]) == 1


def test_budget_mismatch_flagged():
    assert check_budget("사업 예산 2,345,670원 ... 합계 3,700,000원")
    assert not check_budget("사업 예산 2,345,670원 ... 합계 2,345,670원")


def test_budget_without_numbers_not_flagged():
    assert check_budget("예산 계획(안)") == []


def test_changed_years_from_applied_pairs():
    from hwpgpt.rules import changed_years

    pairs = [("2026학년도", "2027학년도"), ("2026. 10. 31.(토)", "2027. 10. 31.(일)"), ("1,880,670원", "1,930,670원")]
    assert changed_years(pairs) == {"2026"}


def test_leftover_years_finds_missed_dates_skips_ids():
    from hwpgpt.rules import leftover_years

    doc = "2027학년도 계획\r\n신청일 2026년  9월  1일\r\n학번 202699001\r\n2026년 실적"
    out = leftover_years(doc, {"2026"})
    assert [(c["text"], c["nth"]) for c in out] == [("2026년", 0), ("2026년", 1)]
    assert "2026년 9월 1일" in out[0]["note"]


def test_budget_flags_only_grand_total_once():
    doc = "사업 예산 5,000,000원\n재료비 합계 1,111,000원\n합계 2,345,670원"
    assert [c.text for c in check_budget(doc)] == ["2,345,670"]
    assert check_budget("사업 예산 2,345,670원\n소계 합계 1,111,000원\n합계 2,345,670원") == []


def test_resolve_text_restores_document_spacing():
    from hwpgpt.rules import resolve_text

    doc = "신청일\r\n2026년  9월  1일\r\n"
    assert resolve_text("2026년 9월 1일", doc) == "2026년  9월  1일"
    assert resolve_text("없는 문구", doc) == "없는 문구"


def test_check_math_finds_wrong_calculation():
    from hwpgpt.rules import check_math

    doc = "식비·다과\r\n- 20,000원×10명\r\n= 200,000원\r\n- 30,000원×2명×2회\r\n= 100,000원"
    out = check_math(doc)
    assert [c.text for c in out] == ["100,000"] and "120,000" in out[0].note


def test_table_sum_mismatch_found():
    from hwpgpt.rules import check_table_sums

    doc = "연번\r\n예산(원)\r\n산출내역\r\n1\r\n200,000\r\n식비\r\n2\r\n700,000\r\n3\r\n100,000\r\n합계\r\n1,234,560원"
    out = check_table_sums(doc)
    assert [c.text for c in out] == ["1,234,560"] and "1,000,000" in out[0].note
    assert check_table_sums(doc.replace("1,234,560원", "1,000,000원")) == []


def test_strip_unit():
    from hwpgpt.rules import strip_unit

    assert strip_unit("1,234,560원") == "1,234,560" and strip_unit("1,234,560") is None and strip_unit("원") is None


def test_table_sum_accepts_price_and_amount_columns():
    from hwpgpt.rules import check_table_sums

    # 연번·수량·단가·금액. 2번처럼 단가에 쉼표가 없는 칸도 있음
    doc = ("품명\r\n수량\r\n단가\r\n금액\r\n1\r\n2\r\n3,000\r\n6,000\r\n2\r\n500\r\n168\r\n84,000"
           "\r\n3\r\n1\r\n4,000\r\n4,000\r\n합계\r\n94,000원")
    assert check_table_sums(doc) == []
    out = check_table_sums(doc.replace("94,000원", "75,000원"))  # 합계만 바꾸고 물품은 그대로인 경우
    assert "물품 금액(수량×단가)의 합 94,000원" in out[0].note


def test_short_number_needs_location_and_line_context_avoids_false_id():
    doc = "학번 202699001\r\n참여시간\r\n6\r\n만족도 4.0"
    ok, checks = validate_edits(doc, [Edit("6", "8", "")])  # 위치 없는 "6"은 문서 곳곳(학번 등)이 바뀜
    assert ok == [] and "줄 번호" in checks[0].note
    ok, checks = validate_edits(doc, [Edit("6", "8", "", nths=(1,), context=("6",))])  # 표 칸 "6"만
    assert len(ok) == 1 and checks == []
    ok, checks = validate_edits(doc, [Edit("6", "8", "", nths=(), context=())])
    assert ok == [] and "지정한 줄에 없음" in checks[0].note
    assert len(validate_edits(doc, [Edit("만족도 4.0", "만족도 5.0", "")])[0]) == 1  # 긴 문구는 위치 없이도


def test_para_kind_groups_same_bullets():
    from hwpgpt.rules import para_kind, same_kind_neighbor

    assert para_kind("  - 행사 안내") == para_kind("  - 다른 줄") != para_kind("- 행사 안내")  # 앞 공백도 봄
    assert para_kind("1. 목적") == para_kind("12. 기대효과") and para_kind("가. 일정") == para_kind("나. 장소")
    assert para_kind("○ 추진 배경") == para_kind("○ 추진 내용")
    assert para_kind("평생학습축제 운영 계획") is None  # 글머리 없으면 맞추지 않음
    near = [(4, "□ 개요"), (6, " ○ 장소: OO구"), (3, " ○ 일시: 2027. 10. 30.")]
    assert same_kind_neighbor(" ○ 대상: 주민 누구나", near) == 6
    assert same_kind_neighbor("제목 줄", near) is None
