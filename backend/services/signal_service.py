"""
TradeAI Signal Service v4.3
18 indicators + Kalman/FRAMA/Hilbert/AdaptiveRSI/Entropy/OFI
+ Meta-Learner boost + Confluence Memory + LLM Sentiment + Volume Profile + Microstructure
+ Bayesian voting (regime-conditional)
"""
import asyncio, time, numpy as np, pandas as pd, ta, yfinance as yf, ccxt
from datetime import datetime
from functools import partial
from database import db
from services.weight_engine import get_weights
from services.advanced_indicators import calc_kalman_signal,calc_frama,calc_hilbert,calc_adaptive_rsi,calc_entropy,calc_ofi
from services.bayesian_engine import bayesian_vote
from services.logger import child as _child_log
_log = _child_log('signal_service')

TF = {"scalping":{"period":50,"atr":14,"sl":0.5,"tp":1.0},"intraday":{"period":100,"atr":14,"sl":1.0,"tp":2.0},"swing":{"period":200,"atr":14,"sl":1.5,"tp":3.0},"position":{"period":300,"atr":14,"sl":2.0,"tp":4.0}}

# ── In-memory OHLCV cache (populated by batch prefetch for universe scans) ────
_OHLCV_CACHE: dict = {}   # key: "TICKER_atype" → (DataFrame, timestamp)
_CACHE_TTL = 3600          # 1 hour

def _cache_get(ticker: str, atype: str):
    entry = _OHLCV_CACHE.get(f"{ticker}_{atype}")
    if entry:
        df, ts = entry
        if time.time() - ts < _CACHE_TTL:
            return df
    return None

def _cache_set(ticker: str, atype: str, df: pd.DataFrame):
    _OHLCV_CACHE[f"{ticker}_{atype}"] = (df.copy(), time.time())


def _normalize_ohlcv(h: pd.DataFrame) -> pd.DataFrame:
    """Flatten multi-level columns (yfinance 0.2.38+), lowercase, return open/high/low/close/volume."""
    if isinstance(h.columns, pd.MultiIndex):
        h.columns = h.columns.droplevel(1)
    h.columns = [c.lower() for c in h.columns]
    needed = [c for c in ["open","high","low","close","volume"] if c in h.columns]
    if len(needed) < 5:
        return pd.DataFrame()
    df = h[needed].copy()
    df.columns = ["open","high","low","close","volume"]
    return df.dropna()


def _fetch_single_stock(ticker: str) -> pd.DataFrame:
    """Download 1y of daily data for a single stock ticker."""
    h = yf.download(ticker, period="1y", interval="1d",
                    auto_adjust=True, progress=False, threads=False)
    if h.empty:
        h = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=True)
    return _normalize_ohlcv(h)


def batch_prefetch_stocks(tickers: list):
    """
    Download all stock tickers in a single yf.download() call and populate the cache.
    Called from the universe scanner before spawning individual signal generators.
    Using group_by='ticker' so we get one DataFrame per ticker.
    """
    if not tickers:
        return
    try:
        df_all = yf.download(
            tickers, period="1y", interval="1d",
            auto_adjust=True, progress=False, threads=True, group_by="ticker",
        )
        if df_all.empty:
            return
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    df = _normalize_ohlcv(df_all)
                elif isinstance(df_all.columns, pd.MultiIndex):
                    df = df_all[ticker].copy() if ticker in df_all.columns.get_level_values(0) else pd.DataFrame()
                    df = _normalize_ohlcv(df) if not df.empty else df
                else:
                    df = _normalize_ohlcv(df_all)
                if not df.empty:
                    _cache_set(ticker, "stock", df)
            except Exception as e:
                _log.debug(f"batch_prefetch {ticker}: {e}")
    except Exception as e:
        _log.debug(f"batch_prefetch error: {e}")


async def batch_prefetch_stocks_async(tickers: list):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, batch_prefetch_stocks, tickers)


def _fetch(ticker, atype, period):
    try:
        if atype == "stock":
            # Check cache first (populated by batch_prefetch for universe scans)
            cached = _cache_get(ticker, atype)
            if cached is not None and not cached.empty:
                return cached.tail(period)
            # Individual download fallback
            df = _fetch_single_stock(ticker)
            if df.empty:
                return pd.DataFrame()
            _cache_set(ticker, atype, df)
            return df.tail(period)
        else:
            ohlcv = ccxt.binance().fetch_ohlcv(f"{ticker}/USDT", "1d", limit=max(period, 100))
            df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
            return df[["open","high","low","close","volume"]].dropna().tail(period)
    except Exception as e:
        _log.debug(f"_fetch {ticker} {atype} error: {e}")
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
        if price<=lower*1.01: s,r=+2,f"At lower band"
        elif price>=upper*0.99: s,r=-2,f"At upper band"
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
        val=float(ta.volume.VolumeWeightedAveragePrice(h,l,c,v).volume_weighted_average_price().dropna().iloc[-1]); price=float(c.iloc[-1])
        diff=round((price-val)/val*100,2)
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
        if price>lv: s,r=+2,f"SuperTrend bullish"
        else: s,r=-2,f"SuperTrend bearish"
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
    df=await loop.run_in_executor(None,partial(_fetch,ticker,atype,cfg["period"]))
    if df.empty or len(df)<50:
        return {"ticker":ticker,"signal":"HOLD","confidence":0,"error":"Not enough data","timestamp":datetime.now().isoformat()}
    c=df["close"]; h=df["high"]; l=df["low"]; v=df["volume"]; price=float(c.iloc[-1])
    weights=await get_weights()
    hilbert_data=calc_hilbert(c)
    inds=[rsi(c),macd(c),ema(c),bollinger(c),stoch(h,l,c),adx(h,l,c),vwap(h,l,c,v),obv(c,v),supertrend(h,l,c),ichimoku(h,l,c),volume_sig(c,v),atr_vol(h,l,c),
          calc_kalman_signal(c),calc_frama(h,l,c),hilbert_data,calc_adaptive_rsi(c,hilbert_data.get("cycle_period",14)),calc_entropy(c),calc_ofi(df["open"],h,l,c,v)]
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
        bv=await bayesian_vote(inds,regime,ai_score)
        sig=bv["signal"]; conf=bv["confidence"]; pb=bv["p_buy"]
    except:
        sig,conf,pb="HOLD",50,0.5
        bv={}
    if not entropy_ok: conf=int(conf*0.5)

    # ─── ADVANCED ENHANCEMENTS ───
    enhancements = {}
    if use_advanced:
        # 1) LLM Sentiment
        try:
            from services.llm_sentiment import get_llm_sentiment
            llm = await get_llm_sentiment(ticker, atype)
            enhancements["llm_sentiment"] = llm
            if llm.get("score",0) != 0:
                conf = max(0, min(100, conf + llm["score"]*4))
                if llm.get("signal","NEUTRAL") != sig.replace("STRONG ","").replace("WEAK ",""):
                    # disagreement → reduce confidence
                    conf = max(0, conf - 5)
        except Exception as e: enhancements["llm_sentiment"]={"error":str(e)}
        # 2) Volume Profile
        try:
            from services.volume_profile import get_volume_profile
            vp = await get_volume_profile(ticker, atype)
            enhancements["volume_profile"] = {"poc":vp.get("poc"),"vah":vp.get("vah"),"val":vp.get("val"),"signal":vp.get("signal"),"score":vp.get("score"),"reason":vp.get("reason")}
            if vp.get("score",0)>0 and "BUY" in sig: conf = min(100, conf+3)
            elif vp.get("score",0)<0 and "SELL" in sig: conf = min(100, conf+3)
            elif vp.get("score",0)>0 and "SELL" in sig: conf = max(0, conf-5)
        except Exception as e: enhancements["volume_profile"]={"error":str(e)}
        # 3) Microstructure (crypto only)
        if atype == "crypto":
            try:
                from services.microstructure import get_microstructure
                micro = await get_microstructure(ticker, atype)
                enhancements["microstructure"] = micro
                if micro.get("funding_score",0) != 0:
                    if (micro["funding_score"]>0 and "BUY" in sig) or (micro["funding_score"]<0 and "SELL" in sig):
                        conf = min(100, conf+5)
                    else:
                        conf = max(0, conf-8)
            except Exception as e: enhancements["microstructure"]={"error":str(e)}
        # 4) Confluence Memory (historical similar setups)
        try:
            from services.confluence_memory import get_historical_accuracy
            mem = await get_historical_accuracy(inds, regime, entropy_ok)
            enhancements["confluence_memory"] = mem
            if mem.get("has_history"):
                conf = max(0, min(100, conf + mem.get("confidence_boost",0)))
        except Exception as e: enhancements["confluence_memory"]={"error":str(e)}

    if conf<40: sig="HOLD"
    try:
        atr_val=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1])
    except: atr_val=price*0.02
    sl=price*(1-cfg["sl"]*atr_val/price) if "BUY" in sig else price*(1+cfg["sl"]*atr_val/price)
    tp=price*(1+cfg["tp"]*atr_val/price) if "BUY" in sig else price*(1-cfg["tp"]*atr_val/price)

    result = {"ticker":ticker,"asset_type":atype,"timeframe":timeframe,"signal":sig,"confidence":conf,
              "price":round(price,4),"sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),
              "regime":regime,"indicators":inds,"bayesian":bv,"enhancements":enhancements,
              "timestamp":datetime.now().isoformat()}

    # 5) Meta Learner prediction (after we have full signal)
    if use_advanced:
        try:
            from services.meta_learner import predict_signal_quality
            meta = await predict_signal_quality(result)
            result["meta_learner"] = meta
            if meta.get("available"):
                boost = meta.get("boost",0)
                result["confidence"] = max(0, min(100, conf + boost))
                if result["confidence"] < 40 and sig != "HOLD": result["signal"] = "HOLD"
        except Exception as e: result["meta_learner"]={"error":str(e)}

    return result
