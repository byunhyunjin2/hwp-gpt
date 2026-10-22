"""set_window_long이 다른 스레드 창을 기다리는 동안 GIL을 풀어 주는지 (패널 '응답 없음' 교착, MISTAKES M-007).
GIL을 쥐면 시험 프로세스 전체가 멈추므로 별도 프로세스에서 돌리고 시간 초과로 판정한다."""
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("win32gui")

PROBE = r"""
import ctypes, sys, threading
sys.path.insert(0, sys.argv[1])
import win32con, win32gui
from hwpgpt.dock import set_window_long

k32 = ctypes.windll.kernel32
ready, ev, box = threading.Event(), k32.CreateEventW(None, True, False, None), {}

def owner():  # 창을 만들고 메시지를 처리하지 않은 채 대기 (= 바쁜 패널 화면 스레드)
    box["h"] = win32gui.CreateWindow("STATIC", "probe", win32con.WS_OVERLAPPED, 0, 0, 100, 100, 0, 0, 0, None)
    ready.set()
    k32.WaitForSingleObject(ev, 0xFFFFFFFF)
    win32gui.PumpWaitingMessages()

threading.Thread(target=owner, daemon=True).start()
ready.wait()
h = box["h"]
ex = win32gui.GetWindowLong(h, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED
threading.Thread(target=set_window_long, args=(h, win32con.GWL_EXSTYLE, ex), daemon=True).start()
started = threading.Event()
threading.Thread(target=started.set).start()  # GIL이 풀려 있어야 새 스레드가 시작된다
assert started.wait(2)
k32.SetEvent(ev)
print("ok")
"""


def test_set_window_long_releases_gil():
    src = str(Path(__file__).resolve().parent.parent / "src")
    r = subprocess.run([sys.executable, "-c", PROBE, src], capture_output=True, text=True, timeout=20)
    assert r.stdout.strip() == "ok", r.stderr
