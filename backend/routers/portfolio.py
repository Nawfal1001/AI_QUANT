"""Portfolio router — user-scoped."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

from database import db
from middleware.auth import get_current_user, scope_filter
from services.logger import child

log = child("portfolio")
router = APIRouter()
col = db["portfolio"]


@router.get("/")
async def get_portfolio(user=Depends(get_current_user)):
    q = scope_filter(user)
    docs = await col.find(q).to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"portfolio": docs, "count": len(docs)}


@router.post("/position")
async def add_position(p: dict, user=Depends(get_current_user)):
    ticker = (p.get("ticker") or "").upper().strip()
    if not ticker:
        raise HTTPException(400, "ticker required")
    try:
        qty = float(p.get("qty", 0))
        entry_price = float(p.get("entry_price", 0))
    except (ValueError, TypeError):
        raise HTTPException(400, "qty and entry_price must be numeric")
    if qty <= 0 or entry_price <= 0:
        raise HTTPException(400, "qty and entry_price must be positive")

    doc = {
        "user_id": user["id"],
        "ticker": ticker,
        "asset_type": p.get("asset_type", "stock"),
        "qty": qty,
        "entry_price": entry_price,
        "added_at": datetime.utcnow().isoformat(),
    }
    await col.replace_one({"user_id": user["id"], "ticker": ticker}, doc, upsert=True)
    log.info(f"user {user['id']} added position {ticker} qty={qty} @ ${entry_price}")
    return {"status": "added", "ticker": ticker}


@router.delete("/position/{ticker}")
async def remove_position(ticker: str, user=Depends(get_current_user)):
    res = await col.delete_one({"user_id": user["id"], "ticker": ticker.upper()})
    if res.deleted_count == 0:
        raise HTTPException(404, f"Position {ticker} not found")
    return {"status": "removed", "ticker": ticker.upper()}
