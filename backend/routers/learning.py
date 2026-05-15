"""Learning & Self-Improvement endpoints — auth required."""
from fastapi import APIRouter, Depends

from middleware.auth import get_current_user, require_admin
from services.meta_learner import train_meta_learner, predict_signal_quality, get_model_info
from services.rl_agent import get_rl_stats, get_action, update_q
from services.confluence_memory import get_top_setups, get_memory_stats, get_historical_accuracy
from services.wfo_service import run_wfo, get_wfo_history, start_wfo_scheduler
from services.hyper_tuner import run_tuning, get_best_params, start_tuning_scheduler
from services.defensive_mode import check_defensive_mode, get_state, update_thresholds, calculate_recent_pnl

router = APIRouter()


# Meta Learner
@router.post("/meta/train")
async def train_meta(min_samples: int = 50, user=Depends(get_current_user)):
    return await train_meta_learner(min_samples)


@router.get("/meta/info")
async def meta_info(user=Depends(get_current_user)):
    return await get_model_info()


@router.post("/meta/predict")
async def meta_predict(signal_dict: dict, user=Depends(get_current_user)):
    return await predict_signal_quality(signal_dict)


# RL Agent
@router.get("/rl/stats")
async def rl_stats(user=Depends(get_current_user)):
    return await get_rl_stats()


@router.post("/rl/get-action")
async def rl_action(d: dict, user=Depends(get_current_user)):
    return await get_action(
        d.get("regime", "RANGING"), d.get("confidence", 50),
        d.get("atr_pct", 1.0), d.get("recent_pnl", 0),
        d.get("open_count", 0), d.get("epsilon", 0.05),
    )


@router.post("/rl/update")
async def rl_update(d: dict, user=Depends(get_current_user)):
    return await update_q(d["state_key"], d["action_idx"], d["reward"], d.get("next_state_key"))


# Confluence Memory
@router.get("/memory/top")
async def memory_top(limit: int = 20, min_samples: int = 5, user=Depends(get_current_user)):
    return {"setups": await get_top_setups(limit, min_samples)}


@router.get("/memory/stats")
async def memory_stats(user=Depends(get_current_user)):
    return await get_memory_stats()


@router.post("/memory/lookup")
async def memory_lookup(d: dict, user=Depends(get_current_user)):
    return await get_historical_accuracy(
        d.get("indicators", []), d.get("regime", "RANGING"),
        d.get("entropy_tradeable", True), d.get("min_samples", 5),
    )


# WFO
@router.post("/wfo/run")
async def wfo_run(window_days: int = 90, n_candidates: int = 30, user=Depends(get_current_user)):
    return await run_wfo(window_days, n_candidates)


@router.get("/wfo/history")
async def wfo_hist(limit: int = 20, user=Depends(get_current_user)):
    return {"history": await get_wfo_history(limit)}


# Admin-only: scheduler is a global thread
@router.post("/wfo/scheduler/start")
async def wfo_start(user=Depends(require_admin)):
    return await start_wfo_scheduler()


# Hyper Tuner
@router.post("/tuner/run")
async def tuner_run(n_trials: int = 40, user=Depends(get_current_user)):
    return await run_tuning(n_trials)


@router.get("/tuner/best")
async def tuner_best(user=Depends(get_current_user)):
    return await get_best_params()


@router.post("/tuner/scheduler/start")
async def tuner_start(user=Depends(require_admin)):
    return await start_tuning_scheduler()


# Defensive Mode
@router.get("/defensive/check")
async def def_check(user=Depends(get_current_user)):
    return await check_defensive_mode()


@router.get("/defensive/state")
async def def_state(user=Depends(get_current_user)):
    return await get_state()


@router.patch("/defensive/thresholds")
async def def_thresholds(d: dict, user=Depends(get_current_user)):
    return await update_thresholds(d)


@router.get("/defensive/pnl-24h")
async def pnl_24h(hours: int = 24, user=Depends(get_current_user)):
    return await calculate_recent_pnl(hours)
