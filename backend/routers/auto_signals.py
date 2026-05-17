import asyncio, uuid
from datetime import datetime
from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.auto_signal_scanner import latest_auto_signals, scan_all_auto_signals, scan_auto_signals
router = APIRouter()
JOBS = {}
def _new_job(kind='all'):
    jid=str(uuid.uuid4())
    JOBS[jid]={"job_id":jid,"kind":kind,"status":"queued","progress":0,"created_at":datetime.utcnow().isoformat(),"updated_at":datetime.utcnow().isoformat(),"logs":[{"ts":datetime.utcnow().isoformat(),"level":"info","message":"Auto signal scan queued"}],"result":None,"error":None}
    return jid
async def _log(jid,msg,level='info'):
    j=JOBS.get(jid)
    if not j: return
    j["logs"].append({"ts":datetime.utcnow().isoformat(),"level":level,"message":msg}); j["logs"]=j["logs"][-300:]; j["updated_at"]=datetime.utcnow().isoformat()
def _set(jid,**kw):
    j=JOBS.get(jid)
    if j: j.update(kw); j["updated_at"]=datetime.utcnow().isoformat()
async def _run_all(jid):
    try:
        _set(jid,status='running',progress=5); await _log(jid,'Starting full auto-universe scan')
        res=await scan_all_auto_signals()
        runs=res.get('runs',[]) if isinstance(res,dict) else []
        stored=sum(int(r.get('stored_count',0) or 0) for r in runs if isinstance(r,dict))
        actionable=sum(int(r.get('actionable_count',0) or 0) for r in runs if isinstance(r,dict))
        await _log(jid,f'Finished scan: runs={len(runs)} actionable={actionable} stored={stored}','success')
        _set(jid,status='completed',progress=100,result=res)
    except Exception as e:
        await _log(jid,f'Auto scan failed: {e}','error'); _set(jid,status='failed',progress=100,error=str(e))
async def _run_one(jid,broker,asset_type,timeframe,interval,use_ai):
    try:
        _set(jid,status='running',progress=5); await _log(jid,f'Starting scan {broker}/{asset_type} {timeframe} {interval}')
        res=await scan_auto_signals(broker_id=broker,asset_type=asset_type,timeframe=timeframe,interval=interval,use_ai=use_ai)
        await _log(jid,f"Finished scan {broker}/{asset_type}: stored={res.get('stored_count')} actionable={res.get('actionable_count')}",'success')
        _set(jid,status='completed',progress=100,result=res)
    except Exception as e:
        await _log(jid,f'Scan failed: {e}','error'); _set(jid,status='failed',progress=100,error=str(e))
@router.get('/latest')
async def latest(broker: str = None, asset_type: str = None, limit: int = 50, user=Depends(get_current_user)):
    return {"signals": await latest_auto_signals(broker_id=broker, asset_type=asset_type, limit=limit)}
@router.post('/scan')
async def scan_now(user=Depends(get_current_user)):
    jid=_new_job('all'); asyncio.create_task(_run_all(jid)); return {"job_id":jid,"status":"queued","progress":0}
@router.get('/scan/jobs/{job_id}')
async def scan_job(job_id: str, user=Depends(get_current_user)):
    return JOBS.get(job_id) or {"job_id":job_id,"status":"not_found","progress":100,"logs":[],"error":"job not found"}
@router.post('/scan/{broker}/{asset_type}')
async def scan_one(broker: str, asset_type: str, timeframe: str = 'swing', interval: str = '1d', use_ai: bool = True, user=Depends(get_current_user)):
    jid=_new_job(f'{broker}/{asset_type}'); asyncio.create_task(_run_one(jid,broker,asset_type,timeframe,interval,use_ai)); return {"job_id":jid,"status":"queued","progress":0}
