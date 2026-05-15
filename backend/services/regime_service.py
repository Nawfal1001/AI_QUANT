import numpy as np, pandas as pd, ta, asyncio, yfinance as yf, ccxt
from datetime import datetime
from functools import partial
from database import db
col=db["regime_history"]
REGIMES={"TRENDING_BULL":{"label":"Trending Bull","icon":"📈","color":"#3fb950"},"TRENDING_BEAR":{"label":"Trending Bear","icon":"📉","color":"#f85149"},"RANGING":{"label":"Ranging","icon":"↔️","color":"#e3b341"},"VOLATILE":{"label":"Volatile","icon":"🌪️","color":"#f0883e"},"QUIET":{"label":"Quiet","icon":"😴","color":"#8b949e"}}
REGIME_WEIGHTS={"TRENDING_BULL":{"RSI":12,"MACD":16,"EMA_CROSS":16,"BOLLINGER":4,"STOCHASTIC":4,"ADX":14,"VWAP":6,"OBV":8,"SUPERTREND":14,"ICHIMOKU":10,"VOLUME":8,"ATR_VOLATILITY":2,"KALMAN_EMA":10,"FRAMA":8,"ADAPTIVE_RSI":4,"ORDER_FLOW":8,"ENTROPY":2,"HILBERT":2},"TRENDING_BEAR":{"RSI":10,"MACD":14,"EMA_CROSS":12,"BOLLINGER":6,"STOCHASTIC":6,"ADX":16,"VWAP":6,"OBV":12,"SUPERTREND":16,"ICHIMOKU":8,"VOLUME":10,"ATR_VOLATILITY":4,"KALMAN_EMA":8,"FRAMA":8,"ADAPTIVE_RSI":4,"ORDER_FLOW":10,"ENTROPY":2,"HILBERT":2},"RANGING":{"RSI":16,"MACD":6,"EMA_CROSS":4,"BOLLINGER":18,"STOCHASTIC":16,"ADX":4,"VWAP":14,"OBV":6,"SUPERTREND":4,"ICHIMOKU":6,"VOLUME":4,"ATR_VOLATILITY":2,"KALMAN_EMA":6,"FRAMA":6,"ADAPTIVE_RSI":14,"ORDER_FLOW":6,"ENTROPY":6,"HILBERT":4},"VOLATILE":{"RSI":8,"MACD":10,"EMA_CROSS":8,"BOLLINGER":12,"STOCHASTIC":8,"ADX":10,"VWAP":10,"OBV":8,"SUPERTREND":10,"ICHIMOKU":6,"VOLUME":6,"ATR_VOLATILITY":14,"KALMAN_EMA":6,"FRAMA":4,"ADAPTIVE_RSI":6,"ORDER_FLOW":10,"ENTROPY":8,"HILBERT":4},"QUIET":{"RSI":18,"MACD":8,"EMA_CROSS":6,"BOLLINGER":14,"STOCHASTIC":18,"ADX":6,"VWAP":12,"OBV":4,"SUPERTREND":6,"ICHIMOKU":4,"VOLUME":4,"ATR_VOLATILITY":2,"KALMAN_EMA":6,"FRAMA":6,"ADAPTIVE_RSI":14,"ORDER_FLOW":6,"ENTROPY":6,"HILBERT":4}}

def hurst(prices):
    try:
        p=prices.dropna()
        if len(p)<60: return 0.5
        lags=range(2,min(100,len(p)//4)); RS=[]
        for lag in lags:
            vals=[]
            for i in range(0,len(p)-lag,lag):
                c=p.iloc[i:i+lag]
                if len(c)<2: continue
                dv=(c-c.mean()).cumsum(); R=dv.max()-dv.min(); S=c.std()
                if S>0: vals.append(R/S)
            if vals: RS.append(np.mean(vals))
        if len(RS)<2: return 0.5
        return round(float(np.polyfit(np.log(range(2,2+len(RS))),np.log(RS),1)[0]),4)
    except: return 0.5

def adx_regime(highs,lows,closes):
    try:
        adx_obj=ta.trend.ADXIndicator(highs,lows,closes,14)
        adx=float(adx_obj.adx().dropna().iloc[-1]); dp=float(adx_obj.adx_pos().dropna().iloc[-1]); dm=float(adx_obj.adx_neg().dropna().iloc[-1])
        atr_pct=float(ta.volatility.AverageTrueRange(highs,lows,closes,14).average_true_range().dropna().iloc[-1])/float(closes.iloc[-1])*100
        if atr_pct>4: r="VOLATILE"
        elif atr_pct<0.5 and adx<20: r="QUIET"
        elif adx>=25 and dp>dm: r="TRENDING_BULL"
        elif adx>=25 and dp<dm: r="TRENDING_BEAR"
        else: r="RANGING"
        return {"regime":r,"adx":round(adx,2),"confidence":round(min(adx/50*100,100),1)}
    except: return {"regime":"RANGING","adx":0,"confidence":30}

def simple_regime(closes):
    ret=closes.pct_change().dropna(); mean=float(ret.iloc[-20:].mean()); vol=float(ret.iloc[-20:].std())
    if mean>vol*0.5: return {"regime":"TRENDING_BULL","confidence":65}
    elif mean<-vol*0.5: return {"regime":"TRENDING_BEAR","confidence":65}
    else: return {"regime":"RANGING","confidence":50}

def _fetch(ticker,atype):
    try:
        if atype=="stock":
            h=yf.Ticker(ticker).history(period="6mo",interval="1d")
            if h.empty: return pd.DataFrame()
            df=h[["Open","High","Low","Close","Volume"]].copy(); df.columns=["open","high","low","close","volume"]; return df.dropna()
        else:
            ohlcv=ccxt.binance().fetch_ohlcv(f"{ticker}/USDT","1d",limit=180)
            df=pd.DataFrame(ohlcv,columns=["ts","open","high","low","close","volume"]); return df[["open","high","low","close","volume"]].dropna()
    except: return pd.DataFrame()

async def detect_regime(ticker,atype="stock"):
    loop=asyncio.get_event_loop()
    df=await loop.run_in_executor(None,partial(_fetch,ticker,atype))
    if df.empty or len(df)<50:
        return {"ticker":ticker,"regime":"RANGING","confidence":30,"error":"Not enough data"}
    closes=df["close"]; highs=df["high"]; lows=df["low"]
    H=await loop.run_in_executor(None,hurst,closes)
    ar=await loop.run_in_executor(None,adx_regime,highs,lows,closes)
    final=ar["regime"]; conf=ar["confidence"]
    if H>0.65 and "TRENDING" not in final: final=simple_regime(closes)["regime"]
    elif H<0.4 and "TRENDING" in final: final="RANGING"; conf=max(conf-15,30)
    info=REGIMES[final]
    res={"ticker":ticker,"regime":final,"confidence":conf,"hurst":H,"adx":ar.get("adx",0),"label":info["label"],"icon":info["icon"],"color":info["color"],"recommended_weights":REGIME_WEIGHTS.get(final,{}),"timestamp":datetime.now().isoformat()}
    await col.insert_one(dict(res))
    return res

async def detect_global(watchlist):
    tasks=[detect_regime(w["ticker"],w.get("type","stock")) for w in watchlist[:8]]
    results=await asyncio.gather(*tasks,return_exceptions=True)
    votes={}; per_asset={}
    for w,r in zip(watchlist[:8],results):
        if isinstance(r,dict) and "error" not in r:
            rv=r["regime"]; c=r["confidence"]
            votes[rv]=votes.get(rv,0)+c
            per_asset[w["ticker"]]={"regime":rv,"confidence":c,"label":r.get("label",""),"icon":r.get("icon",""),"color":r.get("color","#8b949e")}
    if not votes: gr,gc="RANGING",30
    else:
        gr=max(votes,key=votes.get); total=sum(votes.values())
        gc=round(votes[gr]/total*100,1)
    info=REGIMES[gr]
    return {"global_regime":gr,"global_confidence":gc,"label":info["label"],"icon":info["icon"],"color":info["color"],"per_asset":per_asset,"recommended_weights":REGIME_WEIGHTS.get(gr,{}),"timestamp":datetime.now().isoformat()}

async def get_history(ticker=None,limit=50):
    q={"ticker":ticker} if ticker else {}
    docs=await col.find(q).sort("timestamp",-1).limit(limit).to_list(limit)
    for d in docs: d.pop("_id",None)
    return docs
