import yfinance as yf, ccxt, pandas as pd, asyncio
from functools import partial
from services.logger import child as _child_log
_log = _child_log('market_service')


def _yf_download(ticker, period, interval="1d"):
    """Download OHLCV from yfinance, handling multi-level columns from v0.2.38+."""
    df = yf.download(ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False, threads=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df.columns = [c.capitalize() for c in df.columns]
    return df


def _stock(ticker, rng):
    pm={"1d":"1d","5d":"5d","1mo":"1mo","3mo":"3mo","6mo":"6mo","1y":"1y"}
    period = pm.get(rng, "1mo")
    try:
        hist = _yf_download(ticker, period)
        if hist.empty:
            # fallback: try Ticker.history
            hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if hist.empty:
            return {"error": "No data"}
        hist = hist.reset_index()
        date_col = next((c for c in hist.columns if "date" in c.lower() or "datetime" in c.lower()), hist.columns[0])
        hist[date_col] = hist[date_col].astype(str)
        close_col = next(c for c in hist.columns if c.lower() == "close")
        vol_col   = next(c for c in hist.columns if c.lower() == "volume")
        p  = float(hist[close_col].iloc[-1])
        pp = float(hist[close_col].iloc[-2]) if len(hist) > 1 else p
        try:
            info = yf.Ticker(ticker).fast_info
            name       = getattr(info, "display_name", ticker) or ticker
            market_cap = getattr(info, "market_cap", 0) or 0
        except Exception:
            name = ticker; market_cap = 0
        return {
            "ticker": ticker, "name": name, "price": round(p, 2),
            "change": round(p - pp, 2),
            "change_pct": round((p - pp) / pp * 100, 2) if pp else 0,
            "volume": int(hist[vol_col].iloc[-1]),
            "market_cap": market_cap,
            "history": [
                {"date": str(r[date_col]),
                 "open":  round(float(r.get("Open",  r.get("open",  0))), 2),
                 "high":  round(float(r.get("High",  r.get("high",  0))), 2),
                 "low":   round(float(r.get("Low",   r.get("low",   0))), 2),
                 "close": round(float(r[close_col]), 2),
                 "volume": int(r[vol_col])}
                for _, r in hist.iterrows()
            ],
        }
    except Exception as e:
        _log.debug(f"_stock {ticker} error: {e}")
        return {"error": str(e)}

def _crypto(symbol, rng):
    lm={"1d":1,"5d":5,"1mo":30,"3mo":90,"6mo":180,"1y":365}
    ex=ccxt.binance()
    try:
        ohlcv=ex.fetch_ohlcv(f"{symbol}/USDT","1d",limit=lm.get(rng,30)+2)
        df=pd.DataFrame(ohlcv,columns=["ts","open","high","low","close","volume"])
        t=ex.fetch_ticker(f"{symbol}/USDT")
        return {"ticker":symbol,"price":round(t["last"],4),"change":round(t.get("change",0) or 0,4),
                "change_pct":round(t.get("percentage",0) or 0,2),"volume":round(t.get("quoteVolume",0) or 0,2),
                "history":[{"date":str(pd.Timestamp(r["ts"],unit="ms").date()),"open":round(r["open"],4),"high":round(r["high"],4),"low":round(r["low"],4),"close":round(r["close"],4),"volume":round(r["volume"],2)} for _,r in df.iterrows()]}
    except Exception as e: return {"error":str(e)}

def _movers():
    movers=[]
    stocks=["AAPL","NVDA","TSLA","MSFT","AMZN","META","GOOGL","AMD","NFLX","INTC","BABA","ORCL"]
    for t in stocks:
        try:
            df = _yf_download(t, "2d")
            if df.empty or len(df) < 2:
                continue
            close_col = next((c for c in df.columns if c.lower() == "close"), None)
            if not close_col:
                continue
            p  = float(df[close_col].iloc[-1])
            pp = float(df[close_col].iloc[-2])
            chg_pct = round((p - pp) / pp * 100, 2) if pp else 0
            movers.append({"ticker": t, "name": t, "price": round(p, 2), "change_pct": chg_pct, "type": "stock"})
        except Exception as _e: _log.debug(f"ignored: {_e}")
    try:
        ex=ccxt.binance(); td=ex.fetch_tickers(["BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","ADA/USDT","XRP/USDT","DOGE/USDT"])
        for p,d in td.items():
            s=p.replace("/USDT","")
            movers.append({"ticker":s,"name":s,"price":round(d.get("last",0),4),"change_pct":round(d.get("percentage",0) or 0,2),"type":"crypto"})
    except Exception as _e: _log.debug(f"ignored: {_e}")
    movers.sort(key=lambda x:abs(x.get("change_pct",0)),reverse=True)
    return movers[:20]

async def get_stock(ticker,rng="1mo"):
    return await asyncio.get_event_loop().run_in_executor(None,partial(_stock,ticker.upper(),rng))
async def get_crypto(symbol,rng="1mo"):
    return await asyncio.get_event_loop().run_in_executor(None,partial(_crypto,symbol.upper(),rng))
async def get_movers(atype="all"):
    return await asyncio.get_event_loop().run_in_executor(None,_movers)
async def search(q):
    res=[]
    try:
        i=yf.Ticker(q.upper()).info
        if i.get("longName"): res.append({"ticker":q.upper(),"name":i["longName"],"type":"stock"})
    except Exception as _e: _log.debug(f"ignored: {_e}")
    for c in ["BTC","ETH","BNB","SOL","ADA","XRP","DOGE","AVAX","MATIC","DOT"]:
        if q.upper() in c: res.append({"ticker":c,"name":c,"type":"crypto"})
    return res[:10]
