"""
Bayesian Engine with regime-conditional likelihoods + self-learning from outcomes
"""
import numpy as np
from datetime import datetime
from database import db
col=db["bayesian_likelihoods"]
DEFAULTS={
    "TRENDING_BULL":{"RSI":0.62,"MACD":0.68,"EMA_CROSS":0.70,"BOLLINGER":0.52,"STOCHASTIC":0.55,"ADX":0.72,"VWAP":0.60,"OBV":0.65,"SUPERTREND":0.74,"ICHIMOKU":0.68,"VOLUME":0.58,"ATR_VOLATILITY":0.50,"KALMAN_EMA":0.66,"FRAMA":0.67,"ADAPTIVE_RSI":0.63,"ORDER_FLOW":0.69,"ENTROPY":0.55,"HILBERT":0.50},
    "TRENDING_BEAR":{"RSI":0.60,"MACD":0.66,"EMA_CROSS":0.68,"BOLLINGER":0.53,"STOCHASTIC":0.54,"ADX":0.73,"VWAP":0.58,"OBV":0.67,"SUPERTREND":0.75,"ICHIMOKU":0.66,"VOLUME":0.60,"ATR_VOLATILITY":0.50,"KALMAN_EMA":0.64,"FRAMA":0.65,"ADAPTIVE_RSI":0.61,"ORDER_FLOW":0.70,"ENTROPY":0.55,"HILBERT":0.50},
    "RANGING":{"RSI":0.68,"MACD":0.52,"EMA_CROSS":0.50,"BOLLINGER":0.72,"STOCHASTIC":0.70,"ADX":0.48,"VWAP":0.65,"OBV":0.55,"SUPERTREND":0.50,"ICHIMOKU":0.53,"VOLUME":0.56,"ATR_VOLATILITY":0.50,"KALMAN_EMA":0.60,"FRAMA":0.58,"ADAPTIVE_RSI":0.70,"ORDER_FLOW":0.62,"ENTROPY":0.60,"HILBERT":0.55},
    "VOLATILE":{"RSI":0.54,"MACD":0.55,"EMA_CROSS":0.53,"BOLLINGER":0.60,"STOCHASTIC":0.55,"ADX":0.58,"VWAP":0.56,"OBV":0.57,"SUPERTREND":0.58,"ICHIMOKU":0.54,"VOLUME":0.62,"ATR_VOLATILITY":0.65,"KALMAN_EMA":0.55,"FRAMA":0.56,"ADAPTIVE_RSI":0.55,"ORDER_FLOW":0.60,"ENTROPY":0.65,"HILBERT":0.52},
    "QUIET":{"RSI":0.65,"MACD":0.54,"EMA_CROSS":0.52,"BOLLINGER":0.68,"STOCHASTIC":0.67,"ADX":0.50,"VWAP":0.63,"OBV":0.54,"SUPERTREND":0.52,"ICHIMOKU":0.53,"VOLUME":0.55,"ATR_VOLATILITY":0.58,"KALMAN_EMA":0.62,"FRAMA":0.60,"ADAPTIVE_RSI":0.66,"ORDER_FLOW":0.60,"ENTROPY":0.60,"HILBERT":0.55},
}
async def get_likelihoods(regime):
    doc=await col.find_one({"_id":"likelihoods"})
    base=DEFAULTS.get(regime,DEFAULTS["RANGING"])
    if doc and doc.get("data",{}).get(regime): return {**base,**doc["data"][regime]}
    return base

async def bayesian_vote(indicators, regime="RANGING", ai_score=0, prior=0.5):
    L=await get_likelihoods(regime)
    lb=np.log(prior); ls=np.log(1-prior); used=[]
    for ind in indicators:
        name=ind.get("indicator","") if isinstance(ind,dict) else ""
        score=ind.get("score",0) if isinstance(ind,dict) else 0
        sig=ind.get("signal","") if isinstance(ind,dict) else ""
        if not name or sig in ("NEUTRAL","INFO","ALERT","PENDING"): continue
        p=L.get(name,0.55); q=1-p
        if score>0: lb+=np.log(max(p,0.01)); ls+=np.log(max(q,0.01))
        elif score<0: lb+=np.log(max(q,0.01)); ls+=np.log(max(p,0.01))
        used.append({"indicator":name,"likelihood":round(p,3),"vote":"BUY" if score>0 else "SELL"})
    if ai_score==1: lb+=np.log(0.65); ls+=np.log(0.35)
    elif ai_score==-1: lb+=np.log(0.35); ls+=np.log(0.65)
    le=np.logaddexp(lb,ls)
    pb=float(np.clip(np.exp(lb-le),0.01,0.99)); ps=float(np.clip(np.exp(ls-le),0.01,0.99))
    if pb>=0.80: sig,conf="STRONG BUY",int(pb*100)
    elif pb>=0.60: sig,conf="BUY",int(pb*100)
    elif ps>=0.80: sig,conf="STRONG SELL",int(ps*100)
    elif ps>=0.60: sig,conf="SELL",int(ps*100)
    else: sig,conf="HOLD",50
    return {"signal":sig,"confidence":conf,"p_buy":round(pb,4),"p_sell":round(ps,4),"regime":regime,"indicator_votes":used}

async def update_likelihoods_from_outcome(regime, indicators, signal, correct):
    """Update Bayesian likelihoods from actual trade outcomes (Laplace smoothing)"""
    import copy
    doc = await col.find_one({"_id":"likelihoods"}) or {}
    likelihoods = doc.get("data",{})
    if regime not in likelihoods:
        likelihoods[regime] = copy.deepcopy(DEFAULTS.get(regime,DEFAULTS["RANGING"]))
    counts_doc = await col.find_one({"_id":"counts"}) or {}
    counts = counts_doc.get("data",{})
    if regime not in counts: counts[regime] = {}
    is_buy = "BUY" in signal
    for ind in (indicators or []):
        name = ind.get("indicator","") if isinstance(ind,dict) else ""
        ind_sig = ind.get("signal","") if isinstance(ind,dict) else ""
        if not name or ind_sig in ("NEUTRAL","INFO","ALERT"): continue
        ind_says_buy = "BUY" in ind_sig
        if name not in counts[regime]: counts[regime][name]={"tp":0,"fp":0,"tn":0,"fn":0}
        c = counts[regime][name]
        if ind_says_buy and is_buy and correct: c["tp"]+=1
        elif ind_says_buy and is_buy and not correct: c["fp"]+=1
        elif not ind_says_buy and not is_buy and correct: c["tn"]+=1
        elif not ind_says_buy and not is_buy and not correct: c["fn"]+=1
        # Laplace smoothing: P = (tp+1)/(tp+fp+2)
        tp,fp = c["tp"],c["fp"]
        if tp+fp>0: likelihoods[regime][name] = round((tp+1)/(tp+fp+2),4)
    await col.replace_one({"_id":"likelihoods"},{"_id":"likelihoods","data":likelihoods,"updated":datetime.now().isoformat()},upsert=True)
    await col.replace_one({"_id":"counts"},{"_id":"counts","data":counts,"updated":datetime.now().isoformat()},upsert=True)
    return {"updated":True,"regime":regime}

async def get_likelihood_table():
    doc=await col.find_one({"_id":"likelihoods"})
    counts_doc=await col.find_one({"_id":"counts"})
    return {"likelihoods":doc.get("data",DEFAULTS) if doc else DEFAULTS,
            "counts":counts_doc.get("data",{}) if counts_doc else {},
            "updated":doc.get("updated","never") if doc else "never"}
