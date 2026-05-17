import React, { useEffect, useState } from 'react'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, PageHeader, SectionTitle, Grid, Metric } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Brain, RefreshCw, Sparkles, Save } from 'lucide-react'

export default function AsiEvolve() {
  const [health, setHealth] = useState(null)
  const [ticker, setTicker] = useState('AAPL')
  const [assetType, setAssetType] = useState('stock')
  const [objective, setObjective] = useState('balanced')
  const [generations, setGenerations] = useState(5)
  const [notes, setNotes] = useState('Generate a robust strategy with low drawdown and clear risk rules.')
  const [loading, setLoading] = useState(false)
  const [refs, setRefs] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { checkHealth() }, [])
  async function checkHealth() { try { const r = await api.get('/asi/health'); setHealth(r.data) } catch (e) { setHealth({ status: 'error', error: e.message }) } }
  async function loadRefs() { setError(null); try { const r = await api.get(`/asi/references?ticker=${ticker}&asset_type=${assetType}&limit=10`); setRefs(r.data) } catch (e) { setError(e.response?.data?.detail || e.message) } }
  async function generate() { setLoading(true); setError(null); setResult(null); try { const r = await api.post('/asi/generate-strategy', { ticker, asset_type: assetType, objective, generations: Number(generations), notes, save: true, reference_limit: 10, timeout: 240 }); setResult(r.data) } catch (e) { setError(e.response?.data?.detail || e.message || 'ASI generation failed') } finally { setLoading(false) } }
  const strategy = result?.saved_strategy || result?.strategy || result?.generated_strategy || result

  return <div>
    <PageHeader title="🧠 ASI Evolve" subtitle="Generate new strategies from app references, backtests, indicators, and Colab-hosted ASI" />
    <Card style={{ marginBottom: 14 }}><div style={{ display:'flex', justifyContent:'space-between', gap:12, alignItems:'center' }}><SectionTitle icon={<Brain size={14}/>}>ASI Colab Connection</SectionTitle><Button size="sm" variant="secondary" onClick={checkHealth} leftIcon={<RefreshCw size={13}/>}>Refresh</Button></div><Grid cols={3} minCol={160} gap={10} style={{marginTop:10}}><Metric label="Enabled" value={health?.enabled ? 'Yes' : 'No'} /><Metric label="Status" value={health?.status || 'unknown'} color={health?.status === 'ok' ? tokens.success : tokens.warning} /><Metric label="Endpoint" value={health?.enabled ? 'Configured' : 'Missing'} /></Grid>{health?.error && <div style={{color:tokens.danger,fontSize:12,marginTop:8}}>{health.error}</div>}</Card>
    <Card style={{ marginBottom: 14 }}><SectionTitle icon={<Sparkles size={14}/>}>Generate Strategy</SectionTitle><Grid cols={4} minCol={150} gap={12}><Input label="Ticker" value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())}/><Select label="Asset" value={assetType} onChange={e=>setAssetType(e.target.value)}><option value="stock">Stock</option><option value="crypto">Crypto</option><option value="forex">Forex</option><option value="gold">Gold</option><option value="oil">Oil</option></Select><Select label="Objective" value={objective} onChange={e=>setObjective(e.target.value)}><option value="balanced">Balanced</option><option value="sharpe">Sharpe</option><option value="return">Return</option><option value="return_drawdown">Return / Drawdown</option><option value="profit_factor">Profit Factor</option></Select><Input label="Generations" type="number" value={generations} onChange={e=>setGenerations(e.target.value)}/></Grid><div style={{marginTop:10}}><Input label="Notes for ASI" value={notes} onChange={e=>setNotes(e.target.value)} /></div><div style={{display:'flex',gap:8,marginTop:12}}><Button variant="secondary" onClick={loadRefs}>Preview References</Button><Button onClick={generate} loading={loading} leftIcon={<Save size={14}/>}>Generate + Save Strategy</Button></div></Card>
    {error && <Card style={{borderColor:tokens.danger,color:tokens.danger,marginBottom:14}}>{error}</Card>}
    {refs && <Card style={{marginBottom:14}}><SectionTitle>📚 References Sent to ASI</SectionTitle><Grid cols={3} minCol={150} gap={10}><Metric label="Backtests" value={refs.recent_backtests?.length || 0}/><Metric label="User Strategies" value={refs.existing_user_strategies?.length || 0}/><Metric label="Indicators" value={refs.strategy_contract?.tradingview_style_indicators?.length || 0}/></Grid><pre style={{maxHeight:260,overflow:'auto',background:'#05080d',border:`1px solid ${tokens.border}`,borderRadius:10,padding:10,fontSize:11,color:tokens.textMuted,marginTop:10}}>{JSON.stringify(refs, null, 2)}</pre></Card>}
    {result && <Card><SectionTitle>✅ ASI Result</SectionTitle>{strategy?.name && <h3 style={{color:tokens.text,marginTop:0}}>{strategy.name}</h3>}{strategy?.description && <p style={{color:tokens.textMuted}}>{strategy.description}</p>}<Grid cols={3} minCol={150} gap={10}><Metric label="Saved" value={result?.saved_strategy?._id ? 'Yes' : 'No'} color={result?.saved_strategy?._id ? tokens.success : tokens.warning}/><Metric label="Source" value="ASI Evolve"/><Metric label="Next" value="Backtest / Optuna"/></Grid><pre style={{maxHeight:420,overflow:'auto',background:'#05080d',border:`1px solid ${tokens.border}`,borderRadius:10,padding:10,fontSize:11,color:tokens.textMuted,marginTop:12}}>{JSON.stringify(result, null, 2)}</pre></Card>}
  </div>
}
