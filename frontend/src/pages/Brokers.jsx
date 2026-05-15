import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Card, Button, Input, PageHeader, SectionTitle, Loading, Empty, Badge } from '@/components/ui'
import { tokens, fmt$ } from '@/components/ui/tokens'
import { CheckCircle, XCircle, AlertCircle, Plus, Trash2, ExternalLink, X } from 'lucide-react'
import toast from 'react-hot-toast'

const STATUS = {
  connected: { color: tokens.success, label: 'Connected', icon: CheckCircle },
  auth_failed: { color: tokens.danger, label: 'Auth Failed', icon: XCircle },
  test_failed: { color: tokens.warning, label: 'Test Failed', icon: AlertCircle },
  stored: { color: tokens.info, label: 'Stored', icon: AlertCircle },
  unknown: { color: tokens.textMuted, label: 'Unknown', icon: AlertCircle },
}

export default function Brokers() {
  const [available, setAvailable] = useState([])
  const [connected, setConnected] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [creds, setCreds] = useState({})
  const [paperMode, setPaperMode] = useState(true)
  const [connecting, setConnecting] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const [a, s] = await Promise.all([api.get('/broker/available'), api.get('/broker/status')])
      setAvailable(a.data?.brokers || [])
      setConnected(s.data?.connected || [])
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function submit() {
    if (!selected) return
    for (const f of selected.fields) {
      if (!creds[f]) { toast.error(`Missing ${f}`); return }
    }
    setConnecting(true)
    try {
      const r = await api.post('/broker/connect', { broker: selected.id, paper_mode: paperMode, ...creds })
      if (r.data?.status === 'connected') toast.success(`${selected.name} connected — ${fmt$(r.data.balance || 0)}`)
      else toast.error(`${selected.name}: ${r.data?.message || 'connection issue'}`)
      setSelected(null); setCreds({})
      load()
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Connect failed')
    }
    setConnecting(false)
  }

  async function disconnect(id) {
    if (!window.confirm(`Disconnect ${id}?`)) return
    try {
      await api.delete(`/broker/${id}`)
      toast.success('Disconnected')
      load()
    } catch { toast.error('Failed') }
  }

  if (loading) return <Loading message="Loading brokers…" />

  return (
    <div>
      <PageHeader title="🔌 Brokers" subtitle="Connect brokers for live execution · Paper mode by default · Credentials stored encrypted" />

      {connected.length > 0 && (
        <Card style={{ marginBottom: 14 }}>
          <SectionTitle>Connected</SectionTitle>
          {connected.map((c, i) => {
            const meta = available.find(a => a.id === c.broker_id) || {}
            const s = STATUS[c.status] || STATUS.unknown
            const Icon = s.icon
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: i < connected.length - 1 ? `1px solid ${tokens.border}` : 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 8, background: tokens.surfaceAlt, display: 'flex', alignItems: 'center', justifyContent: 'center', color: tokens.text, fontWeight: 700 }}>{(meta.name || c.broker_id)[0].toUpperCase()}</div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{meta.name || c.broker_id}</div>
                    <div style={{ fontSize: 11, color: tokens.textMuted }}>{meta.type} · API key: {c.api_key_masked} · {c.paper_mode ? '📄 Paper' : '⚡ Live'}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                  {c.balance != null && (
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: 10, color: tokens.textMuted, textTransform: 'uppercase' }}>Balance</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{fmt$(c.balance)}</div>
                    </div>
                  )}
                  <Badge color={s.color}><Icon size={10} /> {s.label}</Badge>
                  <Button variant="danger" size="sm" onClick={() => disconnect(c.broker_id)} leftIcon={<Trash2 size={11} />}>Remove</Button>
                </div>
              </div>
            )
          })}
        </Card>
      )}

      <Card>
        <SectionTitle>Available Brokers</SectionTitle>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
          {available.map(b => {
            const isConnected = connected.find(c => c.broker_id === b.id)
            return (
              <Card key={b.id} style={{ background: tokens.bg, padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: tokens.surfaceAlt, display: 'flex', alignItems: 'center', justifyContent: 'center', color: tokens.text, fontWeight: 700 }}>{b.name[0]}</div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{b.name}</div>
                    <div style={{ fontSize: 10, color: tokens.textMuted, textTransform: 'uppercase' }}>{b.type}</div>
                  </div>
                </div>
                <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 10 }}>
                  Requires: {b.fields.join(', ')} {b.supports_paper && '· Paper mode available'}
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {isConnected ? (
                    <Button variant="secondary" size="sm" disabled leftIcon={<CheckCircle size={11} />}>Connected</Button>
                  ) : (
                    <Button size="sm" leftIcon={<Plus size={12} />} onClick={() => { setSelected(b); setCreds({}); setPaperMode(b.supports_paper) }}>Connect</Button>
                  )}
                  <a href={b.docs_url} target="_blank" rel="noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'transparent', border: `1px solid ${tokens.borderHover}`, borderRadius: 8, padding: '5px 10px', color: tokens.textMuted, fontSize: 11, textDecoration: 'none' }}>
                    <ExternalLink size={10} /> Docs
                  </a>
                </div>
              </Card>
            )
          })}
        </div>
      </Card>

      {selected && (
        <div onClick={() => setSelected(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <Card onClick={e => e.stopPropagation()} style={{ maxWidth: 460, width: '90%' }}>
            <SectionTitle action={<Button variant="ghost" size="sm" onClick={() => setSelected(null)}><X size={14} /></Button>}>
              Connect {selected.name}
            </SectionTitle>
            <div style={{ fontSize: 12, color: tokens.textMuted, marginBottom: 14 }}>Credentials obfuscated when stored. We test the connection before saving.</div>
            {selected.fields.map(f => (
              <div key={f} style={{ marginBottom: 12 }}>
                <Input
                  label={f.replace('_', ' ')}
                  type={f.includes('secret') || f.includes('key') ? 'password' : 'text'}
                  value={creds[f] || ''}
                  onChange={e => setCreds({ ...creds, [f]: e.target.value })}
                  fullWidth
                  placeholder={`Your ${f.replace('_', ' ')}`}
                />
              </div>
            ))}
            {selected.supports_paper && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, cursor: 'pointer', color: tokens.text, fontSize: 13 }}>
                <input type="checkbox" checked={paperMode} onChange={e => setPaperMode(e.target.checked)} />
                Use paper trading mode (recommended)
              </label>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Button variant="ghost" onClick={() => setSelected(null)}>Cancel</Button>
              <Button onClick={submit} loading={connecting}>Connect & Test</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
