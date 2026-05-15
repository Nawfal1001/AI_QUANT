"""Alerts router — user-scoped."""
from fastapi import APIRouter, Depends, HTTPException
from middleware.auth import get_current_user
from services.alert_service import send_telegram, create_alert, get_alerts, delete_alert

router = APIRouter()


@router.post("/create")
async def create(a: dict, user=Depends(get_current_user)):
    return await create_alert(
        user_id=user["id"],
        ticker=a.get("ticker", ""),
        condition=a.get("condition", ""),
        threshold=a.get("threshold", 0),
        channels=a.get("channels", ["telegram"]),
        asset_type=a.get("asset_type", "stock"),
    )


@router.get("/list")
async def list_alerts(user=Depends(get_current_user)):
    return {"alerts": await get_alerts(user["id"])}


@router.delete("/{alert_id}")
async def delete(alert_id: str, user=Depends(get_current_user)):
    res = await delete_alert(user["id"], alert_id)
    if "error" in res:
        raise HTTPException(400, res["error"])
    if res.get("deleted", 0) == 0:
        raise HTTPException(404, "Alert not found")
    return res


@router.post("/test/telegram")
async def test(user=Depends(get_current_user)):
    return await send_telegram(f"✅ TradeAI test from <b>{user['username']}</b>")
