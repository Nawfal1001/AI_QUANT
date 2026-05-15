"""
Reinforcement Learning Agent for auto-trader decisions.
Uses tabular Q-learning (no torch dependency).
State: (regime, confidence_bucket, atr_bucket, recent_pnl_bucket, open_positions_bucket)
Actions: SKIP, ENTER_SMALL, ENTER_NORMAL, ENTER_LARGE
"""
import numpy as np, pickle, base64
from database import db
from datetime import datetime

rl_col = db["rl_agent"]

ACTIONS = ["SKIP","ENTER_SMALL","ENTER_NORMAL","ENTER_LARGE"]
ACTION_SIZES = {"SKIP":0, "ENTER_SMALL":0.5, "ENTER_NORMAL":1.0, "ENTER_LARGE":1.5}

REGIMES = ["TRENDING_BULL","TRENDING_BEAR","RANGING","VOLATILE","QUIET"]

def state_key(regime, confidence, atr_pct, recent_pnl, open_count):
    """Discretize state into a hashable key"""
    r_idx = REGIMES.index(regime) if regime in REGIMES else 2
    c_bucket = min(int(confidence // 10), 9)   # 0-9
    a_bucket = min(int(atr_pct * 2), 9)         # 0-9
    p_bucket = max(-3, min(3, int(recent_pnl // 5)))  # -3 to +3 → 0-6
    o_bucket = min(open_count, 5)
    return f"{r_idx}-{c_bucket}-{a_bucket}-{p_bucket+3}-{o_bucket}"

async def get_q_table():
    doc = await rl_col.find_one({"_id":"q_table"})
    if not doc: return {}
    return doc.get("table", {})

async def save_q_table(table, stats=None):
    await rl_col.replace_one({"_id":"q_table"},{"_id":"q_table","table":table,
        "updated":datetime.now().isoformat(),"stats":stats or {}},upsert=True)

async def get_action(regime, confidence, atr_pct, recent_pnl, open_count, epsilon=0.1):
    """Choose action via epsilon-greedy"""
    table = await get_q_table()
    key = state_key(regime, confidence, atr_pct, recent_pnl, open_count)
    q_vals = table.get(key, [0.0, 0.0, 0.0, 0.0])
    if np.random.random() < epsilon:
        action_idx = np.random.randint(0, 4)
    else:
        action_idx = int(np.argmax(q_vals))
    return {"action": ACTIONS[action_idx], "action_idx": action_idx,
            "size_multiplier": ACTION_SIZES[ACTIONS[action_idx]],
            "q_values": q_vals, "state_key": key, "exploration": np.random.random() < epsilon}

async def update_q(state_key_val, action_idx, reward, next_state_key=None, alpha=0.1, gamma=0.95):
    """Q-learning update: Q(s,a) ← Q(s,a) + α[r + γ·max_a Q(s',a) - Q(s,a)]"""
    table = await get_q_table()
    if state_key_val not in table: table[state_key_val] = [0.0, 0.0, 0.0, 0.0]
    next_max = 0.0
    if next_state_key and next_state_key in table:
        next_max = max(table[next_state_key])
    old_q = table[state_key_val][action_idx]
    new_q = old_q + alpha * (reward + gamma * next_max - old_q)
    table[state_key_val][action_idx] = round(new_q, 4)
    stats = await rl_col.find_one({"_id":"q_table"}) or {}
    upd_count = stats.get("stats",{}).get("updates",0) + 1
    await save_q_table(table, {"updates": upd_count, "states": len(table)})
    return {"old_q":old_q,"new_q":new_q,"delta":new_q-old_q}

async def get_rl_stats():
    doc = await rl_col.find_one({"_id":"q_table"})
    if not doc: return {"trained":False,"states":0,"updates":0}
    table = doc.get("table",{})
    # Find best states
    best_states = []
    for k,vals in table.items():
        best_states.append({"state":k,"best_action":ACTIONS[int(np.argmax(vals))],"q_max":max(vals),"q_values":vals})
    best_states.sort(key=lambda x:x["q_max"],reverse=True)
    return {"trained":True,"states":len(table),"updates":doc.get("stats",{}).get("updates",0),
            "updated":doc.get("updated",""),"top_states":best_states[:10]}
