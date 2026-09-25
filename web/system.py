"""Real system metrics for the HUD. Values are measured, never simulated."""

from __future__ import annotations

import os
import platform
import time

try:
    import psutil  # type: ignore
    _PSUTIL = True
    psutil.cpu_percent(interval=None)  # prime: the first reading is always 0.0
    _PROC = psutil.Process(os.getpid())
except ImportError:  # metrics are optional
    _PSUTIL = False
    _PROC = None

_BOOT = time.time()


def system_metrics() -> dict:
    data: dict = {
        "platform": f"{platform.system()} {platform.machine()}",
        "uptime_s": round(time.time() - _BOOT),
        "metrics_available": _PSUTIL,
        "cpu_percent": None,
        "memory_percent": None,
        "memory_used_gb": None,
        "memory_total_gb": None,
        "process_memory_mb": None,
    }
    if not _PSUTIL:
        return data
    vm = psutil.virtual_memory()
    data.update(
        cpu_percent=round(psutil.cpu_percent(interval=None), 1),
        memory_percent=round(vm.percent, 1),
        memory_used_gb=round((vm.total - vm.available) / 1024**3, 1),
        memory_total_gb=round(vm.total / 1024**3, 1),
        process_memory_mb=round(_PROC.memory_info().rss / 1024**2),
    )
    return data
