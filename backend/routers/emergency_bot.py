from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.emergency_bot_service import get_config, update_config, evaluate_macro_signals, list_actions

router = APIRouter()

@router.get('/config')
async def config(user=Depends(get_current_user)):
    return await get_config()

@router.patch('/config')
async def patch_config(body: dict, user=Depends(get_current_user)):
    return await update_config(body or {})

@router.post('/evaluate')
async def evaluate(asset_type: str = None, user=Depends(get_current_user)):
    return await evaluate_macro_signals(asset_type=asset_type)

@router.get('/actions')
async def actions(limit: int = 50, user=Depends(get_current_user)):
    return {'actions': await list_actions(limit=limit)}
