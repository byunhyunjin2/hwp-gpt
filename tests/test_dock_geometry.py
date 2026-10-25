from hwpgpt.dock import dock_layout, embed_rect


def test_embed_sits_at_right_of_edit_area_leaving_scrollbar():
    # 한글 클라이언트 좌표의 문서 영역 (29,214)-(2139,977)
    assert embed_rect((29, 214, 2139, 977), 380) == (1741, 214, 380, 763)


def test_embed_narrow_edit_area_keeps_min_doc_width():
    x, y, w, h = embed_rect((0, 100, 600, 700), 380)
    assert x >= 300 and w == 600 - 18 - x  # 문서가 최소 300px는 보이게 패널을 좁힘

WORK = (0, 0, 1920, 1040)


def test_hwp_and_panel_fill_work_area_without_gap():
    assert dock_layout(WORK) == ((0, 0, 1540, 1040), (1540, 0, 1920, 1040))


def test_narrow_screen_keeps_min_hwp_width():
    hwp, pnl = dock_layout((0, 0, 700, 800))
    assert hwp[2] - hwp[0] >= 400 and hwp[2] == pnl[0]


def test_outer_rect_adds_invisible_borders():
    from hwpgpt.dock import outer_rect

    assert outer_rect((0, 0, 1540, 1040), (7, 0, 7, 7)) == (-7, 0, 1547, 1047)


def test_dragging_panel_left_edge_resizes_hwp():
    from hwpgpt.dock import follow_layout

    hwp, pnl = dock_layout(WORK)  # (0,0,1540,1040), (1540,0,1920,1040)
    new_hwp, p, w = follow_layout(hwp, hwp, (1400, 0, 1920, 1040), pnl, WORK, 380)
    assert new_hwp == (0, 0, 1400, 1040) and p == (1400, 0, 1920, 1040) and w == 520


def test_dragging_hwp_right_edge_resizes_panel():
    from hwpgpt.dock import follow_layout

    hwp, pnl = dock_layout(WORK)
    new_hwp, p, w = follow_layout((0, 0, 1600, 1040), hwp, pnl, pnl, WORK, 380)
    assert new_hwp is None and p == (1600, 0, 1920, 1040) and w == 320
    assert follow_layout((0, 0, 1700, 1040), hwp, pnl, pnl, WORK, 380)[1] == (1320, 0, 1700, 1040)  # 너무 좁아지면 겹침


def test_moving_hwp_panel_follows_with_same_width():
    from hwpgpt.dock import follow_layout

    hwp, pnl = dock_layout(WORK)
    assert follow_layout((100, 50, 1000, 900), hwp, pnl, pnl, WORK, 380) == (None, (1000, 50, 1380, 900), 380)


def test_scaled_panel_fits_screen_at_150_percent():
    # 150%: pywebview 최소 폭 320×1.5 = 480. 패널 폭도 380×1.5 = 570으로 잡아야 화면 안에 들어감
    hwp, pnl = dock_layout((0, 0, 1920, 1040), round(380 * 1.5))
    assert pnl == (1350, 0, 1920, 1040) and pnl[2] - pnl[0] >= 480
