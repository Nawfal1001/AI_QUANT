"""
Autonomous trading bots router.
All routes user-scoped. Runner control endpoints are admin-only.
"""
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, require_admin
from services import bots as bot_service
from services import bot_runner

router = APIRouter()


@router.get("/")
async def list_mine(user=Depends(get_current_user)):
    return {"bots": await bot_service.list_bots(user["id"])}


@router.get("/runner-status")
async def runner_status(user=Depends(get_current_user)):
    return {"running": bot_runner.is_running()}


@router.get("/schedules")
async def schedules(user=Depends(get_current_user)):
    """Available schedule options for the bot wizard."""
    return {"schedules": list(bot_service.SCHEDULES.keys()), "sizing_modes": bot_service.SIZING_MODES}


# Admin-only — controls the global runner thread.
# Keep these static routes before /{bot_id}; otherwise FastAPI treats
# "runner" as a bot_id and the start/stop endpoints become unreachable.
@router.post("/runner/start")
async def runner_start(user=Depends(require_admin)):
    return await bot_runner.start_runner()


@router.post("/runner/stop")
async def runner_stop(user=Depends(require_admin)):
    return await bot_runner.stop_runner()


@router.get("/{bot_id}")
async def get_one(bot_id: str, user=Depends(get_current_user)):
    doc = await bot_service.get_bot(user["id"], bot_id)
    if not doc:
        raise HTTPException(404, "Bot not found")
    return doc


@router.post("/")
async def create(data: dict, user=Depends(get_current_user)):
    res = await bot_service.create_bot(user["id"], data)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


@router.patch("/{bot_id}")
async def update(bot_id: str, data: dict, user=Depends(get_current_user)):
    res = await bot_service.update_bot(user["id"], bot_id, data)
    if "error" in res:
        if res["error"] == "bot not found":
            raise HTTPException(404, res["error"])
        raise HTTPException(400, res["error"])
    return res


@router.delete("/{bot_id}")
async def delete(bot_id: str, user=Depends(get_current_user)):
    res = await bot_service.delete_bot(user["id"], bot_id)
    if "error" in res:
        if res["error"] == "bot not found":
            raise HTTPException(404, res["error"])
        raise HTTPException(400, res["error"])
    return res


@router.post("/{bot_id}/toggle")
async def toggle(bot_id: str, data: dict, user=Depends(get_current_user)):
    enabled = bool(data.get("enabled", False))
    res = await bot_service.toggle_bot(user["id"], bot_id, enabled)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


@router.get("/{bot_id}/executions")
async def executions(bot_id: str, limit: int = 50, user=Depends(get_current_user)):
    bot = await bot_service.get_bot(user["id"], bot_id)
    if not bot:
        raise HTTPException(404, "Bot not found")
    return {"executions": await bot_service.get_executions(user["id"], bot_id, limit)}
