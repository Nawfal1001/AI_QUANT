"""
Trade Optimizer: MTF confluence, order book, mean reversion, portfolio risk, news halt
Supports: scalping (crypto/forex 1m+5m+15m), day_trading (stocks 15m+1h+4h), swing, position
"""
import asyncio, numpy as np, pandas as pd, ta, ccxt, yfinance as yf
from datetime import datetime, timedelta
from functools import partial
from database import db
from services.logger import child as _child_log
_log = _child_log('trade_optimizer')
cfg_col=db["trading_config"]

DEFAULT_CONFIG={"mode":"swing","asset_focus":"mixed","mtf_enabled":True,"orderbook_enabled":True,"mean_reversion_enabled":True,"portfolio_risk_enabled":True,"news_halt_enabled":True,"max_portfolio_risk":6.0,"mtf_timeframes":{"scalping":["1m","5m","15m"],"day_trading":["15m","1h","4h"],"swing":["1h","4h","1d"],"position":["4h","1d","1w"]}}

async def get_config():
    doc=await cfg_col.find_one({"_id":"trading_config"})
    if not doc: return DEFAULT_CONFIG.copy()
    doc.pop("_id",None); return doc

async def save_config(cfg):
    await cfg_col.replace_one({"_id":"trading_config"},{"_id":"trading_config",**cfg},upsert=True)
    return {"status":"saved"}

def _ohlcv_ccxt(ticker,tf,limit=100):
    try:
        ex=ccxt.binance(); data=ex.fetch_ohlcv(f"{ticker}/USDT",tf,limit=limit)
        df=pd.DataFrame(data,columns=["ts","open","high","low","close","volume"]); return df[["open","high","low","close","volume"]].dropna()
    except: return pd.DataFrame()

def _ohlcv_stock(ticker,tf,limit=100):
    try:
        pm={"1m":"5d","5m":"5d","15m":"5d","1h":"1mo","4h":"3mo","1d":"6mo"}
        im={"1m":"1m","5m":"5m","15m":"15m","1h":"1h","4h":"1h","1d":"1d"}
        h=yf.Ticker(ticker).history(period=pm.get(tf,"1mo"),interval=im.get(tf,"1d"))
        if h.empty: return pd.DataFrame()
        df=h[["Open","High","Low","Close","Volume"]].copy(); df.columns=["open","high","low","close","volume"]; return df.dropna().tail(limit)
    except: return pd.DataFrame()

def _quick_sig(df):
    if df.empty or len(df)<20: return {"signal":"NEUTRAL","score":0}
    c=df["close"]; h=df["high"]; l=df["low"]; scores=[]
    try: v=float(ta.momentum.RSIIndicator(c,14).rsi().dropna().iloc[-1]); scores.append(+2 if v<35 else -2 if v>65 else 0)
    except Exception as _e: _log.debug(f"ignored: {_e}")
    try: m=ta.trend.MACD(c); scores.append(+2 if float(m.macd().dropna().iloc[-1])>float(m.macd_signal().dropna().iloc[-1]) else -2)
    except Exception as _e: _log.debug(f"ignored: {_e}")
    try: e9=float(ta.trend.EMAIndicator(c,9).ema_indicator().dropna().iloc[-1]); e21=float(ta.trend.EMAIndicator(c,21).ema_indicator().dropna().iloc[-1]); scores.append(+2 if e9>e21 else -2)
    except Exception as _e: _log.debug(f"ignored: {_e}")
    try:
        atr=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1])
        lw=float(((h+l)/2-3*ta.volatility.AverageTrueRange(h,l,c,14).average_true_range()).dropna().iloc[-1])
        scores.append(+2 if float(c.iloc[-1])>lw else -2)
    except Exception as _e: _log.debug(f"ignored: {_e}")
    if not scores: return {"signal":"NEUTRAL","score":0}
    total=sum(scores); mx=len(scores)*2
    if total>=3: sig="STRONG BUY"
    elif total>=1: sig="BUY"
    elif total<=-3: sig="STRONG SELL"
    elif total<=-1: sig="SELL"
    else: sig="NEUTRAL"
    return {"signal":sig,"score":total,"confidence":int(abs(total)/mx*100)}

async def mtf_confluence(ticker,atype,mode="swing"):
    config=await get_config()
    tfs=config.get("mtf_timeframes",DEFAULT_CONFIG["mtf_timeframes"]).get(mode,["1h","4h","1d"])
    labels=["short","medium","long"]; loop=asyncio.get_event_loop(); results={}
    for tf,label in zip(tfs,labels):
        if atype=="stock": df=await loop.run_in_executor(None,partial(_ohlcv_stock,ticker,tf))
        else: df=await loop.run_in_executor(None,partial(_ohlcv_ccxt,ticker,tf))
        results[label]={"timeframe":tf,**_quick_sig(df)}
    buys=sum(1 for r in results.values() if "BUY" in r["signal"])
    sells=sum(1 for r in results.values() if "SELL" in r["signal"])
    n=len(results)
    if buys>=2: final="STRONG BUY" if buys==n else "BUY"; conf=int(buys/n*100); aligned=True
    elif sells>=2: final="STRONG SELL" if sells==n else "SELL"; conf=int(sells/n*100); aligned=True
    else: final="HOLD"; conf=33; aligned=False
    long_sig=results.get("long",{}).get("signal","NEUTRAL")
    if final=="BUY" and "SELL" in long_sig: final="HOLD"; conf=30; aligned=False
    elif final=="SELL" and "BUY" in long_sig: final="HOLD"; conf=30; aligned=False
    return {"signal":final,"confidence":conf,"aligned":aligned,"buy_votes":buys,"sell_votes":sells,"timeframes":results,"mode":mode,"recommendation":"TRADE" if aligned and conf>=60 else "WAIT"}

def _order_book(ticker):
    try: return ccxt.binance().fetch_order_book(f"{ticker}/USDT",limit=20)
    except: return None

async def order_book_analysis(ticker):
    loop=asyncio.get_event_loop(); book=await loop.run_in_executor(None,_order_book,ticker)
    if not book: return {"signal":"NEUTRAL","score":0,"reason":"Order book unavailable","imbalance":0}
    bids=book.get("bids",[]); asks=book.get("asks",[])
    if not bids or not asks: return {"signal":"NEUTRAL","score":0,"reason":"Empty","imbalance":0}
    bd=sum(b[1] for b in bids[:10]); ad=sum(a[1] for a in asks[:10]); total=bd+ad
    imb=(bd-ad)/total if total>0 else 0
    best_bid=float(bids[0][0]); best_ask=float(asks[0][0])
    spread=(best_ask-best_bid)/best_bid*100 if best_bid>0 else 0
    if imb>0.2: s,r=+2,f"Strong buy wall imb={imb:.2f}"
    elif imb>0.1: s,r=+1,f"Mild buy pressure imb={imb:.2f}"
    elif imb<-0.2: s,r=-2,f"Strong sell wall imb={imb:.2f}"
    elif imb<-0.1: s,r=-1,f"Mild sell pressure imb={imb:.2f}"
    else: s,r=0,f"Balanced imb={imb:.2f}"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"ORDER_BOOK","signal":sig,"score":s,"reason":r,"imbalance":round(imb,4),"bid_depth":round(bd,2),"ask_depth":round(ad,2),"spread_pct":round(spread,4),"best_bid":best_bid,"best_ask":best_ask}

def mean_reversion(closes,regime="RANGING"):
    if len(closes)<20: return {"indicator":"MEAN_REVERSION","signal":"NEUTRAL","score":0,"reason":"Not enough data"}
    sma=float(closes.rolling(20).mean().dropna().iloc[-1]); std=float(closes.rolling(20).std().dropna().iloc[-1]); price=float(closes.iloc[-1])
    z=(price-sma)/std if std>0 else 0
    mult=1.5 if regime=="RANGING" else 1.0
    if z<-2*mult: s,r=+2,f"MR BUY z={z:.2f}"
    elif z<-1.5*mult: s,r=+1,f"Possible MR BUY z={z:.2f}"
    elif z>2*mult: s,r=-2,f"MR SELL z={z:.2f}"
    elif z>1.5*mult: s,r=-1,f"Possible MR SELL z={z:.2f}"
    else: s,r=0,f"Within range z={z:.2f}"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"MEAN_REVERSION","signal":sig,"score":s,"reason":r,"z_score":round(z,4),"sma20":round(sma,4)}

async def portfolio_risk_check(new_risk,open_positions):
    config=await get_config(); max_total=config.get("max_portfolio_risk",6.0)
    current=sum(p.get("risk_pct",0) for p in (open_positions or [])); total_after=current+new_risk
    max_single=max_total*0.4
    if new_risk>max_single:
        return {"approved":False,"reason":f"Single trade {new_risk:.1f}% > limit {max_single:.1f}%","scale_factor":max_single/new_risk,"adjusted_risk":round(max_single,2),"current_exposure":round(current,2),"max_total":max_total}
    if total_after>max_total:
        remaining=max(0,max_total-current)
        if remaining<=0:
            return {"approved":False,"reason":f"Portfolio fully exposed {current:.1f}%/{max_total:.1f}%","scale_factor":0,"adjusted_risk":0,"current_exposure":round(current,2),"max_total":max_total}
        scale=remaining/new_risk
        return {"approved":True,"scaled_down":True,"reason":"Scaled to fit budget","scale_factor":round(scale,3),"adjusted_risk":round(remaining,2),"current_exposure":round(current,2),"total_after":round(current+remaining,2),"max_total":max_total}
    return {"approved":True,"scaled_down":False,"reason":f"OK {total_after:.1f}%/{max_total:.1f}%","scale_factor":1.0,"adjusted_risk":round(new_risk,2),"current_exposure":round(current,2),"total_after":round(total_after,2),"max_total":max_total}

HALT_KEYWORDS=["federal reserve","fomc","interest rate","cpi","inflation","nfp","non-farm","gdp","default","bankruptcy","sec investigation","fraud","delisted","earnings","quarterly results","hack","exploit","rug pull","liquidation cascade","sanctions","ban","regulation","sec lawsuit"]

async def news_halt_check(ticker,atype):
    try:
        import feedparser
        url=f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
        feed=feedparser.parse(url); titles=[e.get("title","").lower() for e in feed.entries[:10]]
        for title in titles:
            for kw in HALT_KEYWORDS:
                if kw in title and (ticker.lower() in title or atype in ("forex","crypto")):
                    return {"halt_trading":True,"reason":f"High-impact news: {title[:80]}","duration_minutes":60}
        return {"halt_trading":False,"reason":"No high-impact news","checked":len(titles)}
    except Exception as e: return {"halt_trading":False,"reason":f"News check skipped: {e}"}

async def run_optimization(ticker,atype,base_signal,base_confidence,closes=None,regime="RANGING",open_positions=None,risk_pct=2.0):
    config=await get_config(); mode=config.get("mode","swing"); checks={}; final_signal=base_signal; final_conf=base_confidence
    if config.get("news_halt_enabled",True):
        news=await news_halt_check(ticker,atype); checks["news"]=news
        if news["halt_trading"]: return {"approved":False,"reason":news["reason"],"checks":checks,"halt":True}
    if config.get("mtf_enabled",True):
        mtf=await mtf_confluence(ticker,atype,mode); checks["mtf"]=mtf
        if mtf["aligned"]:
            if ("BUY" in mtf["signal"] and "BUY" in base_signal) or ("SELL" in mtf["signal"] and "SELL" in base_signal):
                final_conf=min(100,int((base_confidence+mtf["confidence"])/2))
            else: final_conf=int(base_confidence*0.7)
        else:
            final_conf=int(base_confidence*0.5)
            if final_conf<50: return {"approved":False,"reason":"MTF conflict","checks":checks,"halt":False}
    if config.get("orderbook_enabled",True) and atype in ("crypto","forex"):
        try:
            ob=await order_book_analysis(ticker); checks["order_book"]=ob
            if ("BUY" in base_signal and "BUY" in ob.get("signal","")): final_conf=min(100,final_conf+5)
            elif ("SELL" in base_signal and "SELL" in ob.get("signal","")): final_conf=min(100,final_conf+5)
            elif ("BUY" in base_signal and "SELL" in ob.get("signal","")): final_conf=max(0,final_conf-10)
        except Exception as _e: _log.debug(f"ignored: {_e}")
    if config.get("mean_reversion_enabled",True) and closes is not None:
        mr=mean_reversion(closes,regime); checks["mean_reversion"]=mr
        if regime=="RANGING":
            if "BUY" in mr["signal"] and "SELL" in base_signal: final_signal=mr["signal"]; final_conf=60
            elif "SELL" in mr["signal"] and "BUY" in base_signal: final_signal=mr["signal"]; final_conf=60
    adjusted_risk=risk_pct
    if config.get("portfolio_risk_enabled",True):
        pr=await portfolio_risk_check(risk_pct,open_positions or []); checks["portfolio_risk"]=pr
        if not pr["approved"]: return {"approved":False,"reason":pr["reason"],"checks":checks,"halt":False}
        adjusted_risk=pr["adjusted_risk"]
    return {"approved":True,"final_signal":final_signal,"final_confidence":final_conf,"adjusted_risk_pct":adjusted_risk,"original_signal":base_signal,"original_confidence":base_confidence,"checks":checks,"mode":mode,"halt":False}
