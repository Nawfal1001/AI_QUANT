import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, Toggle, PageHeader, SectionTitle, Loading, Empty, Badge, Grid, Metric, ErrorState } from '@/components/ui'
import { tokens, fmt$, fmtPct } from '@/components/ui/tokens'
import { Plus, Trash2, Save, Bot, Play, Pause, X, Activity, AlertCircle, ChevronRight } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'

const EMPTY_BOT = {
  name: '',
  description: '',
  strategy_type: 'builtin',
  strategy_id: 'ensemble',
  watchlist: [{ ticker: 'AAPL', asset_type: 'stock' }],
  schedule: '1h',
  broker: 'paper',
  sizing_mode: 'fixed_pct',
  sizing_pct: 2.0,
  min_confidence: 60,
  enabled: false,
}

const ROW = { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: `1px solid ${tokens.border}` }

function BotCard({ bot, onEdit, onToggle, onDelete, onView }) {
  const last = bot.last_run_at ? new Date(bot.last_run_at).toLocaleString() : 'never'
  const stats = bot.stats || {}
  return (
    <Card style={{ padding: '14px 16px', cursor: 'pointer' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }} onClick={() => onView(bot)}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <Bot size={14} color={bot.enabled ? tokens.success : tokens.textMuted} />
            <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{bot.name}</div>
            {bot.enabled
              ? <Badge color={tokens.success}>● Live</Badge>
              : <Badge color={tokens.textMuted}>Paused</Badge>}
          </div>
          <div style={{ fontSize: 11, color: tokens.textMuted }}>
            {bot.strategy_type === 'user' ? '🧪 Custom' : '📦 Built-in'} ·
            {' '}{bot.strategy_id} · {bot.watchlist?.length || 0} tickers · every {bot.schedule}
          </div>
        </div>
        <Toggle value={bot.enabled} onChange={v => onToggle(bot, v)} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 10 }}>
        <Stat label="Runs" value={stats.runs || 0} />
        <Stat label="Signals" value={stats.signals_fired || 0} color={tokens.info} />
        <Stat label="Placed" value={stats.orders_placed || 0} color={tokens.success} />
        <Stat label="Rejected" value={stats.orders_rejected || 0} color={tokens.danger} />
      </div>

      <div style={{ fontSize: 10, color: tokens.textFaint, marginBottom: 10 }}>
        Last run: {last} · Broker: {bot.broker} · {bot.sizing_pct}% per trade
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <Button variant="secondary" size="sm" onClick={() => onView(bot)} leftIcon={<Activity size={11} />}>Activity</Button>
        <Button variant="secondary" size="sm" onClick={() => onEdit(bot)}>Edit</Button>
        <Button variant="danger" size="sm" onClick={() => onDelete(bot)} leftIcon={<Trash2 size={11} />}>Delete</Button>
      </div>
    </Card>
  )
}

const Stat = ({ label, value, color = tokens.text }) => (
  <div>
    <div style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>
    <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
  </div>
)


export default function Bots() {
  const [bots, setBots] = useState([])
  const [strategies, setStrategies] = useState([])
  const [userStrategies, setUserStrategies] = useState([])
  const [schedules, setSchedules] = useState([])
  const [editing, setEditing] = useState(null)
  const [viewing, setViewing] = useState(null)
  const [executions, setExecutions] = useState([])
  const [runnerStatus, setRunnerStatus] = useState(null)
  const [riskConfigured, setRiskConfigured] = useState(true)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const navigate = useNavigate()

  async function load() {
    setLoading(true)
    try {
      const [b, s, u, sch, rs, risk] = await Promise.all([
        api.get('/bots/'),
        api.get('/backtest/strategies'),
        api.get('/strategy-lab/'),
        api.get('/bots/schedules'),
        api.get('/bots/runner-status'),
        api.get('/risk/limits'),
      ])
      setBots(b.data?.bots || [])
      setStrategies(s.data?.strategies || [])
      setUserStrategies(u.data?.strategies || [])
      setSchedules(sch.data?.schedules || [])
      setRunnerStatus(rs.data?.running || false)
      setRiskConfigured(risk.data?.configured || false)
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function viewBot(bot) {
    setViewing(bot)
    try {
      const r = await api.get(`/bots/${bot._id}/executions?limit=50`)
      setExecutions(r.data?.executions || [])
    } catch (e) { setExecutions([]) }
  }

  async function toggleBot(bot, enabled) {
    if (enabled && !riskConfigured) {
      toast.error('Set risk limits in Settings first')
      return
    }
    try {
      await api.post(`/bots/${bot._id}/toggle`, { enabled })
      toast.success(enabled ? `${bot.name} is now LIVE` : `${bot.name} paused`)
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
  }

  async function deleteBot(bot) {
    if (!window.confirm(`Delete bot "${bot.name}"? Its execution history will be removed.`)) return
    try {
      await api.delete(`/bots/${bot._id}`)
      toast.success('Bot deleted')
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
  }

  async function saveBot() {
    if (!editing) return
    setSaving(true)
    try {
      if (editing._id) {
        const { _id, stats, last_run_at, next_run_at, created_at, updated_at, user_id, ...patch } = editing
        await api.patch(`/bots/${_id}`, patch)
        toast.success('Bot updated')
      } else {
        await api.post('/bots/', editing)
        toast.success('Bot created')
      }
      setEditing(null)
      load()
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Save failed')
    }
    setSaving(false)
  }

  function startNew() {
    setEditing({ ...EMPTY_BOT })
  }

  function startEdit(bot) {
    setEditing({ ...bot })
  }

  function addWatchlistItem() {
    setEditing(e => ({ ...e, watchlist: [...e.watchlist, { ticker: '', asset_type: 'stock' }] }))
  }

  function updateWatchlist(idx, patch) {
    setEditing(e => ({
      ...e,
      watchlist: e.watchlist.map((w, i) => i === idx ? { ...w, ...patch } : w),
    }))
  }

  function removeWatchlist(idx) {
    setEditing(e => ({ ...e, watchlist: e.watchlist.filter((_, i) => i !== idx) }))
  }

  if (loading) return <Loading message="Loading bots…" />

  // Aggregate stats
  const totalRuns = bots.reduce((s, b) => s + (b.stats?.runs || 0), 0)
  const totalOrders = bots.reduce((s, b) => s + (b.stats?.orders_placed || 0), 0)
  const activeCount = bots.filter(b => b.enabled).length

  return (
    <div>
      <PageHeader
        title="🤖 Trading Bots"
        subtitle="Autonomous strategies that run on schedule and place trades through your chosen broker"
        action={
          !editing && !viewing && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Badge color={runnerStatus ? tokens.success : tokens.textMuted}>
                Runner: {runnerStatus ? '● Active' : 'Stopped'}
              </Badge>
              <Button leftIcon={<Plus size={14} />} onClick={startNew}>New Bot</Button>
            </div>
          )
        }
      />

      {/* Risk warning */}
      {!riskConfigured && !editing && !viewing && (
        <Card style={{ marginBottom: 14, borderColor: tokens.warning, background: 'rgba(227,179,65,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: tokens.warning, fontSize: 13 }}>
            <AlertCircle size={16} />
            <div style={{ flex: 1 }}>
              <strong>Risk limits required.</strong> You can build and edit bots, but they can't be turned ON until you configure risk limits in Settings.
            </div>
            <Button variant="secondary" size="sm" onClick={() => navigate('/settings')} leftIcon={<ChevronRight size={11} />}>Go to Settings</Button>
          </div>
        </Card>
      )}

      {/* Summary tiles */}
      {!editing && !viewing && bots.length > 0 && (
        <Grid cols={4} minCol={150} gap={10} style={{ marginBottom: 14 }}>
          <Metric label="Total Bots" value={bots.length} />
          <Metric label="Active" value={activeCount} color={activeCount > 0 ? tokens.success : tokens.textMuted} />
          <Metric label="Total Runs" value={totalRuns} />
          <Metric label="Orders Placed" value={totalOrders} color={tokens.success} />
        </Grid>
      )}

      {/* Editor */}
      {editing && (
        <Card>
          <SectionTitle
            icon={<Bot size={14} />}
            action={
              <div style={{ display: 'flex', gap: 6 }}>
                <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>Cancel</Button>
                <Button size="sm" onClick={saveBot} loading={saving} leftIcon={<Save size={11} />}>Save</Button>
              </div>
            }
          >
            {editing._id ? 'Edit Bot' : 'New Bot'}
          </SectionTitle>

          <Grid cols={2} minCol={220} gap={12}>
            <Input label="Name" value={editing.name} onChange={e => setEditing({ ...editing, name: e.target.value })} fullWidth />
            <Input label="Description" value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} fullWidth />
          </Grid>

          {/* Strategy selector */}
          <div style={{ marginTop: 14 }}>
            <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>Strategy</div>
            <Select
              value={`${editing.strategy_type}::${editing.strategy_id}`}
              onChange={e => {
                const [t, id] = e.target.value.split('::')
                setEditing({ ...editing, strategy_type: t, strategy_id: id })
              }}
              fullWidth
            >
              <optgroup label="Built-in">
                {strategies.map(s => (
                  <option key={s.id} value={`builtin::${s.id}`}>{s.name}</option>
                ))}
              </optgroup>
              {userStrategies.length > 0 && (
                <optgroup label="My Custom Strategies">
                  {userStrategies.map(s => (
                    <option key={s._id} value={`user::${s._id}`}>🧪 {s.name}</option>
                  ))}
                </optgroup>
              )}
            </Select>
          </div>

          {/* Watchlist */}
          <div style={{ marginTop: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ fontSize: 11, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.3 }}>
                Watchlist ({editing.watchlist?.length || 0}/20)
              </div>
              <Button variant="ghost" size="sm" onClick={addWatchlistItem} leftIcon={<Plus size={11} />}>Add ticker</Button>
            </div>
            {editing.watchlist?.map((w, idx) => (
              <div key={idx} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                <input
                  value={w.ticker}
                  onChange={e => updateWatchlist(idx, { ticker: e.target.value.toUpperCase() })}
                  placeholder="AAPL"
                  style={{
                    flex: 1, background: tokens.bg, border: `1px solid ${tokens.border}`,
                    borderRadius: 6, padding: '7px 10px', color: tokens.text, fontSize: 12, outline: 'none',
                  }}
                />
                <select
                  value={w.asset_type}
                  onChange={e => updateWatchlist(idx, { asset_type: e.target.value })}
                  style={{
                    background: tokens.bg, border: `1px solid ${tokens.border}`,
                    borderRadius: 6, padding: '7px 10px', color: tokens.text, fontSize: 12, outline: 'none', width: 100,
                  }}
                >
                  <option value="stock">Stock</option>
                  <option value="crypto">Crypto</option>
                </select>
                <button onClick={() => removeWatchlist(idx)} style={{ background: 'none', border: 'none', color: tokens.danger, cursor: 'pointer', padding: 6 }}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>

          {/* Schedule + Broker + Sizing */}
          <Grid cols={3} minCol={140} gap={12} style={{ marginTop: 14 }}>
            <Select label="Run every" value={editing.schedule} onChange={e => setEditing({ ...editing, schedule: e.target.value })} fullWidth>
              {schedules.map(s => <option key={s} value={s}>{s}</option>)}
            </Select>
            <Select label="Broker" value={editing.broker} onChange={e => setEditing({ ...editing, broker: e.target.value })} fullWidth>
              <option value="paper">📄 Paper</option>
              <option value="alpaca">⚡ Alpaca</option>
              <option value="binance">⚡ Binance</option>
              <option value="oanda">⚡ OANDA</option>
            </Select>
            <Input label="Size per trade %" type="number" step="0.1" min="0.1" max="50"
                   value={editing.sizing_pct} onChange={e => setEditing({ ...editing, sizing_pct: Number(e.target.value) })} fullWidth />
          </Grid>

          <Grid cols={2} minCol={180} gap={12} style={{ marginTop: 10 }}>
            <Select label="Sizing mode" value={editing.sizing_mode} onChange={e => setEditing({ ...editing, sizing_mode: e.target.value })} fullWidth>
              <option value="fixed_pct">Fixed %</option>
              <option value="kelly">Kelly (data-driven)</option>
              <option value="atr_volatility">ATR-adjusted</option>
            </Select>
            <Input label="Min confidence %" type="number" min="0" max="100"
                   value={editing.min_confidence} onChange={e => setEditing({ ...editing, min_confidence: Number(e.target.value) })} fullWidth />
          </Grid>

          {/* Live mode info */}
          {editing.broker !== 'paper' && (
            <div style={{ marginTop: 14, padding: '10px 12px', background: 'rgba(248,81,73,0.08)', borderRadius: 8, fontSize: 12, color: tokens.danger, lineHeight: 1.5 }}>
              <strong>⚠ Live trading.</strong> This bot will place real orders on {editing.broker}. The broker must be connected (Brokers page),
              <code style={{ color: tokens.text, background: tokens.bg, padding: '0 4px', borderRadius: 3, margin: '0 2px' }}>LIVE_TRADING_ENABLED=true</code>
              in your .env, and your risk limits will gate every order.
            </div>
          )}
        </Card>
      )}

      {/* Activity view */}
      {viewing && (
        <Card>
          <SectionTitle
            icon={<Activity size={14} />}
            action={<Button variant="ghost" size="sm" onClick={() => { setViewing(null); setExecutions([]) }}><X size={14} /></Button>}
          >
            {viewing.name} · Activity
          </SectionTitle>

          <Grid cols={4} minCol={120} gap={10} style={{ marginBottom: 14 }}>
            <Stat label="Runs" value={viewing.stats?.runs || 0} />
            <Stat label="Signals" value={viewing.stats?.signals_fired || 0} color={tokens.info} />
            <Stat label="Placed" value={viewing.stats?.orders_placed || 0} color={tokens.success} />
            <Stat label="Rejected" value={viewing.stats?.orders_rejected || 0} color={tokens.danger} />
          </Grid>

          {executions.length === 0 ? (
            <Empty message="No executions yet. The bot will start running on its schedule once enabled." icon="⏳" />
          ) : (
            <div style={{ overflowX: 'auto', maxHeight: 500 }}>
              <table style={{ width: '100%', fontSize: 11, color: tokens.textMuted }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                    {['When', 'Ticker', 'Signal', 'Conf', 'Action', 'Reason / Fill'].map(h =>
                      <th key={h} style={{ padding: '7px 10px', fontWeight: 500, position: 'sticky', top: 0, background: tokens.surface }}>{h}</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {executions.map((e, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                      <td style={{ padding: '7px 10px' }}>{(e.ran_at || '').slice(5, 16)}</td>
                      <td style={{ padding: '7px 10px', color: tokens.text, fontWeight: 600 }}>{e.ticker}</td>
                      <td style={{ padding: '7px 10px' }}>
                        <Badge color={e.signal?.includes('BUY') ? tokens.success : e.signal?.includes('SELL') ? tokens.danger : tokens.textMuted}>
                          {e.signal}
                        </Badge>
                      </td>
                      <td style={{ padding: '7px 10px' }}>{e.confidence?.toFixed(0)}%</td>
                      <td style={{ padding: '7px 10px' }}>
                        <Badge color={e.action === 'placed' ? tokens.success : e.action === 'skipped' ? tokens.textMuted : tokens.danger}>
                          {e.action}
                        </Badge>
                      </td>
                      <td style={{ padding: '7px 10px', fontSize: 10, color: tokens.textMuted, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {e.action === 'placed' && e.order_result?.order?.fill_price
                          ? `Filled @ $${e.order_result.order.fill_price?.toFixed(2)}`
                          : e.reason}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Bot list */}
      {!editing && !viewing && (
        bots.length === 0 ? (
          <Empty
            message="No bots yet. Create one to put a strategy on autopilot."
            icon="🤖"
            action={<Button leftIcon={<Plus size={13} />} onClick={startNew}>Create First Bot</Button>}
          />
        ) : (
          <Grid cols={2} minCol={400} gap={14}>
            {bots.map(b => (
              <BotCard key={b._id} bot={b} onEdit={startEdit} onToggle={toggleBot} onDelete={deleteBot} onView={viewBot} />
            ))}
          </Grid>
        )
      )}
    </div>
  )
}
