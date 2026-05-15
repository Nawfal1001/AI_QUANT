import yfinance as yf, ccxt, pandas as pd, asyncio
from functools import partial
from services.logger import child as _child_log
_log = _child_log('market_service')

def _stock(ticker, rng):
    pm={"1d":"1d","5d":"5d","1mo":"1mo","3mo":"3mo","6mo":"6mo","1y":"1y"}
    t=yf.Ticker(ticker); info=t.info or {}
    hist=t.history(period=pm.get(rng,"1mo"),interval="1d")
    if hist.empty: return {"error":"No data"}
    hist=hist.reset_index(); hist["Date"]=hist["Date"].astype(str)
    p=float(hist["Close"].iloc[-1]); pp=float(hist["Close"].iloc[-2]) if len(hist)>1 else p
    return {"ticker":ticker,"name":info.get("longName",ticker),"price":round(p,2),
            "change":round(p-pp,2),"change_pct":round((p-pp)/pp*100,2) if pp else 0,
            "volume":int(hist["Volume"].iloc[-1]),"market_cap":info.get("marketCap",0),
            "sector":info.get("sector",""),"pe_ratio":info.get("trailingPE",None),
            "history":[{"date":r["Date"],"open":round(r["Open"],2),"high":round(r["High"],2),"low":round(r["Low"],2),"close":round(r["Close"],2),"volume":int(r["Volume"])} for _,r in hist.iterrows()]}

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
            i=yf.Ticker(t).info
            movers.append({"ticker":t,"name":i.get("shortName",t),"price":round(i.get("regularMarketPrice",0),2),"change_pct":round(i.get("regularMarketChangePercent",0) or 0,2),"type":"stock"})
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
