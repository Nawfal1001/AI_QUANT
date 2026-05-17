from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.activity_log import get_logs

router = APIRouter()

@router.get('/')
async def read_logs(scope: str | None = None, entity_id: str | None = None, limit: int = 200, user=Depends(get_current_user)):
    return {
        'logs': await get_logs(scope=scope, user_id=user['id'], entity_id=entity_id, limit=limit)
    }
