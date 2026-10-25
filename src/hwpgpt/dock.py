"""패널을 한글 창 오른쪽에 붙이고 따라다니게 한다."""
import threading
import time
from typing import Callable

Rect = tuple[int, int, int, int]  # left, top, right, bottom
MIN_HWP_W = 400
MIN_PANEL_W = 320  # 패널 창 min_size와 같게


def dock_layout(work_area: Rect, panel_w: int = 380) -> tuple[Rect, Rect]:
    """(한글 위치, 패널 위치) — 둘이 화면(작업 영역)을 빈틈없이 채운다. 한글 왼쪽, 패널 오른쪽. 보이는 테두리 기준."""
    wl, wt, wr, wb = work_area
    r = max(wl + MIN_HWP_W, wr - panel_w)
    return (wl, wt, r, wb), (r, wt, wr, wb)


def follow_layout(hwp: Rect, hwp_last: Rect | None, pnl: Rect, placed: Rect | None, work: Rect,
                  w: int) -> tuple[Rect | None, Rect, int]:
    """따라다니기 한 번: (한글을 옮길 자리 또는 None, 패널 자리, 패널 폭). placed = 지난번 패널 자리.
    둘이 붙어 있을 때 맞닿은 경계를 어느 쪽에서 끌든 다른 쪽이 같이 줄고 늘어난다."""
    if placed and pnl[2] == placed[2] and pnl[0] != placed[0]:  # 패널 왼쪽 끝을 끌어 폭을 바꿈 → 한글 오른쪽을 맞춤
        r = max(hwp[0] + MIN_HWP_W, pnl[0])
        return (hwp[0], hwp[1], r, hwp[3]), (r, hwp[1], pnl[2], hwp[3]), pnl[2] - r
    if (hwp_last and placed and hwp[0] == hwp_last[0] and hwp[2] != hwp_last[2] and placed[0] == hwp_last[2]
            and placed[2] - hwp[2] >= MIN_PANEL_W):  # 한글 오른쪽 끝을 끌면 패널 폭이 바뀜 (패널 오른쪽은 그대로)
        return None, (hwp[2], hwp[1], placed[2], hwp[3]), placed[2] - hwp[2]
    p = (hwp[2], hwp[1], hwp[2] + w, hwp[3])  # 옮기면 오른쪽에 딱 붙어 따라감
    if p[2] > work[2]:  # 화면 오른쪽 끝이라 옆에 못 붙으면 한글 안쪽 오른쪽에 겹쳐 둠
        p = (hwp[2] - w, hwp[1], hwp[2], hwp[3])
    return None, p, w


def outer_rect(visible: Rect, margins: Rect) -> Rect:
    """보이는 테두리를 visible에 맞추려면 창에 줄 좌표 (Win10/11 창의 투명 크기조절 테두리만큼 넓힘)."""
    return visible[0] - margins[0], visible[1] - margins[1], visible[2] + margins[2], visible[3] + margins[3]


def _visible_rect(hwnd: int) -> Rect:
    """DWM이 그리는 실제 창 테두리 (GetWindowRect는 투명 테두리를 포함해 틈이 생김)."""
    import ctypes
    from ctypes import wintypes

    r = wintypes.RECT()
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)):  # DWMWA_EXTENDED_FRAME_BOUNDS
        import win32gui

        return win32gui.GetWindowRect(hwnd)
    return r.left, r.top, r.right, r.bottom


def _place_visible(hwnd: int, visible: Rect, flags: int) -> None:
    import win32gui

    w, v = win32gui.GetWindowRect(hwnd), _visible_rect(hwnd)
    l, t, r, b = outer_rect(visible, (v[0] - w[0], v[1] - w[1], w[2] - v[2], w[3] - v[3]))
    win32gui.SetWindowPos(hwnd, 0, l, t, r - l, b - t, flags)


def place_right(hwnd: int, panel_w: int = 380) -> None:
    """한글이 아직 없을 때: 패널을 붙을 자리(화면 오른쪽 끝, 위아래 꽉)에 미리 둔다."""
    import win32con

    _place_visible(hwnd, dock_layout(_work_area(hwnd), panel_w)[1], win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)


def embed_rect(edit: Rect, panel_w: int = 380, scrollbar: int = 18, min_doc: int = 300) -> tuple[int, int, int, int]:
    """한글 안에 넣을 때 패널 위치 (x, y, w, h). edit = 문서 영역(한글 클라이언트 좌표).
    문서 영역 오른쪽, 세로 스크롤바 왼쪽. 문서가 min_doc만큼은 보이게 패널을 좁힌다."""
    l, t, r, b = edit
    x = max(r - scrollbar - panel_w, l + min_doc)
    return x, t, r - scrollbar - x, b - t


def set_window_long(hwnd: int, index: int, value: int) -> None:
    """win32gui.SetWindowLong은 다른 스레드 창의 응답을 기다리는 동안 GIL을 쥐고 있어
    패널 화면 스레드와 교착된다 (MISTAKES M-007). ctypes는 호출 중 GIL을 푼다."""
    import ctypes

    ctypes.windll.user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
    ctypes.windll.user32.SetWindowLongPtrW(hwnd, index, value)


def find_hwp_window() -> int | None:
    """보이는 한글 최상위 창 (한글 2022는 WPF 창: HwndWrapper[Hwp.exe;;...])."""
    import win32gui

    found: list[int] = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h).startswith(("HwndWrapper[Hwp.exe", "HwpFrame")):
            found.append(h)

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def _work_area(hwnd: int) -> Rect:
    import win32api
    import win32con

    mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    return tuple(win32api.GetMonitorInfo(mon)["Work"])


class Docker:
    """ponytail: 0.15초 간격 위치 확인(polling). 끊김이 느껴지면 SetWinEventHook으로 교체."""

    def __init__(self, panel_hwnd: int, on_hwp_gone: Callable[[], None], panel_w: int = 380) -> None:
        self.panel = panel_hwnd
        self.on_gone = on_hwp_gone
        self.w = panel_w
        self.hwp: int | None = None
        self._orig: Rect | None = None
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def attach(self, hwp_hwnd: int) -> None:
        import win32con
        import win32gui

        self.detach(restore=False)
        self.hwp = hwp_hwnd
        # 패널을 한글 소유 창으로: 한글 위에 뜨고 한글과 함께 최소화됨
        set_window_long(self.panel, win32con.GWL_HWNDPARENT, hwp_hwnd)
        if not win32gui.IsIconic(hwp_hwnd):  # 최소화 상태면 복원될 때 _follow가 배치
            self._first_layout()
        self._stop.clear()
        self._t = threading.Thread(target=self._follow, daemon=True)
        self._t.start()

    def _first_layout(self) -> None:
        """처음 붙일 때: 최대화면 풀고, 원래 크기를 기억하고, 필요하면 한글을 줄여 패널 자리를 만든다."""
        import win32con
        import win32gui

        h = self.hwp
        if win32gui.GetWindowPlacement(h)[1] == win32con.SW_SHOWMAXIMIZED:
            win32gui.ShowWindow(h, win32con.SW_RESTORE)
        self._orig = win32gui.GetWindowRect(h)
        new_hwp, pnl = dock_layout(_work_area(h), self.w)
        _place_visible(h, new_hwp, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        self._place(pnl)

    def _place(self, pnl: Rect) -> None:
        import win32con
        import win32gui

        _place_visible(self.panel, pnl, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)

    def _follow(self) -> None:
        import win32con
        import win32gui

        last = placed = None
        while not self._stop.wait(0.15):
            if not win32gui.IsWindow(self.hwp):
                self.hwp = None
                self.on_gone()
                return
            if win32gui.IsIconic(self.hwp):
                continue  # 소유 창이라 패널도 함께 숨겨짐
            if self._orig is None:  # 최소화 상태로 붙었다가 이제 복원됨
                self._first_layout()
            rect, pnl = _visible_rect(self.hwp), _visible_rect(self.panel)
            if rect == last and pnl == placed:
                continue
            new_hwp, p, self.w = follow_layout(rect, last, pnl, placed, _work_area(self.hwp), self.w)
            if new_hwp and new_hwp != rect:
                _place_visible(self.hwp, new_hwp, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
                rect = _visible_rect(self.hwp)
            if p != pnl:
                self._place(p)
            win32gui.ShowWindow(self.panel, win32con.SW_SHOWNOACTIVATE)
            last, placed = rect, _visible_rect(self.panel)  # 실제 자리를 기억 (DPI 반올림으로 1px 어긋나도 다음에 오해하지 않게)

    def detach(self, restore: bool = True) -> None:
        import win32gui

        self._stop.set()
        if self._t:
            self._t.join(1)
        if restore and self.hwp and self._orig and win32gui.IsWindow(self.hwp):
            l, t, r, b = self._orig
            win32gui.MoveWindow(self.hwp, l, t, r - l, b - t, True)
        self.hwp, self._orig, self._t = None, None, None


class EmbedDocker:
    """한글 창 안(문서 영역 오른쪽 회색 여백)에 패널을 자식 창으로 넣는다. Docker와 같은 사용법.

    비공식 방식: 다른 프로세스 창을 부모로 삼는다. 한글을 닫으면 자식인 패널 창도 함께 사라진다.
    ponytail: 0.2초 간격으로 문서 영역 크기 확인.
    """

    def __init__(self, panel_hwnd: int, on_hwp_gone: Callable[[], None], panel_w: int = 380) -> None:
        self.panel = panel_hwnd
        self.on_gone = on_hwp_gone
        self.w = panel_w
        self.hwp: int | None = None
        self._style: int | None = None
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def attach(self, hwp_hwnd: int) -> None:
        import win32con
        import win32gui

        self.detach()
        self.hwp = hwp_hwnd
        self._style = win32gui.GetWindowLong(self.panel, win32con.GWL_STYLE)
        child = (self._style & ~(win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_THICKFRAME)) | win32con.WS_CHILD
        set_window_long(self.panel, win32con.GWL_STYLE, child)
        win32gui.SetParent(self.panel, hwp_hwnd)
        self._stop.clear()
        self._t = threading.Thread(target=self._follow, daemon=True)
        self._t.start()

    def _edit_rect(self) -> Rect | None:
        import win32gui

        edit = win32gui.FindWindowEx(self.hwp, 0, "HwpMainEditWnd", None)
        if not edit:
            return None
        l, t, r, b = win32gui.GetWindowRect(edit)
        return (*win32gui.ScreenToClient(self.hwp, (l, t)), *win32gui.ScreenToClient(self.hwp, (r, b)))

    def _follow(self) -> None:
        import win32con
        import win32gui

        last = None
        while not self._stop.wait(0.2):
            if not win32gui.IsWindow(self.hwp):
                self.hwp = None
                self.on_gone()
                return
            rect = self._edit_rect()
            if rect and rect != last:
                last = rect
                x, y, w, h = embed_rect(rect, self.w)
                win32gui.SetWindowPos(self.panel, win32con.HWND_TOP, x, y, w, h, win32con.SWP_SHOWWINDOW)

    def detach(self, restore: bool = True) -> None:
        import win32con
        import win32gui

        self._stop.set()
        if self._t:
            self._t.join(1)
        if self._style is not None and win32gui.IsWindow(self.panel):
            win32gui.SetParent(self.panel, 0)
            set_window_long(self.panel, win32con.GWL_STYLE, self._style)
        self.hwp, self._style, self._t = None, None, None


def wait_for_hwp(stop: threading.Event, interval: float = 2.0) -> int | None:
    while not stop.is_set():
        h = find_hwp_window()
        if h:
            return h
        time.sleep(interval)
    return None
