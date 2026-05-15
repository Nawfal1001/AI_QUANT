"""Paper trading router — user-scoped."""
from fastapi import APIRouter, Depends, HTTPException
from middleware.auth import get_current_user
from services import paper_broker

router = APIRouter()


@router.get("/account")
async def account(user=Depends(get_current_user)):
    return await paper_broker.get_account(user["id"])


@router.get("/summary")
async def summary(user=Depends(get_current_user)):
    return await paper_broker.get_summary(user["id"])


@router.post("/reset")
async def reset(payload: dict = None, user=Depends(get_current_user)):
    payload = payload or {}
    starting = float(payload.get("starting_capital", 10000))
    return await paper_broker.reset_account(user["id"], starting)


@router.post("/order")
async def place_order(payload: dict, user=Depends(get_current_user)):
    res = await paper_broker.place_order(
        user_id=user["id"],
        ticker=payload.get("ticker", "").upper(),
        side=payload.get("side", "buy"),
        qty=float(payload.get("qty", 0)),
        order_type=payload.get("order_type", "market"),
        limit_price=payload.get("limit_price"),
        stop_price=payload.get("stop_price"),
        current_price=payload.get("current_price"),
        asset_type=payload.get("asset_type", "stock"),
        skip_freshness=bool(payload.get("skip_freshness", False)),
    )
    if res.get("status") == "rejected":
        raise HTTPException(400, res["reason"])
    return res


@router.get("/orders")
async def orders(status: str = None, limit: int = 50, user=Depends(get_current_user)):
    return {"orders": await paper_broker.get_orders(user["id"], status, limit)}


@router.delete("/order/{order_id}")
async def cancel(order_id: str, user=Depends(get_current_user)):
    return await paper_broker.cancel_order(user["id"], order_id)


@router.get("/positions")
async def positions(user=Depends(get_current_user)):
    return await paper_broker.get_positions(user["id"])
