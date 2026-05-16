import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { useStore } from '@/store'
import { useAuthStore } from '@/store/auth'
import { Card, Button, Input, Toggle, PageHeader, SectionTitle, Loading, Grid } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Shield, Brain, LogOut, Save, Power, AlertTriangle, RefreshCw, Zap } from 'lucide-react'
import toast from 'react-hot-toast'

const row = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: `1px solid ${tokens.border}` }

export default function Settings() {
  const { tradingMode, setTradingMode } = useStore()
  const { user, logout } = useAuthStore()
  const [loading, setLoading] = useState(true)

  const [limits, setLimits] = useState({
    daily_loss_limit_pct: '',
    max_drawdown_pct: '',
    max_open_trades: '',
    max_position_size_pct: '',
  })
  const [riskStatus, setRiskStatus] = useState(null)
  const [controls, setControls] = useState(null)
  const [savingControls, setSavingControls] = useState(false)

  const [learning, setLearning] = useState({
    meta: true, memory: true, rl: true, defensive: true, hyper: true, sentiment: true, micro: true,
  })

  const isAdmin = user?.role === 'admin'

  async function load() {
    setLoading(true)
    try {
      const [s, l, c] = await Promise.all([
        api.get('/risk/status').catch(() => ({ data: null })),
        api.get('/risk/limits').catch(() => ({ data: null })),
        api.get('/runtime-controls/').catch(() => ({ data: null })),
      ])
      if (s.data) setRiskStatus(s.data)
      if (l.data?.limits) setLimits({
        daily_loss_limit_pct: l.data.limits.daily_loss_limit_pct ?? '',
        max_drawdown_pct: l.data.limits.max_drawdown_pct ?? '',
        max_open_trades: l.data.limits.max_open_trades ?? '',
        max_position_size_pct: l.data.limits.max_position_size_pct ?? '',
      })
      if (c.data) setControls(c.data)
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  async function toggleControl(key, value) {
    if (!isAdmin) {
      toast.error('Only admins can change runtime controls')
      return
    }
    const prev = controls
    setControls({ ...controls, [key]: value })
    setSavingControls(true)
    try {
      const res = await api.patch('/runtime-controls/', { [key]: value })
      setControls(res.data)
      toast.success(`${key.replace(/_/g, ' ')}: ${value ? 'on' : 'off'}`)
    } catch (e) {
      setControls(prev)
      toast.error(e?.response?.data?.detail || 'Failed')
    }
    setSavingControls(false)
  }
  useEffect(() => { load() }, [])

  async function saveLimits() {
    for (const k of Object.keys(limits)) {
      if (limits[k] === '' || isNaN(Number(limits[k]))) {
        toast.error(`Set a value for ${k.replace(/_/g, ' ')}`); return
      }
    }
    try {
      await api.post('/risk/limits', limits)
      toast.success('Risk limits saved')
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
  }

  async function toggleKill() {
    const newState = !riskStatus?.kill_switch
    if (newState && !window.confirm('Enable kill switch? Blocks ALL new orders until disabled.')) return
    try {
      await api.post('/risk/kill-switch', { enabled: newState })
      toast.success(newState ? '🛑 Kill switch ENABLED' : '✅ Kill switch disabled')
      load()
    } catch { toast.error('Failed') }
  }

  if (loading) return <Loading message="Loading settings…" />

  const configured = riskStatus?.configured
  const killActive = riskStatus?.kill_switch

  return (
    <div>
      <PageHeader title="⚙️ Settings" subtitle="Account, risk limits, and learning systems" />

      <Grid cols={2} minCol={420} gap={14}>
        <Card>
          <SectionTitle icon={<LogOut size={14} />}>Account</SectionTitle>
          <div style={row}>
            <div>
              <div style={{ fontSize: tokens.fs_md, color: tokens.text }}>{user?.username || '—'}</div>
              <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted, textTransform: 'capitalize' }}>
                {user?.email} · {user?.role}
              </div>
            </div>
            <Button variant="danger" size="sm" onClick={logout} leftIcon={<LogOut size={12} />}>Logout</Button>
          </div>
          <div style={{ ...row, borderBottom: 'none' }}>
            <div>
              <div style={{ fontSize: tokens.fs_md, color: tokens.text }}>Trading Mode</div>
              <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted }}>Paper = simulated · Live = real money</div>
            </div>
            <div style={{ display: 'flex', background: tokens.bgInput, borderRadius: tokens.r1, padding: 2 }}>
              {[['paper', '📄'], ['live', '⚡']].map(([m, ic]) => (
                <button key={m} onClick={() => {
                  if (m === 'live' && !window.confirm('Switch to LIVE trading?')) return
                  setTradingMode(m)
                }} style={{
                  padding: '5px 12px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12,
                  background: tradingMode === m ? (m === 'live' ? tokens.danger : tokens.primary) : 'transparent',
                  color: tradingMode === m ? '#fff' : tokens.textMuted,
                }}>{ic} {m}</button>
              ))}
            </div>
          </div>
        </Card>

        <Card>
          <SectionTitle icon={<Shield size={14} color={tokens.warning} />}>Risk Limits</SectionTitle>
          {!configured && (
            <div style={{
              background: tokens.warningBg, border: `1px solid ${tokens.warning}`, borderRadius: tokens.r1,
              padding: '8px 12px', fontSize: tokens.fs_sm, color: tokens.warning, marginBottom: 12,
              display: 'flex', alignItems: 'center', gap: 6
            }}>
              <AlertTriangle size={13} /> Required — set all four before any trading.
            </div>
          )}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Input label="Daily loss limit (%)" type="number" step="0.1" value={limits.daily_loss_limit_pct}
              onChange={e => setLimits({ ...limits, daily_loss_limit_pct: e.target.value })} placeholder="e.g. 2" />
            <Input label="Max drawdown (%)" type="number" step="0.1" value={limits.max_drawdown_pct}
              onChange={e => setLimits({ ...limits, max_drawdown_pct: e.target.value })} placeholder="e.g. 10" />
            <Input label="Max open trades" type="number" value={limits.max_open_trades}
              onChange={e => setLimits({ ...limits, max_open_trades: e.target.value })} placeholder="e.g. 5" />
            <Input label="Max position size (%)" type="number" step="0.1" value={limits.max_position_size_pct}
              onChange={e => setLimits({ ...limits, max_position_size_pct: e.target.value })} placeholder="e.g. 5" />
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <Button onClick={saveLimits} leftIcon={<Save size={12} />}>Save Limits</Button>
            <Button variant={killActive ? 'danger' : 'secondary'} onClick={toggleKill} leftIcon={<Power size={12} />}>
              {killActive ? 'Disable Kill' : 'Kill Switch'}
            </Button>
          </div>
          {riskStatus && (
            <div style={{ marginTop: 14, padding: '10px 12px', background: tokens.bgInput, borderRadius: tokens.r1, fontSize: tokens.fs_sm }}>
              <div style={{ color: tokens.textMuted, marginBottom: 5 }}>Current</div>
              <div style={{ color: tokens.text, lineHeight: 1.6 }}>
                Equity: ${riskStatus.equity?.toLocaleString()} · Open: {riskStatus.open_trades} · 24h:&nbsp;
                <span style={{ color: riskStatus.daily_pnl >= 0 ? tokens.success : tokens.danger }}>${riskStatus.daily_pnl}</span>
                &nbsp;· DD: {riskStatus.drawdown_pct?.toFixed(2)}%
              </div>
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle icon={<Brain size={14} color={tokens.purple} />}>Self-Learning Systems</SectionTitle>
          {[
            ['Meta-learner', 'meta', 'GradientBoosting re-scores signals'],
            ['Confluence memory', 'memory', 'Pattern → historical win rate'],
            ['RL agent', 'rl', 'Q-learning entry/sizing'],
            ['Defensive mode', 'defensive', '5-level drawdown protection'],
            ['Auto hyper-tuning', 'hyper', 'Grid search on params'],
            ['LLM sentiment', 'sentiment', 'Gemini headline scoring'],
            ['Microstructure', 'micro', 'Funding rates / OI (crypto)'],
          ].map(([label, key, sub], i, arr) => (
            <div key={key} style={{ ...row, ...(i === arr.length - 1 ? { borderBottom: 'none' } : {}) }}>
              <div>
                <div style={{ fontSize: tokens.fs_md, color: tokens.text }}>{label}</div>
                <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted }}>{sub}</div>
              </div>
              <Toggle value={learning[key]} onChange={v => setLearning({ ...learning, [key]: v })} />
            </div>
          ))}
        </Card>

        {controls && (
          <Card>
            <SectionTitle icon={<Zap size={14} color={tokens.warning} />}>Runtime Controls {!isAdmin && <span style={{ fontSize: 10, color: tokens.textMuted, marginLeft: 6 }}>(admin only)</span>}</SectionTitle>
            <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted, marginBottom: 10, lineHeight: 1.5 }}>
              Live kill-switches for the trading stack. Flipping these takes effect on the next scheduler tick — no backend restart needed.
            </div>
            {[
              ['live_trading_enabled', 'Live trading', 'Allow real-broker orders. Server-side LIVE_TRADING_ENABLED or ALLOW_FRONTEND_LIVE_OVERRIDE must also be set in env.'],
              ['auto_trader_enabled', 'Auto-trader', 'Master switch for the auto_trader scan loop.'],
              ['normal_bots_enabled', 'Normal bots', 'Pause/resume the standard bot fleet without disabling each bot.'],
              ['emergency_macro_enabled', 'Emergency macro bots', 'Run macro-event-driven emergency trades on releases (CPI, NFP, FOMC).'],
              ['economic_events_enabled', 'Economic event scanner', 'Background scanner that detects due macro releases.'],
              ['require_live_confirmation', 'Require live confirmation', 'Every live order must pass confirm_live=true (a UI confirm step).'],
            ].map(([key, label, desc], i, arr) => (
              <div key={key} style={{ ...row, ...(i === arr.length - 1 ? { borderBottom: 'none' } : {}) }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: tokens.fs_md, color: tokens.text }}>{label}</div>
                  <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted, lineHeight: 1.4 }}>{desc}</div>
                </div>
                <Toggle value={!!controls[key]} onChange={v => toggleControl(key, v)} disabled={!isAdmin || savingControls} />
              </div>
            ))}
            {controls.live_trading_enabled && !controls.effective_live_trading_enabled && (
              <div style={{ marginTop: 10, padding: '8px 12px', background: 'rgba(248,81,73,0.08)', border: `1px solid ${tokens.danger}`, borderRadius: 6, fontSize: 11, color: tokens.danger, lineHeight: 1.5 }}>
                Live trading is toggled ON but the server hard-lock is in place. Ask your operator to set
                <code style={{ background: tokens.bg, padding: '0 4px', borderRadius: 3, margin: '0 2px' }}>ALLOW_FRONTEND_LIVE_OVERRIDE=true</code>
                or <code style={{ background: tokens.bg, padding: '0 4px', borderRadius: 3, margin: '0 2px' }}>LIVE_TRADING_ENABLED=true</code>
                so this toggle takes effect.
              </div>
            )}
          </Card>
        )}

        <Card>
          <SectionTitle icon={<RefreshCw size={14} />}>Paper Account</SectionTitle>
          <div style={{ fontSize: tokens.fs_sm, color: tokens.textMuted, marginBottom: 12 }}>
            Reset your paper trading account. All paper orders, positions, and closed trades wiped.
          </div>
          <Button variant="secondary" onClick={async () => {
            if (!window.confirm('Wipe all paper trading data?')) return
            try {
              await api.post('/paper/reset', { starting_capital: 10000 })
              toast.success('Paper account reset to $10,000')
            } catch { toast.error('Failed') }
          }}>Reset to $10,000</Button>
        </Card>
      </Grid>
    </div>
  )
}
