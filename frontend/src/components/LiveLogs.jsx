import React, { useEffect, useRef, useState } from 'react'
import { api } from '@/store/auth'
import { Card, SectionTitle, Select, Button } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Activity, RefreshCw } from 'lucide-react'

const scopes = ['', 'backtest', 'bot', 'signals', 'trading', 'broker', 'market_data', 'ai', 'auth']

export default function LiveLogs({ scope = '', entityId = '', title = 'Live Logs', compact = false, auto = true }) {
  const [selectedScope, setSelectedScope] = useState(scope)
  const [logs, setLogs] = useState([])
  const [loading, setLoading] = useState(false)
  const timer = useRef(null)

  async function load() {
    setLoading(true)
    try {
      const qs = new URLSearchParams()
      if (selectedScope) qs.set('scope', selectedScope)
      if (entityId) qs.set('entity_id', entityId)
      qs.set('limit', compact ? '80' : '250')
      const r = await api.get(`/logs?${qs.toString()}`)
      setLogs(r.data?.logs || [])
    } catch (e) {
      setLogs([{ ts: new Date().toISOString(), level: 'error', scope: 'frontend', message: e.response?.data?.detail || e.message || 'Could not load logs' }])
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [selectedScope, entityId])
  useEffect(() => {
    if (!auto) return
    timer.current = setInterval(load, 2500)
    return () => timer.current && clearInterval(timer.current)
  }, [selectedScope, entityId, auto])

  const levelColor = l => l === 'error' ? tokens.danger : l === 'warning' ? tokens.warning : l === 'success' ? tokens.success : tokens.textMuted

  return <Card style={{ marginBottom: 14 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', marginBottom: 10 }}>
      <SectionTitle icon={<Activity size={14} />}>{title}</SectionTitle>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        {!scope && <Select value={selectedScope} onChange={e => setSelectedScope(e.target.value)} style={{ minWidth: 140 }}>
          {scopes.map(s => <option key={s} value={s}>{s || 'all scopes'}</option>)}
        </Select>}
        <Button size="sm" variant="secondary" onClick={load} loading={loading} leftIcon={<RefreshCw size={13} />}>Refresh</Button>
      </div>
    </div>
    <div style={{ maxHeight: compact ? 220 : 420, overflowY: 'auto', background: '#05080d', border: `1px solid ${tokens.border}`, borderRadius: 10, padding: 10, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>
      {logs.length === 0 && <div style={{ color: tokens.textMuted }}>No logs yet.</div>}
      {logs.map((l, i) => <div key={l._id || i} style={{ color: levelColor(l.level), marginBottom: 6, whiteSpace: 'pre-wrap' }}>
        <span style={{ color: '#64748b' }}>{(l.ts || '').slice(11, 19)}</span> <span style={{ color: '#94a3b8' }}>[{l.scope || 'app'}]</span> {l.message}
      </div>)}
    </div>
  </Card>
}
