"""Endpoints for the Bayesian online weights table and the meta-labeller."""
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, require_admin
from services import bayesian_online_weights as _bow
from services import meta_labeler as _ml

router = APIRouter()


@router.get("/bayesian-online/snapshot")
async def bayesian_snapshot(user=Depends(get_current_user)):
    return await _bow.snapshot()


@router.get("/meta-labeler/info")
async def meta_info(user=Depends(get_current_user)):
    return await _ml.model_info()


@router.post("/meta-labeler/retrain")
async def meta_retrain(user=Depends(require_admin)):
    res = await _ml.train_from_history()
    if res.get("status") == "skipped":
        raise HTTPException(400, res.get("reason", "not enough samples"))
    return res


@router.post("/meta-labeler/score")
async def meta_score(payload: dict, user=Depends(get_current_user)):
    """Diagnostic: pass a signal dict, get back P(win) under the current model."""
    return await _ml.score(payload)
