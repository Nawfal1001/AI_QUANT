import React, { useState } from 'react'
import { api } from '@/store/auth'
import { Search, Zap, Info } from 'lucide-react'
const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const sig_color = (s) => s?.includes('BUY') ? '#3fb950' : s?.includes('SELL') ? '#f85149' : '#8b949e'
const sig_bg = (s) => s?.includes('BUY') ? 'rgba(63,185,80,0.12)' : s?.includes('SELL') ? 'rgba(248,81,73,0.12)' : 'rgba(139,148,158,0.1)'

export default function Signals() {
  const [ticker,  setTicker]  = useState('AAPL')
  const [atype,   setAtype]   = useState('stock')
  const [tf,      setTf]      = useState('swing')
  const [signal,  setSignal]  = useState(null)
  const [loading, setLoading] = useState(false)
  const [multitf, setMultiTf] = useState(null)
  const [mode,    setMode]    = useState('single') // single | multi | opportunities

  async function run() {
    if (!ticker) return
    setLoading(true); setSignal(null); setMultiTf(null)
    try {
      if (mode === 'multi') {
        const res = await api.get(`/signals/multi/${ticker.toUpperCase()}?asset_type=${atype}`)
        setMultiTf(res.data)
      } else {
        const res = await api.get(`/signals/${ticker.toUpperCase()}?asset_type=${atype}&timeframe=${tf}`)
        setSignal(res.data)
      }
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  const ConfBar = ({ value, max = 100 }) => (
    <div style={{ background: '#21262d', borderRadius: 4, height: 6, width: '100%', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${Math.min(100, (value / max) * 100)}%`, background: value > 60 ? '#3fb950' : value > 40 ? '#e3b341' : '#f85149', borderRadius: 4 }} />
    </div>
  )

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 20 }}>⚡ Signal Scanner</h1>

      {/* Controls */}
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TICKER</div>
            <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} onKeyDown={e => e.key === 'Enter' && run()}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 12px', color: '#e2e8f0', fontSize: 14, width: 110, outline: 'none' }} placeholder="AAPL" />
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>ASSET</div>
            <select value={atype} onChange={e => setAtype(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}>
              {['stock', 'crypto', 'forex'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TIMEFRAME</div>
            <select value={tf} onChange={e => setTf(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}>
              {['scalping', 'intraday', 'swing', 'position'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>MODE</div>
            <select value={mode} onChange={e => setMode(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}>
              <option value="single">Single TF</option>
              <option value="multi">All Timeframes</option>
            </select>
          </div>
          <button onClick={run} disabled={loading}
            style={{ padding: '9px 20px', borderRadius: 7, border: 'none', background: loading ? '#21262d' : '#1f6feb', color: loading ? '#8b949e' : '#fff', fontWeight: 600, fontSize: 13, cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Search size={14} /> {loading ? 'Scanning...' : 'Scan Signal'}
          </button>
        </div>
      </div>

      {/* Single Signal Result */}
      {signal && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{signal.ticker}</div>
                <div style={{ fontSize: 12, color: '#8b949e' }}>${signal.price?.toFixed(4)} · {signal.timeframe} · {signal.regime}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: sig_color(signal.signal), background: sig_bg(signal.signal), padding: '4px 12px', borderRadius: 10 }}>{signal.signal}</div>
                <div style={{ fontSize: 12, color: '#8b949e', marginTop: 4 }}>Confidence: {signal.confidence}%</div>
              </div>
            </div>
            <ConfBar value={signal.confidence} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 14 }}>
              {[['Price', `$${signal.price}`], ['SL', `$${signal.sl}`], ['TP', `$${signal.tp}`], ['ATR', `$${signal.atr}`], ['Regime', signal.regime], ['Bayesian', `${Math.round(signal.bayesian?.p_buy * 100 || 50)}% BUY`]].map(([k, v]) => (
                <div key={k} style={{ background: '#0d1117', borderRadius: 7, padding: '8px 10px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>{k}</div>
                  <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={card}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>📊 Indicator Breakdown</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 320, overflowY: 'auto' }}>
              {signal.indicators?.map((ind, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: '#0d1117', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: '#8b949e', flex: 1 }}>{ind.indicator}</div>
                  <div style={{ fontSize: 11, color: sig_color(ind.signal), background: sig_bg(ind.signal), padding: '1px 7px', borderRadius: 8, marginRight: 6 }}>{ind.signal}</div>
                  <div style={{ fontSize: 10, color: '#8b949e', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ind.reason}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Multi-TF Results */}
      {multitf && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 14 }}>
          {Object.entries(multitf).map(([tf, s]) => (
            <div key={tf} style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', textTransform: 'capitalize' }}>{tf}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: sig_color(s.signal), background: sig_bg(s.signal), padding: '2px 10px', borderRadius: 10 }}>{s.signal}</div>
              </div>
              <ConfBar value={s.confidence} />
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 8 }}>Confidence: {s.confidence}% · {s.regime}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
