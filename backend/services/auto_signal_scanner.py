"""
Automatic Universe Signal Scanner.

Scans every broker configured in the platform, ranks each broker-compatible
universe, generates full signals for the best candidates, and stores the latest
actionable opportunities for dashboard/API consumption.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import db
from services.logger import child
from services.signal_service import generate_signal
from services.symbol_scanner import scan_universe, normalize_broker_id, infer_asset_type_for_broker, BROKER_DEFAULT_ASSET_TYPE

log = child("auto_signal_scanner")

col_auto_signals = db["auto_signals"]
col_auto_signal_runs = db["auto_signal_runs"]
_TASK: Optional[asyncio.Task] = None
_RUNNING = False

FUSION_ASSET_TYPES = ["stock", "forex", "crypto"]
BROKER_MULTI_ASSETS = {"fusion": FUSION_ASSET_TYPES}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> List[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


async def _configured_brokers() -> List[str]:
    explicit = _csv_env("AUTO_SIGNAL_BROKERS")
    brokers = [normalize_broker_id(x) for x in explicit] if explicit else []
    brokers.extend([normalize_broker_id(x) for x in BROKER_DEFAULT_ASSET_TYPE.keys()])
    brokers.append("fusion")
    try:
        docs = await db["bots"].distinct("broker")
        brokers.extend([normalize_broker_id(x) for x in docs if x])
    except Exception:
        pass
    try:
        docs = await db["broker_accounts"].distinct("broker")
        brokers.extend([normalize_broker_id(x) for x in docs if x])
    except Exception:
        pass
    out = []
    for b in brokers:
        if b and b not in out:
            out.append(b)
    return out


def _asset_types_for_broker(broker: str) -> List[str]:
    broker = normalize_broker_id(broker)
    raw = _csv_env(f"AUTO_SIGNAL_ASSET_TYPES_{broker.upper()}")
    if broker == "fusion":
        raw = raw or _csv_env("FUSION_ASSET_TYPES") or FUSION_ASSET_TYPES
    if raw:
        return [x.lower() for x in raw]
    if broker in BROKER_MULTI_ASSETS:
        return BROKER_MULTI_ASSETS[broker]
    return [infer_asset_type_for_broker(broker)]


def _signal_direction(signal: str) -> str:
    s = str(signal or "HOLD").upper()
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return "HOLD"


async def scan_auto_signals(broker_id: str = "paper", asset_type: Optional[str] = None, timeframe: str = "swing", interval: str = "1d", scan_limit: int = 20, signal_limit: int = 10, min_confidence: float = 55, use_ai: bool = True, discover: bool = True) -> Dict[str, Any]:
    broker = normalize_broker_id(broker_id)
    asset = asset_type or infer_asset_type_for_broker(broker)
    started = datetime.utcnow().isoformat()
    scan = await scan_universe(asset_type=asset, interval=interval, limit=scan_limit, use_ai=use_ai, discover=discover, broker_id=broker)
    candidates = scan.get("selected", [])[:scan_limit]
    generated: List[Dict[str, Any]] = []
    for candidate in candidates:
        ticker = candidate.get("ticker")
        if not ticker:
            continue
        try:
            sig = await generate_signal(ticker, asset, timeframe, use_ai=use_ai)
            sig.update({"broker": broker, "scanner_score": candidate.get("score"), "scanner_reason": candidate.get("reason"), "auto_signal": True, "created_at": datetime.utcnow().isoformat(), "direction": _signal_direction(sig.get("signal"))})
            generated.append(sig)
        except Exception as e:
            generated.append({"ticker": ticker, "asset_type": asset, "broker": broker, "signal": "HOLD", "confidence": 0, "error": str(e), "created_at": datetime.utcnow().isoformat(), "direction": "HOLD"})
    actionable = [x for x in generated if x.get("direction") in {"BUY", "SELL"} and float(x.get("confidence", 0) or 0) >= min_confidence]
    actionable.sort(key=lambda x: (float(x.get("confidence", 0) or 0), float(x.get("scanner_score", 0) or 0)), reverse=True)
    best = actionable[:signal_limit]
    run = {"broker": broker, "asset_type": asset, "timeframe": timeframe, "interval": interval, "scan_limit": scan_limit, "signal_limit": signal_limit, "min_confidence": min_confidence, "use_ai": use_ai, "discover": discover, "started_at": started, "finished_at": datetime.utcnow().isoformat(), "candidate_count": len(candidates), "generated_count": len(generated), "actionable_count": len(actionable), "best": best}
    await col_auto_signal_runs.insert_one(dict(run))
    await col_auto_signals.delete_many({"broker": broker, "asset_type": asset, "timeframe": timeframe})
    if best:
        await col_auto_signals.insert_many([{**x, "timeframe": timeframe, "broker": broker, "asset_type": asset} for x in best])
    run.pop("_id", None)
    return run


async def scan_all_auto_signals() -> Dict[str, Any]:
    brokers = await _configured_brokers()
    timeframe = os.getenv("AUTO_SIGNAL_TIMEFRAME", "swing")
    interval = os.getenv("AUTO_SIGNAL_INTERVAL", "1d")
    scan_limit = int(os.getenv("AUTO_SIGNAL_SCAN_LIMIT", "20"))
    signal_limit = int(os.getenv("AUTO_SIGNAL_LIMIT", "10"))
    min_confidence = float(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE", "55"))
    use_ai = _env_bool("AUTO_SIGNAL_USE_AI", True)
    discover = _env_bool("AUTO_SIGNAL_DISCOVER_UNIVERSE", True)
    runs = []
    for broker in brokers:
        for asset in _asset_types_for_broker(broker):
            try:
                runs.append(await scan_auto_signals(broker_id=broker, asset_type=asset, timeframe=timeframe, interval=interval, scan_limit=scan_limit, signal_limit=signal_limit, min_confidence=min_confidence, use_ai=use_ai, discover=discover))
            except Exception as e:
                log.warning(f"auto signal scan failed for {broker}/{asset}: {e}")
                runs.append({"broker": broker, "asset_type": asset, "error": str(e), "finished_at": datetime.utcnow().isoformat()})
    return {"brokers": brokers, "runs": runs, "finished_at": datetime.utcnow().isoformat()}


async def latest_auto_signals(broker_id: Optional[str] = None, asset_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if broker_id:
        q["broker"] = normalize_broker_id(broker_id)
    if asset_type:
        q["asset_type"] = asset_type
    docs = await col_auto_signals.find(q).sort([("confidence", -1), ("created_at", -1)]).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def _loop(interval_sec: int):
    global _RUNNING
    _RUNNING = True
    log.info(f"auto_signal_scanner started interval={interval_sec}s")
    while _RUNNING:
        try:
            await scan_all_auto_signals()
        except Exception as e:
            log.warning(f"auto signal scanner loop failed: {e}")
        await asyncio.sleep(interval_sec)


async def start_auto_signal_scanner(interval_sec: Optional[int] = None):
    global _TASK
    if _TASK and not _TASK.done():
        return
    if not _env_bool("AUTO_SIGNAL_SCANNER_ENABLED", True):
        log.info("auto_signal_scanner disabled by AUTO_SIGNAL_SCANNER_ENABLED=false")
        return
    interval = interval_sec or int(os.getenv("AUTO_SIGNAL_SCAN_INTERVAL_SEC", "900"))
    _TASK = asyncio.create_task(_loop(interval))


def stop_auto_signal_scanner():
    global _RUNNING, _TASK
    _RUNNING = False
    if _TASK:
        _TASK.cancel()
        _TASK = None
