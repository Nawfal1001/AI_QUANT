import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Brain, CheckCircle, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'
const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const REGIME_COLORS = { TRENDING_BULL: '#3fb950', TRENDING_BEAR: '#f85149', RANGING: '#e3b341', VOLATILE: '#f0883e', QUIET: '#8b949e' }

export default function StrategyDashboard() {
  const [strategies,  setStrategies]  = useState([])
  const [regimeHist,  setRegimeHist]  = useState([])
  const [pending,     setPending]     = useState([])
  const [weights,     setWeights]     = useState({})
  const [globalReg,   setGlobalReg]   = useState(null)
  const [tab,         setTab]         = useState('strategies')
  const [loading,     setLoading]     = useState(false)

  async function loadAll() {
    try {
      const [s, h, p, w] = await Promise.all([
        api.get('/strategy/strategies'), api.get('/strategy/history?limit=30'),
        api.get('/strategy/pending'), api.get('/walkforward/weights').catch(() => ({ data: { weights: {} } }))
      ])
      setStrategies(s.data?.strategies || []); setRegimeHist(h.data?.history || [])
      setPending(p.data?.pending || []); setWeights(w.data?.weights || {})
    } catch (e) { console.warn("caught:", e) }
  }
  useEffect(() => { loadAll() }, [])

  async function detectGlobal() {
    setLoading(true)
    try {
      const res = await api.post('/strategy/check-and-switch', { watchlist: [
        { ticker: 'AAPL', type: 'stock' }, { ticker: 'NVDA', type: 'stock' }, { ticker: 'BTC', type: 'crypto' }, { ticker: 'ETH', type: 'crypto' }
      ], paper_mode: true })
      setGlobalReg(res.data); toast.success(`Regime: ${res.data.regime}`)
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }

  async function applyStrategy(id, name) {
    await api.post(`/strategy/strategies/${id}/apply`)
    toast.success(`✅ Applied: ${name}`)
  }

  async function confirmSwitch(id) {
    await api.post(`/strategy/confirm/${id}`)
    toast.success('Strategy confirmed'); loadAll()
  }

  const TABS = ['strategies', 'regime history', 'weights', 'pending']

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>🧠 Strategy Dashboard</h1>
        <button onClick={detectGlobal} disabled={loading} style={{ padding: '8px 16px', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, fontSize: 13, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
          <RefreshCw size={13} /> Detect Regime
        </button>
      </div>

      {/* Global Regime Banner */}
      {globalReg && (
        <div style={{ ...card, marginBottom: 16, borderColor: REGIME_COLORS[globalReg.regime] || '#21262d' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 11, color: '#8b949e' }}>GLOBAL REGIME</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: REGIME_COLORS[globalReg.regime] || '#e2e8f0', marginTop: 2 }}>{globalReg.regime?.replace('_', ' ')}</div>
              <div style={{ fontSize: 12, color: '#8b949e', marginTop: 2 }}>Confidence: {globalReg.confidence}% · {globalReg.action}</div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {Object.entries(globalReg.per_asset || {}).map(([t, d]) => (
                <div key={t} style={{ background: '#0d1117', borderRadius: 7, padding: '6px 10px', textAlign: 'center' }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: '#e2e8f0' }}>{t}</div>
                  <div style={{ fontSize: 10, color: REGIME_COLORS[d.regime] || '#8b949e' }}>{d.icon} {d.regime?.replace('_',' ')}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {TABS.map(t => <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: tab === t ? '#1f6feb' : '#21262d', color: tab === t ? '#fff' : '#8b949e', textTransform: 'capitalize' }}>{t}</button>)}
      </div>

      {/* Strategies Tab */}
      {tab === 'strategies' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 12 }}>
          {strategies.map((s, i) => (
            <div key={i} style={{ ...card, borderColor: REGIME_COLORS[s.regime] ? REGIME_COLORS[s.regime] + '40' : '#21262d' }}>
              <div style={{ fontSize: 22, marginBottom: 6 }}>{s.icon}</div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>{s.name}</div>
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4, marginBottom: 10 }}>Optimised for {s.regime?.replace('_',' ')}</div>
              <button onClick={() => applyStrategy(s.id, s.name)}
                style={{ width: '100%', padding: '7px 0', borderRadius: 6, border: 'none', background: '#1f6feb', color: '#fff', fontSize: 12, fontWeight: 500, cursor: 'pointer' }}>
                Apply Strategy
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Regime History */}
      {tab === 'regime history' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Regime History</div>
          {regimeHist.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No regime history yet</div> :
            regimeHist.map((r, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '7px 0', borderBottom: '1px solid #21262d' }}>
                <div>
                  <span style={{ fontSize: 12, fontWeight: 600, color: REGIME_COLORS[r.regime] || '#e2e8f0' }}>{r.regime?.replace('_',' ')}</span>
                  <span style={{ fontSize: 11, color: '#8b949e', marginLeft: 8 }}>{r.ticker}</span>
                </div>
                <div style={{ fontSize: 11, color: '#8b949e' }}>{r.confidence?.toFixed(1)}% · {r.timestamp?.slice(0,16)}</div>
              </div>
            ))}
        </div>
      )}

      {/* Weights Tab */}
      {tab === 'weights' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Self-Learning Indicator Weights</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.entries(weights).filter(([k]) => !['updated_at','version','active_strategy'].includes(k)).sort(([,a],[,b]) => b-a).map(([key, val]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 120, fontSize: 11, color: '#8b949e', flexShrink: 0 }}>{key}</div>
                <div style={{ flex: 1, background: '#0d1117', borderRadius: 4, height: 8, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(100, val)}%`, background: '#1f6feb', borderRadius: 4 }} />
                </div>
                <div style={{ width: 40, fontSize: 11, color: '#e2e8f0', textAlign: 'right' }}>{typeof val === 'number' ? val.toFixed(1) : val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pending Tab */}
      {tab === 'pending' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Pending Regime Switches</div>
          {pending.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No pending switches</div> :
            pending.map((p, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #21262d' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{p.prev_regime} → {p.regime}</div>
                  <div style={{ fontSize: 11, color: '#8b949e' }}>Confidence: {p.confidence}%</div>
                </div>
                <button onClick={() => confirmSwitch(p._id)} style={{ padding: '6px 14px', borderRadius: 6, border: 'none', background: '#238636', color: '#fff', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <CheckCircle size={13} /> Confirm
                </button>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
