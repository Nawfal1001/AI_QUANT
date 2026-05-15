from datetime import datetime
from database import db
from services.regime_service import REGIME_WEIGHTS,REGIMES,detect_global
from services.weight_engine import get_weights,col as wcol,ID as WID,DEFAULT as WDEF
import asyncio
from services.logger import child as _child_log
_log = _child_log('strategy_manager')

scol=db["strategies"]; rcol=db["regime_history"]; pcol=db["regime_pending"]

PRESETS=[
    {"id":"trending_bull","name":"Trending Bull","icon":"📈","regime":"TRENDING_BULL","preset":True,"weights":REGIME_WEIGHTS["TRENDING_BULL"]},
    {"id":"trending_bear","name":"Trending Bear","icon":"📉","regime":"TRENDING_BEAR","preset":True,"weights":REGIME_WEIGHTS["TRENDING_BEAR"]},
    {"id":"ranging","name":"Range Trader","icon":"↔️","regime":"RANGING","preset":True,"weights":REGIME_WEIGHTS["RANGING"]},
    {"id":"volatile","name":"Volatility","icon":"🌪️","regime":"VOLATILE","preset":True,"weights":REGIME_WEIGHTS["VOLATILE"]},
    {"id":"quiet","name":"Scalper","icon":"😴","regime":"QUIET","preset":True,"weights":REGIME_WEIGHTS["QUIET"]},
]

async def get_strategies():
    custom=await scol.find({}).to_list(100)
    for s in custom: s["_id"]=str(s["_id"])
    return PRESETS+custom

async def apply_strategy(sid):
    st=next((s for s in PRESETS if s["id"]==sid),None)
    if not st:
        from bson import ObjectId
        try: st=await scol.find_one({"_id":ObjectId(sid)}); st["_id"]=str(st["_id"])
        except Exception as _e: _log.debug(f"ignored: {_e}")
    if not st: return {"error":f"Strategy {sid} not found"}
    w=st.get("weights",WDEF); doc=await wcol.find_one({"_id":WID}) or {}; log=doc.get("update_log",[])
    log.insert(0,{"ts":datetime.now().isoformat(),"source":"strategy_switch","strategy":sid})
    await wcol.replace_one({"_id":WID},{"_id":WID,**w,"updated_at":datetime.now().isoformat(),"version":doc.get("version",0)+1,"update_log":log[:100],"active_strategy":sid},upsert=True)
    return {"status":"applied","strategy_id":sid,"strategy_name":st.get("name",""),"weights":w}

async def check_and_switch(watchlist,paper_mode=True):
    gd=await detect_global(watchlist); gr=gd["global_regime"]; gc=gd["global_confidence"]
    prev=await rcol.find_one({"global_regime":{"$exists":True}},sort=[("timestamp",-1)]); prev_r=prev.get("global_regime","") if prev else ""
    await rcol.insert_one(dict(gd)); switched=False; action="no_change"
    smap={"TRENDING_BULL":"trending_bull","TRENDING_BEAR":"trending_bear","RANGING":"ranging","VOLATILE":"volatile","QUIET":"quiet"}
    if gr!=prev_r and gc>=55:
        sid=smap.get(gr,"ranging")
        if paper_mode: await apply_strategy(sid); switched=True; action="auto_switched"
        else:
            await pcol.insert_one({"regime":gr,"strategy_id":sid,"confidence":gc,"prev_regime":prev_r,"created_at":datetime.now().isoformat(),"confirmed":False})
            action="pending_confirmation"
    return {"regime":gr,"confidence":gc,"prev_regime":prev_r,"regime_changed":gr!=prev_r,"action":action,"switched":switched,"per_asset":gd.get("per_asset",{}),"recommended_weights":gd.get("recommended_weights",{})}

async def get_pending():
    docs=await pcol.find({"confirmed":False}).sort("created_at",-1).to_list(10)
    for d in docs: d["_id"]=str(d["_id"])
    return docs

async def confirm_switch(pid):
    from bson import ObjectId
    p=await pcol.find_one({"_id":ObjectId(pid)})
    if not p: return {"error":"Not found"}
    r=await apply_strategy(p["strategy_id"])
    await pcol.update_one({"_id":ObjectId(pid)},{"$set":{"confirmed":True,"confirmed_at":datetime.now().isoformat()}})
    return {"status":"confirmed","applied":r}

_reg_running=False
async def start_regime_scheduler(watchlist,paper_mode=True):
    global _reg_running
    if _reg_running: return {"status":"running"}
    _reg_running=True; asyncio.create_task(_reg_loop(watchlist,paper_mode)); return {"status":"started"}
async def _reg_loop(watchlist,paper_mode):
    while _reg_running:
        try: await check_and_switch(watchlist,paper_mode)
        except Exception as e: print(f"[Regime] {e}")
        await asyncio.sleep(900)
