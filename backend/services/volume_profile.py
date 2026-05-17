"""
Volume Profile + Liquidity Levels
Computes Point of Control (POC), Value Area High/Low, HVN/LVN.
"""
import numpy as np, pandas as pd, asyncio
import yfinance as yf, ccxt
from functools import partial

def _fetch(ticker, atype, period=60):
    try:
        if atype == "stock":
            # Check signal_service cache first (avoids redundant downloads during scans)
            try:
                from services.signal_service import _cache_get
                cached = _cache_get(ticker, atype)
                if cached is not None and not cached.empty:
                    return cached.tail(period)
            except Exception:
                pass
            h = yf.download(ticker, period="3mo", interval="1d",
                            auto_adjust=True, progress=False, threads=False)
            if isinstance(h.columns, pd.MultiIndex):
                h.columns = h.columns.droplevel(1)
            if h.empty:
                h = yf.Ticker(ticker).history(period="3mo", interval="1d", auto_adjust=True)
            if h.empty:
                return pd.DataFrame()
            h.columns = [c.lower() for c in h.columns]
            needed = [c for c in ["open","high","low","close","volume"] if c in h.columns]
            if len(needed) < 5:
                return pd.DataFrame()
            df = h[needed].copy()
            df.columns = ["open","high","low","close","volume"]
            return df.dropna().tail(period)
        else:
            ohlcv = ccxt.binance().fetch_ohlcv(f"{ticker}/USDT", "1d", limit=period)
            df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
            return df[["open","high","low","close","volume"]].dropna()
    except Exception as e:
        return pd.DataFrame()

def compute_volume_profile(df, bins=24):
    """Compute volume distribution across price levels"""
    if df.empty or len(df)<10:
        return {"poc":0,"vah":0,"val":0,"hvn":[],"lvn":[],"profile":[]}
    price_min = float(df["low"].min()); price_max = float(df["high"].max())
    if price_max <= price_min: return {"poc":price_min,"vah":price_max,"val":price_min,"hvn":[],"lvn":[],"profile":[]}
    edges = np.linspace(price_min, price_max, bins+1)
    centers = (edges[:-1]+edges[1:])/2
    volume_at = np.zeros(bins)
    for _,row in df.iterrows():
        low = float(row["low"]); high = float(row["high"]); vol = float(row["volume"])
        # Distribute bar volume across price levels it touched
        for i in range(bins):
            if edges[i+1] >= low and edges[i] <= high:
                overlap = min(edges[i+1],high) - max(edges[i],low)
                bar_range = high - low
                if bar_range>0: volume_at[i] += vol * (overlap/bar_range)
                else: volume_at[i] += vol/bins
    total_vol = volume_at.sum()
    if total_vol == 0:
        return {"poc":centers[0],"vah":centers[-1],"val":centers[0],"hvn":[],"lvn":[],"profile":[]}
    # POC = highest volume node
    poc_idx = int(np.argmax(volume_at)); poc = float(centers[poc_idx])
    # Value Area = 70% of volume around POC
    target_vol = total_vol * 0.7
    accumulated = volume_at[poc_idx]
    lo = hi = poc_idx
    while accumulated < target_vol and (lo > 0 or hi < bins-1):
        lo_vol = volume_at[lo-1] if lo > 0 else 0
        hi_vol = volume_at[hi+1] if hi < bins-1 else 0
        if lo_vol >= hi_vol and lo > 0: lo -= 1; accumulated += lo_vol
        elif hi < bins-1: hi += 1; accumulated += hi_vol
        else: break
    vah = float(centers[hi]); val = float(centers[lo])
    # HVN (High Volume Nodes) and LVN (Low Volume Nodes)
    avg_vol = total_vol / bins
    hvn = [{"price":round(float(centers[i]),4),"volume":round(float(volume_at[i]),0)} for i in range(bins) if volume_at[i] > avg_vol * 1.5]
    lvn = [{"price":round(float(centers[i]),4),"volume":round(float(volume_at[i]),0)} for i in range(bins) if volume_at[i] < avg_vol * 0.4 and volume_at[i] > 0]
    profile = [{"price":round(float(centers[i]),4),"volume":round(float(volume_at[i]),0)} for i in range(bins)]
    return {"poc":round(poc,4),"vah":round(vah,4),"val":round(val,4),"hvn":hvn[:5],"lvn":lvn[:5],"profile":profile}

async def get_volume_profile(ticker, atype="stock"):
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, partial(_fetch, ticker, atype))
    if df.empty: return {"error":"No data"}
    profile = compute_volume_profile(df)
    current_price = float(df["close"].iloc[-1])
    poc = profile.get("poc",current_price); vah = profile.get("vah",current_price); val = profile.get("val",current_price)
    # Generate signal based on position relative to value area
    if current_price < val:
        sig,score,reason = "BUY",+1,f"Below Value Area Low (${val:.2f}) — value buy zone"
    elif current_price > vah:
        sig,score,reason = "SELL",-1,f"Above Value Area High (${vah:.2f}) — overpriced zone"
    elif abs(current_price - poc)/poc < 0.01:
        sig,score,reason = "NEUTRAL",0,f"At Point of Control (${poc:.2f}) — equilibrium"
    elif current_price > poc:
        sig,score,reason = "WEAK SELL",-1,f"Above POC, below VAH — slight overpriced"
    else:
        sig,score,reason = "WEAK BUY",+1,f"Below POC, above VAL — slight value"
    return {"indicator":"VOLUME_PROFILE","ticker":ticker,"current_price":current_price,
            **profile,"signal":sig,"score":score,"reason":reason}
