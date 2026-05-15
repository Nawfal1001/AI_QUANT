"""Rewards router — user-scoped XP, badges, signal log."""
from datetime import datetime
from fastapi import APIRouter, Depends

from database import db
from middleware.auth import get_current_user
from services.logger import child

log = child("reward")
router = APIRouter()

profiles = db["profiles"]
scol = db["signal_log"]

LEVELS = [
    {"name": "Beginner", "min_xp": 0},
    {"name": "Novice", "min_xp": 100},
    {"name": "Intermediate", "min_xp": 500},
    {"name": "Advanced", "min_xp": 1500},
    {"name": "Expert", "min_xp": 5000},
    {"name": "Master", "min_xp": 15000},
]


def get_level(xp):
    lvl = LEVELS[0]
    for l in LEVELS:
        if xp >= l["min_xp"]:
            lvl = l
    return lvl


async def get_or_create(user_id):
    p = await profiles.find_one({"user_id": user_id})
    if not p:
        p = {
            "user_id": user_id,
            "xp": 0,
            "badges": [],
            "streak": 0,
            "total_signals": 0,
            "correct_signals": 0,
            "created_at": datetime.utcnow().isoformat(),
        }
        await profiles.insert_one(p)
    return p


@router.get("/profile")
async def profile(user=Depends(get_current_user)):
    p = await get_or_create(user["id"])
    xp = p.get("xp", 0)
    lvl = get_level(xp)
    total = p.get("total_signals", 0)
    correct = p.get("correct_signals", 0)
    next_idx = min(LEVELS.index(lvl) + 1, len(LEVELS) - 1)
    nxt = LEVELS[next_idx]
    return {
        **p,
        "_id": str(p.get("_id", "")),
        "level_name": lvl["name"],
        "win_rate": round(correct / max(total, 1) * 100, 1),
        "xp_to_next": max(0, nxt["min_xp"] - xp),
        "next_level": nxt["name"],
    }


@router.post("/daily-login")
async def daily(user=Depends(get_current_user)):
    p = await get_or_create(user["id"])
    today = datetime.utcnow().date().isoformat()
    last = p.get("last_daily")
    if last == today:
        return {"xp_gained": 0, "message": "Already claimed today"}
    await profiles.update_one(
        {"user_id": user["id"]},
        {"$inc": {"xp": 15, "streak": 1}, "$set": {"last_daily": today}},
    )
    return {"xp_gained": 15, "streak": p.get("streak", 0) + 1}


@router.get("/signals-log")
async def slog(limit: int = 50, user=Depends(get_current_user)):
    docs = await scol.find({"user_id": user["id"]}).sort("emitted_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"signals": docs}
