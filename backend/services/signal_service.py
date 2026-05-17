"""
TradeAI Signal Service v4.6
Adds true intraday timeframe support and higher-timeframe confirmation.
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
TF={
 "1m":{"period":240,"days":7,"interval":"1m","atr":14,"sl":0.45,"tp":0.9},
 "5m":{"period":240,"days":14,"interval":"5m","atr":14,"sl":0.55,"tp":1.1},
 "15m":{"period":220,"days":30,"interval":"15m","atr":14,"sl":0.75,"tp":1.5},
 "30m":{"period":220,"days":45,"interval":"30m","atr":14,"sl":0.9,"tp":1.8},
 "1h":{"period":220,"days":90,"interval":"1h","atr":14,"sl":1.1,"tp":2.2},
 "4h":{"period":220,"days":180,"interval":"4h","atr":14,"sl":1.35,"tp":2.7},
 "1d":{"period":220,"days":365,"interval":"1d","atr":14,"sl":1.5,"tp":3.0},
 "1w":{"period":180,"days":1600,"interval":"1wk","atr":14,"sl":2.0,"tp":4.0},
 "scalping":{"period":200,"days":14,"interval":"5m","atr":14,"sl":0.55,"tp":1.1},
 "intraday":{"period":220,"days":45,"interval":"30m","atr":14,"sl":0.9,"tp":1.8},
 "swing":{"period":220,"days":365,"interval":"1d","atr":14,"sl":1.5,"tp":3.0},
 "position":{"period":320,"days":1600,"interval":"1wk","atr":14,"sl":2.0,"tp":4.0},
}
MTF_CONFIRMATIONS={"1m":["5m","15m"],"5m":["15m","30m"],"15m":["30m","1h"],"30m":["1h","4h"],"1h":["4h","1d"],"4h":["1d"],"1d":["1w"],"scalping":["15m","30m"],"intraday":["1h","4h"],"swing":["1w"],"position":[]}
def _normalize_df(df,period):
    if df is None or len(df)==0: return pd.DataFrame()
    out=df.copy(); out=out.rename(columns={c:str(c).lower() for c in out.columns}); needed=["open","high","low","close","volume"]
    if not all(c in out.columns for c in needed): return pd.DataFrame()
    return out[needed].apply(pd.to_numeric,errors="coerce").dropna().tail(period)
def _fetch(ticker,atype,period,days=365,interval="1d"):
    try:
        from services.backtest_engine import fetch_history
        end=datetime.utcnow(); start=end-timedelta(days=days); loop=asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop); df=loop.run_until_complete(fetch_history(ticker,atype,start.strftime("%Y-%m-%d"),end.strftime("%Y-%m-%d"),interval))
        finally:
            loop.close(); asyncio.set_event_loop(None)
        return _normalize_df(df,period)
    except Exception as e: _log.warning(f"shared fetch failed for {ticker} ({atype}) interval={interval}: {e}"); return pd.DataFrame()
def _ind(name,val,signal,score,reason,**extra):
    return {"indicator":name,"value":val,"signal":signal,"score":score,"reason":reason,**extra}
def rsi(c):
    try:
        v=float(ta.momentum.RSIIndicator(c,14).rsi().dropna().iloc[-1]); s=2 if v<30 else 1 if v<45 else -2 if v>70 else -1 if v>55 else 0; r=f"RSI {v:.1f}"
        return _ind("RSI",round(v,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,r)
    except: return _ind("RSI",50,"NEUTRAL",0,"Error")
def macd(c):
    try:
        m=ta.trend.MACD(c); mv=float(m.macd().dropna().iloc[-1]); sv=float(m.macd_signal().dropna().iloc[-1]); hv=float(m.macd_diff().dropna().iloc[-1]); s=2 if mv>sv and hv>0 else -2 if mv<sv and hv<0 else 1 if mv>sv else -1
        return _ind("MACD",round(mv,4),"BUY" if s>0 else "SELL",s,"Bullish" if s>0 else "Bearish")
    except: return _ind("MACD",0,"NEUTRAL",0,"Error")
def ema(c):
    try:
        e9=float(ta.trend.EMAIndicator(c,9).ema_indicator().dropna().iloc[-1]); e21=float(ta.trend.EMAIndicator(c,21).ema_indicator().dropna().iloc[-1]); e50=float(ta.trend.EMAIndicator(c,50).ema_indicator().dropna().iloc[-1]); price=float(c.iloc[-1]); s=2 if e9>e21>e50 and price>e9 else -2 if e9<e21<e50 and price<e9 else 1 if e9>e21 else -1
        return _ind("EMA_CROSS",round(e9,4),"BUY" if s>0 else "SELL",s,"EMA trend stack")
    except: return _ind("EMA_CROSS",0,"NEUTRAL",0,"Error")
def bollinger(c):
    try:
        bb=ta.volatility.BollingerBands(c,20,2); price=float(c.iloc[-1]); upper=float(bb.bollinger_hband().dropna().iloc[-1]); lower=float(bb.bollinger_lband().dropna().iloc[-1]); mid=float(bb.bollinger_mavg().dropna().iloc[-1]); s=2 if price<=lower*1.01 else -2 if price>=upper*0.99 else 1 if price<mid else -1
        return _ind("BOLLINGER",round(price,4),"BUY" if s>0 else "SELL",s,"Band location")
    except: return _ind("BOLLINGER",0,"NEUTRAL",0,"Error")
def stoch(h,l,c):
    try:
        st=ta.momentum.StochasticOscillator(h,l,c,14,3); k=float(st.stoch().dropna().iloc[-1]); d=float(st.stoch_signal().dropna().iloc[-1]); s=2 if k<20 and k>d else -2 if k>80 and k<d else 1 if k<35 else -1 if k>65 else 0
        return _ind("STOCHASTIC",round(k,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"K={k:.1f}")
    except: return _ind("STOCHASTIC",50,"NEUTRAL",0,"Error")
def adx(h,l,c):
    try:
        a=ta.trend.ADXIndicator(h,l,c,14); av=float(a.adx().dropna().iloc[-1]); dp=float(a.adx_pos().dropna().iloc[-1]); dm=float(a.adx_neg().dropna().iloc[-1]); s=2 if av>25 and dp>dm else -2 if av>25 and dp<dm else 1 if av>20 and dp>dm else -1 if av>20 else 0
        return _ind("ADX",round(av,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"ADX={av:.1f}")
    except: return _ind("ADX",0,"NEUTRAL",0,"Error")
def vwap(h,l,c,v):
    try:
        val=float(ta.volume.VolumeWeightedAveragePrice(h,l,c,v).volume_weighted_average_price().dropna().iloc[-1]); price=float(c.iloc[-1]); diff=(price-val)/val*100; s=2 if price>val*1.005 else -2 if price<val*0.995 else 0
        return _ind("VWAP",round(val,4),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"VWAP diff {diff:.2f}%")
    except: return _ind("VWAP",0,"NEUTRAL",0,"Error")
def obv(c,v):
    try:
        ob=ta.volume.OnBalanceVolumeIndicator(c,v).on_balance_volume(); oe=ob.ewm(span=20).mean(); s=2 if float(ob.iloc[-1])>float(oe.iloc[-1]) else -2
        return _ind("OBV",round(float(ob.iloc[-1]),0),"BUY" if s>0 else "SELL",s,"Accumulation" if s>0 else "Distribution")
    except: return _ind("OBV",0,"NEUTRAL",0,"Error")
def supertrend(h,l,c):
    try:
        atr=ta.volatility.AverageTrueRange(h,l,c,10).average_true_range(); hl2=(h+l)/2; lw=hl2-3*atr; price=float(c.iloc[-1]); lv=float(lw.dropna().iloc[-1]); s=2 if price>lv else -2
        return _ind("SUPERTREND",round(lv,4),"BUY" if s>0 else "SELL",s,"Supertrend direction")
    except: return _ind("SUPERTREND",0,"NEUTRAL",0,"Error")
def ichimoku(h,l,c):
    try:
        ich=ta.trend.IchimokuIndicator(h,l); conv=float(ich.ichimoku_conversion_line().dropna().iloc[-1]); base=float(ich.ichimoku_base_line().dropna().iloc[-1]); price=float(c.iloc[-1]); s=2 if price>conv>base else -2 if price<conv<base else 1 if conv>base else -1
        return _ind("ICHIMOKU",round(conv,4),"BUY" if s>0 else "SELL",s,"Ichimoku alignment")
    except: return _ind("ICHIMOKU",0,"NEUTRAL",0,"Error")
def volume_sig(c,v):
    try:
        avg=float(v.rolling(20).mean().dropna().iloc[-1]); curr=float(v.iloc[-1]); ratio=curr/avg if avg>0 else 1; pc=(float(c.iloc[-1])-float(c.iloc[-2]))/float(c.iloc[-2])*100; s=2 if ratio>2 and pc>0 else -2 if ratio>2 and pc<0 else (1 if pc>0 else -1) if ratio>1.5 else 0
        return _ind("VOLUME",round(ratio,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"Volume {ratio:.1f}x")
    except: return _ind("VOLUME",1,"NEUTRAL",0,"Error")
def atr_vol(h,l,c):
    try:
        atr=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1]); price=float(c.iloc[-1]); pct=atr/price*100; sig="ALERT" if pct>3 else "INFO" if pct<0.5 else "NEUTRAL"
        return _ind("ATR_VOLATILITY",round(pct,3),sig,0,f"ATR={pct:.2f}%",atr_abs=round(atr,4))
    except: return _ind("ATR_VOLATILITY",1,"NEUTRAL",0,"Error")
def cci(h,l,c):
    try:
        v=float(ta.trend.CCIIndicator(h,l,c,20).cci().dropna().iloc[-1]); s=2 if v<-150 else 1 if v<-80 else -2 if v>150 else -1 if v>80 else 0
        return _ind("CCI",round(v,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"CCI {v:.1f}")
    except: return _ind("CCI",0,"NEUTRAL",0,"Error")
def williams_r(h,l,c):
    try:
        v=float(ta.momentum.WilliamsRIndicator(h,l,c,14).williams_r().dropna().iloc[-1]); s=2 if v<-85 else 1 if v<-70 else -2 if v>-15 else -1 if v>-30 else 0
        return _ind("WILLIAMS_R",round(v,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"%R {v:.1f}")
    except: return _ind("WILLIAMS_R",-50,"NEUTRAL",0,"Error")
def mfi(h,l,c,v):
    try:
        val=float(ta.volume.MFIIndicator(h,l,c,v,14).money_flow_index().dropna().iloc[-1]); s=2 if val<20 else 1 if val<35 else -2 if val>80 else -1 if val>65 else 0
        return _ind("MFI",round(val,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"MFI {val:.1f}")
    except: return _ind("MFI",50,"NEUTRAL",0,"Error")
def donchian(h,l,c):
    try:
        hi=float(h.rolling(20).max().iloc[-2]); lo=float(l.rolling(20).min().iloc[-2]); price=float(c.iloc[-1]); s=2 if price>hi else -2 if price<lo else 0
        return _ind("DONCHIAN_BREAKOUT",round(price,4),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,"20-bar breakout" if s else "Inside channel")
    except: return _ind("DONCHIAN_BREAKOUT",0,"NEUTRAL",0,"Error")
def keltner(h,l,c):
    try:
        kc=ta.volatility.KeltnerChannel(h,l,c,20,10); price=float(c.iloc[-1]); up=float(kc.keltner_channel_hband().dropna().iloc[-1]); dn=float(kc.keltner_channel_lband().dropna().iloc[-1]); mid=float(kc.keltner_channel_mband().dropna().iloc[-1]); s=2 if price>up else -2 if price<dn else 1 if price>mid else -1
        return _ind("KELTNER",round(price,4),"BUY" if s>0 else "SELL",s,"Keltner channel position")
    except: return _ind("KELTNER",0,"NEUTRAL",0,"Error")
def choppiness(h,l,c):
    try:
        tr=pd.concat([(h-l),(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1); n=14; chop=100*np.log10(tr.rolling(n).sum()/(h.rolling(n).max()-l.rolling(n).min()))/np.log10(n); val=float(chop.dropna().iloc[-1]); s=0; sig="NEUTRAL"
        return _ind("CHOPPINESS",round(val,2),sig,s,"Trending" if val<38 else "Choppy" if val>61 else "Normal",tradeable=val<61)
    except: return _ind("CHOPPINESS",50,"NEUTRAL",0,"Error",tradeable=True)
def roc(c):
    try:
        val=float(ta.momentum.ROCIndicator(c,12).roc().dropna().iloc[-1]); s=2 if val>6 else 1 if val>1 else -2 if val<-6 else -1 if val<-1 else 0
        return _ind("ROC",round(val,2),"BUY" if s>0 else "SELL" if s<0 else "NEUTRAL",s,f"ROC {val:.2f}%")
    except: return _ind("ROC",0,"NEUTRAL",0,"Error")
def _confidence_quality(inds, conf):
    votes=[i for i in inds if abs(float(i.get("score",0) or 0))>0]
    buy=sum(1 for i in votes if i.get("score",0)>0); sell=sum(1 for i in votes if i.get("score",0)<0); total=max(1,len(votes)); agreement=max(buy,sell)/total*100; conflict=min(buy,sell)/total*100
    return {"vote_count":len(votes),"buy_votes":buy,"sell_votes":sell,"agreement_pct":round(agreement,2),"conflict_pct":round(conflict,2),"confidence_raw":conf,"confidence_note":"confidence is an estimate, calibrated by evidence and not a guaranteed win probability"}
async def _calibrate_confidence(ticker,atype,timeframe,signal,conf,regime,quality):
    calibrated=float(conf); details={"method":"vote_conflict_and_history","before":round(float(conf),2)}
    if quality["vote_count"]<8: calibrated-=8; details["low_vote_penalty"]=-8
    if quality["conflict_pct"]>35: p=min(18,(quality["conflict_pct"]-35)*0.7); calibrated-=p; details["conflict_penalty"]=-round(p,2)
    if quality["agreement_pct"]>75 and conf>=55: calibrated+=4; details["agreement_boost"]=4
    try:
        q={"ticker":ticker.upper(),"asset_type":atype,"timeframe":timeframe,"regime":regime,"signal":signal,"resolved":True}
        docs=await db["signal_outcomes"].find(q).sort("resolved_at",-1).limit(80).to_list(80)
        if len(docs)>=10:
            wins=sum(1 for d in docs if d.get("outcome")=="WIN" or float(d.get("pnl_pct",0) or 0)>0); wr=wins/len(docs)*100; adj=(wr-50)*0.25; calibrated+=adj; details.update({"samples":len(docs),"historical_win_rate":round(wr,2),"history_adjustment":round(adj,2)})
    except Exception as e: details["history_error"]=str(e)
    calibrated=max(0,min(100,calibrated)); details["after"]=round(calibrated,2); return int(round(calibrated)),details
async def _base_signal(ticker,atype,timeframe,use_ai=False,allow_advanced=False):
    cfg=TF.get(timeframe,TF["swing"]); loop=asyncio.get_event_loop(); df=await loop.run_in_executor(None,partial(_fetch,ticker,atype,cfg["period"],cfg.get("days",365),cfg.get("interval","1d")))
    if df.empty or len(df)<50: return {"ticker":ticker,"asset_type":atype,"timeframe":timeframe,"signal":"HOLD","confidence":0,"error":f"Not enough candle data for {ticker} ({atype}). Received {len(df)} bars; need at least 50.","timestamp":datetime.utcnow().isoformat(),"indicators":[],"bayesian":{},"interval":cfg.get("interval")}
    c=df["close"]; h=df["high"]; l=df["low"]; v=df["volume"]; price=float(c.iloc[-1]); weights=await get_weights(); hilbert_data=calc_hilbert(c)
    inds=[rsi(c),macd(c),ema(c),bollinger(c),stoch(h,l,c),adx(h,l,c),vwap(h,l,c,v),obv(c,v),supertrend(h,l,c),ichimoku(h,l,c),volume_sig(c,v),atr_vol(h,l,c),cci(h,l,c),williams_r(h,l,c),mfi(h,l,c,v),donchian(h,l,c),keltner(h,l,c),choppiness(h,l,c),roc(c),calc_kalman_signal(c),calc_frama(h,l,c),hilbert_data,calc_adaptive_rsi(c,hilbert_data.get("cycle_period",14)),calc_entropy(c),calc_ofi(df["open"],h,l,c,v)]
    entropy_ok=next((i for i in inds if i["indicator"]=="ENTROPY"),{}).get("tradeable",True); chop_ok=next((i for i in inds if i["indicator"]=="CHOPPINESS"),{}).get("tradeable",True)
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
    if not chop_ok and conf<70: conf=int(conf*0.85)
    quality=_confidence_quality(inds,conf); enhancements={}
    if allow_advanced:
        try:
            from services.llm_sentiment import get_llm_sentiment
            llm=await get_llm_sentiment(ticker,atype); enhancements["llm_sentiment"]=llm; llm_score=llm.get("score",0)
            if llm_score!=0:
                llm_label=str(llm.get("signal","NEUTRAL")).upper(); llm_dir="BUY" if llm_label in ("BULLISH","BUY") else "SELL" if llm_label in ("BEARISH","SELL") else "HOLD"; sig_dir="BUY" if "BUY" in sig else "SELL" if "SELL" in sig else "HOLD"
                if llm_dir==sig_dir and llm_dir!="HOLD": conf=max(0,min(100,conf+abs(llm_score)*4))
                elif llm_dir!=sig_dir and llm_dir!="HOLD" and sig_dir!="HOLD": conf=max(0,conf-5)
        except Exception as e: enhancements["llm_sentiment"]={"error":str(e)}
        try:
            from services.volume_profile import get_volume_profile
            vp=await get_volume_profile(ticker,atype); enhancements["volume_profile"]={"poc":vp.get("poc"),"vah":vp.get("vah"),"val":vp.get("val"),"signal":vp.get("signal"),"score":vp.get("score"),"reason":vp.get("reason")}
            if vp.get("score",0)>0 and "BUY" in sig: conf=min(100,conf+3)
            elif vp.get("score",0)<0 and "SELL" in sig: conf=min(100,conf+3)
            elif vp.get("score",0)>0 and "SELL" in sig: conf=max(0,conf-5)
        except Exception as e: enhancements["volume_profile"]={"error":str(e)}
        if atype=="crypto":
            try:
                from services.microstructure import get_microstructure
                micro=await get_microstructure(ticker,atype); enhancements["microstructure"]=micro
                if micro.get("funding_score",0)!=0:
                    if (micro["funding_score"]>0 and "BUY" in sig) or (micro["funding_score"]<0 and "SELL" in sig): conf=min(100,conf+5)
                    else: conf=max(0,conf-8)
            except Exception as e: enhancements["microstructure"]={"error":str(e)}
        try:
            from services.confluence_memory import get_historical_accuracy
            mem=await get_historical_accuracy(inds,regime,entropy_ok); enhancements["confluence_memory"]=mem
            if mem.get("has_history"): conf=max(0,min(100,conf+mem.get("confidence_boost",0)))
        except Exception as e: enhancements["confluence_memory"]={"error":str(e)}
    conf,calibration=await _calibrate_confidence(ticker,atype,timeframe,sig,conf,regime,quality); quality["confidence_calibrated"]=conf
    if conf<40: sig="HOLD"
    try: atr_val=float(ta.volatility.AverageTrueRange(h,l,c,14).average_true_range().dropna().iloc[-1])
    except: atr_val=price*0.02
    sl=price*(1-cfg["sl"]*atr_val/price) if "BUY" in sig else price*(1+cfg["sl"]*atr_val/price); tp=price*(1+cfg["tp"]*atr_val/price) if "BUY" in sig else price*(1-cfg["tp"]*atr_val/price)
    return {"ticker":ticker,"asset_type":atype,"timeframe":timeframe,"interval":cfg.get("interval"),"signal":sig,"confidence":conf,"price":round(price,4),"sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),"bars":len(df),"regime":regime,"indicators":inds,"bayesian":bv,"quality":quality,"calibration":calibration,"enhancements":enhancements,"timestamp":datetime.utcnow().isoformat()}
def _dir(sig):
    s=str(sig or "").upper()
    return "BUY" if "BUY" in s else "SELL" if "SELL" in s else "HOLD"
async def _mtf_confirm(ticker,atype,base_timeframe,base_signal,base_conf,use_ai=False):
    frames=MTF_CONFIRMATIONS.get(base_timeframe,[]); confirmations=[]
    base_dir=_dir(base_signal); agree=0; oppose=0; hold=0; errors=0
    if base_dir=="HOLD" or not frames:
        return {"enabled":bool(frames),"base_timeframe":base_timeframe,"confirmations":[],"agreement":0,"decision":"not_required" if not frames else "base_hold","confidence_adjustment":0}
    for tf in frames:
        r=await _base_signal(ticker,atype,tf,use_ai=False,allow_advanced=False)
        d=_dir(r.get("signal")); c=float(r.get("confidence",0) or 0)
        confirmations.append({"timeframe":tf,"interval":r.get("interval"),"signal":r.get("signal"),"direction":d,"confidence":c,"error":r.get("error")})
        if r.get("error"): errors+=1
        elif d==base_dir and c>=45: agree+=1
        elif d in {"BUY","SELL"} and d!=base_dir and c>=45: oppose+=1
        else: hold+=1
    usable=max(1,len(frames)-errors); agreement=agree/usable
    adj=0; decision="neutral"
    if oppose>=1 and agree==0:
        adj=-22; decision="blocked_by_mtf_opposition"
    elif oppose>=1:
        adj=-12; decision="reduced_by_mtf_conflict"
    elif agree==len(frames):
        adj=8; decision="boosted_by_full_mtf_agreement"
    elif agree>=1:
        adj=4; decision="boosted_by_partial_mtf_agreement"
    else:
        adj=-8; decision="reduced_by_no_mtf_confirmation"
    return {"enabled":True,"base_timeframe":base_timeframe,"confirmations":confirmations,"agreement":round(agreement,3),"agree":agree,"oppose":oppose,"hold":hold,"errors":errors,"decision":decision,"confidence_adjustment":adj}
async def generate_signal(ticker,atype="stock",timeframe="swing",use_ai=False,use_advanced=True,use_mtf=True):
    result=await _base_signal(ticker,atype,timeframe,use_ai=use_ai,allow_advanced=use_advanced)
    if result.get("error"):
        return result
    if use_mtf:
        mtf=await _mtf_confirm(ticker,atype,timeframe,result.get("signal"),result.get("confidence",0),use_ai=False)
        result["mtf_confirmation"]=mtf
        adj=float(mtf.get("confidence_adjustment",0) or 0)
        result["confidence"]=int(max(0,min(100,float(result.get("confidence",0) or 0)+adj)))
        result["calibration"]["mtf_adjustment"]=adj
        result["calibration"]["after_mtf"]=result["confidence"]
        if mtf.get("decision")=="blocked_by_mtf_opposition" and result["confidence"]<65:
            result["signal"]="HOLD"; result["blocked_by_mtf"]=True
        elif result["confidence"]<40:
            result["signal"]="HOLD"
    else:
        result["mtf_confirmation"]={"enabled":False,"decision":"disabled"}
    if use_advanced:
        try:
            from services.meta_learner import predict_signal_quality
            meta=await predict_signal_quality(result); result["meta_learner"]=meta
            if meta.get("available"):
                boost=meta.get("boost",0); result["confidence"]=max(0,min(100,result["confidence"]+boost)); result["calibration"]["meta_boost"]=boost; result["calibration"]["final_after_meta"]=result["confidence"]
                if result["confidence"]<40 and result.get("signal")!="HOLD": result["signal"]="HOLD"
        except Exception as e: result["meta_learner"]={"error":str(e)}
    return result
