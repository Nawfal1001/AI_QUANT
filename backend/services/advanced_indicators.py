import numpy as np, pandas as pd, ta

def kalman(prices, Q=0.01, R=1.0):
    n=len(prices); x=np.zeros(n); P=np.zeros(n)
    x[0]=prices.iloc[0]; P[0]=1.0
    for t in range(1,n):
        Pp=P[t-1]+Q; K=Pp/(Pp+R); x[t]=x[t-1]+K*(prices.iloc[t]-x[t-1]); P[t]=(1-K)*Pp
    return pd.Series(x,index=prices.index)

def calc_kalman_signal(prices):
    kf=kalman(prices); price=float(prices.iloc[-1]); kfv=float(kf.iloc[-1]); kfp=float(kf.iloc[-2]) if len(kf)>1 else kfv
    gap=(price-kfv)/kfv*100; rising=kfv>kfp
    if price>kfv and rising: s,r=+2,f"Above rising Kalman ({gap:.2f}%)"
    elif price>kfv: s,r=+1,"Above Kalman, flattening"
    elif price<kfv and not rising: s,r=-2,f"Below falling Kalman ({gap:.2f}%)"
    else: s,r=-1,"Below Kalman, flattening"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"KALMAN_EMA","value":round(kfv,4),"signal":sig,"score":s,"reason":r}

def calc_frama(highs, lows, closes, N=16):
    if len(closes)<N*2: return {"indicator":"FRAMA","value":float(closes.iloc[-1]),"signal":"NEUTRAL","score":0,"reason":"Not enough data"}
    frama=pd.Series(index=closes.index,dtype=float); frama.iloc[N-1]=closes.iloc[:N].mean()
    for i in range(N,len(closes)):
        h=N//2; H1=highs.iloc[i-N:i-h].max(); L1=lows.iloc[i-N:i-h].min()
        H2=highs.iloc[i-h:i].max(); L2=lows.iloc[i-h:i].min()
        H3=highs.iloc[i-N:i].max(); L3=lows.iloc[i-N:i].min()
        r1,r2,r3=H1-L1,H2-L2,H3-L3
        if r3==0 or r1+r2==0: frama.iloc[i]=frama.iloc[i-1] if not pd.isna(frama.iloc[i-1]) else closes.iloc[i]; continue
        D=np.clip(np.log(r1+r2)/np.log(r3) if r3>0 else 1.5,1.0,2.0)
        alpha=np.clip(np.exp(-4.6*(D-1.0)),0.01,1.0)
        prev=frama.iloc[i-1] if not pd.isna(frama.iloc[i-1]) else closes.iloc[i]
        frama.iloc[i]=alpha*closes.iloc[i]+(1-alpha)*prev
    fv=float(frama.dropna().iloc[-1]) if not frama.dropna().empty else float(closes.iloc[-1])
    fp=float(frama.dropna().iloc[-2]) if len(frama.dropna())>1 else fv
    price=float(closes.iloc[-1]); rising=fv>fp
    if price>fv and rising: s,r=+2,"Above rising FRAMA"
    elif price>fv: s,r=+1,"Above FRAMA, flattening"
    elif price<fv and not rising: s,r=-2,"Below falling FRAMA"
    else: s,r=-1,"Below FRAMA, flattening"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"FRAMA","value":round(fv,4),"signal":sig,"score":s,"reason":r}

def calc_hilbert(closes):
    try:
        p=closes.values.astype(float); n=len(p)
        if n<40: return {"indicator":"HILBERT","cycle_period":14,"trending":True,"score":0,"signal":"NEUTRAL","reason":"Need more data","value":14}
        sm=np.zeros(n)
        for i in range(3,n): sm[i]=(4*p[i]+3*p[i-1]+2*p[i-2]+p[i-3])/10
        det=np.zeros(n)
        for i in range(4,n): det[i]=(0.0962*sm[i]+0.5769*sm[i-2]-0.5769*sm[i-4]-0.0962*sm[i-6])*(0.5+0.08)
        Q1=np.zeros(n); I1=np.zeros(n)
        for i in range(6,n):
            Q1[i]=(0.0962*det[i]+0.5769*det[i-2]-0.5769*det[i-4]-0.0962*det[i-6])*(0.5+0.08); I1[i]=det[i-3]
        Re=np.zeros(n); Im=np.zeros(n); Per=np.zeros(n)
        for i in range(1,n):
            Re[i]=0.2*(I1[i]*I1[i]+Q1[i]*Q1[i])+0.8*Re[i-1]; Im[i]=0.2*(I1[i]*Q1[i]-Q1[i]*I1[i])+0.8*Im[i-1]
            if Im[i]!=0 and Re[i]!=0: Per[i]=np.clip(2*np.pi/np.arctan(Im[i]/Re[i]),6,50)
            elif i>0: Per[i]=Per[i-1]
        sp=np.zeros(n)
        for i in range(3,n): sp[i]=(Per[i]+Per[i-1]+Per[i-2]+Per[i-3])/4
        cp=int(round(sp[-1])) if sp[-1]>0 else 14; cp=max(6,min(50,cp))
        return {"indicator":"HILBERT","cycle_period":cp,"trending":float(np.std(sp[-10:][sp[-10:]>0]))>3,"score":0,"signal":"INFO","reason":f"Cycle: {cp} bars","value":cp}
    except: return {"indicator":"HILBERT","cycle_period":14,"trending":True,"score":0,"signal":"NEUTRAL","reason":"Error","value":14}

def calc_adaptive_rsi(closes, period=None):
    if period is None: period=calc_hilbert(closes)["cycle_period"]
    period=max(2,period//2)
    try: v=float(ta.momentum.RSIIndicator(closes,period).rsi().dropna().iloc[-1])
    except: v=50
    if v<25: s,r=+2,f"AdaptRSI oversold({v:.1f})"
    elif v<40: s,r=+1,f"AdaptRSI low({v:.1f})"
    elif v>75: s,r=-2,f"AdaptRSI overbought({v:.1f})"
    elif v>60: s,r=-1,f"AdaptRSI high({v:.1f})"
    else: s,r=0,f"AdaptRSI neutral({v:.1f})"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"ADAPTIVE_RSI","value":round(v,2),"signal":sig,"score":s,"reason":r,"rsi_period":period}

def calc_entropy(closes, window=20, bins=10):
    ret=closes.pct_change().dropna()
    if len(ret)<window: return {"indicator":"ENTROPY","value":2.5,"signal":"NEUTRAL","score":0,"reason":"Need data","tradeable":True}
    counts,_=np.histogram(ret.iloc[-window:],bins=bins)
    probs=counts/counts.sum(); probs=probs[probs>0]
    H=float(-np.sum(probs*np.log2(probs))); Hn=H/np.log2(bins)
    if Hn<0.6: s,sig,t=+1,"TRADE",True
    elif Hn>0.85: s,sig,t=-1,"AVOID",False
    else: s,sig,t=0,"CAUTION",True
    return {"indicator":"ENTROPY","value":round(H,4),"normalized":round(Hn,3),"signal":sig,"score":s,"reason":f"Entropy={'predictable' if t else 'random'} H={H:.2f}","tradeable":t}

def calc_ofi(opens, highs, lows, closes, volumes, w=14):
    hl=(highs-lows).replace(0,np.nan)
    bv=volumes*(closes-lows)/hl; sv=volumes*(highs-closes)/hl
    ofi=((bv-sv)/volumes).fillna(0).rolling(w).mean()
    v=float(ofi.dropna().iloc[-1]) if not ofi.dropna().empty else 0
    if v>0.15: s,r=+2,f"Strong buy pressure OFI={v:.3f}"
    elif v>0.05: s,r=+1,f"Mild buy pressure OFI={v:.3f}"
    elif v<-0.15: s,r=-2,f"Strong sell pressure OFI={v:.3f}"
    elif v<-0.05: s,r=-1,f"Mild sell pressure OFI={v:.3f}"
    else: s,r=0,f"Balanced OFI={v:.3f}"
    sig="BUY" if s>0 else "SELL" if s<0 else "NEUTRAL"
    return {"indicator":"ORDER_FLOW","value":round(v,4),"signal":sig,"score":s,"reason":r}

def optimal_trailing_stop(entry, current, atr, elapsed, max_bars, side="long", k=2.0):
    sigma=atr/entry if entry>0 else 0.02
    ratio=min(elapsed/max_bars,1.0) if max_bars>0 else 0.5
    mult=max(0.005,min(0.15,k*sigma*(ratio**0.5)))
    if side=="long": stop=max(entry*(1-mult),current*(1-mult*0.5)); locked=max(0,(current-stop)/entry*100)
    else: stop=min(entry*(1+mult),current*(1+mult*0.5)); locked=max(0,(stop-current)/entry*100)
    return {"optimal_stop":round(stop,4),"locked_pnl_pct":round(locked,3),"multiplier":round(mult,4),"tightness":"tight" if ratio>0.7 else "wide"}
