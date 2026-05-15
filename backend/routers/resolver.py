from fastapi import APIRouter, Depends
from middleware.auth import get_current_user, require_admin
from services.signal_resolver import run_resolver, resolver_stats, start_resolver, stop_resolver

router = APIRouter()


@router.post("/run")
async def run(user=Depends(get_current_user)):
    return await run_resolver()


@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    return await resolver_stats()


# Admin-only: affects the global scheduler thread
@router.post("/start")
async def start(user=Depends(require_admin)):
    return await start_resolver()


@router.post("/stop")
async def stop(user=Depends(require_admin)):
    return await stop_resolver()
