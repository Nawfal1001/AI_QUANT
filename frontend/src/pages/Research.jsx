import React, { useState } from 'react'
import { api } from '@/store/auth'
import { Search, Sparkles, MessageCircle, TrendingUp, RefreshCw } from 'lucide-react'

const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const input = { background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '9px 12px', color: '#e2e8f0', fontSize: 13, outline: 'none', width: '100%' }
const btnPrimary = { background: '#1f6feb', border: 'none', borderRadius: 8, padding: '9px 16px', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6 }

const PRESETS = [
  'What are the best swing trade setups in tech right now?',
  'Analyze BTC price action and key levels',
  'Compare AAPL vs MSFT fundamentals',
  'What macro factors should I watch this week?',
]

export default function Research() {
  const [query, setQuery] = useState('')
  const [ticker, setTicker] = useState('')
  const [assetType, setAssetType] = useState('stock')
  const [thread, setThread] = useState([]) // {role, text}
  const [loading, setLoading] = useState(false)
  const [aiSignal, setAiSignal] = useState(null)

  async function run() {
    if (!query) return
    setLoading(true)
    setThread(t => [...t, { role: 'user', text: query, ticker: ticker || null }])
    try {
      const r = await api.post('/ai/research', { query, ticker: ticker || null, asset_type: assetType })
      const reply = r.data?.response || r.data?.message || 'No response'
      setThread(t => [...t, { role: 'ai', text: reply }])
      setQuery('')
    } catch (e) {
      setThread(t => [...t, { role: 'ai', text: 'AI unavailable. Check Gemini API key in .env' }])
    }
    setLoading(false)
  }

  async function getSignalAI() {
    if (!ticker) return
    setLoading(true); setAiSignal(null)
    try {
      const r = await api.get(`/ai/signal/${ticker.toUpperCase()}?asset_type=${assetType}`)
      setAiSignal(r.data)
    } catch { setAiSignal({ error: 'AI signal unavailable' }) }
    setLoading(false)
  }

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 6 }}>🔍 AI Research</h1>
      <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 18 }}>Ask Gemini anything about markets, get AI-powered analysis</div>

      {/* Quick AI signal */}
      <div style={{ ...card, marginBottom: 14 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <Sparkles size={14} color="#bc8cff" /> Quick AI Signal
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>Ticker</div>
            <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="AAPL or BTC" style={input} />
          </div>
          <div style={{ width: 130 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>Type</div>
            <select value={assetType} onChange={e => setAssetType(e.target.value)} style={input}>
              <option value="stock">Stock</option>
              <option value="crypto">Crypto</option>
            </select>
          </div>
          <button onClick={getSignalAI} disabled={loading || !ticker} style={{ ...btnPrimary, opacity: (loading || !ticker) ? 0.6 : 1 }}>
            <TrendingUp size={14} /> Get AI Signal
          </button>
        </div>
        {aiSignal && (
          <div style={{ marginTop: 12, padding: '12px 14px', background: '#0d1117', borderRadius: 8, border: '1px solid #21262d' }}>
            {aiSignal.error ? (
              <div style={{ color: '#f85149', fontSize: 13 }}>{aiSignal.error}</div>
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: aiSignal.score > 0 ? '#3fb950' : aiSignal.score < 0 ? '#f85149' : '#8b949e' }}>
                    {aiSignal.score > 0 ? '🟢 BULLISH' : aiSignal.score < 0 ? '🔴 BEARISH' : '⚪ NEUTRAL'} ({aiSignal.score > 0 ? '+' : ''}{aiSignal.score})
                  </div>
                  <div style={{ fontSize: 11, color: '#8b949e' }}>{aiSignal.confidence}% confidence</div>
                </div>
                <div style={{ fontSize: 12, color: '#8b949e', lineHeight: 1.5 }}>{aiSignal.reason}</div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Chat */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          <MessageCircle size={14} /> Ask AI
        </div>

        {/* Presets */}
        {thread.length === 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>Try one of these:</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {PRESETS.map(p => (
                <button key={p} onClick={() => setQuery(p)} style={{ background: '#21262d', border: '1px solid #30363d', borderRadius: 6, padding: '6px 12px', color: '#8b949e', cursor: 'pointer', fontSize: 12 }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Thread */}
        <div style={{ maxHeight: 400, overflowY: 'auto', marginBottom: 12 }}>
          {thread.map((m, i) => (
            <div key={i} style={{ marginBottom: 10, padding: '10px 12px', background: m.role === 'user' ? '#21262d' : '#0d1117', borderRadius: 8, borderLeft: `3px solid ${m.role === 'user' ? '#58a6ff' : '#bc8cff'}` }}>
              <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>
                {m.role === 'user' ? 'You' : '✨ Gemini AI'}{m.ticker ? ` · ${m.ticker}` : ''}
              </div>
              <div style={{ fontSize: 13, color: '#e2e8f0', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{m.text}</div>
            </div>
          ))}
          {loading && (
            <div style={{ padding: 12, color: '#8b949e', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <RefreshCw size={12} className="spin" /> Thinking…
            </div>
          )}
        </div>

        {/* Input */}
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Enter' && run()} placeholder="Ask about markets, tickers, strategies…" style={input} />
          <button onClick={run} disabled={loading || !query} style={{ ...btnPrimary, opacity: (loading || !query) ? 0.6 : 1 }}>
            <Search size={14} /> Ask
          </button>
        </div>
      </div>

      <style>{`.spin { animation: spin 1s linear infinite } @keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  )
}
