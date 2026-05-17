import React, { useEffect, useState } from 'react'
import { api } from '@/store/auth'
import { Card, Button, PageHeader, Badge, SectionTitle } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Activity, RefreshCw, Sparkles, AlertCircle } from 'lucide-react'

const levelColor = (level, ok) => ok ? tokens.success : level === 'warning' ? tokens.warning : tokens.danger

export default function Diagnostics() {
  const [health, setHealth] = useState(null)
  const [prompt, setPrompt] = useState('Reply with OK and one short market risk warning.')
  const [aiResult, setAiResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [testingAi, setTestingAi] = useState(false)
  const [logs, setLogs] = useState([])
  const addLog = (msg, level='info', data=null) => setLogs(p => [...p.slice(-120), { ts: new Date().toISOString(), msg, level, data }])

  async function loadHealth() {
    setLoading(true)
    addLog('Loading diagnostics health...')
    try {
      const r = await api.get('/diagnostics/health')
      setHealth(r.data)
      addLog(`Diagnostics loaded: ${r.data?.status || 'unknown'}`, r.data?.status === 'ok' ? 'success' : 'warning', r.data)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || 'Diagnostics health failed'
      addLog(msg, 'error', e.response?.data || null)
    }
    setLoading(false)
  }

  async function testAi() {
    setTestingAi(true)
    setAiResult(null)
    addLog('Starting AI test...')
    try {
      const r = await api.post('/diagnostics/ai-test', { prompt })
      setAiResult(r.data)
      addLog(r.data?.ok ? `AI test OK in ${r.data.latency_ms}ms` : `AI test failed: ${r.data?.error}`, r.data?.ok ? 'success' : 'error', r.data)
    } catch (e) {
      const msg = e.response?.data?.detail || e.message || 'AI test failed'
      addLog(msg, 'error', e.response?.data || null)
    }
    setTestingAi(false)
  }

  async function testCalendar() {
    addLog('Testing calendar events endpoint...')
    try {
      const r = await api.get('/calendar/events?with_ai=false&limit=5')
      addLog(`Calendar OK: ${(r.data?.events || []).length} events returned`, 'success', r.data)
    } catch (e) { addLog(e.response?.data?.detail || e.message, 'error', e.response?.data || null) }
  }

  async function testAutoSignals() {
    addLog('Testing auto-signals latest endpoint...')
    try {
      const r = await api.get('/auto-signals/latest?limit=5')
      addLog(`Auto-signals OK: ${(r.data?.signals || []).length} rows returned`, 'success', r.data)
    } catch (e) { addLog(e.response?.data?.detail || e.message, 'error', e.response?.data || null) }
  }

  useEffect(() => { loadHealth() }, [])

  const checks = health?.checks || []
  return <div>
    <PageHeader title="🧪 Diagnostics" subtitle="Environment, AI, provider checks, and debug logs without exposing secrets" action={<Button variant="secondary" size="sm" onClick={loadHealth} loading={loading} leftIcon={<RefreshCw size={12}/>}>Refresh</Button>} />

    <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))', gap:12, marginBottom:14 }}>
      <Card><div style={{ fontSize:11, color:tokens.textMuted }}>SYSTEM STATUS</div><div style={{ fontSize:22, fontWeight:800, color:health?.status==='ok'?tokens.success:tokens.warning }}>{health?.status || 'loading'}</div></Card>
      <Card><div style={{ fontSize:11, color:tokens.textMuted }}>LIVE TRADING</div><Badge color={health?.live_trading ? tokens.danger : tokens.success}>{health?.live_trading ? 'enabled' : 'disabled / paper'}</Badge></Card>
      <Card><div style={{ fontSize:11, color:tokens.textMuted }}>AUTO SCANNER</div><Badge color={String(health?.auto_signal_scanner).toLowerCase()==='true' ? tokens.success : tokens.warning}>{String(health?.auto_signal_scanner ?? 'unknown')}</Badge></Card>
    </div>

    <Card style={{ marginBottom:14 }}>
      <SectionTitle icon={<Activity size={14}/>}>Environment Health</SectionTitle>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(250px,1fr))', gap:10 }}>
        {checks.map((c,i)=><div key={i} style={{ background:tokens.bg, border:`1px solid ${tokens.border}`, borderRadius:10, padding:12 }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', gap:8 }}><strong style={{ color:tokens.text }}>{c.name}</strong><Badge color={levelColor(c.level,c.ok)}>{c.ok ? 'OK' : c.level}</Badge></div>
          <div style={{ fontSize:11, color:tokens.textMuted, marginTop:6 }}>{c.detail || '—'}</div>
        </div>)}
      </div>
    </Card>

    <Card style={{ marginBottom:14 }}>
      <SectionTitle icon={<Sparkles size={14}/>}>AI Test</SectionTitle>
      <textarea value={prompt} onChange={e=>setPrompt(e.target.value)} style={{ width:'100%', minHeight:80, background:tokens.bg, border:`1px solid ${tokens.border}`, borderRadius:8, color:tokens.text, padding:10, marginBottom:10 }} />
      <Button onClick={testAi} loading={testingAi} leftIcon={<Sparkles size={12}/>}>Run AI Test</Button>
      {aiResult && <div style={{ marginTop:12, background:tokens.bg, border:`1px solid ${tokens.border}`, borderRadius:8, padding:12, color:aiResult.ok?tokens.text:tokens.danger, fontSize:12, whiteSpace:'pre-wrap' }}>{aiResult.ok ? aiResult.response : aiResult.error}</div>}
    </Card>

    <Card style={{ marginBottom:14 }}>
      <SectionTitle icon={<AlertCircle size={14}/>}>Provider Quick Tests</SectionTitle>
      <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
        <Button variant="secondary" size="sm" onClick={testCalendar}>Test Calendar</Button>
        <Button variant="secondary" size="sm" onClick={testAutoSignals}>Test Auto Signals</Button>
      </div>
    </Card>

    <Card>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:8 }}><SectionTitle icon={<Activity size={14}/>}>Diagnostic Logs</SectionTitle><div style={{ color:tokens.textMuted, fontSize:12 }}>{logs.length} events</div></div>
      <div style={{ maxHeight:300, overflowY:'auto', background:'#05080d', border:`1px solid ${tokens.border}`, borderRadius:10, padding:10, fontFamily:'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize:12 }}>
        {logs.map((l,i)=><div key={i} style={{ color:l.level==='error'?tokens.danger:l.level==='warning'?tokens.warning:l.level==='success'?tokens.success:tokens.textMuted, marginBottom:6 }}><span style={{ color:'#64748b' }}>{l.ts.slice(11,19)}</span> {l.msg}{l.data&&<details><summary>details</summary><pre style={{ whiteSpace:'pre-wrap' }}>{JSON.stringify(l.data,null,2)}</pre></details>}</div>)}
      </div>
    </Card>
  </div>
}
