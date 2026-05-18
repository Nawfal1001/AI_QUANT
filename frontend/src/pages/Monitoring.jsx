import React, { useEffect, useMemo, useState } from 'react'
import { api } from '@/store/auth'
import { Card, Button, PageHeader, SectionTitle, Loading, Badge, Grid, Empty } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Activity, Cpu, RefreshCw, Server, Zap } from 'lucide-react'

const mb = v => v === null || v === undefined ? '—' : `${Number(v).toFixed(1)} MB`
const pct = v => v === null || v === undefined ? '—' : `${Number(v).toFixed(1)}%`

function Bar({ value, max = 100 }) {
  const w = Math.max(0, Math.min(100, (Number(value || 0) / max) * 100))
  return <div style={{ height: 8, background: tokens.bg, borderRadius: 999, overflow: 'hidden' }}><div style={{ width: `${w}%`, height: '100%', background: w > 85 ? tokens.danger : w > 70 ? tokens.warning : tokens.success }} /></div>
}

function recommendation(data) {
  const recs = []
  const p = data?.process || {}
  const sys = data?.system || {}
  const libs = Object.fromEntries((data?.loaded_libraries || []).map(x => [x.name, x.loaded]))
  if ((sys.percent || 0) > 80) recs.push('System RAM is high: reduce active schedulers and watchlist size.')
  if ((p.rss_mb || 0) > 450) recs.push('Backend process RAM is high for Render free/small plans: lazy-load heavy libraries and reduce candle cache sizes.')
  if (libs.torch || libs.tensorflow) recs.push('Torch/TensorFlow is loaded: lazy-load ML models only when training/inference is requested.')
  if (libs.pandas && libs.numpy) recs.push('Pandas/NumPy loaded: avoid keeping large historical DataFrames in memory after scans/backtests.')
  const running = (data?.services || []).filter(s => s.running).length
  if (running >= 5) recs.push('Many background services are running: disable WFO/Hyper Tuner/Economic scheduler unless actively used.')
  if (!recs.length) recs.push('RAM looks healthy. Keep one Render worker and monitor after long backtests/scans.')
  return recs
}

export default function Monitoring() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  async function load() {
    setErr(null)
    try {
      const r = await api.get('/monitoring/system')
      setData(r.data)
    } catch (e) {
      setErr(e?.response?.data?.detail || 'Failed to load monitoring data')
    }
    setLoading(false)
  }

  useEffect(() => { load(); const id = setInterval(load, 15000); return () => clearInterval(id) }, [])
  const recs = useMemo(() => recommendation(data), [data])

  if (loading) return <Loading message="Loading monitoring…" />

  return <div>
    <PageHeader title="📊 Monitoring" subtitle="RAM usage, service status and optimization hints for Render" action={<Button leftIcon={<RefreshCw size={13} />} onClick={load}>Refresh</Button>} />
    {err && <Card style={{ borderColor: tokens.danger, marginBottom: 14, color: tokens.danger }}>{err}</Card>}

    <Grid cols={4} minCol={180} gap={12}>
      <Card><SectionTitle icon={<Server size={14} />}>Process RAM</SectionTitle><div style={{ fontSize: 24, fontWeight: 800, color: tokens.text }}>{mb(data?.process?.rss_mb)}</div><div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 4 }}>RSS memory used by backend</div></Card>
      <Card><SectionTitle icon={<Cpu size={14} />}>System RAM</SectionTitle><div style={{ fontSize: 24, fontWeight: 800, color: tokens.text }}>{pct(data?.system?.percent)}</div><Bar value={data?.system?.percent || 0} /><div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 6 }}>{mb(data?.system?.available_mb)} available</div></Card>
      <Card><SectionTitle icon={<Activity size={14} />}>Threads</SectionTitle><div style={{ fontSize: 24, fontWeight: 800, color: tokens.text }}>{data?.process?.threads ?? '—'}</div><div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 4 }}>Open files: {data?.process?.open_files ?? '—'}</div></Card>
      <Card><SectionTitle icon={<Zap size={14} />}>Uptime</SectionTitle><div style={{ fontSize: 24, fontWeight: 800, color: tokens.text }}>{Math.floor((data?.uptime_sec || 0) / 60)}m</div><div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 4 }}>PID {data?.pid}</div></Card>
    </Grid>

    <Grid cols={2} minCol={320} gap={14} style={{ marginTop: 14 }}>
      <Card><SectionTitle>Background Services</SectionTitle>{data?.services?.length ? data.services.map(s => <div key={s.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 0', borderBottom: `1px solid ${tokens.border}` }}><div><div style={{ fontSize: 13, color: tokens.text, fontWeight: 600 }}>{s.name}</div><div style={{ fontSize: 10, color: tokens.textMuted }}>{s.module}</div></div><Badge color={s.running ? tokens.success : tokens.textMuted}>{s.running ? 'running' : 'stopped'}</Badge></div>) : <Empty message="No service data" />}</Card>
      <Card><SectionTitle>Loaded Heavy Libraries</SectionTitle>{data?.loaded_libraries?.map(l => <div key={l.name} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: `1px solid ${tokens.border}` }}><code style={{ color: tokens.text, fontSize: 12 }}>{l.name}</code><Badge color={l.loaded ? tokens.warning : tokens.textMuted}>{l.loaded ? 'loaded' : 'not loaded'}</Badge></div>)}</Card>
    </Grid>

    <Card style={{ marginTop: 14 }}><SectionTitle>Optimization Recommendations</SectionTitle>{recs.map((r, i) => <div key={i} style={{ padding: '8px 0', fontSize: 13, color: tokens.text, borderBottom: i < recs.length - 1 ? `1px solid ${tokens.border}` : 'none' }}>• {r}</div>)}</Card>

    <Card style={{ marginTop: 14 }}><SectionTitle>Render / Env</SectionTitle><Grid cols={4} minCol={160} gap={10}><div><div style={{ fontSize: 10, color: tokens.textMuted }}>Environment</div><div style={{ color: tokens.text }}>{data?.env?.environment}</div></div><div><div style={{ fontSize: 10, color: tokens.textMuted }}>Render</div><div style={{ color: tokens.text }}>{String(data?.env?.render)}</div></div><div><div style={{ fontSize: 10, color: tokens.textMuted }}>AI daily limit</div><div style={{ color: tokens.text }}>{data?.env?.ai_max_calls_per_day}</div></div><div><div style={{ fontSize: 10, color: tokens.textMuted }}>AI cache TTL</div><div style={{ color: tokens.text }}>{data?.env?.ai_cache_ttl_seconds}s</div></div></Grid></Card>
  </div>
}
