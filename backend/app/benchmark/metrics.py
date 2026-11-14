from __future__ import annotations

import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def _rss_tree_bytes(root_pid: int | None = None) -> int:
    try:
        proc = psutil.Process(root_pid) if root_pid else psutil.Process()
    except psutil.Error:
        return 0
    total = 0
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


def memory_pressure_snapshot() -> dict[str, Any]:
    """Best-effort macOS memory pressure (system-wide)."""
    exe = shutil.which("memory_pressure")
    if not exe:
        return {"available": False, "source": "memory_pressure not found"}
    try:
        out = subprocess.check_output([exe], stderr=subprocess.STDOUT, text=True, timeout=4)
    except Exception as e:
        return {"available": False, "source": "memory_pressure", "error": str(e)}
    free_pct = None
    m = re.search(r"System-wide memory free percentage:\s*([0-9]+)%", out)
    if m:
        free_pct = int(m.group(1))
    label = "unknown"
    if free_pct is not None:
        if free_pct >= 20:
            label = "normal"
        elif free_pct >= 10:
            label = "warn"
        else:
            label = "critical"
    # capture swap/page hints if present
    swapins = swapouts = None
    m = re.search(r"Swapins:\s*([0-9]+)", out)
    if m:
        swapins = int(m.group(1))
    m = re.search(r"Swapouts:\s*([0-9]+)", out)
    if m:
        swapouts = int(m.group(1))
    return {
        "available": True,
        "source": "memory_pressure",
        "free_percent_reported": free_pct,
        "level": label,
        "swapins": swapins,
        "swapouts": swapouts,
    }


def gpu_snapshot() -> dict[str, Any]:
    # Reliable GPU/Metal utilization requires privileged tooling (e.g. powermetrics) on macOS.
    # Report honestly rather than fabricating.
    if shutil.which("powermetrics"):
        return {
            "available": False,
            "source": "powermetrics present but requires elevated privileges; not sampled automatically",
            "note": "Run `sudo powermetrics --samplers gpu_power -n 1` manually for a point sample if needed.",
        }
    return {
        "available": False,
        "source": "not available (no powermetrics/unprivileged Metal counters)",
        "note": "GPU/Metal utilization not reliably measurable in this environment; not fabricated.",
    }


def sample_once(data_path: Path | None = None, root_pid: int | None = None) -> dict[str, Any]:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    try:
        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        cpu = None
    try:
        per_core = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:
        per_core = None
    disk = {}
    try:
        usage = shutil.disk_usage(str(data_path or Path.cwd()))
        disk = {
            "total_gb": round(usage.total / 1024**3, 2),
            "free_gb": round(usage.free / 1024**3, 2),
            "used_gb": round((usage.total - usage.free) / 1024**3, 2),
        }
    except Exception:
        pass
    app_rss_mb = round(_rss_tree_bytes(root_pid) / 1048576, 1)
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "cpu_percent": cpu,
        "cpu_per_core": per_core,
        "app_memory": {
            "rss_mb": app_rss_mb,
            "source": "psutil RSS of sampled process tree (app + child processes)",
        },
        "system_memory": {
            "total_mb": round(vm.total / 1048576, 1),
            "available_mb": round(vm.available / 1048576, 1),
            "used_mb": round((vm.total - vm.available) / 1048576, 1),
            "percent": vm.percent,
            "source": "psutil.virtual_memory",
        },
        "swap": {
            "used_mb": round(swap.used / 1048576, 1),
            "total_mb": round(swap.total / 1048576, 1),
            "percent": swap.percent,
            "source": "psutil.swap_memory",
        },
        "memory_pressure": memory_pressure_snapshot(),
        "disk": disk,
        "gpu": gpu_snapshot(),
    }


class MetricSampler:
    def __init__(self, interval: float = 1.0, data_path: Path | None = None, root_pid: int | None = None):
        self.interval = interval
        self.data_path = data_path
        self.root_pid = root_pid
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        while not self._stop.is_set():
            try:
                self.samples.append(sample_once(self.data_path, self.root_pid))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def start(self) -> "MetricSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> list[dict[str, Any]]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        # final sample
        try:
            self.samples.append(sample_once(self.data_path, self.root_pid))
        except Exception:
            pass
        return self.samples

    def summary(self) -> dict[str, Any]:
        if not self.samples:
            return {"samples": 0, "interval_sec": self.interval}
        cpus = [s.get("cpu_percent") for s in self.samples if isinstance(s.get("cpu_percent"), (int, float))]
        rss = [s["app_memory"].get("rss_mb", 0) for s in self.samples if "app_memory" in s]
        sys_pct = [s["system_memory"].get("percent", 0) for s in self.samples if "system_memory" in s]
        sys_used = [s["system_memory"].get("used_mb", 0) for s in self.samples if "system_memory" in s]
        avail = [s["system_memory"].get("available_mb", 0) for s in self.samples if "system_memory" in s]
        swap = [s["swap"].get("used_mb", 0) for s in self.samples if "swap" in s]
        disk_free = [s["disk"].get("free_gb", 0) for s in self.samples if s.get("disk")]
        pressure_levels = [s.get("memory_pressure", {}).get("level") for s in self.samples]
        return {
            "samples": len(self.samples),
            "interval_sec": self.interval,
            "cpu_percent_avg": round(sum(cpus) / len(cpus), 2) if cpus else None,
            "cpu_percent_peak": max(cpus) if cpus else None,
            "app_rss_mb_avg": round(sum(rss) / len(rss), 2) if rss else None,
            "app_rss_mb_peak": max(rss) if rss else None,
            "system_memory_percent_avg": round(sum(sys_pct) / len(sys_pct), 2) if sys_pct else None,
            "system_memory_percent_peak": max(sys_pct) if sys_pct else None,
            "system_memory_used_mb_peak": max(sys_used) if sys_used else None,
            "system_available_mb_min": min(avail) if avail else None,
            "swap_used_mb_peak": max(swap) if swap else None,
            "disk_free_gb_min": min(disk_free) if disk_free else None,
            "memory_pressure_levels_seen": sorted({p for p in pressure_levels if p}),
            "sources": {
                "app_memory": "psutil RSS process tree",
                "system_memory": "psutil.virtual_memory",
                "swap": "psutil.swap_memory",
                "cpu": "psutil.cpu_percent",
                "memory_pressure": "macOS memory_pressure (best-effort)",
                "gpu": "not reliably available without privileged powermetrics",
                "disk": "shutil.disk_usage",
            },
        }