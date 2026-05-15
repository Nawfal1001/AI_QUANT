import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { useStore } from '@/store'
import { AlertCircle } from 'lucide-react'
import { tokens, fmt$ } from './ui/tokens'
import { Toggle, Badge } from './ui'
import toast from 'react-hot-toast'

export const SafetyBar = () => {
  const { tradingMode } = useStore()
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    try {
      const r = await api.get('/risk/status')
      setStatus(r.data)
    } catch {
      setStatus(null)
    }
    setLoading(false)
  }

  useEffect(() => {
    load()
    const i = setInterval(load, 15000) // refresh every 15s
    return () => clearInterval(i)
  }, [])

  async function toggleKill() {
    if (!status) return
    const newVal = !status.kill_switch
    if (newVal && !window.confirm('Activate KILL SWITCH? This blocks ALL new orders until you turn it off.')) return
    try {
      await api.post('/risk/kill-switch', { enabled: newVal })
      toast.success(newVal ? 'Kill switch ACTIVATED' : 'Kill switch deactivated')
      load()
    } catch { toast.error('Failed') }
  }

  if (loading || !status) return null

  const isLive = tradingMode === 'live'
  const killed = status.kill_switch
  const dailyLossWarn = status.daily_loss_pct >= (status.limits?.daily_loss_limit_pct || 100) * 0.7
  const drawdownWarn = status.drawdown_pct >= (status.limits?.max_drawdown_pct || 100) * 0.7

  // Banner color
  let banner = tokens.success
  if (killed) banner = tokens.danger
  else if (dailyLossWarn || drawdownWarn) banner = tokens.warning
  else if (!status.configured) banner = tokens.textMuted

  return (
    <div style={{
      background: tokens.surface,
      border: `1px solid ${tokens.border}`,
      borderTop: `2px solid ${banner}`,
      borderRadius: tokens.radiusMd,
      padding: '10px 16px',
      marginBottom: 14,
      display: 'flex',
      alignItems: 'center',
      gap: 18,
      flexWrap: 'wrap',
      fontSize: 12,
    }}>
      {/* Mode badge */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5 }}>Mode</span>
        <Badge color={isLive ? tokens.danger : tokens.info}>
          {isLive ? '⚡ LIVE' : '📄 PAPER'}
        </Badge>
      </div>

      {/* Config warning */}
      {!status.configured && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: tokens.warning }}>
          <AlertCircle size={12} /> Risk limits not configured — auto-trading blocked
        </div>
      )}

      {/* Daily P&L */}
      {status.configured && (
        <div>
          <span style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginRight: 5 }}>Today</span>
          <span style={{ color: status.daily_pnl >= 0 ? tokens.success : tokens.danger, fontWeight: 600 }}>
            {status.daily_pnl >= 0 ? '+' : ''}{fmt$(status.daily_pnl)}
          </span>
          {status.limits?.daily_loss_limit_pct && status.daily_pnl < 0 && (
            <span style={{ color: dailyLossWarn ? tokens.warning : tokens.textMuted, marginLeft: 5 }}>
              ({status.daily_loss_pct.toFixed(1)}% / {status.limits.daily_loss_limit_pct}%)
            </span>
          )}
        </div>
      )}

      {/* Drawdown */}
      {status.configured && status.drawdown_pct > 0 && (
        <div>
          <span style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginRight: 5 }}>DD</span>
          <span style={{ color: drawdownWarn ? tokens.warning : tokens.text, fontWeight: 600 }}>
            -{status.drawdown_pct.toFixed(2)}%
          </span>
        </div>
      )}

      {/* Open trades */}
      {status.configured && (
        <div>
          <span style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginRight: 5 }}>Open</span>
          <span style={{ color: tokens.text, fontWeight: 600 }}>
            {status.open_trades} / {status.limits?.max_open_trades}
          </span>
        </div>
      )}

      {/* Equity */}
      <div>
        <span style={{ fontSize: 9, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginRight: 5 }}>Equity</span>
        <span style={{ color: tokens.text, fontWeight: 600 }}>{fmt$(status.equity)}</span>
      </div>

      {/* Kill switch */}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
        {killed && <Badge color={tokens.danger}>⛔ KILL ACTIVE</Badge>}
        <span style={{ fontSize: 11, color: killed ? tokens.danger : tokens.textMuted, fontWeight: 600 }}>
          Kill Switch
        </span>
        <Toggle value={killed} onChange={toggleKill} color={tokens.danger} />
      </div>
    </div>
  )
}
