"""
TradeAI Signal Service v4.4
18 indicators + Kalman/FRAMA/Hilbert/AdaptiveRSI/Entropy/OFI
+ Meta-Learner boost + Confluence Memory + LLM Sentiment + Volume Profile + Microstructure
+ Bayesian voting (regime-conditional)
+ Shared market-data fetcher with Yahoo/Alpha Vantage fallback for stocks.
"""
import asyncio, numpy as np, pandas as pd, ta
from datetime import datetime, timedelta
from functools import partial
from database import db
from services.weight_engine import get_weights
from services.advanced_indicators import calc_kalman_signal,calc_frama,calc_hilbert,calc_adaptive_rsi,calc_entropy,calc_ofi
from services.bayesian_engine import bayesian_vote
from services.logger import child as _child_log
_log = _child_log('signal_service')
TF = {"scalping":{"period":50,"days":90,"interval":"1d","atr":14,"sl":0.5,"tp":1.0},"intraday":{"period":100,"days":180,"interval":"1d","atr":14,"sl":1.0,"tp":2.0},"swing":{"period":200,"days":365,"interval":"1d","atr":14,"sl":1.5,"tp":3.0},"position":{"period":300,"days":730,"interval":"1d","atr":14,"sl":2.0,"tp":4.0}}

def _normalize_df(df, period):
    if df is None or len(df) == 0: return pd.DataFrame()
    out = df.copy()
    lower = {c: str(c).lower() for c in out.columns}
    out = out.rename(columns=lower)
    needed = ["open","high","low","close","volume"]
    if not all(c in out.columns for c in needed): return pd.DataFrame()
    out = out[needed].apply(pd.to_numeric, errors="coerce").dropna()
    return out.tail(period)

def _fetch(ticker, atype, period, days=365, interval="1d"):
    try:
        from services.backtest_engine import fetch_history
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            df = loop.run_until_complete(fetch_history(ticker, atype, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval))
        finally:
            loop.close()
            asyncio.set_event_loop(None)
        return _normalize_df(df, period)
    except Exception as e:
        _log.warning(f"shared fetch failed for {ticker} ({atype}): {e}")
        return pd.DataFrame()

def rsi(c):
    try:
        v=float(ta.momentum.RSIIndicator(c,14).rsi().dropna().iloc[-1])
        if v<30: s=+2; r=f"Oversold ({v:.1f})"
        elif v<45: s=+1; r=f"Low ({v:.1f})"
        elif v>70: s=-2; r=f"Overbought ({v:.1f})"
        elif v>55: s=-1; r=f"High ({v:.1f})"
        else: s=0; r=f"Neutral ({v:.1f})"
        return {"indicator":"RSI","value":round(v,2),"signal":"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL","score":s,"reason":r}
    except: return {"indicator":"RSI","value":50,"signal":"NEUTRAL","score":0,"reason":"Error"}
def macd(c):
    try:
        m=ta.trend.MACD(c); mv=float(m.macd().dropna().iloc[-1]); sv=float(m.macd_signal().dropna().iloc[-1]); hv=float(m.macd_diff().dropna().iloc[-1])
        if mv>sv and hv>0: s,r=+2,"Bullish crossover"
        elif mv<sv and hv<0: s,r=-2,"Bearish crossover"
        elif mv>sv: s,r=+1,"MACD above signal"
        else: s,r=-1,"MACD below signal"
        return {"indicator":"MACD","value":round(mv,4),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"MACD","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def ema(c):
    try:
        e9=float(ta.trend.EMAIndicator(c,9).ema_indicator().dropna().iloc[-1]); e21=float(ta.trend.EMAIndicator(c,21).ema_indicator().dropna().iloc[-1]); e50=float(ta.trend.EMAIndicator(c,50).ema_indicator().dropna().iloc[-1]); price=float(c.iloc[-1])
        if e9>e21>e50 and price>e9: s,r=+2,"Bullish stack 9>21>50"
        elif e9<e21<e50 and price<e9: s,r=-2,"Bearish stack 9<21<50"
        elif e9>e21: s,r=+1,"EMA 9>21"
        else: s,r=-1,"EMA 9<21"
        return {"indicator":"EMA_CROSS","value":round(e9,4),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"EMA_CROSS","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def bollinger(c):
    try:
        bb=ta.volatility.BollingerBands(c,20,2); price=float(c.iloc[-1]); upper=float(bb.bollinger_hband().dropna().iloc[-1]); lower=float(bb.bollinger_lband().dropna().iloc[-1]); mid=float(bb.bollinger_mavg().dropna().iloc[-1])
        if price<=lower*1.01: s,r=+2,"At lower band"
        elif price>=upper*0.99: s,r=-2,"At upper band"
        elif price<mid: s,r=+1,"Below midband"
        else: s,r=-1,"Above midband"
        return {"indicator":"BOLLINGER","value":round(price,4),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"BOLLINGER","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def stoch(h,l,c):
    try:
        st=ta.momentum.StochasticOscillator(h,l,c,14,3); k=float(st.stoch().dropna().iloc[-1]); d=float(st.stoch_signal().dropna().iloc[-1])
        if k<20 and k>d: s,r=+2,f"Oversold+cross ({k:.1f})"
        elif k>80 and k<d: s,r=-2,f"Overbought+cross ({k:.1f})"
        elif k<35: s,r=+1,f"Low ({k:.1f})"
        elif k>65: s,r=-1,f"High ({k:.1f})"
        else: s,r=0,f"Neutral ({k:.1f})"
        return {"indicator":"STOCHASTIC","value":round(k,2),"signal":"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL","score":s,"reason":r}
    except: return {"indicator":"STOCHASTIC","value":50,"signal":"NEUTRAL","score":0,"reason":"Error"}
def adx(h,l,c):
    try:
        a=ta.trend.ADXIndicator(h,l,c,14); av=float(a.adx().dropna().iloc[-1]); dp=float(a.adx_pos().dropna().iloc[-1]); dm=float(a.adx_neg().dropna().iloc[-1])
        if av>25 and dp>dm: s,r=+2,f"Strong uptrend ADX={av:.1f}"
        elif av>25 and dp<dm: s,r=-2,f"Strong downtrend ADX={av:.1f}"
        elif av>20 and dp>dm: s,r=+1,f"Moderate uptrend ADX={av:.1f}"
        elif av>20: s,r=-1,f"Moderate downtrend ADX={av:.1f}"
        else: s,r=0,f"No trend ADX={av:.1f}"
        return {"indicator":"ADX","value":round(av,2),"signal":"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL","score":s,"reason":r}
    except: return {"indicator":"ADX","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def vwap(h,l,c,v):
    try:
        val=float(ta.volume.VolumeWeightedAveragePrice(h,l,c,v).volume_weighted_average_price().dropna().iloc[-1]); price=float(c.iloc[-1]); diff=round((price-val)/val*100,2)
        if price>val*1.005: s,r=+2,f"Above VWAP +{diff}%"
        elif price<val*0.995: s,r=-2,f"Below VWAP {diff}%"
        else: s,r=0,f"Near VWAP {diff}%"
        return {"indicator":"VWAP","value":round(val,4),"signal":"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL","score":s,"reason":r}
    except: return {"indicator":"VWAP","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def obv(c,v):
    try:
        ob=ta.volume.OnBalanceVolumeIndicator(c,v).on_balance_volume(); oe=ob.ewm(span=20).mean()
        if float(ob.iloc[-1])>float(oe.iloc[-1]): s,r=+2,"OBV accumulation"
        else: s,r=-2,"OBV distribution"
        return {"indicator":"OBV","value":round(float(ob.iloc[-1]),0),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"OBV","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def supertrend(h,l,c):
    try:
        atr=ta.volatility.AverageTrueRange(h,l,c,10).average_true_range(); hl2=(h+l)/2; lw=hl2-3*atr; price=float(c.iloc[-1]); lv=float(lw.dropna().iloc[-1])
        if price>lv: s,r=+2,"SuperTrend bullish"
        else: s,r=-2,"SuperTrend bearish"
        return {"indicator":"SUPERTREND","value":round(lv,4),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"SUPERTREND","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def ichimoku(h,l,c):
    try:
        ich=ta.trend.IchimokuIndicator(h,l); conv=float(ich.ichimoku_conversion_line().dropna().iloc[-1]); base=float(ich.ichimoku_base_line().dropna().iloc[-1]); price=float(c.iloc[-1])
        if price>conv>base: s,r=+2,"Above Kumo bullish"
        elif price<conv<base: s,r=-2,"Below Kumo bearish"
        elif conv>base: s,r=+1,"Tenkan>Kijun"
        else: s,r=-1,"Tenkan<Kijun"
        return {"indicator":"ICHIMOKU","value":round(conv,4),"signal":"BUY" if s>0 else "SELL","score":s,"reason":r}
    except: return {"indicator":"ICHIMOKU","value":0,"signal":"NEUTRAL","score":0,"reason":"Error"}
def volume_sig(c,v):
    try:
        avg=float(v.rolling(20).mean().dropna().iloc[-1]); curr=float(v.iloc[-1]); ratio=curr/avg if avg>0 else 1; pc=(float(c.iloc[-1])-float(c.iloc[-2]))/float(c.iloc[-2])*100
        if ratio>2 and pc>0: s,r=+2,f"High vol breakout {ratio:.1f}x"
        elif ratio>2 and pc<0: s,r=-2,f"High vol breakdown {ratio:.1f}x"
        elif ratio>1.5: s,r=(+1 if pc>0 else -1),f"Above avg vol {ratio:.1f}x"
        else: s,r=0,f"Normal vol {ratio:.1f}x"
        return {"indicator":"VOLUME","value":round(ratio,2),"signal":"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL","score":s,"reason":r}
    except: return {"indicator":"VOLUME","value":1,"signal":"NEUTRAL","score":0,"reason":"Error"}
def atr_vol(h,l,c):
    try:
        atr=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1]); price=float(c.iloc[-1]); pct=atr/price*100
        if pct>3: sig,r="ALERT",f"HIGH vol ATR={pct:.2f}%"
        elif pct<0.5: sig,r="INFO",f"LOW vol ATR={pct:.2f}%"
        else: sig,r="NEUTRAL",f"Normal ATR={pct:.2f}%"
        return {"indicator":"ATR_VOLATILITY","value":round(pct,3),"signal":sig,"score":0,"reason":r,"atr_abs":round(atr,4)}
    except: return {"indicator":"ATR_VOLATILITY","value":1,"signal":"NEUTRAL","score":0,"reason":"Error"}

async def generate_signal(ticker, atype="stock", timeframe="swing", use_ai=False, use_advanced=True):
    cfg=TF.get(timeframe,TF["swing"])
    loop=asyncio.get_event_loop()
    df=await loop.run_in_executor(None,partial(_fetch,ticker,atype,cfg["period"],cfg.get("days",365),cfg.get("interval","1d")))
    if df.empty or len(df)<50:
        return {"ticker":ticker,"asset_type":atype,"timeframe":timeframe,"signal":"HOLD","confidence":0,"error":f"Not enough candle data for {ticker} ({atype}). Received {len(df)} bars; need at least 50.","timestamp":datetime.utcnow().isoformat(),"indicators":[],"bayesian":{}}
    c=df["close"]; h=df["high"]; l=df["low"]; v=df["volume"]; price=float(c.iloc[-1])
    weights=await get_weights()
    hilbert_data=calc_hilbert(c)
    inds=[rsi(c),macd(c),ema(c),bollinger(c),stoch(h,l,c),adx(h,l,c),vwap(h,l,c,v),obv(c,v),supertrend(h,l,c),ichimoku(h,l,c),volume_sig(c,v),atr_vol(h,l,c),calc_kalman_signal(c),calc_frama(h,l,c),hilbert_data,calc_adaptive_rsi(c,hilbert_data.get("cycle_period",14)),calc_entropy(c),calc_ofi(df["open"],h,l,c,v)]
    entropy_ok=next((i for i in inds if i["indicator"]=="ENTROPY"),{}).get("tradeable",True)
    ai_score=0
    if use_ai:
        try:
            from services.ai_service import get_ai_signal
            ar=await get_ai_signal(ticker,atype); ai_score=ar.get("score",0)
        except Exception as _e: _log.debug(f"ignored: {_e}")
    regime="RANGING"
    try:
        rd=await db["regime_history"].find_one({"ticker":ticker},sort=[("timestamp",-1)])
        if rd: regime=rd.get("regime","RANGING")
    except Exception as _e: _log.debug(f"ignored: {_e}")
    try:
        bv=await bayesian_vote(inds,regime,ai_score); sig=bv["signal"]; conf=bv["confidence"]
    except Exception as _e:
        _log.warning(f"bayesian_vote failed for {ticker}: {_e}"); sig,conf="HOLD",50; bv={"p_buy":0.5}
    if not entropy_ok: conf=int(conf*0.5)
    enhancements = {}
    if use_advanced:
        try:
            from services.llm_sentiment import get_llm_sentiment
            llm = await get_llm_sentiment(ticker, atype); enhancements["llm_sentiment"] = llm; llm_score = llm.get("score", 0)
            if llm_score != 0:
                llm_label = str(llm.get("signal", "NEUTRAL")).upper(); llm_dir = "BUY" if llm_label in ("BULLISH", "BUY") else "SELL" if llm_label in ("BEARISH", "SELL") else "HOLD"; sig_dir = "BUY" if "BUY" in sig else "SELL" if "SELL" in sig else "HOLD"
                if llm_dir == sig_dir and llm_dir != "HOLD": conf = max(0, min(100, conf + abs(llm_score) * 4))
                elif llm_dir != sig_dir and llm_dir != "HOLD" and sig_dir != "HOLD": conf = max(0, conf - 5)
        except Exception as e: enhancements["llm_sentiment"]={"error":str(e)}
        try:
            from services.volume_profile import get_volume_profile
            vp = await get_volume_profile(ticker, atype); enhancements["volume_profile"] = {"poc":vp.get("poc"),"vah":vp.get("vah"),"val":vp.get("val"),"signal":vp.get("signal"),"score":vp.get("score"),"reason":vp.get("reason")}
            if vp.get("score",0)>0 and "BUY" in sig: conf = min(100, conf+3)
            elif vp.get("score",0)<0 and "SELL" in sig: conf = min(100, conf+3)
            elif vp.get("score",0)>0 and "SELL" in sig: conf = max(0, conf-5)
        except Exception as e: enhancements["volume_profile"]={"error":str(e)}
        if atype == "crypto":
            try:
                from services.microstructure import get_microstructure
                micro = await get_microstructure(ticker, atype); enhancements["microstructure"] = micro
                if micro.get("funding_score",0) != 0:
                    if (micro["funding_score"]>0 and "BUY" in sig) or (micro["funding_score"]<0 and "SELL" in sig): conf = min(100, conf+5)
                    else: conf = max(0, conf-8)
            except Exception as e: enhancements["microstructure"]={"error":str(e)}
        try:
            from services.confluence_memory import get_historical_accuracy
            mem = await get_historical_accuracy(inds, regime, entropy_ok); enhancements["confluence_memory"] = mem
            if mem.get("has_history"): conf = max(0, min(100, conf + mem.get("confidence_boost",0)))
        except Exception as e: enhancements["confluence_memory"]={"error":str(e)}
    if conf<40: sig="HOLD"
    try: atr_val=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1])
    except: atr_val=price*0.02
    sl=price*(1-cfg["sl"]*atr_val/price) if "BUY" in sig else price*(1+cfg["sl"]*atr_val/price)
    tp=price*(1+cfg["tp"]*atr_val/price) if "BUY" in sig else price*(1-cfg["tp"]*atr_val/price)
    result = {"ticker":ticker,"asset_type":atype,"timeframe":timeframe,"signal":sig,"confidence":conf,"price":round(price,4),"sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),"bars":len(df),"regime":regime,"indicators":inds,"bayesian":bv,"enhancements":enhancements,"timestamp":datetime.utcnow().isoformat()}
    if use_advanced:
        try:
            from services.meta_learner import predict_signal_quality
            meta = await predict_signal_quality(result); result["meta_learner"] = meta
            if meta.get("available"):
                boost = meta.get("boost",0); result["confidence"] = max(0, min(100, conf + boost))
                if result["confidence"] < 40 and sig != "HOLD": result["signal"] = "HOLD"
        except Exception as e: result["meta_learner"]={"error":str(e)}
    return result
