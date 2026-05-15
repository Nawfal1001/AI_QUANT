"""
Ensemble Meta-Learner using GradientBoosting (LightGBM-like, sklearn-only).
Stacks all indicators into one prediction.
"""
import numpy as np, pickle, base64, asyncio
from datetime import datetime
from database import db
try:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_OK = True
except:
    SKLEARN_OK = False

meta_col = db["meta_learner"]
signals_col = db["signals_log"]

INDICATORS = ["RSI","MACD","EMA_CROSS","BOLLINGER","STOCHASTIC","ADX","VWAP","OBV","SUPERTREND","ICHIMOKU","VOLUME","ATR_VOLATILITY","KALMAN_EMA","FRAMA","ADAPTIVE_RSI","ORDER_FLOW","ENTROPY","HILBERT"]
REGIMES = ["TRENDING_BULL","TRENDING_BEAR","RANGING","VOLATILE","QUIET"]

def features_from_signal(sig):
    feats = []
    ind_map = {i.get("indicator",""):i.get("score",0) for i in sig.get("indicators",[]) if isinstance(i,dict)}
    for name in INDICATORS:
        feats.append(float(ind_map.get(name,0)))
    regime = sig.get("regime","RANGING")
    for r in REGIMES:
        feats.append(1.0 if regime==r else 0.0)
    ent = next((i for i in sig.get("indicators",[]) if isinstance(i,dict) and i.get("indicator")=="ENTROPY"),{})
    feats.append(float(ent.get("normalized",0.5)))
    feats.append(float(sig.get("bayesian",{}).get("p_buy",0.5)))
    feats.append(float(sig.get("confidence",50))/100)
    return feats

async def train_meta_learner(min_samples=50):
    if not SKLEARN_OK: return {"error":"sklearn unavailable"}
    docs = await signals_col.find({"outcome":{"$in":["WIN","LOSS"]}}).to_list(5000)
    if len(docs) < min_samples:
        return {"error":f"Need {min_samples}+ resolved signals, have {len(docs)}"}
    X, y = [], []
    for d in docs:
        try:
            X.append(features_from_signal(d))
            y.append(1 if d.get("outcome")=="WIN" else 0)
        except: continue
    if len(X) < min_samples: return {"error":"Not enough valid samples"}
    X = np.array(X); y = np.array(y)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)
    model = GradientBoostingClassifier(n_estimators=120, max_depth=4, learning_rate=0.07, random_state=42)
    model.fit(Xs, y)
    train_acc = float(model.score(Xs, y))
    # Save serialized model
    model_b64 = base64.b64encode(pickle.dumps(model)).decode()
    scaler_b64 = base64.b64encode(pickle.dumps(scaler)).decode()
    await meta_col.replace_one({"_id":"model"},{"_id":"model","model":model_b64,"scaler":scaler_b64,
        "trained_at":datetime.now().isoformat(),"samples":len(X),"accuracy":round(train_acc,4),
        "feature_importance":{k:float(v) for k,v in zip(INDICATORS+REGIMES+["entropy","bayes_pbuy","confidence"], model.feature_importances_)}
    },upsert=True)
    return {"status":"trained","samples":len(X),"accuracy":round(train_acc*100,2),"wins":int(y.sum()),"losses":int(len(y)-y.sum())}

_cached_model = None
_cached_scaler = None

async def _load_model():
    global _cached_model, _cached_scaler
    if _cached_model is not None: return _cached_model, _cached_scaler
    doc = await meta_col.find_one({"_id":"model"})
    if not doc: return None, None
    _cached_model = pickle.loads(base64.b64decode(doc["model"]))
    _cached_scaler = pickle.loads(base64.b64decode(doc["scaler"]))
    return _cached_model, _cached_scaler

async def predict_signal_quality(signal_dict):
    if not SKLEARN_OK: return {"available":False,"p_win":0.5,"boost":0}
    model, scaler = await _load_model()
    if model is None: return {"available":False,"p_win":0.5,"boost":0,"reason":"Not trained yet"}
    try:
        feats = np.array([features_from_signal(signal_dict)])
        feats_s = scaler.transform(feats)
        p_win = float(model.predict_proba(feats_s)[0,1])
        if p_win >= 0.70: boost = +12
        elif p_win >= 0.60: boost = +6
        elif p_win <= 0.30: boost = -15
        elif p_win <= 0.40: boost = -8
        else: boost = 0
        return {"available":True,"p_win":round(p_win,4),"boost":boost,"recommend":"TAKE" if p_win>=0.55 else "SKIP"}
    except Exception as e:
        return {"available":False,"p_win":0.5,"boost":0,"error":str(e)}

async def get_model_info():
    doc = await meta_col.find_one({"_id":"model"})
    if not doc: return {"trained":False}
    return {"trained":True,"trained_at":doc.get("trained_at"),"samples":doc.get("samples",0),
            "accuracy":doc.get("accuracy",0),"feature_importance":doc.get("feature_importance",{})}
