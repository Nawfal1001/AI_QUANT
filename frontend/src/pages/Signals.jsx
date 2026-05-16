import React, { useEffect, useState } from 'react'
import { api } from '@/store/auth'
import { Search, RefreshCw } from 'lucide-react'
const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const sig_color = (s) => s?.includes('BUY') ? '#3fb950' : s?.includes('SELL') ? '#f85149' : '#8b949e'
const sig_bg = (s) => s?.includes('BUY') ? 'rgba(63,185,80,0.12)' : s?.includes('SELL') ? 'rgba(248,81,73,0.12)' : 'rgba(139,148,158,0.1)'
const fmtMoney = (v, digits = 4) => Number.isFinite(Number(v)) ? `$${Number(v).toFixed(digits)}` : '—'
const fmtPct = (v) => Number.isFinite(Number(v)) ? `${Math.round(Number(v))}%` : '0%'
const cleanSignal = (s) => s || { signal: 'HOLD', confidence: 0, indicators: [], bayesian: {} }

export default function Signals() {
  const [ticker, setTicker] = useState('AAPL')
  const [atype, setAtype] = useState('stock')
  const [broker, setBroker] = useState('')
  const [tf, setTf] = useState('swing')
  const [signal, setSignal] = useState(null)
  const [loading, setLoading] = useState(false)
  const [autoLoading, setAutoLoading] = useState(false)
  const [multitf, setMultiTf] = useState(null)
  const [autoSignals, setAutoSignals] = useState([])
  const [mode, setMode] = useState('auto')
  const [error, setError] = useState('')

  async function loadAuto() {
    setAutoLoading(true); setError('')
    try {
      const qs = new URLSearchParams()
      if (broker) qs.set('broker', broker)
      if (atype) qs.set('asset_type', atype)
      qs.set('limit', '50')
      const res = await api.get(`/auto-signals/latest?${qs.toString()}`)
      setAutoSignals(res.data?.signals || [])
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Could not load auto universe signals')
    } finally { setAutoLoading(false) }
  }

  async function forceAutoScan() {
    setAutoLoading(true); setError('')
    try {
      await api.post('/auto-signals/scan')
      await loadAuto()
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Auto universe scan failed')
      setAutoLoading(false)
    }
  }

  useEffect(() => { loadAuto() }, [])

  async function run() {
    if (mode === 'auto') return loadAuto()
    if (!ticker) return
    setLoading(true); setSignal(null); setMultiTf(null); setError('')
    try {
      if (mode === 'multi') {
        const res = await api.get(`/signals/multi/${ticker.toUpperCase()}?asset_type=${atype}`)
        setMultiTf(res.data)
      } else {
        const res = await api.get(`/signals/${ticker.toUpperCase()}?asset_type=${atype}&timeframe=${tf}&use_ai=true`)
        setSignal(cleanSignal(res.data))
        if (res.data?.error) setError(res.data.error)
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Signal request failed')
    } finally { setLoading(false) }
  }

  const ConfBar = ({ value, max = 100 }) => {
    const n = Math.max(0, Math.min(100, Number(value) || 0))
    return <div style={{ background: '#21262d', borderRadius: 4, height: 6, width: '100%', overflow: 'hidden' }}><div style={{ height: '100%', width: `${Math.min(100, (n / max) * 100)}%`, background: n > 60 ? '#3fb950' : n > 40 ? '#e3b341' : '#f85149', borderRadius: 4 }} /></div>
  }
  const s = signal ? cleanSignal(signal) : null

  return <div>
    <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 20 }}>⚡ Signal Scanner</h1>
    <div style={{ ...card, marginBottom: 16 }}>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div><div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>MODE</div><select value={mode} onChange={e => setMode(e.target.value)} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}><option value="auto">Auto Universe</option><option value="single">Single TF</option><option value="multi">All Timeframes</option></select></div>
        {mode !== 'auto' && <div><div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TICKER</div><input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} onKeyDown={e => e.key === 'Enter' && run()} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 12px', color: '#e2e8f0', fontSize: 14, width: 110, outline: 'none' }} placeholder="AAPL" /></div>}
        <div><div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>ASSET</div><select value={atype} onChange={e => setAtype(e.target.value)} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}>{['stock', 'crypto', 'forex'].map(t => <option key={t} value={t}>{t}</option>)}</select></div>
        {mode === 'auto' && <div><div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>BROKER</div><select value={broker} onChange={e => setBroker(e.target.value)} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}><option value="">All brokers</option><option value="fusion">Fusion</option><option value="paper">Paper</option><option value="alpaca">Alpaca</option><option value="binance">Binance</option><option value="oanda">Oanda</option></select></div>}
        {mode !== 'auto' && <div><div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TIMEFRAME</div><select value={tf} onChange={e => setTf(e.target.value)} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, cursor: 'pointer', outline: 'none' }}>{['scalping', 'intraday', 'swing', 'position'].map(t => <option key={t} value={t}>{t}</option>)}</select></div>}
        <button onClick={run} disabled={loading || autoLoading} style={{ padding: '9px 20px', borderRadius: 7, border: 'none', background: (loading || autoLoading) ? '#21262d' : '#1f6feb', color: (loading || autoLoading) ? '#8b949e' : '#fff', fontWeight: 600, fontSize: 13, cursor: (loading || autoLoading) ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}><Search size={14} /> {(loading || autoLoading) ? 'Scanning...' : mode === 'auto' ? 'Load Auto Signals' : 'Scan Signal'}</button>
        {mode === 'auto' && <button onClick={forceAutoScan} disabled={autoLoading} style={{ padding: '9px 14px', borderRadius: 7, border: '1px solid #30363d', background: '#0d1117', color: '#e2e8f0', fontWeight: 600, fontSize: 13, cursor: autoLoading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}><RefreshCw size={14} /> Force Scan</button>}
      </div>
      {error && <div style={{ marginTop: 12, color: '#e3b341', fontSize: 12 }}>⚠ {error}</div>}
    </div>

    {mode === 'auto' && <div style={card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}><div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>🌐 Auto Universe Opportunities</div><div style={{ color: '#8b949e', fontSize: 12 }}>{autoSignals.length} signals</div></div>
      {autoSignals.length === 0 && <div style={{ color: '#8b949e', fontSize: 13 }}>No stored auto-signals yet. Press Force Scan, or wait for the backend scheduler to populate stock/crypto/forex opportunities.</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 10 }}>
        {autoSignals.map((x, i) => <div key={x._id || i} style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 10, padding: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><div><div style={{ color: '#e2e8f0', fontWeight: 800, fontSize: 18 }}>{x.ticker}</div><div style={{ color: '#8b949e', fontSize: 11 }}>{x.broker || '—'} · {x.asset_type || '—'} · {x.timeframe || '—'}</div></div><div style={{ color: sig_color(x.signal), background: sig_bg(x.signal), padding: '3px 9px', borderRadius: 9, fontWeight: 700, height: 26 }}>{x.signal}</div></div>
          <div style={{ marginTop: 10 }}><ConfBar value={x.confidence} /></div>
          <div style={{ color: '#8b949e', fontSize: 12, marginTop: 8 }}>Conf {fmtPct(x.confidence)} · Score {Number.isFinite(Number(x.scanner_score)) ? Math.round(Number(x.scanner_score)) : '—'}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 8 }}><div style={{ color: '#8b949e', fontSize: 11 }}>Price<br/><span style={{ color: '#e2e8f0' }}>{fmtMoney(x.price)}</span></div><div style={{ color: '#8b949e', fontSize: 11 }}>SL<br/><span style={{ color: '#e2e8f0' }}>{fmtMoney(x.sl)}</span></div><div style={{ color: '#8b949e', fontSize: 11 }}>TP<br/><span style={{ color: '#e2e8f0' }}>{fmtMoney(x.tp)}</span></div></div>
          <div style={{ color: '#8b949e', fontSize: 11, marginTop: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{x.scanner_reason || x.error || 'auto universe signal'}</div>
        </div>)}
      </div>
    </div>}

    {mode !== 'auto' && s && <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
      <div style={card}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}><div><div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{s.ticker || ticker.toUpperCase()}</div><div style={{ fontSize: 12, color: '#8b949e' }}>{fmtMoney(s.price)} · {s.timeframe || tf} · {s.regime || '—'}</div></div><div style={{ textAlign: 'right' }}><div style={{ fontSize: 16, fontWeight: 700, color: sig_color(s.signal), background: sig_bg(s.signal), padding: '4px 12px', borderRadius: 10 }}>{s.signal || 'HOLD'}</div><div style={{ fontSize: 12, color: '#8b949e', marginTop: 4 }}>Confidence: {fmtPct(s.confidence)}</div></div></div><ConfBar value={s.confidence} /><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 14 }}>{[['Price', fmtMoney(s.price)], ['SL', fmtMoney(s.sl)], ['TP', fmtMoney(s.tp)], ['ATR', fmtMoney(s.atr)], ['Regime', s.regime || '—'], ['Bayesian', `${Math.round(Number(s.bayesian?.p_buy ?? 0.5) * 100)}% BUY`]].map(([k, v]) => <div key={k} style={{ background: '#0d1117', borderRadius: 7, padding: '8px 10px' }}><div style={{ fontSize: 10, color: '#8b949e' }}>{k}</div><div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500, marginTop: 2 }}>{v}</div></div>)}</div></div>
      <div style={card}><div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>📊 Indicator Breakdown</div><div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 320, overflowY: 'auto' }}>{(s.indicators || []).length === 0 && <div style={{ color: '#8b949e', fontSize: 12 }}>No indicator data available for this symbol/timeframe.</div>}{(s.indicators || []).map((ind, i) => <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', background: '#0d1117', borderRadius: 6 }}><div style={{ fontSize: 11, color: '#8b949e', flex: 1 }}>{ind.indicator}</div><div style={{ fontSize: 11, color: sig_color(ind.signal), background: sig_bg(ind.signal), padding: '1px 7px', borderRadius: 8, marginRight: 6 }}>{ind.signal}</div><div style={{ fontSize: 10, color: '#8b949e', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ind.reason}</div></div>)}</div></div>
    </div>}
    {mode !== 'auto' && multitf && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 14 }}>{Object.entries(multitf).map(([tfName, raw]) => { const m = cleanSignal(raw); return <div key={tfName} style={card}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}><div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', textTransform: 'capitalize' }}>{tfName}</div><div style={{ fontSize: 12, fontWeight: 600, color: sig_color(m.signal), background: sig_bg(m.signal), padding: '2px 10px', borderRadius: 10 }}>{m.signal}</div></div><ConfBar value={m.confidence} /><div style={{ fontSize: 11, color: '#8b949e', marginTop: 8 }}>Confidence: {fmtPct(m.confidence)} · {m.regime || m.error || '—'}</div></div> })}</div>}
  </div>
}
