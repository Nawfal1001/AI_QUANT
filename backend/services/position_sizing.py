import numpy as np, asyncio
from database import db

def kelly(win_rate,avg_win,avg_loss,fraction=0.5):
    if win_rate<=0 or win_rate>=1: return {"error":"Win rate 0-1"}
    if avg_loss>=0: return {"error":"avg_loss must be negative"}
    p=win_rate; q=1-p; b=abs(avg_win)/abs(avg_loss)
    fk=max(0,(p*b-q)/b); ev=p*avg_win+q*avg_loss
    return {"full_kelly":round(fk,4),"half_kelly":round(fk*0.5,4),"adjusted_kelly":round(fk*fraction,4),"position_pct":round(min(fk*fraction*100,25),2),"expected_value":round(ev,4),"win_loss_ratio":round(b,3),"recommendation":"TRADE" if ev>0 else "SKIP"}

def monte_carlo(history,capital,proposed_pct,max_dd=20.0,n=1000):
    if len(history)<10: return {"approved":True,"final_position_pct":proposed_pct,"reason":"Not enough history","simulated_max_dd":None}
    ret=np.array(history); dds=[]
    for _ in range(n):
        eq=capital*(1+np.random.choice(ret,size=len(ret),replace=True)*proposed_pct/100).cumprod()
        rm=np.maximum.accumulate(eq); dds.append(abs(((eq-rm)/rm*100).min()))
    dd95=np.percentile(dds,95); worst=np.percentile(dds,99)
    if dd95>max_dd:
        scale=max_dd/dd95; final=proposed_pct*scale
        return {"approved":False,"proposed_pct":round(proposed_pct,2),"final_position_pct":round(max(0.1,final),2),"simulated_max_dd":round(dd95,2),"worst_case_dd":round(worst,2),"reason":f"Scaled {proposed_pct:.1f}%→{max(0.1,final):.1f}% DD={dd95:.1f}%"}
    return {"approved":True,"proposed_pct":round(proposed_pct,2),"final_position_pct":round(proposed_pct,2),"simulated_max_dd":round(dd95,2),"worst_case_dd":round(worst,2),"reason":f"OK P95 DD={dd95:.1f}%"}

def dar(equity_curve,conf=0.95):
    if len(equity_curve)<10: return {"dar_95":None,"max_drawdown":None,"error":"Not enough data"}
    eq=np.array(equity_curve); rm=np.maximum.accumulate(eq); dds=abs((eq-rm)/rm*100)
    return {"dar_95":round(float(np.percentile(dds,conf*100)),2),"max_drawdown":round(float(dds.max()),2),"avg_drawdown":round(float(dds.mean()),2),"current_dd":round(float(dds[-1]),2),"risk_level":"HIGH" if float(np.percentile(dds,conf*100))>20 else "MEDIUM" if float(np.percentile(dds,conf*100))>10 else "LOW"}

REGIME_MULT={"TRENDING_BULL":1.0,"TRENDING_BEAR":1.0,"RANGING":0.7,"VOLATILE":0.4,"QUIET":0.5}

async def optimal_position(ticker,atype,signal,capital,win_rate,avg_win,avg_loss,regime,history,equity_curve,fraction=0.5,max_dd=20.0):
    k=kelly(win_rate,avg_win,avg_loss,fraction)
    if k.get("recommendation")=="SKIP": return {"recommended_pct":0,"reason":"Negative EV","kelly":k}
    loop=asyncio.get_event_loop()
    mc=await loop.run_in_executor(None,monte_carlo,history,capital,k["position_pct"],max_dd,1000)
    mult=REGIME_MULT.get(regime,0.7); final=mc["final_position_pct"]*mult
    d=dar(equity_curve) if len(equity_curve)>10 else {}
    return {"ticker":ticker,"signal":signal,"regime":regime,"capital":capital,"recommended_pct":round(final,2),"position_usd":round(capital*final/100,2),"pipeline":{"kelly":k,"monte_carlo":mc,"regime_mult":mult},"risk_metrics":d}
