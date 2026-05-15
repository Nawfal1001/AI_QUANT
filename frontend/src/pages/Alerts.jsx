import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, PageHeader, SectionTitle, Loading, Empty, Badge, Grid } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Bell, Send, Plus, Trash2 } from 'lucide-react'
import toast from 'react-hot-toast'

const CONDITIONS = [
  { id: 'price_above', label: 'Price above' },
  { id: 'price_below', label: 'Price below' },
  { id: 'change_pct_above', label: 'Change % above' },
  { id: 'change_pct_below', label: 'Change % below' },
  { id: 'signal_strong_buy', label: 'Strong BUY signal' },
  { id: 'signal_strong_sell', label: 'Strong SELL signal' },
]

export default function Alerts() {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ ticker: 'AAPL', asset_type: 'stock', condition: 'price_above', threshold: 200, channels: ['telegram'] })
  const [testing, setTesting] = useState(false)
  const [creating, setCreating] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const r = await api.get('/alerts/list')
      setAlerts(r.data?.alerts || [])
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function create() {
    if (!form.ticker || !form.threshold) { toast.error('Fill ticker and threshold'); return }
    setCreating(true)
    try {
      await api.post('/alerts/create', { ...form, ticker: form.ticker.toUpperCase(), threshold: Number(form.threshold) })
      toast.success('Alert created')
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
    setCreating(false)
  }

  async function remove(id) {
    if (!window.confirm('Delete this alert?')) return
    try {
      await api.delete(`/alerts/${id}`)
      toast.success('Deleted')
      load()
    } catch { toast.error('Failed') }
  }

  async function testTelegram() {
    setTesting(true)
    try {
      const r = await api.post('/alerts/test/telegram')
      if (r.data?.ok) toast.success('Telegram message sent')
      else toast.error(r.data?.error || 'Telegram test failed — check .env')
    } catch { toast.error('Failed') }
    setTesting(false)
  }

  return (
    <div>
      <PageHeader
        title="🔔 Alerts"
        subtitle="Trigger Telegram, email, and webhook notifications"
        action={<Button variant="secondary" size="sm" leftIcon={<Send size={12} />} onClick={testTelegram} loading={testing}>Test Telegram</Button>}
      />

      <Card style={{ marginBottom: 14 }}>
        <SectionTitle>Create Alert</SectionTitle>
        <Grid cols={5} minCol={140} gap={10}>
          <Input label="Ticker" value={form.ticker} onChange={e => setForm({ ...form, ticker: e.target.value.toUpperCase() })} fullWidth />
          <Select label="Type" value={form.asset_type} onChange={e => setForm({ ...form, asset_type: e.target.value })} fullWidth>
            <option value="stock">Stock</option>
            <option value="crypto">Crypto</option>
          </Select>
          <Select label="Condition" value={form.condition} onChange={e => setForm({ ...form, condition: e.target.value })} fullWidth>
            {CONDITIONS.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}
          </Select>
          <Input label="Threshold" type="number" step="0.01" value={form.threshold} onChange={e => setForm({ ...form, threshold: e.target.value })} fullWidth />
          <div>
            <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>Channels</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', paddingTop: 6 }}>
              {['telegram', 'email', 'webhook'].map(ch => (
                <label key={ch} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: form.channels.includes(ch) ? tokens.text : tokens.textMuted, cursor: 'pointer' }}>
                  <input type="checkbox" checked={form.channels.includes(ch)}
                    onChange={() => setForm({ ...form, channels: form.channels.includes(ch) ? form.channels.filter(c => c !== ch) : [...form.channels, ch] })} />
                  {ch}
                </label>
              ))}
            </div>
          </div>
        </Grid>
        <div style={{ marginTop: 12 }}>
          <Button onClick={create} loading={creating} leftIcon={<Plus size={13} />}>Create Alert</Button>
        </div>
      </Card>

      <Card>
        <SectionTitle icon={<Bell size={14} />}>Active Alerts ({alerts.length})</SectionTitle>
        {loading ? <Loading message="Loading alerts…" /> :
          alerts.length === 0 ? <Empty message="No alerts configured yet" icon="🔔" /> : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12, color: tokens.textMuted }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                    {['Ticker', 'Condition', 'Threshold', 'Channels', 'Status', 'Created', ''].map(h =>
                      <th key={h} style={{ padding: '8px 10px', fontWeight: 500 }}>{h}</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((a, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                      <td style={{ padding: '10px', color: tokens.text, fontWeight: 600 }}>{a.ticker}</td>
                      <td style={{ padding: '10px' }}>{a.condition}</td>
                      <td style={{ padding: '10px' }}>{a.threshold}</td>
                      <td style={{ padding: '10px' }}>{(a.channels || []).join(', ')}</td>
                      <td style={{ padding: '10px' }}>
                        <Badge color={a.triggered ? tokens.success : tokens.info}>{a.triggered ? 'Triggered' : 'Watching'}</Badge>
                      </td>
                      <td style={{ padding: '10px' }}>{a.created_at?.slice(0, 10)}</td>
                      <td style={{ padding: '10px' }}>
                        <Button variant="danger" size="sm" onClick={() => remove(a._id)} leftIcon={<Trash2 size={11} />}>Delete</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </Card>
    </div>
  )
}
