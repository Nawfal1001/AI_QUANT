"""
Strategy Lab router — CRUD + test for user-defined strategies.
"""
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user
from services import user_strategies
from services.custom_strategy import REFERENCE, validate_strategy, validate_expression
from services.advanced_strategy_templates import BAYESIAN_VOTING_TEMPLATES

router = APIRouter()


@router.get("/reference")
async def reference(user=Depends(get_current_user)):
    """Returns the list of variables, functions, and example rules users can use."""
    return REFERENCE


@router.get("/templates")
async def templates(user=Depends(get_current_user)):
    return {"templates": BAYESIAN_VOTING_TEMPLATES}


@router.get("/")
async def list_mine(user=Depends(get_current_user)):
    return {"strategies": await user_strategies.list_user_strategies(user["id"])}


@router.get("/{strategy_id}")
async def get_one(strategy_id: str, user=Depends(get_current_user)):
    doc = await user_strategies.get_user_strategy(user["id"], strategy_id)
    if not doc:
        raise HTTPException(404, "Strategy not found")
    return doc


@router.post("/")
async def create_or_update(data: dict, user=Depends(get_current_user)):
    res = await user_strategies.save_user_strategy(user["id"], data)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


@router.delete("/{strategy_id}")
async def delete_one(strategy_id: str, user=Depends(get_current_user)):
    res = await user_strategies.delete_user_strategy(user["id"], strategy_id)
    if "error" in res:
        raise HTTPException(400, res["error"])
    if res.get("deleted") == 0:
        raise HTTPException(404, "Strategy not found")
    return res


@router.post("/validate")
async def validate(data: dict, user=Depends(get_current_user)):
    """Validate a strategy (without saving)."""
    return validate_strategy(data)


@router.post("/validate-rule")
async def validate_one_rule(data: dict, user=Depends(get_current_user)):
    """Validate a single rule expression."""
    expr = data.get("when", "")
    return validate_expression(expr)


@router.post("/test")
async def test(data: dict, user=Depends(get_current_user)):
    """Dry-run a strategy on recent history without saving."""
    strategy = data.get("strategy", {})
    ticker = data.get("ticker", "AAPL").upper()
    asset_type = data.get("asset_type", "stock")
    days = int(data.get("days", 180))
    res = await user_strategies.test_user_strategy(strategy, ticker, asset_type, days)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res
