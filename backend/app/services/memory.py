from __future__ import annotations

import threading
import time

import psutil


def _rss_bytes() -> int:
    total = 0
    proc = psutil.Process()
    try:
        total += proc.memory_info().rss
        for child in proc.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except psutil.Error:
        pass
    return total


def system_snapshot() -> dict:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    try:
        load = psutil.getloadavg()
    except Exception:
        load = (0.0, 0.0, 0.0)
    return {
        "total_mb": round(vm.total / 1048576),
        "available_mb": round(vm.available / 1048576),
        "used_mb": round((vm.total - vm.available) / 1048576),
        "percent": vm.percent,
        "swap_used_mb": round(swap.used / 1048576),
        "swap_total_mb": round(swap.total / 1048576),
        "process_rss_mb": round(_rss_bytes() / 1048576, 1),
        "load_avg": [round(x, 2) for x in load],
        "cpu_count": psutil.cpu_count(logical=True),
    }


class MemorySampler:
    """Samples combined RSS of this process + media subprocesses while a job runs."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self):
        while not self._stop.is_set():
            mb = _rss_bytes() / 1048576
            if mb > self.peak_mb:
                self.peak_mb = mb
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> int:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        return int(round(self.peak_mb))

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False


def wait_for_memory(threshold_percent: int = 92, timeout: float = 60.0) -> bool:
    """Best-effort guard before a heavy stage; returns False if pressure stays high."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        vm = psutil.virtual_memory()
        if vm.percent < threshold_percent:
            return True
        time.sleep(1.0)
    return False
