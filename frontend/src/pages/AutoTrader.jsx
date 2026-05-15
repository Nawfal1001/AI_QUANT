import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Bot, Play, Square, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'
import toast from 'react-hot-toast'
const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const sig_color = (s) => s?.includes('BUY') ? '#3fb950' : s?.includes('SELL') ? '#f85149' : '#8b949e'

export default function AutoTrader() {
  const [config, setConfig]   = useState(null)
  const [stats,  setStats]    = useState(null)
  const [trades, setTrades]   = useState([])
  const [history,setHistory]  = useState([])
  const [tab,    setTab]      = useState('config')
  const [loading,setLoading]  = useState(false)

  async function loadAll() {
    try {
      const [cfg, st, tr, hi] = await Promise.all([
        api.get('/autotrader/config'), api.get('/autotrader/stats'),
        api.get('/autotrader/open-trades'), api.get('/autotrader/trade-history?limit=20')
      ])
      setConfig(cfg.data); setStats(st.data); setTrades(tr.data?.trades || []); setHistory(hi.data?.history || [])
    } catch (e) { console.warn("caught:", e) }
  }
  useEffect(() => { loadAll() }, [])

  async function toggle() {
    if (!config) return
    const enabled = !config.enabled
    await api.patch('/autotrader/config', { enabled })
    if (enabled) await api.post('/autotrader/start'); else await api.post('/autotrader/stop')
    setConfig(c => ({ ...c, enabled })); toast.success(enabled ? '🤖 Auto-trader started' : '⏹ Auto-trader stopped')
  }
  async function scanNow() {
    setLoading(true); try { const r = await api.post('/autotrader/scan-now'); toast.success(`Scanned — ${r.data.executed} trades executed`) } catch (e) { console.warn("caught:", e) } setLoading(false)
  }
  async function updateConfig(key, value) {
    setConfig(c => ({ ...c, [key]: value }))
    await api.patch('/autotrader/config', { [key]: value })
  }

  const TABS = ['config', 'open trades', 'history', 'stats']

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>🤖 Auto-Trader</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={scanNow} disabled={loading} style={{ padding: '8px 14px', borderRadius: 7, border: '1px solid #30363d', background: '#21262d', color: '#8b949e', cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
            <RefreshCw size={13} /> Scan Now
          </button>
          {config && (
            <button onClick={toggle}
              style={{ padding: '8px 16px', borderRadius: 7, border: 'none', background: config.enabled ? '#da3633' : '#238636', color: '#fff', cursor: 'pointer', fontWeight: 600, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}>
              {config.enabled ? <><Square size={13} /> Stop</> : <><Play size={13} /> Start</>}
            </button>
          )}
        </div>
      </div>

      {/* Stats bar */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 16 }}>
          {[['Open Positions', stats.open_positions, '🔓'], ['Total Trades', stats.total_trades, '📊'], ['Win Rate', `${stats.win_rate}%`, '🎯'], ['Wins / Losses', `${stats.wins} / ${stats.losses}`, '📈']].map(([label, value, icon]) => (
            <div key={label} style={{ ...card, padding: '12px 14px' }}>
              <div style={{ fontSize: 10, color: '#8b949e' }}>{icon} {label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {TABS.map(t => <button key={t} onClick={() => setTab(t)} style={{ padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: tab === t ? '#1f6feb' : '#21262d', color: tab === t ? '#fff' : '#8b949e', textTransform: 'capitalize' }}>{t}</button>)}
      </div>

      {/* Config Tab */}
      {tab === 'config' && config && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={card}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Core Settings</div>
            {[['min_confidence', 'Min Confidence %', 40, 95], ['risk_per_trade', 'Risk per Trade %', 0.5, 10], ['capital', 'Capital ($)', 1000, 100000], ['max_open', 'Max Open Trades', 1, 10]].map(([key, label, min, max]) => (
              <div key={key} style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <label style={{ fontSize: 12, color: '#8b949e' }}>{label}</label>
                  <span style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500 }}>{config[key]}</span>
                </div>
                <input type="range" min={min} max={max} step={key === 'capital' ? 500 : key === 'risk_per_trade' ? 0.5 : 1} value={config[key] || min}
                  onChange={e => updateConfig(key, parseFloat(e.target.value))}
                  style={{ width: '100%', accentColor: '#1f6feb' }} />
              </div>
            ))}
          </div>
          <div style={card}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Feature Flags</div>
            {[['use_quant', '🧮 Quant Sizing (Kelly+MC)', 'Uses Kelly Criterion + Monte Carlo for optimal position sizes'],
              ['use_stops', '🛑 Optimal Stops (Shiryaev)', 'Adaptive trailing stops based on Shiryaev optimal stopping theory'],
              ['use_mtf', '📊 MTF Confluence', 'Requires timeframe alignment before entering a trade'],
              ['use_portfolio_risk', '🔒 Portfolio Risk Check', 'Prevents overexposure across all open positions'],
              ['paper_mode', '📄 Paper Mode (Safe)', 'Simulate trades without real broker connections']].map(([key, label, desc]) => (
              <div key={key} style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 12, gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, color: '#e2e8f0' }}>{label}</div>
                  <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>{desc}</div>
                </div>
                <button onClick={() => updateConfig(key, !config[key])}
                  style={{ width: 42, height: 22, borderRadius: 11, border: 'none', cursor: 'pointer', background: config[key] ? '#238636' : '#30363d', position: 'relative', flexShrink: 0 }}>
                  <div style={{ width: 16, height: 16, borderRadius: '50%', background: '#fff', position: 'absolute', top: 3, left: config[key] ? 22 : 3, transition: '0.2s' }} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Open Trades */}
      {tab === 'open trades' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Open Positions ({trades.length})</div>
          {trades.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No open trades</div> :
            trades.map((t, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid #21262d' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{t.ticker} <span style={{ fontSize: 11, color: '#8b949e' }}>{t.asset_type}</span></div>
                  <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>Entry: ${t.entry_price} · SL: ${t.sl} · TP: ${t.tp}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: sig_color(t.signal), background: 'rgba(31,111,235,0.1)', padding: '2px 8px', borderRadius: 8 }}>{t.signal}</div>
                  <div style={{ fontSize: 11, color: '#8b949e', marginTop: 2 }}>{t.confidence}% · {t.position_pct?.toFixed(1)}% risk</div>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* History */}
      {tab === 'history' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Trade History</div>
          {history.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No completed trades</div> :
            history.map((t, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 0', borderBottom: '1px solid #21262d' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{t.ticker}</div>
                  <div style={{ fontSize: 11, color: '#8b949e' }}>{t.signal} · {t.close_reason}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: t.outcome === 'WIN' ? '#3fb950' : '#f85149' }}>
                    {t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct?.toFixed(2)}%
                  </div>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>{t.outcome}</div>
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Stats Tab */}
      {tab === 'stats' && stats && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Performance Statistics</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12 }}>
            {Object.entries(stats).map(([k, v]) => (
              <div key={k} style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{typeof v === 'number' ? v.toLocaleString() : v}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
