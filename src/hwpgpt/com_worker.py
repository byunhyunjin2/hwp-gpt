"""COM 호출을 전용 스레드 하나에서만 실행한다 (COM 객체는 만든 스레드에서만 써야 함)."""
import queue
import threading
from concurrent.futures import Future
from typing import Callable, TypeVar

T = TypeVar("T")


class ComWorker:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._t = threading.Thread(target=self._run, name="hwp-com", daemon=True)
        self._t.start()

    def _run(self) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            while (item := self._q.get()) is not None:
                fn, fut = item
                try:
                    fut.set_result(fn())
                except BaseException as e:  # 호출한 쪽으로 그대로 전달
                    fut.set_exception(e)
        finally:
            pythoncom.CoUninitialize()

    def call(self, fn: Callable[[], T], timeout: float = 30) -> T:
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout)

    def stop(self) -> None:
        self._q.put(None)
        self._t.join(5)
