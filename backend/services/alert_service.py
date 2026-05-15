"""Alert service — user-scoped, with Telegram/email/webhook delivery."""
import os
from datetime import datetime

import httpx

from database import db
from services.logger import child

log = child("alerts")
acol = db["alerts"]


async def send_telegram(msg: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    cid = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not cid:
        return {"error": "Telegram not configured (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env)"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": cid, "text": msg, "parse_mode": "HTML"},
            )
            data = r.json()
            return {"ok": data.get("ok", False), **data}
    except Exception as e:
        log.exception(f"send_telegram failed: {e}")
        return {"error": str(e)}


async def create_alert(user_id: str, ticker: str, condition: str, threshold: float, channels: list, asset_type: str = "stock"):
    doc = {
        "user_id": user_id,
        "ticker": (ticker or "").upper().strip(),
        "condition": condition,
        "threshold": float(threshold),
        "channels": channels or ["telegram"],
        "asset_type": asset_type,
        "active": True,
        "triggered": False,
        "created_at": datetime.utcnow().isoformat(),
    }
    r = await acol.insert_one(doc)
    log.info(f"alert created by {user_id}: {ticker} {condition} {threshold}")
    return {"id": str(r.inserted_id), "status": "created"}


async def get_alerts(user_id: str, include_inactive: bool = False):
    q = {"user_id": user_id}
    if not include_inactive:
        q["active"] = True
    docs = await acol.find(q).sort("created_at", -1).to_list(200)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def delete_alert(user_id: str, alert_id: str):
    from bson import ObjectId
    try:
        oid = ObjectId(alert_id)
    except Exception:
        return {"error": "Invalid alert_id"}
    res = await acol.delete_one({"_id": oid, "user_id": user_id})
    return {"deleted": res.deleted_count}
