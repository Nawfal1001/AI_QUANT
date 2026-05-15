import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Brain, Activity, BookOpen, Shield, Zap, RefreshCw, Play } from 'lucide-react'
import toast from 'react-hot-toast'

const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }

export default function Learning() {
  const [meta, setMeta]       = useState(null)
  const [rl, setRl]           = useState(null)
  const [memStats, setMemStats] = useState(null)
  const [topSetups, setTopSetups] = useState([])
  const [defensive, setDefensive] = useState(null)
  const [wfoHist, setWfoHist] = useState([])
  const [tuner, setTuner]     = useState(null)
  const [tab, setTab]         = useState('overview')
  const [loading, setLoading] = useState(false)

  async function loadAll() {
    try {
      const [m, r, ms, ts, d, w, t] = await Promise.all([
        api.get('/learning/meta/info'),
        api.get('/learning/rl/stats'),
        api.get('/learning/memory/stats'),
        api.get('/learning/memory/top?limit=10&min_samples=3'),
        api.get('/learning/defensive/state'),
        api.get('/learning/wfo/history?limit=10'),
        api.get('/learning/tuner/best'),
      ])
      setMeta(m.data); setRl(r.data); setMemStats(ms.data)
      setTopSetups(ts.data?.setups || []); setDefensive(d.data)
      setWfoHist(w.data?.history || []); setTuner(t.data)
    } catch (e) { console.error(e) }
  }
  useEffect(() => { loadAll() }, [])

  async function trainMeta() {
    setLoading(true)
    try {
      const r = await api.post('/learning/meta/train?min_samples=30')
      if (r.data.error) toast.error(r.data.error)
      else toast.success(`Trained! Accuracy: ${r.data.accuracy}%`)
      await loadAll()
    } catch (e) { toast.error('Training failed') }
    setLoading(false)
  }

  async function runWfo() {
    setLoading(true)
    try {
      const r = await api.post('/learning/wfo/run?window_days=60&n_candidates=20')
      if (r.data.error) toast.error(r.data.error)
      else toast.success(`WFO complete: best Sharpe ${r.data.best_score?.sharpe || '?'}`)
      await loadAll()
    } catch { toast.error('WFO failed') }
    setLoading(false)
  }

  async function runTuner() {
    setLoading(true)
    try {
      const r = await api.post('/learning/tuner/run?n_trials=30')
      if (r.data.error) toast.error(r.data.error)
      else toast.success(`Best params found! Score: ${r.data.best_score?.toFixed(3)}`)
      await loadAll()
    } catch { toast.error('Tuning failed') }
    setLoading(false)
  }

  async function checkDefensive() {
    try { const r = await api.get('/learning/defensive/check'); setDefensive(r.data); toast.success(`Mode: ${r.data.mode}`) } catch (e) { console.warn("caught:", e) }
  }

  const TABS = [
    { id: 'overview',   label: '📊 Overview',   icon: Activity },
    { id: 'meta',       label: '🧠 Meta Learner',  icon: Brain },
    { id: 'rl',         label: '🎮 RL Agent',     icon: Zap },
    { id: 'memory',     label: '📚 Confluence Memory', icon: BookOpen },
    { id: 'wfo',        label: '⚙️ WFO + Tuner',  icon: RefreshCw },
    { id: 'defensive',  label: '🛡️ Defensive Mode', icon: Shield },
  ]

  const modeColor = (m) => m === 'NORMAL' ? '#3fb950' : m === 'WARNING' ? '#e3b341' : m === 'DEFENSIVE' ? '#f0883e' : '#f85149'

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>🤖 Self-Learning Dashboard</h1>
        <button onClick={loadAll} style={{ padding: '8px 14px', borderRadius: 7, border: '1px solid #30363d', background: '#21262d', color: '#8b949e', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(t => <button key={t.id} onClick={() => setTab(t.id)} style={{ padding: '7px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: tab === t.id ? '#1f6feb' : '#21262d', color: tab === t.id ? '#fff' : '#8b949e' }}>{t.label}</button>)}
      </div>

      {/* Overview */}
      {tab === 'overview' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(260px,1fr))', gap: 14 }}>
          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Brain size={16} color="#1f6feb" />
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Meta Learner</div>
            </div>
            {meta?.trained ? (
              <>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#3fb950' }}>{(meta.accuracy * 100).toFixed(1)}%</div>
                <div style={{ fontSize: 11, color: '#8b949e' }}>{meta.samples} samples · trained {meta.trained_at?.slice(0, 10)}</div>
              </>
            ) : <div style={{ fontSize: 12, color: '#8b949e' }}>Not trained yet — need 50+ resolved signals</div>}
          </div>

          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Zap size={16} color="#f0883e" />
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>RL Agent</div>
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{rl?.states || 0}</div>
            <div style={{ fontSize: 11, color: '#8b949e' }}>states learned · {rl?.updates || 0} Q-updates</div>
          </div>

          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <BookOpen size={16} color="#a371f7" />
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Confluence Memory</div>
            </div>
            <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{memStats?.total_setups || 0}</div>
            <div style={{ fontSize: 11, color: '#8b949e' }}>setups · {memStats?.setups_with_history || 0} with history</div>
          </div>

          <div style={{ ...card, borderColor: modeColor(defensive?.mode) + '40' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Shield size={16} color={modeColor(defensive?.mode)} />
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Defensive Mode</div>
            </div>
            <div style={{ fontSize: 18, fontWeight: 700, color: modeColor(defensive?.mode) }}>{defensive?.mode || 'NORMAL'}</div>
            <div style={{ fontSize: 11, color: '#8b949e' }}>24h P&L: {defensive?.pnl_24h?.total_pnl?.toFixed(2) || 0}%</div>
          </div>
        </div>
      )}

      {/* Meta Learner Tab */}
      {tab === 'meta' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Ensemble Meta Learner (GradientBoosting)</div>
            <button onClick={trainMeta} disabled={loading} style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: '#1f6feb', color: '#fff', cursor: 'pointer', fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Play size={12} /> {loading ? 'Training...' : 'Train Now'}
            </button>
          </div>
          {meta?.trained ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 16 }}>
                <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>ACCURACY</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#3fb950', marginTop: 4 }}>{(meta.accuracy * 100).toFixed(1)}%</div>
                </div>
                <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>SAMPLES</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{meta.samples}</div>
                </div>
                <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>LAST TRAIN</div>
                  <div style={{ fontSize: 12, color: '#e2e8f0', marginTop: 4 }}>{meta.trained_at?.slice(0, 16)}</div>
                </div>
              </div>
              {meta.feature_importance && (
                <div>
                  <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 8 }}>FEATURE IMPORTANCE</div>
                  {Object.entries(meta.feature_importance).filter(([,v]) => v > 0.01).sort(([,a],[,b]) => b - a).slice(0, 12).map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                      <div style={{ width: 130, fontSize: 11, color: '#8b949e' }}>{k}</div>
                      <div style={{ flex: 1, background: '#0d1117', borderRadius: 4, height: 6, overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${Math.min(100, v * 500)}%`, background: '#1f6feb' }} />
                      </div>
                      <div style={{ width: 50, fontSize: 11, color: '#e2e8f0', textAlign: 'right' }}>{(v * 100).toFixed(2)}%</div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : <div style={{ color: '#8b949e', fontSize: 13, textAlign: 'center', padding: 30 }}>Model not trained yet. You need at least 30-50 resolved trade signals for the meta-learner to start.</div>}
        </div>
      )}

      {/* RL Tab */}
      {tab === 'rl' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Q-Learning Agent</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginBottom: 16 }}>
            <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#8b949e' }}>STATES EXPLORED</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{rl?.states || 0}</div>
            </div>
            <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#8b949e' }}>Q-UPDATES</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{rl?.updates || 0}</div>
            </div>
            <div style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#8b949e' }}>STATUS</div>
              <div style={{ fontSize: 12, color: rl?.trained ? '#3fb950' : '#e3b341', marginTop: 4 }}>{rl?.trained ? '✓ Learning' : 'Initial'}</div>
            </div>
          </div>
          {rl?.top_states?.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 8 }}>TOP-PERFORMING STATES</div>
              {rl.top_states.slice(0, 8).map((s, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 10px', background: '#0d1117', borderRadius: 6, marginBottom: 4 }}>
                  <div style={{ fontSize: 11, fontFamily: 'monospace', color: '#8b949e' }}>{s.state}</div>
                  <div style={{ display: 'flex', gap: 10 }}>
                    <span style={{ fontSize: 11, color: '#3fb950' }}>{s.best_action}</span>
                    <span style={{ fontSize: 11, color: '#e2e8f0', fontWeight: 600 }}>Q={s.q_max?.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Confluence Memory */}
      {tab === 'memory' && (
        <div style={card}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Top Historical Setups</div>
          {topSetups.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No setups recorded yet</div> :
            topSetups.map((s, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 10px', borderBottom: '1px solid #21262d' }}>
                <div>
                  <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#e2e8f0' }}>{s.signature}</div>
                  <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2 }}>{s.regime} · {s.total} trades</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, color: s.win_rate >= 60 ? '#3fb950' : s.win_rate <= 40 ? '#f85149' : '#e3b341' }}>{s.win_rate}%</div>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>{s.wins}W / {s.total - s.wins}L · avg {s.avg_pnl?.toFixed(2)}%</div>
                </div>
              </div>
            ))
          }
        </div>
      )}

      {/* WFO + Tuner */}
      {tab === 'wfo' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Walk-Forward Optimizer</div>
              <button onClick={runWfo} disabled={loading} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: '#1f6feb', color: '#fff', cursor: 'pointer', fontSize: 11 }}>
                {loading ? '...' : 'Run WFO'}
              </button>
            </div>
            {wfoHist.length === 0 ? <div style={{ color: '#8b949e', fontSize: 13 }}>No runs yet</div> :
              wfoHist.slice(0, 5).map((h, i) => (
                <div key={i} style={{ padding: '8px 0', borderBottom: '1px solid #21262d' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                    <span style={{ color: '#8b949e' }}>{h.timestamp?.slice(0, 16)}</span>
                    <span style={{ color: '#3fb950', fontWeight: 600 }}>Sharpe {h.best_score?.sharpe || '?'}</span>
                  </div>
                  <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2 }}>{h.signals_used} signals · {h.candidates} candidates</div>
                </div>
              ))}
          </div>

          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Hyperparameter Tuner</div>
              <button onClick={runTuner} disabled={loading} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: '#1f6feb', color: '#fff', cursor: 'pointer', fontSize: 11 }}>
                {loading ? '...' : 'Run Tuner'}
              </button>
            </div>
            {tuner?.available ? (
              <>
                <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 8 }}>BEST PARAMETERS</div>
                {Object.entries(tuner.params || {}).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid #21262d' }}>
                    <div style={{ fontSize: 11, color: '#8b949e', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500 }}>{typeof v === 'number' ? v.toFixed(2) : v}</div>
                  </div>
                ))}
                <div style={{ fontSize: 10, color: '#8b949e', marginTop: 8 }}>Score: {tuner.score?.toFixed(3)} · {tuner.updated?.slice(0, 16)}</div>
              </>
            ) : <div style={{ color: '#8b949e', fontSize: 13 }}>No tuning runs yet</div>}
          </div>
        </div>
      )}

      {/* Defensive Mode */}
      {tab === 'defensive' && (
        <div style={card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>Drawdown Protection</div>
            <button onClick={checkDefensive} style={{ padding: '6px 12px', borderRadius: 6, border: 'none', background: '#1f6feb', color: '#fff', cursor: 'pointer', fontSize: 11 }}>
              Recheck
            </button>
          </div>
          {defensive && (
            <>
              <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
                <div style={{ flex: 1, background: '#0d1117', borderRadius: 8, padding: '12px 14px', border: `1px solid ${modeColor(defensive.mode)}40` }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>CURRENT MODE</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: modeColor(defensive.mode), marginTop: 4 }}>{defensive.mode}</div>
                </div>
                <div style={{ flex: 1, background: '#0d1117', borderRadius: 8, padding: '12px 14px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>24H P&L</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: defensive.pnl_24h?.total_pnl >= 0 ? '#3fb950' : '#f85149', marginTop: 4 }}>{defensive.pnl_24h?.total_pnl?.toFixed(2) || 0}%</div>
                </div>
                <div style={{ flex: 1, background: '#0d1117', borderRadius: 8, padding: '12px 14px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>TRADES (24H)</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0', marginTop: 4 }}>{defensive.pnl_24h?.trades || 0}</div>
                </div>
              </div>
              <div style={{ fontSize: 12, color: '#e2e8f0', marginBottom: 4 }}>{defensive.reason}</div>
              <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 12 }}>
                Size Mult: {defensive.adjustments?.size_multiplier?.toFixed(2) || '1.00'}x ·
                Min Conf: {defensive.adjustments?.min_confidence || 70}% ·
                Halt: {defensive.adjustments?.halt_trading ? '⚠️ YES' : '✓ No'}
              </div>
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 12 }}>THRESHOLDS</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                {Object.entries(defensive.thresholds || {}).map(([k, v]) => (
                  <div key={k} style={{ flex: 1, background: '#0d1117', borderRadius: 6, padding: '8px 10px' }}>
                    <div style={{ fontSize: 10, color: '#8b949e' }}>{k.replace('_dd_pct', '').toUpperCase()}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>-{v}%</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
