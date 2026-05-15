"""
Market Microstructure: funding rates, open interest, bid-ask spread analysis.
Crypto-focused via CCXT.
"""
import ccxt, asyncio
from datetime import datetime

def _funding_rate(symbol):
    try:
        ex = ccxt.binanceusdm()
        rates = ex.fetch_funding_rate(f"{symbol}/USDT:USDT")
        return float(rates.get("fundingRate", 0))
    except: return None

def _open_interest(symbol):
    try:
        ex = ccxt.binanceusdm()
        ex.options['defaultType'] = 'future'
        oi = ex.fetch_open_interest(f"{symbol}/USDT")
        return float(oi.get("openInterestAmount", 0))
    except: return None

def _spread_analysis(symbol):
    try:
        ex = ccxt.binance()
        book = ex.fetch_order_book(f"{symbol}/USDT", limit=5)
        bids = book.get("bids", []); asks = book.get("asks", [])
        if not bids or not asks: return None
        best_bid = float(bids[0][0]); best_ask = float(asks[0][0])
        mid = (best_bid + best_ask) / 2
        spread_pct = (best_ask - best_bid) / mid * 100
        return {"best_bid":best_bid,"best_ask":best_ask,"mid":mid,"spread_pct":round(spread_pct,4)}
    except: return None

async def get_microstructure(ticker, atype):
    """Get crypto microstructure data"""
    if atype not in ("crypto",): 
        return {"available":False,"reason":"Microstructure only available for crypto"}
    loop = asyncio.get_event_loop()
    funding = await loop.run_in_executor(None, _funding_rate, ticker)
    oi = await loop.run_in_executor(None, _open_interest, ticker)
    spread = await loop.run_in_executor(None, _spread_analysis, ticker)
    # Generate signals
    funding_signal = "NEUTRAL"; funding_score = 0; funding_reason = ""
    if funding is not None:
        if funding > 0.001:  # >0.1% positive — longs paying shorts heavily
            funding_signal = "SELL"; funding_score = -1
            funding_reason = f"High positive funding {funding*100:.3f}% — longs overcrowded"
        elif funding < -0.0005:  # negative funding — shorts paying longs
            funding_signal = "BUY"; funding_score = +1
            funding_reason = f"Negative funding {funding*100:.3f}% — shorts overcrowded"
        else:
            funding_reason = f"Neutral funding {funding*100:.4f}%"
    # Spread analysis
    spread_signal = "NEUTRAL"; spread_score = 0
    if spread is not None:
        if spread["spread_pct"] > 0.05:
            spread_signal = "CAUTION"
            spread_score = 0  # not a trade signal, but raises slippage concern
    return {
        "available":True,"ticker":ticker,
        "funding_rate":round(funding*100,4) if funding is not None else None,
        "funding_signal":funding_signal,"funding_score":funding_score,"funding_reason":funding_reason,
        "open_interest":oi,
        "spread":spread,
        "spread_signal":spread_signal,"spread_score":spread_score,
        "indicator":"MICROSTRUCTURE","signal":funding_signal,"score":funding_score,"reason":funding_reason,
        "timestamp":datetime.now().isoformat()
    }
