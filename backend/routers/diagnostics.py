import os, time
from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.gemini_utils import generate_content, ping, get_gemini_model_name, get_gemini_api_key
router = APIRouter()

def present(*names):
    return any(bool(os.getenv(n)) for n in names)

def item(name, ok, level='ok', detail=''):
    return {'name': name, 'ok': bool(ok), 'level': level if ok else 'error', 'detail': detail}

@router.get('/health')
async def health(user=Depends(get_current_user)):
    jwt = os.getenv('JWT_SECRET','')
    gem = ping()
    checks = [
        item('JWT_SECRET', bool(jwt and len(jwt) >= 32 and jwt not in {'secret','change_me','tradeai_secret_change_me'}), detail='secure length required'),
        item('MongoDB', present('MONGO_URL','MONGODB_URI'), detail='database connection env'),
        item('CORS_ORIGINS', present('CORS_ORIGINS') or os.getenv('ENVIRONMENT','development')!='production', detail=os.getenv('CORS_ORIGINS','dev default')),
        item('Gemini AI', bool(gem.get('available')), detail=f"{gem.get('model')} · {gem.get('reason')} · key={gem.get('key_source') or 'missing'}"),
        item('Finnhub calendar', present('FINNHUB_API_KEY'), level='warning', detail='economic calendar provider'),
        item('Alpha Vantage', present('ALPHA_VANTAGE_API_KEY'), level='warning', detail='sentiment/market fallback'),
        item('Alpaca', present('ALPACA_API_KEY','APCA_API_KEY_ID'), level='warning', detail='stocks/crypto broker/data'),
        item('Binance', present('BINANCE_API_KEY','BINANCE_SECRET_KEY') or os.getenv('BINANCE_ENABLED'), level='warning', detail='crypto broker/data'),
        item('Oanda', present('OANDA_API_KEY','OANDA_TOKEN'), level='warning', detail='forex broker/data'),
        item('ASI Evolve', present('ASI_EVOLVE_URL','ASI_COLAB_URL'), level='warning', detail='strategy evolution endpoint'),
    ]
    return {'status': 'ok' if all(c['ok'] or c['level']=='warning' for c in checks) else 'degraded', 'gemini': gem, 'live_trading': os.getenv('LIVE_TRADING_ENABLED','false').lower() in {'1','true','yes'}, 'auto_signal_scanner': os.getenv('AUTO_SIGNAL_SCANNER_ENABLED','true'), 'checks': checks}

@router.post('/ai-test')
async def ai_test(req: dict, user=Depends(get_current_user)):
    prompt = req.get('prompt') or 'Reply with OK and one short market risk warning.'
    started = time.time()
    try:
        if not get_gemini_api_key():
            return {'ok': False, 'latency_ms': 0, 'model': get_gemini_model_name(), 'error': 'Gemini key missing'}
        resp = generate_content(prompt)
        text = getattr(resp, 'text', '') or ''
        return {'ok': True, 'latency_ms': int((time.time()-started)*1000), 'model': get_gemini_model_name(), 'response': text}
    except Exception as e:
        return {'ok': False, 'latency_ms': int((time.time()-started)*1000), 'model': get_gemini_model_name(), 'error': str(e)}
