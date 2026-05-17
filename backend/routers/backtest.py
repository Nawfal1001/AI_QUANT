"""Backtest router — user-scoped, multi-strategy, async jobs with progress logs and multi-timeframe tests."""
import asyncio
import uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, scope_filter
from services.backtest_engine import fetch_history, run_backtest, run_compare
from services.strategies import list_strategies
from services.logger import child
from database import db

log = child("backtest_router")
router = APIRouter()
col = db["backtests"]
jobs = db["backtest_jobs"]

VALID_INTERVALS = {"1d", "4h", "1h", "15m"}
MAX_BACKTEST_DAYS = 3650


def _now(): return datetime.utcnow().isoformat()


def _intervals(req: dict):
    raw = req.get("intervals") or req.get("timeframes") or req.get("frames")
    if raw is None:
        return [req.get("interval", "1d")]
    if isinstance(raw, str):
        vals = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, list):
        vals = [str(x).strip() for x in raw if str(x).strip()]
    else:
        vals = []
    return vals or [req.get("interval", "1d")]


def _clean_req(req: dict):
    ticker = (req.get("ticker") or "AAPL").upper()
    asset_type = req.get("asset_type", "stock")
    capital = float(req.get("capital", 10000))
    days = int(req.get("days", 365))
    intervals = _intervals(req)
    if capital <= 0 or capital > 1e10: raise HTTPException(400, "capital out of range")
    if days <= 0 or days > MAX_BACKTEST_DAYS: raise HTTPException(400, f"days must be 1..{MAX_BACKTEST_DAYS}")
    bad = [i for i in intervals if i not in VALID_INTERVALS]
    if bad: raise HTTPException(400, f"interval must be one of {sorted(VALID_INTERVALS)}")
    return ticker, asset_type, capital, days, intervals


async def _job_log(job_id, message, level="info", data=None):
    entry = {"ts": _now(), "level": level, "message": message, "data": data or {}}
    await jobs.update_one({"job_id": job_id}, {"$push": {"logs": entry}, "$set": {"updated_at": _now()}})


async def _set_progress(job_id, status=None, progress=None, result=None, error=None):
    update = {"updated_at": _now()}
    if status is not None: update["status"] = status
    if progress is not None: update["progress"] = progress
    if result is not None: update["result"] = result
    if error is not None: update["error"] = error
    await jobs.update_one({"job_id": job_id}, {"$set": update})


async def _run_one(job_id, req, user, ticker, asset_type, capital, days, interval, index=1, total=1):
    strategy = req.get("strategy", "ensemble")
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    await _job_log(job_id, f"[{index}/{total}] Starting {ticker} {asset_type} backtest on {interval} for {days} days.")
    await _job_log(job_id, f"[{interval}] Loading historical candles from configured providers...")
    df = await fetch_history(ticker, asset_type, start, end, interval)
    if df is None or len(df) < 60:
        msg = f"[{interval}] Not enough candle data for {ticker}. Received {0 if df is None else len(df)} bars; need at least 60."
        await _job_log(job_id, msg, "error")
        return {"interval": interval, "error": msg}
    await _job_log(job_id, f"[{interval}] Loaded {len(df)} candles from {str(df['date'].iloc[0])[:10]} to {str(df['date'].iloc[-1])[:10]}.", data={"bars": len(df), "interval": interval})
    await _job_log(job_id, f"[{interval}] Running strategy: {strategy}. Min confidence: {int(req.get('min_confidence', 55))}%")
    result = await run_backtest(
        ticker=ticker, asset_type=asset_type, start_date=start, end_date=end, interval=interval,
        initial_capital=capital, risk_per_trade=float(req.get("risk_per_trade", 0.02)),
        min_confidence=int(req.get("min_confidence", 55)), sl_atr_mult=float(req.get("sl_atr_mult", 2.0)),
        tp_atr_mult=float(req.get("tp_atr_mult", 3.0)), fee_bps=float(req.get("fee_bps", 5)),
        slippage_bps=float(req.get("slippage_bps", 3)), spread_bps=float(req.get("spread_bps", 2)),
        max_hold_bars=int(req.get("max_hold_bars", 30)), strategy=strategy,
        custom_strategy_def=None,
    )
    if "error" in result:
        await _job_log(job_id, f"[{interval}] {result['error']}", "error")
        result["interval"] = interval
        return result
    result["interval"] = interval
    trades = result.get("trades", []) or []
    await _job_log(job_id, f"[{interval}] Produced {len(trades)} trades. Win rate: {result.get('win_rate')}%. Return: {result.get('total_return_pct')}%.")
    for i, t in enumerate(trades[:100], 1):
        await _job_log(job_id, f"[{interval}] Trade {i}: {t.get('side')} entry {t.get('entry_date')} @ {t.get('entry_price')} → exit {t.get('exit_date')} @ {t.get('exit_price')} | PnL ${t.get('pnl')} ({t.get('pnl_pct')}%) | {t.get('exit_reason')}", data={**t, "interval": interval})
    if len(trades) > 100: await _job_log(job_id, f"[{interval}] Showing first 100 trades only. Total trades: {len(trades)}.")
    if len(trades) == 0: await _job_log(job_id, f"[{interval}] No trades opened. Try lowering Min Confidence or changing strategy/timeframe.", "warning")
    try:
        await col.insert_one({**{k: v for k, v in result.items() if k not in ("equity_curve", "trades", "drawdown_curve")}, "user_id": user["id"], "trades_count": result.get("total_trades", 0), "saved_at": _now()})
    except Exception as e:
        await _job_log(job_id, f"[{interval}] Completed but save failed: {e}", "warning")
    return result


async def _run_backtest_job(job_id, req, user):
    try:
        ticker, asset_type, capital, days, intervals = _clean_req(req)
        await _set_progress(job_id, "running", 5)
        await _job_log(job_id, f"Testing {ticker} on {len(intervals)} timeframe(s): {', '.join(intervals)}")
        results = []
        for idx, interval in enumerate(intervals, 1):
            await _set_progress(job_id, "running", 5 + int((idx - 1) / max(1, len(intervals)) * 85))
            results.append(await _run_one(job_id, req, user, ticker, asset_type, capital, days, interval, idx, len(intervals)))
        valid = [r for r in results if "error" not in r]
        if not valid:
            msg = "All timeframe backtests failed. Check logs for provider/candle errors."
            await _job_log(job_id, msg, "error")
            await _set_progress(job_id, "failed", 100, result={"mode":"multi_timeframe","results":results}, error=msg)
            return
        best = sorted(valid, key=lambda r: (float(r.get("total_return_pct", 0)), float(r.get("sharpe", 0)), int(r.get("total_trades", 0))), reverse=True)[0]
        await _job_log(job_id, f"Best timeframe: {best.get('interval')} | Return {best.get('total_return_pct')}% | Sharpe {best.get('sharpe')} | Trades {best.get('total_trades')}", "success")
        final = best if len(intervals) == 1 else {"mode": "multi_timeframe", "ticker": ticker, "asset_type": asset_type, "best_interval": best.get("interval"), "best_result": best, "results": results, "summary": [{"interval": r.get("interval"), "error": r.get("error"), "return": r.get("total_return_pct"), "sharpe": r.get("sharpe"), "win_rate": r.get("win_rate"), "trades": r.get("total_trades"), "max_drawdown": r.get("max_drawdown")} for r in results]}
        await _job_log(job_id, "Backtest job completed.")
        await _set_progress(job_id, "completed", 100, result=final)
    except Exception as e:
        log.exception(f"backtest job failed: {e}")
        await _job_log(job_id, f"Backtest job failed: {e}", "error")
        await _set_progress(job_id, "failed", 100, error=str(e))


@router.get("/strategies")
async def strategies(): return {"strategies": list_strategies()}


@router.post("/jobs")
async def create_job(req: dict, user=Depends(get_current_user)):
    _clean_req(req)
    job_id = str(uuid.uuid4())
    doc = {"job_id": job_id, "user_id": user["id"], "status": "queued", "progress": 0, "logs": [{"ts": _now(), "level": "info", "message": "Queued backtest job.", "data": {}}], "request": req, "created_at": _now(), "updated_at": _now()}
    await jobs.insert_one(doc)
    asyncio.create_task(_run_backtest_job(job_id, req, user))
    return {"job_id": job_id, "status": "queued", "progress": 0}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user=Depends(get_current_user)):
    doc = await jobs.find_one({"job_id": job_id, "user_id": user["id"]})
    if not doc: raise HTTPException(404, "job not found")
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, user=Depends(get_current_user)):
    doc = await jobs.find_one({"job_id": job_id, "user_id": user["id"]}, {"logs": 1, "status": 1, "progress": 1, "error": 1})
    if not doc: raise HTTPException(404, "job not found")
    return {"job_id": job_id, "status": doc.get("status"), "progress": doc.get("progress", 0), "logs": doc.get("logs", []), "error": doc.get("error")}


@router.post("/run")
async def run(req: dict, user=Depends(get_current_user)):
    ticker, asset_type, capital, days, intervals = _clean_req(req)
    interval = intervals[0]
    strategy = req.get("strategy", "ensemble")
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return await run_backtest(ticker=ticker, asset_type=asset_type, start_date=start, end_date=end, interval=interval, initial_capital=capital, risk_per_trade=float(req.get("risk_per_trade", 0.02)), min_confidence=int(req.get("min_confidence", 55)), sl_atr_mult=float(req.get("sl_atr_mult", 2.0)), tp_atr_mult=float(req.get("tp_atr_mult", 3.0)), fee_bps=float(req.get("fee_bps", 5)), slippage_bps=float(req.get("slippage_bps", 3)), spread_bps=float(req.get("spread_bps", 2)), max_hold_bars=int(req.get("max_hold_bars", 30)), strategy=strategy)


@router.post("/compare")
async def compare(req: dict, user=Depends(get_current_user)):
    ticker, asset_type, capital, days, intervals = _clean_req(req)
    raw_strategies = req.get("strategies") or ["trend_follow", "mean_revert", "breakout", "ensemble"]
    if not isinstance(raw_strategies, list) or len(raw_strategies) > 20: raise HTTPException(400, "strategies must be a list of <= 20 names")
    end = datetime.now().strftime("%Y-%m-%d"); start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return await run_compare(ticker=ticker, asset_type=asset_type, start_date=start, end_date=end, interval=intervals[0], initial_capital=capital, strategies=raw_strategies, risk_per_trade=float(req.get("risk_per_trade", 0.02)), min_confidence=int(req.get("min_confidence", 55)))


@router.get("/history")
async def history(limit: int = 20, user=Depends(get_current_user)):
    q = scope_filter(user); docs = await col.find(q).sort("saved_at", -1).limit(limit).to_list(limit)
    for d in docs: d["_id"] = str(d["_id"])
    return {"backtests": docs, "count": len(docs)}


@router.delete("/history")
async def clear_history(user=Depends(get_current_user)):
    q = scope_filter(user); res = await col.delete_many(q); return {"deleted": res.deleted_count}


@router.get("/timeframes")
async def tfs():
    return {"intervals": ["1d", "4h", "1h", "15m"], "presets": [{"label": "Last 90 days", "days": 90}, {"label": "Last 6 months", "days": 180}, {"label": "Last 1 year", "days": 365}, {"label": "Last 2 years", "days": 730}]}
