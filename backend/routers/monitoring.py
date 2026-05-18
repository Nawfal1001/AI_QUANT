from __future__ import annotations

import os
import sys
import time
from fastapi import APIRouter, Depends

from middleware.auth import get_current_user

router = APIRouter()
STARTED_AT = time.time()


def _bytes_mb(v: float) -> float:
    return round(float(v) / 1024 / 1024, 2)


def _process_memory():
    try:
        import psutil
        p = psutil.Process(os.getpid())
        m = p.memory_info()
        return {"rss_mb": _bytes_mb(m.rss), "vms_mb": _bytes_mb(m.vms), "percent": round(p.memory_percent(), 2), "threads": p.num_threads(), "open_files": len(p.open_files()), "connections": len(p.net_connections(kind="inet"))}
    except Exception as e:
        import resource
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            rss_mb = _bytes_mb(rss_kb)
        else:
            rss_mb = round(rss_kb / 1024, 2)
        return {"rss_mb": rss_mb, "vms_mb": None, "percent": None, "threads": None, "open_files": None, "connections": None, "note": f"psutil unavailable: {str(e)[:80]}"}


def _system_memory():
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {"total_mb": _bytes_mb(vm.total), "used_mb": _bytes_mb(vm.used), "available_mb": _bytes_mb(vm.available), "percent": vm.percent}
    except Exception as e:
        return {"total_mb": None, "used_mb": None, "available_mb": None, "percent": None, "note": f"psutil unavailable: {str(e)[:80]}"}


def _service_statuses():
    services = []
    checks = [
        ("Auto signal scanner", "services.auto_signal_scanner", "_scanner_task"),
        ("Signal resolver", "services.signal_resolver", "_resolver_task"),
        ("AutoTrader scheduler", "services.auto_trader", "_scheduler_task"),
        ("Bot runner", "services.bot_runner", "_runner_task"),
        ("WFO scheduler", "services.wfo_service", "_wfo_task"),
        ("Hyper tuner", "services.hyper_tuner", "_tuning_task"),
        ("Emergency macro runner", "services.emergency_macro_runner", "_runner_task"),
    ]
    for name, module, attr in checks:
        try:
            import importlib
            mod = importlib.import_module(module)
            task = getattr(mod, attr, None)
            running = bool(task and not task.done()) if hasattr(task, "done") else bool(task)
            services.append({"name": name, "module": module, "running": running, "memory_mb": None, "note": "async service in app process"})
        except Exception as e:
            services.append({"name": name, "module": module, "running": False, "memory_mb": None, "note": str(e)[:80]})
    return services


def _top_imports():
    names = ["pandas", "numpy", "sklearn", "torch", "tensorflow", "yfinance", "motor", "pymongo", "google", "psutil"]
    loaded = []
    for n in names:
        loaded.append({"name": n, "loaded": any(k == n or k.startswith(n + ".") for k in sys.modules.keys())})
    return loaded


@router.get("/system")
async def system_monitor(user=Depends(get_current_user)):
    return {
        "uptime_sec": int(time.time() - STARTED_AT),
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "process": _process_memory(),
        "system": _system_memory(),
        "services": _service_statuses(),
        "loaded_libraries": _top_imports(),
        "env": {
            "render": bool(os.getenv("RENDER")),
            "environment": os.getenv("ENVIRONMENT", "development"),
            "ai_max_calls_per_day": os.getenv("AI_MAX_CALLS_PER_DAY", "15"),
            "ai_cache_ttl_seconds": os.getenv("AI_SIGNAL_CACHE_TTL_SECONDS", "14400"),
        },
    }
