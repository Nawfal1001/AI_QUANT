"""
Backtest Engine v2.4 — dynamic provider fetcher + adaptive regime strategy mode.
"""
import asyncio, math, os
from datetime import datetime, timedelta
from functools import partial
from io import StringIO
import numpy as np, pandas as pd
from services.strategies import STRATEGIES
from services.logger import child
log = child("backtest")
DEFAULT_FEE_BPS = 5; DEFAULT_SLIPPAGE_BPS = 3; DEFAULT_SPREAD_BPS = 2; _HISTORY_CACHE = {}
YAHOO_SPECIAL={"XAUUSD":"GC=F","XAU_USD":"GC=F","GOLD":"GC=F","GC":"GC=F","GC=F":"GC=F","XAGUSD":"SI=F","XAG_USD":"SI=F","SILVER":"SI=F","SI":"SI=F","SI=F":"SI=F","OIL":"CL=F","WTI":"CL=F","CL":"CL=F","CL=F":"CL=F","BRENT":"BZ=F","BZ":"BZ=F","BZ=F":"BZ=F"}
USD_BASE_YAHOO={"USD_JPY":"JPY=X","USDJPY":"JPY=X","USD_CHF":"CHF=X","USDCHF":"CHF=X","USD_CAD":"CAD=X","USDCAD":"CAD=X","USD_MXN":"MXN=X","USDMXN":"MXN=X"}
REGIME_STRATEGY_MAP={"TRENDING_BULL":"trend_follow","TRENDING_BEAR":"trend_follow","RANGING":"mean_revert","VOLATILE":"breakout","QUIET":"mean_revert"}
def _cache_key(ticker,asset_type,start,end,interval): return f"{asset_type}:{str(ticker).upper()}:{start}:{end}:{interval}"
def _env(*names):
    for n in names:
        v=os.getenv(n)
        if v: return v.strip()
    return ""
def _configured_providers(asset_type):
    default="alpaca,alpha_vantage,stooq,yahoo" if asset_type=="stock" else "oanda,twelvedata,finnhub,yahoo" if asset_type in {"forex","fx"} else "kraken,coinbase,okx,bybit,binance,yahoo"
    raw=_env("MARKET_DATA_PROVIDERS",f"{asset_type.upper()}_DATA_PROVIDERS") or default
    providers=[p.strip().lower() for p in raw.split(",") if p.strip()]
    if asset_type=="stock" and _env("ALPACA_API_KEY","APCA_API_KEY_ID") and "alpaca" not in providers: providers.insert(0,"alpaca")
    if asset_type in {"forex","fx"} and _env("OANDA_API_KEY","OANDA_TOKEN") and "oanda" not in providers: providers.insert(0,"oanda")
    return providers
def _base_crypto(symbol): return str(symbol or "").upper().replace("/USDT","").replace("USDT","").replace("_USDT","").replace("-USD","").replace("/USD","").replace("USD","")
def _to_yahoo_symbol(ticker,asset_type="stock"):
    raw=str(ticker or "").upper().strip().replace("/","_").replace("-","_").replace(" ","").replace(".FX","").replace(".FOREX","")
    if asset_type=="crypto": return f"{_base_crypto(raw)}-USD"
    if raw in YAHOO_SPECIAL: return YAHOO_SPECIAL[raw]
    if asset_type in {"forex","fx"} or ("_" in raw and len(raw.replace("_",""))==6):
        if raw in USD_BASE_YAHOO: return USD_BASE_YAHOO[raw]
        pair=raw.replace("_","")
        if len(pair)==6: return f"{pair}=X"
    return raw
def _normalize_history_frame(hist):
    if hist is None or len(hist)==0: return None
    hist=hist.copy()
    if isinstance(hist.columns,pd.MultiIndex): hist.columns=[c[0] if isinstance(c,tuple) else c for c in hist.columns]
    if "Date" not in hist.columns and "Datetime" not in hist.columns and "date" not in hist.columns and "time" not in hist.columns and "t" not in hist.columns: hist=hist.reset_index()
    cols={str(c).lower().replace(" ","_"):c for c in hist.columns}; date_col=cols.get("date") or cols.get("datetime") or cols.get("time") or cols.get("timestamp") or cols.get("t") or cols.get("index"); open_col=cols.get("open") or cols.get("o"); high_col=cols.get("high") or cols.get("h"); low_col=cols.get("low") or cols.get("l"); close_col=cols.get("close") or cols.get("c") or cols.get("adj_close") or cols.get("adjusted_close"); volume_col=cols.get("volume") or cols.get("v")
    if not all([date_col,open_col,high_col,low_col,close_col]): log.warning(f"history frame missing OHLC columns: {list(hist.columns)}"); return None
    date_series=hist[date_col]
    if pd.api.types.is_numeric_dtype(date_series):
        mx=pd.to_numeric(date_series,errors="coerce").max(); unit="ms" if mx and mx>10_000_000_000 else "s" if mx and mx>10_000_000 else None; dates=pd.to_datetime(date_series,unit=unit,errors="coerce") if unit else pd.to_datetime(date_series,errors="coerce")
    else: dates=pd.to_datetime(date_series,errors="coerce")
    out=pd.DataFrame({"date":dates,"open":pd.to_numeric(hist[open_col],errors="coerce"),"high":pd.to_numeric(hist[high_col],errors="coerce"),"low":pd.to_numeric(hist[low_col],errors="coerce"),"close":pd.to_numeric(hist[close_col],errors="coerce"),"volume":pd.to_numeric(hist[volume_col],errors="coerce") if volume_col else 0}).dropna(subset=["date","open","high","low","close"])
    return out.sort_values("date") if len(out) else None
def _fetch_alpaca_stock_history(ticker,start,end,interval="1d"):
    key=_env("ALPACA_API_KEY","APCA_API_KEY_ID"); secret=_env("ALPACA_SECRET_KEY","APCA_API_SECRET_KEY"); feed=_env("ALPACA_DATA_FEED") or "iex"
    if not key or not secret: return None
    try:
        import httpx
        tf={"1m":"1Min","5m":"5Min","15m":"15Min","30m":"30Min","1h":"1Hour","4h":"4Hour","1d":"1Day"}.get(interval,"1Day"); url=f"https://data.alpaca.markets/v2/stocks/{str(ticker).upper()}/bars"; params={"timeframe":tf,"start":pd.Timestamp(start).isoformat()+"Z","end":pd.Timestamp(end).isoformat()+"Z","feed":feed,"limit":10000,"adjustment":"raw"}; r=httpx.get(url,params=params,headers={"APCA-API-KEY-ID":key,"APCA-API-SECRET-KEY":secret},timeout=20); r.raise_for_status(); bars=r.json().get("bars") or []; return _normalize_history_frame(pd.DataFrame(bars)) if bars else None
    except Exception as e: log.warning(f"Alpaca stock data failed for {ticker}: {e}"); return None
def _fetch_yahoo_history(symbol,start,end,interval="1d"):
    try:
        import yfinance as yf
        for method in ("download","ticker"):
            hist=yf.download(symbol,start=start,end=end,interval=interval,progress=False,auto_adjust=False,threads=False) if method=="download" else yf.Ticker(symbol).history(start=start,end=end,interval=interval,auto_adjust=False,raise_errors=False); df=_normalize_history_frame(hist)
            if df is not None and len(df)>0: return df
        log.warning(f"Yahoo returned 0 candles for {symbol}")
    except Exception as e: log.warning(f"Yahoo fetch failed for {symbol}: {e}")
    return None
def _fetch_stooq_stock_history(ticker,start,end):
    try:
        import httpx
        symbol=str(ticker).lower().replace(".","-")
        if "." not in symbol: symbol=f"{symbol}.us"
        url=f"https://stooq.com/q/d/l/?s={symbol}&d1={pd.Timestamp(start).strftime('%Y%m%d')}&d2={pd.Timestamp(end).strftime('%Y%m%d')}&i=d"; r=httpx.get(url,timeout=15); r.raise_for_status()
        if not r.text or "No data" in r.text or len(r.text.splitlines())<2: return None
        return _normalize_history_frame(pd.read_csv(StringIO(r.text)))
    except Exception as e: log.warning(f"Stooq fallback failed for {ticker}: {e}"); return None
def _fetch_alpha_vantage_stock_history(ticker,start,end,interval="1d"):
    key=_env("ALPHA_VANTAGE_API_KEY","ALPHAVANTAGE_API_KEY")
    if not key: return None
    try:
        import httpx
        is_daily=interval in {"1d","1D","day","daily"}; params={"function":"TIME_SERIES_DAILY_ADJUSTED","symbol":ticker,"outputsize":"full","apikey":key} if is_daily else {"function":"TIME_SERIES_INTRADAY","symbol":ticker,"interval":"15min","outputsize":"full","apikey":key}; time_key="Time Series (Daily)" if is_daily else "Time Series (15min)"; r=httpx.get("https://www.alphavantage.co/query",params=params,timeout=20); r.raise_for_status(); series=r.json().get(time_key) or {}; rows=[]; start_ts=pd.Timestamp(start).tz_localize(None); end_ts=pd.Timestamp(end).tz_localize(None)+pd.Timedelta(days=1)
        for dt,vals in series.items():
            ts=pd.Timestamp(dt).tz_localize(None)
            if start_ts<=ts<=end_ts: rows.append({"date":ts,"open":vals.get("1. open"),"high":vals.get("2. high"),"low":vals.get("3. low"),"close":vals.get("4. close") or vals.get("5. adjusted close"),"volume":vals.get("6. volume") or vals.get("5. volume") or 0})
        return _normalize_history_frame(pd.DataFrame(rows)) if rows else None
    except Exception as e: log.warning(f"Alpha Vantage stock fallback failed for {ticker}: {e}"); return None
def _fetch_oanda_forex_history(ticker,start,end,interval="1d"):
    token=_env("OANDA_API_KEY","OANDA_TOKEN"); account_type=(_env("OANDA_ENV","OANDA_ACCOUNT_TYPE") or "practice").lower()
    if not token: return None
    try:
        import httpx
        instr=str(ticker).upper().replace("/","_").replace("-","_"); gran={"1m":"M1","5m":"M5","15m":"M15","30m":"M30","1h":"H1","4h":"H4","1d":"D"}.get(interval,"D"); host="https://api-fxpractice.oanda.com" if account_type!="live" else "https://api-fxtrade.oanda.com"; r=httpx.get(f"{host}/v3/instruments/{instr}/candles",params={"from":pd.Timestamp(start).isoformat()+"Z","to":pd.Timestamp(end).isoformat()+"Z","granularity":gran,"price":"M"},headers={"Authorization":f"Bearer {token}"},timeout=20); r.raise_for_status(); rows=[]
        for c in r.json().get("candles",[]):
            if c.get("complete",True): rows.append({"date":c.get("time"),"open":c.get("mid",{}).get("o"),"high":c.get("mid",{}).get("h"),"low":c.get("mid",{}).get("l"),"close":c.get("mid",{}).get("c"),"volume":c.get("volume",0)})
        return _normalize_history_frame(pd.DataFrame(rows)) if rows else None
    except Exception as e: log.warning(f"Oanda forex data failed for {ticker}: {e}"); return None
def _fetch_stock_history(ticker,start,end,interval="1d"):
    symbol=_to_yahoo_symbol(ticker,"stock")
    for p in _configured_providers("stock"):
        df={"alpaca":lambda:_fetch_alpaca_stock_history(symbol,start,end,interval),"alpha_vantage":lambda:_fetch_alpha_vantage_stock_history(symbol,start,end,interval),"stooq":lambda:_fetch_stooq_stock_history(symbol,start,end),"yahoo":lambda:_fetch_yahoo_history(symbol,start,end,interval)}.get(p,lambda:None)()
        if df is not None and len(df)>0: return df
    return None
def _fetch_yahoo_asset_history(ticker,asset_type,start,end,interval="1d"): return _fetch_yahoo_history(_to_yahoo_symbol(ticker,asset_type),start,end,interval)
def _fetch_forex_history(ticker,start,end,interval="1d"):
    for p in _configured_providers("forex"):
        df={"oanda":lambda:_fetch_oanda_forex_history(ticker,start,end,interval),"yahoo":lambda:_fetch_yahoo_asset_history(ticker,"forex",start,end,interval)}.get(p,lambda:None)()
        if df is not None and len(df)>0: return df
    return None
def _fetch_crypto_history(symbol,start,end,interval="1d"):
    base=_base_crypto(symbol); tf={"1m":"1m","5m":"5m","15m":"15m","30m":"30m","1d":"1d","4h":"4h","1h":"1h"}.get(interval,"1d")
    try:
        import ccxt
        for ex_name in _configured_providers("crypto"):
            if ex_name=="yahoo":
                df=_fetch_yahoo_history(_to_yahoo_symbol(base,"crypto"),start,end,interval)
                if df is not None and len(df)>0: return df
                continue
            try:
                pair=f"{base}/USD" if ex_name in {"kraken","coinbase"} else f"{base}/USDT"; ex=getattr(ccxt,ex_name)({"enableRateLimit":True}); since_ms=int(pd.Timestamp(start).timestamp()*1000); end_ms=int(pd.Timestamp(end).timestamp()*1000); bars=[]; cursor=since_ms
                while cursor<end_ms:
                    chunk=ex.fetch_ohlcv(pair,tf,since=cursor,limit=1000)
                    if not chunk: break
                    bars.extend(chunk); cursor=chunk[-1][0]+1
                    if len(chunk)<1000: break
                if bars:
                    df=pd.DataFrame(bars,columns=["ts","open","high","low","close","volume"]); df["date"]=pd.to_datetime(df["ts"],unit="ms"); df=df[df["date"]<=pd.Timestamp(end)]; return df[["date","open","high","low","close","volume"]]
            except Exception as e: log.warning(f"ccxt {ex_name} failed for {base}: {e}")
    except Exception as e: log.warning(f"ccxt unavailable for {base}: {e}")
    return _fetch_yahoo_history(_to_yahoo_symbol(base,"crypto"),start,end,interval)
async def fetch_history(ticker,asset_type,start,end,interval="1d"):
    at=str(asset_type or "stock").lower(); key=_cache_key(ticker,at,start,end,interval); cached=_HISTORY_CACHE.get(key); now=datetime.utcnow().timestamp()
    if cached and now-cached["ts"]<900: return cached["df"].copy() if cached["df"] is not None else None
    loop=asyncio.get_event_loop()
    if at=="crypto": df=await loop.run_in_executor(None,partial(_fetch_crypto_history,ticker,start,end,interval))
    elif at in {"forex","fx"}: df=await loop.run_in_executor(None,partial(_fetch_forex_history,ticker,start,end,interval))
    elif at in {"gold","oil","metal","metals","commodity","future","futures"}: df=await loop.run_in_executor(None,partial(_fetch_yahoo_asset_history,ticker,at,start,end,interval))
    else: df=await loop.run_in_executor(None,partial(_fetch_stock_history,ticker,start,end,interval))
    _HISTORY_CACHE[key]={"ts":now,"df":df.copy() if df is not None else None}; return df
def _apply_costs(price, side, fee_bps, slip_bps, spread_bps):
    cost_pct=(slip_bps+spread_bps)/10000; fee_pct=fee_bps/10000
    return price*(1+cost_pct)*(1+fee_pct) if side=="BUY" else price*(1-cost_pct)*(1-fee_pct)
def _detect_backtest_regime(window):
    try:
        if window is None or len(window)<50: return "RANGING",30.0
        close=window["close"].astype(float); high=window["high"].astype(float); low=window["low"].astype(float); ret=close.pct_change().dropna(); recent_ret=float(ret.iloc[-20:].mean()) if len(ret)>=20 else float(ret.mean()); recent_vol=float(ret.iloc[-20:].std()) if len(ret)>=20 else float(ret.std()); atr_pct=float(((high-low).rolling(14).mean().iloc[-1]/close.iloc[-1])*100); ema_fast=close.ewm(span=12,adjust=False).mean().iloc[-1]; ema_slow=close.ewm(span=26,adjust=False).mean().iloc[-1]; trend_strength=abs(ema_fast-ema_slow)/close.iloc[-1]*100
        if atr_pct>1.8 and trend_strength>0.25: return "VOLATILE",round(min(90.0,55.0+atr_pct*8),1)
        if trend_strength>0.35 and recent_ret>recent_vol*0.25: return "TRENDING_BULL",round(min(90.0,55.0+trend_strength*30),1)
        if trend_strength>0.35 and recent_ret< -recent_vol*0.25: return "TRENDING_BEAR",round(min(90.0,55.0+trend_strength*30),1)
        if atr_pct<0.35 and trend_strength<0.15: return "QUIET",55.0
        return "RANGING",55.0
    except Exception: return "RANGING",30.0
def _pick_adaptive_strategy(regime, fallback="ensemble", regime_strategy_map=None):
    mp={**REGIME_STRATEGY_MAP, **(regime_strategy_map or {})}; picked=mp.get(regime) or fallback
    return picked if picked in STRATEGIES else (fallback if fallback in STRATEGIES else "ensemble")
async def run_backtest(ticker: str, asset_type: str = "stock", start_date: str = None, end_date: str = None, interval: str = "1d", initial_capital: float = 10000, risk_per_trade: float = 0.02, min_confidence: int = 55, sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0, fee_bps: float = DEFAULT_FEE_BPS, slippage_bps: float = DEFAULT_SLIPPAGE_BPS, spread_bps: float = DEFAULT_SPREAD_BPS, max_hold_bars: int = 30, strategy: str = "ensemble", custom_strategy_def: dict = None, strategy_mode: str = "static", adaptive_regime: bool = False, regime_strategy_map: dict = None, strategy_params: dict = None):
    adaptive_regime = adaptive_regime or strategy_mode in {"adaptive","adaptive_regime","regime"}
    if custom_strategy_def is not None and not adaptive_regime:
        from services.custom_strategy import run_custom_strategy
        strategy_name=custom_strategy_def.get("name","custom")
        def static_signal_fn(window): return run_custom_strategy(custom_strategy_def,window)
    elif strategy == "universal" and strategy_params and not adaptive_regime:
        from services.universal_strategy import make_universal_fn
        static_signal_fn=make_universal_fn(strategy_params); strategy_name="universal"
    else:
        if strategy not in STRATEGIES: return {"error":f"Unknown strategy: {strategy}. Available: {list(STRATEGIES.keys())}"}
        static_signal_fn=STRATEGIES[strategy]; strategy_name=strategy
    if not end_date: end_date=datetime.now().strftime("%Y-%m-%d")
    if not start_date: start_date=(datetime.now()-timedelta(days=365)).strftime("%Y-%m-%d")
    df=await fetch_history(ticker,asset_type,start_date,end_date,interval)
    if df is None or len(df)<60: return {"error":f"Insufficient history for {ticker}","bars":0 if df is None else len(df)}
    capital=initial_capital; equity_curve=[{"date":str(df["date"].iloc[0])[:10],"equity":capital}]; drawdown_curve=[{"date":str(df["date"].iloc[0])[:10],"dd_pct":0}]; trades=[]; open_position=None; bars_since_entry=0; peak_equity=capital; regime_counts={}; strategy_counts={}; switch_count=0; last_strategy=None; last_regime=None
    for i in range(50,len(df)):
        row=df.iloc[i]; sig_window=df.iloc[max(0,i-50):i]; regime="STATIC"; regime_confidence=None; strategy_used=strategy_name
        if adaptive_regime:
            regime,regime_confidence=_detect_backtest_regime(sig_window); strategy_used=_pick_adaptive_strategy(regime,strategy,regime_strategy_map); signal_fn=STRATEGIES[strategy_used]
            if last_strategy and strategy_used!=last_strategy: switch_count+=1
            last_strategy=strategy_used; last_regime=regime; regime_counts[regime]=regime_counts.get(regime,0)+1; strategy_counts[strategy_used]=strategy_counts.get(strategy_used,0)+1; sig=signal_fn(sig_window); sig["regime"]=regime; sig["regime_confidence"]=regime_confidence; sig["strategy_used"]=strategy_used
        else:
            sig=static_signal_fn(sig_window); sig.setdefault("strategy_used",strategy_name)
        price=float(row["close"]); high=float(row["high"]); low=float(row["low"]); atr=price*(float(sig.get("atr_pct",1) or 1)/100)
        if open_position:
            bars_since_entry+=1; exit_reason=None; exit_price=None
            if open_position["side"]=="BUY":
                if low<=open_position["sl"]: exit_price,exit_reason=open_position["sl"],"SL"
                elif high>=open_position["tp"]: exit_price,exit_reason=open_position["tp"],"TP"
                elif bars_since_entry>=max_hold_bars: exit_price,exit_reason=price,"TIME"
            else:
                if high>=open_position["sl"]: exit_price,exit_reason=open_position["sl"],"SL"
                elif low<=open_position["tp"]: exit_price,exit_reason=open_position["tp"],"TP"
                elif bars_since_entry>=max_hold_bars: exit_price,exit_reason=price,"TIME"
            if not exit_reason and sig.get("confidence",0)>=min_confidence:
                if open_position["side"]=="BUY" and "SELL" in sig.get("signal",""): exit_price,exit_reason=price,"REVERSAL"
                elif open_position["side"]=="SELL" and "BUY" in sig.get("signal",""): exit_price,exit_reason=price,"REVERSAL"
            if exit_reason:
                exec_exit=_apply_costs(exit_price,"SELL" if open_position["side"]=="BUY" else "BUY",fee_bps,slippage_bps,spread_bps); pnl=(exec_exit-open_position["entry_price_net"])*open_position["qty"] if open_position["side"]=="BUY" else (open_position["entry_price_net"]-exec_exit)*open_position["qty"]; capital+=pnl
                trades.append({"entry_date":open_position["entry_date"],"exit_date":str(row["date"])[:10],"side":open_position["side"],"entry_price":round(open_position["entry_price_net"],4),"exit_price":round(exec_exit,4),"qty":round(open_position["qty"],4),"pnl":round(pnl,2),"pnl_pct":round(pnl/(open_position["entry_price_net"]*open_position["qty"])*100,2),"exit_reason":exit_reason,"bars_held":bars_since_entry,"confidence":open_position.get("confidence"),"regime":open_position.get("regime"),"regime_confidence":open_position.get("regime_confidence"),"strategy_used":open_position.get("strategy_used")}); open_position=None; bars_since_entry=0
        if not open_position and sig.get("confidence",0)>=min_confidence and "HOLD" not in sig.get("signal",""):
            side="BUY" if "BUY" in sig["signal"] else "SELL"; risk_dollars=capital*risk_per_trade; stop_distance=max(atr*sl_atr_mult,price*0.005); qty=risk_dollars/stop_distance; entry_price_net=_apply_costs(price,side,fee_bps,slippage_bps,spread_bps); sl=price-stop_distance if side=="BUY" else price+stop_distance; tp=price+atr*tp_atr_mult if side=="BUY" else price-atr*tp_atr_mult; open_position={"side":side,"entry_price":price,"entry_price_net":entry_price_net,"qty":qty,"sl":sl,"tp":tp,"entry_date":str(row["date"])[:10],"confidence":sig.get("confidence"),"regime":sig.get("regime"),"regime_confidence":sig.get("regime_confidence"),"strategy_used":sig.get("strategy_used",strategy_used)}; bars_since_entry=0
        equity=capital
        if open_position: equity+=(price-open_position["entry_price_net"])*open_position["qty"] if open_position["side"]=="BUY" else (open_position["entry_price_net"]-price)*open_position["qty"]
        peak_equity=max(peak_equity,equity); dd_pct=(equity-peak_equity)/peak_equity*100 if peak_equity>0 else 0; equity_curve.append({"date":str(row["date"])[:10],"equity":round(equity,2)}); drawdown_curve.append({"date":str(row["date"])[:10],"dd_pct":round(dd_pct,2)})
    if open_position:
        last_price=float(df["close"].iloc[-1]); exec_exit=_apply_costs(last_price,"SELL" if open_position["side"]=="BUY" else "BUY",fee_bps,slippage_bps,spread_bps); pnl=(exec_exit-open_position["entry_price_net"])*open_position["qty"] if open_position["side"]=="BUY" else (open_position["entry_price_net"]-exec_exit)*open_position["qty"]; capital+=pnl; trades.append({"entry_date":open_position["entry_date"],"exit_date":str(df["date"].iloc[-1])[:10],"side":open_position["side"],"entry_price":round(open_position["entry_price_net"],4),"exit_price":round(exec_exit,4),"qty":round(open_position["qty"],4),"pnl":round(pnl,2),"pnl_pct":round(pnl/(open_position["entry_price_net"]*open_position["qty"])*100,2),"exit_reason":"EOT","bars_held":bars_since_entry,"confidence":open_position.get("confidence"),"regime":open_position.get("regime"),"regime_confidence":open_position.get("regime_confidence"),"strategy_used":open_position.get("strategy_used")})
    wins=[t for t in trades if t["pnl"]>0]; losses=[t for t in trades if t["pnl"]<=0]; total=len(trades); win_rate=len(wins)/total*100 if total else 0; gross_profit=sum(t["pnl"] for t in wins); gross_loss=abs(sum(t["pnl"] for t in losses)); profit_factor=gross_profit/gross_loss if gross_loss>0 else (gross_profit if gross_profit else 0); avg_win=gross_profit/len(wins) if wins else 0; avg_loss=gross_loss/len(losses) if losses else 0; expectancy=(win_rate/100)*avg_win-(1-win_rate/100)*avg_loss
    eq_series=pd.Series([e["equity"] for e in equity_curve]); returns=eq_series.pct_change().dropna(); sharpe=(returns.mean()/returns.std()*math.sqrt(252)) if returns.std()>0 else 0; downside=returns[returns<0]; sortino=(returns.mean()/downside.std()*math.sqrt(252)) if len(downside)>0 and downside.std()>0 else 0; rolling_max=eq_series.cummax(); drawdowns=(eq_series-rolling_max)/rolling_max*100; max_dd=float(drawdowns.min()) if len(drawdowns) else 0; days=(pd.Timestamp(end_date)-pd.Timestamp(start_date)).days; years=days/365.25 if days>0 else 1; cagr=((capital/initial_capital)**(1/years)-1)*100 if years>0 else 0
    by_regime={}; by_strategy={}
    for t in trades:
        rg=t.get("regime") or "STATIC"; st=t.get("strategy_used") or strategy_name
        for bucket,key in ((by_regime,rg),(by_strategy,st)):
            b=bucket.setdefault(key,{"trades":0,"pnl":0,"wins":0}); b["trades"]+=1; b["pnl"]+=t["pnl"]; b["wins"]+=1 if t["pnl"]>0 else 0
    for bucket in (by_regime,by_strategy):
        for b in bucket.values(): b["pnl"]=round(b["pnl"],2); b["win_rate"]=round(b["wins"]/b["trades"]*100,2) if b["trades"] else 0
    return {"ticker":ticker,"asset_type":asset_type,"strategy":strategy_name,"strategy_mode":"adaptive_regime" if adaptive_regime else "static","adaptive_regime":adaptive_regime,"start_date":start_date,"end_date":end_date,"interval":interval,"bars":len(df),"capital_start":initial_capital,"capital_end":round(capital,2),"total_return_pct":round((capital/initial_capital-1)*100,2),"cagr_pct":round(cagr,2),"total_trades":total,"wins":len(wins),"losses":len(losses),"win_rate":round(win_rate,2),"profit_factor":round(profit_factor,2),"sharpe":round(sharpe,2),"sortino":round(sortino,2),"max_drawdown":round(max_dd,2),"avg_win":round(avg_win,2),"avg_loss":round(avg_loss,2),"expectancy":round(expectancy,2),"gross_profit":round(gross_profit,2),"gross_loss":round(gross_loss,2),"equity_curve":equity_curve,"drawdown_curve":drawdown_curve,"trades":trades,"regime_summary":{"regime_counts":regime_counts,"strategy_counts":strategy_counts,"strategy_switches":switch_count,"by_regime":by_regime,"by_strategy":by_strategy,"mapping":{**REGIME_STRATEGY_MAP,**(regime_strategy_map or {})}},"params":{"min_confidence":min_confidence,"risk_per_trade":risk_per_trade,"sl_atr_mult":sl_atr_mult,"tp_atr_mult":tp_atr_mult,"fee_bps":fee_bps,"slippage_bps":slippage_bps,"spread_bps":spread_bps,"max_hold_bars":max_hold_bars},"status":"completed"}
async def run_compare(ticker,asset_type,start_date,end_date,interval,initial_capital,strategies:list,**kwargs):
    results=await asyncio.gather(*[run_backtest(ticker,asset_type,start_date,end_date,interval,initial_capital,strategy=s,**kwargs) for s in strategies]); out={"ticker":ticker,"strategies":{}}
    for r in results:
        s=r.get("strategy","unknown"); out["strategies"][s]={"error":r["error"]} if "error" in r else {"total_return_pct":r["total_return_pct"],"sharpe":r["sharpe"],"max_drawdown":r["max_drawdown"],"win_rate":r["win_rate"],"profit_factor":r["profit_factor"],"total_trades":r["total_trades"],"expectancy":r["expectancy"],"strategy_mode":r.get("strategy_mode"),"regime_summary":r.get("regime_summary"),"equity_curve":r["equity_curve"],"drawdown_curve":r["drawdown_curve"]}
    return out
