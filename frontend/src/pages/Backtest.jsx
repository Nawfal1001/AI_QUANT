import React, { useState, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, PageHeader, SectionTitle, Metric, Grid, Badge } from '@/components/ui'
import { LineChart, DrawdownChart } from '@/components/ui/charts'
import { tokens, signColor } from '@/components/ui/tokens'
import { Play, History, AlertCircle, ChevronDown, ChevronUp, BarChart2, Activity } from 'lucide-react'

const FRAME_OPTIONS = ['15m', '1h', '4h', '1d']

export default function Backtest() {
  const [searchParams] = useSearchParams()
  const initialUserStrategy = searchParams.get('user_strategy_id') || ''
  const [ticker, setTicker] = useState('AAPL')
  const [assetType, setAssetType] = useState('stock')
  const [capital, setCapital] = useState(10000)
  const [days, setDays] = useState(365)
  const [interval, setInterval_] = useState('1d')
  const [multiFrames, setMultiFrames] = useState(false)
  const [selectedFrames, setSelectedFrames] = useState(['1d'])
  const [strategy, setStrategy] = useState('ensemble')
  const [minConf, setMinConf] = useState(55)
  const [risk, setRisk] = useState(2)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [slMult, setSlMult] = useState(2.0)
  const [tpMult, setTpMult] = useState(3.0)
  const [feeBps, setFeeBps] = useState(5)
  const [slipBps, setSlipBps] = useState(3)
  const [spreadBps, setSpreadBps] = useState(2)
  const [strategies, setStrategies] = useState([])
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  const [showTrades, setShowTrades] = useState(false)
  const [compareMode, setCompareMode] = useState(false)
  const [comparison, setComparison] = useState(null)
  const [userStrategies, setUserStrategies] = useState([])
  const [userStrategyId, setUserStrategyId] = useState(initialUserStrategy)
  const [jobId, setJobId] = useState(null)
  const [jobStatus, setJobStatus] = useState(null)
  const [jobProgress, setJobProgress] = useState(0)
  const [jobLogs, setJobLogs] = useState([])
  const pollRef = useRef(null)

  useEffect(() => {
    api.get('/backtest/strategies').then(r => setStrategies(r.data?.strategies || [])).catch(e => console.warn('caught:', e))
    api.get('/strategy-lab/').then(r => setUserStrategies(r.data?.strategies || [])).catch(e => console.warn('caught:', e))
    loadHistory()
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  async function loadHistory() {
    try { const r = await api.get('/backtest/history?limit=10'); setHistory(r.data?.backtests || []) }
    catch (e) { console.warn('caught:', e) }
  }

  function toggleFrame(f) {
    setSelectedFrames(prev => prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f])
  }

  function payload() {
    const frames = selectedFrames.length ? selectedFrames : [interval]
    const p = { ticker, asset_type: assetType, capital: Number(capital), days: Number(days), interval, intervals: multiFrames ? frames : [interval], strategy, min_confidence: Number(minConf), risk_per_trade: Number(risk) / 100, sl_atr_mult: Number(slMult), tp_atr_mult: Number(tpMult), fee_bps: Number(feeBps), slippage_bps: Number(slipBps), spread_bps: Number(spreadBps) }
    if (userStrategyId) p.user_strategy_id = userStrategyId
    return p
  }

  async function pollJob(id) {
    try {
      const r = await api.get(`/backtest/jobs/${id}`)
      setJobStatus(r.data?.status)
      setJobProgress(Number(r.data?.progress || 0))
      setJobLogs(r.data?.logs || [])
      if (r.data?.error) setError(r.data.error)
      if (r.data?.status === 'completed') {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setRunning(false)
        setResult(r.data?.result)
        loadHistory()
      }
      if (r.data?.status === 'failed') {
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = null
        setRunning(false)
      }
    } catch (e) { setError(e?.response?.data?.detail || e?.message || 'Could not load backtest job') }
  }

  async function runBacktest() {
    setRunning(true); setError(null); setResult(null); setComparison(null); setJobId(null); setJobLogs([]); setJobProgress(0); setJobStatus('starting')
    try {
      if (compareMode) {
        const r = await api.post('/backtest/compare', { ticker, asset_type: assetType, capital: Number(capital), days: Number(days), interval, min_confidence: Number(minConf), risk_per_trade: Number(risk) / 100 })
        setComparison(r.data); setRunning(false)
      } else {
        const r = await api.post('/backtest/jobs', payload())
        const id = r.data?.job_id
        setJobId(id); setJobStatus(r.data?.status || 'queued'); setJobProgress(r.data?.progress || 0)
        await pollJob(id)
        if (pollRef.current) clearInterval(pollRef.current)
        pollRef.current = setInterval(() => pollJob(id), 1500)
      }
    } catch (e) { setError(e?.response?.data?.detail || e?.message || 'Backtest failed'); setRunning(false) }
  }

  const finalResult = result?.mode === 'multi_timeframe' ? result.best_result : result

  return <div>
    <PageHeader title="📊 Backtesting" subtitle="Single or multi-timeframe tests with live logs and trade-by-trade output" />
    <Card style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', background: tokens.bgInput, borderRadius: tokens.r1, padding: 2 }}>
          <button onClick={() => setCompareMode(false)} style={{ padding: '6px 14px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12, background: !compareMode ? tokens.primary : 'transparent', color: !compareMode ? '#fff' : tokens.textMuted }}>Single Strategy</button>
          <button onClick={() => setCompareMode(true)} style={{ padding: '6px 14px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12, background: compareMode ? tokens.primary : 'transparent', color: compareMode ? '#fff' : tokens.textMuted }}>Compare All Strategies</button>
        </div>
        {!compareMode && <label style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: tokens.textMuted }}><input type="checkbox" checked={multiFrames} onChange={e => setMultiFrames(e.target.checked)} /> Test multiple frames</label>}
      </div>
      <Grid cols={4} minCol={130} gap={12}>
        <Input label="Ticker" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="AAPL or BTC" />
        <Select label="Asset" value={assetType} onChange={e => setAssetType(e.target.value)}><option value="stock">Stock</option><option value="crypto">Crypto</option><option value="forex">Forex</option><option value="gold">Gold</option><option value="oil">Oil</option></Select>
        <Input label="Capital ($)" type="number" value={capital} onChange={e => setCapital(e.target.value)} />
        <Select label="Period" value={days} onChange={e => setDays(Number(e.target.value))}><option value={90}>90 days</option><option value={180}>6 months</option><option value={365}>1 year</option><option value={730}>2 years</option></Select>
        {!multiFrames && <Select label="Interval" value={interval} onChange={e => setInterval_(e.target.value)}><option value="1d">Daily</option><option value="4h">4 Hour</option><option value="1h">1 Hour</option><option value="15m">15 Min</option></Select>}
        {multiFrames && <div><div style={{ fontSize: 12, color: tokens.textMuted, marginBottom: 6 }}>Timeframes</div><div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{FRAME_OPTIONS.map(f => <button key={f} type="button" onClick={() => toggleFrame(f)} style={{ padding: '7px 10px', borderRadius: 8, border: `1px solid ${selectedFrames.includes(f) ? tokens.primary : tokens.border}`, background: selectedFrames.includes(f) ? tokens.primary : tokens.bgInput, color: selectedFrames.includes(f) ? '#fff' : tokens.textMuted, cursor: 'pointer' }}>{f}</button>)}</div></div>}
        {!compareMode && <Select label="Strategy" value={userStrategyId ? `__user__${userStrategyId}` : strategy} onChange={e => { const val = e.target.value; if (val.startsWith('__user__')) setUserStrategyId(val.replace('__user__', '')); else { setUserStrategyId(''); setStrategy(val) } }}><optgroup label="Built-in">{strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</optgroup>{userStrategies.length > 0 && <optgroup label="My Custom Strategies">{userStrategies.map(s => <option key={s._id} value={`__user__${s._id}`}>🧪 {s.name}</option>)}</optgroup>}</Select>}
        <Input label="Min Confidence (%)" type="number" value={minConf} onChange={e => setMinConf(e.target.value)} />
        <Input label="Risk Per Trade (%)" type="number" step="0.5" value={risk} onChange={e => setRisk(e.target.value)} />
      </Grid>
      {!compareMode && <div style={{ marginTop: 12 }}><button onClick={() => setShowAdvanced(!showAdvanced)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, color: tokens.textMuted, display: 'flex', alignItems: 'center', gap: 5, padding: '4px 0' }}>{showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />} Advanced</button>{showAdvanced && <Grid cols={5} minCol={120} gap={10} style={{ marginTop: 8 }}><Input label="SL ATR Mult" type="number" step="0.5" value={slMult} onChange={e => setSlMult(e.target.value)} /><Input label="TP ATR Mult" type="number" step="0.5" value={tpMult} onChange={e => setTpMult(e.target.value)} /><Input label="Fee (bps)" type="number" value={feeBps} onChange={e => setFeeBps(e.target.value)} /><Input label="Slippage (bps)" type="number" value={slipBps} onChange={e => setSlipBps(e.target.value)} /><Input label="Spread (bps)" type="number" value={spreadBps} onChange={e => setSpreadBps(e.target.value)} /></Grid>}</div>}
      <div style={{ marginTop: 14 }}><Button onClick={runBacktest} disabled={running || (multiFrames && selectedFrames.length === 0)} loading={running} leftIcon={<Play size={14} />}>{running ? 'Running…' : compareMode ? 'Compare Strategies' : multiFrames ? `Run ${selectedFrames.length} Frames` : 'Run Backtest'}</Button></div>
    </Card>

    {(jobId || running || jobLogs.length > 0) && !compareMode && <Card style={{ marginBottom: 14 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}><SectionTitle icon={<Activity size={14} />}>Live Backtest Progress</SectionTitle><div style={{ fontSize: 12, color: tokens.textMuted }}>{jobStatus || 'idle'} · {Math.round(jobProgress)}%</div></div><div style={{ background: tokens.bgInput, borderRadius: 8, height: 9, overflow: 'hidden', marginBottom: 12 }}><div style={{ height: '100%', width: `${Math.min(100, jobProgress)}%`, background: tokens.primary }} /></div><div style={{ maxHeight: 280, overflowY: 'auto', background: '#05080d', border: `1px solid ${tokens.border}`, borderRadius: 10, padding: 10, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12 }}>{jobLogs.length === 0 && <div style={{ color: tokens.textMuted }}>Waiting for logs...</div>}{jobLogs.map((l, i) => <div key={i} style={{ color: l.level === 'error' ? tokens.danger : l.level === 'warning' ? tokens.warning : l.level === 'success' ? tokens.success : tokens.textMuted, marginBottom: 5 }}><span style={{ color: '#64748b' }}>{l.ts?.slice(11, 19)}</span> {l.message}</div>)}</div></Card>}
    {error && <Card style={{ borderColor: tokens.danger, marginBottom: 14, color: tokens.danger, display: 'flex', gap: 8, alignItems: 'center' }}><AlertCircle size={14} /><div style={{ fontSize: 13 }}>{error}</div></Card>}

    {result?.mode === 'multi_timeframe' && <Card style={{ marginBottom: 14 }}><SectionTitle>🧪 Multi-Timeframe Summary — Best: {result.best_interval}</SectionTitle><div style={{ overflowX: 'auto' }}><table style={{ width: '100%', fontSize: 12 }}><thead><tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left', color: tokens.textMuted }}>{['Frame', 'Return', 'Sharpe', 'Max DD', 'Win %', 'Trades', 'Status'].map(h => <th key={h} style={{ padding: '8px 10px', fontWeight: 500 }}>{h}</th>)}</tr></thead><tbody>{result.summary?.map((s, i) => <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}><td style={{ padding: '8px 10px', color: s.interval === result.best_interval ? tokens.success : tokens.text, fontWeight: 700 }}>{s.interval}</td><td style={{ padding: '8px 10px', color: signColor(s.return) }}>{s.return == null ? '-' : `${s.return > 0 ? '+' : ''}${s.return}%`}</td><td style={{ padding: '8px 10px' }}>{s.sharpe ?? '-'}</td><td style={{ padding: '8px 10px', color: tokens.danger }}>{s.max_drawdown == null ? '-' : `${s.max_drawdown}%`}</td><td style={{ padding: '8px 10px' }}>{s.win_rate == null ? '-' : `${s.win_rate}%`}</td><td style={{ padding: '8px 10px' }}>{s.trades ?? '-'}</td><td style={{ padding: '8px 10px', color: s.error ? tokens.danger : tokens.success }}>{s.error ? 'failed' : 'ok'}</td></tr>)}</tbody></table></div></Card>}

    {finalResult && !error && <><Grid cols={4} minCol={150} gap={10} style={{ marginBottom: 14 }}><Metric label="Total Return" value={`${finalResult.total_return_pct >= 0 ? '+' : ''}${finalResult.total_return_pct}%`} color={signColor(finalResult.total_return_pct)} sub={`Best frame ${finalResult.interval || interval}`} /><Metric label="CAGR" value={`${finalResult.cagr_pct}%`} color={signColor(finalResult.cagr_pct)} /><Metric label="Sharpe" value={finalResult.sharpe} color={finalResult.sharpe >= 1 ? tokens.success : finalResult.sharpe >= 0 ? tokens.warning : tokens.danger} sub={`Sortino ${finalResult.sortino}`} /><Metric label="Max Drawdown" value={`${finalResult.max_drawdown}%`} color={tokens.danger} /><Metric label="Win Rate" value={`${finalResult.win_rate}%`} color={finalResult.win_rate >= 50 ? tokens.success : tokens.warning} sub={`${finalResult.wins}W / ${finalResult.losses}L`} /><Metric label="Profit Factor" value={finalResult.profit_factor} color={finalResult.profit_factor >= 1.5 ? tokens.success : finalResult.profit_factor >= 1 ? tokens.warning : tokens.danger} /><Metric label="Expectancy" value={`$${finalResult.expectancy}`} color={signColor(finalResult.expectancy)} sub="per trade" /><Metric label="Total Trades" value={finalResult.total_trades} sub={`${finalResult.bars} bars`} /></Grid><Card style={{ marginBottom: 14 }}><SectionTitle>📈 Equity Curve</SectionTitle><LineChart data={finalResult.equity_curve} xKey="date" yKey="equity" height={220} /></Card><Card style={{ marginBottom: 14 }}><SectionTitle>📉 Drawdown</SectionTitle><DrawdownChart data={finalResult.drawdown_curve} xKey="date" yKey="dd_pct" height={160} /></Card><Card><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}><SectionTitle>📋 Trades ({finalResult.trades?.length || 0})</SectionTitle><Button size="sm" variant="secondary" onClick={() => setShowTrades(!showTrades)}>{showTrades ? 'Hide' : 'Show'}</Button></div>{showTrades && <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', fontSize: 11, color: tokens.textMuted }}><thead><tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>{['#', 'Entry', 'Exit', 'Side', 'Entry $', 'Exit $', 'PnL', 'PnL %', 'Reason', 'Bars'].map(h => <th key={h} style={{ padding: '6px 8px', fontWeight: 500 }}>{h}</th>)}</tr></thead><tbody>{finalResult.trades?.map((t, i) => <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}><td style={{ padding: '6px 8px' }}>{i + 1}</td><td style={{ padding: '6px 8px' }}>{t.entry_date}</td><td style={{ padding: '6px 8px' }}>{t.exit_date}</td><td style={{ padding: '6px 8px', color: t.side === 'BUY' ? tokens.success : tokens.danger, fontWeight: 600 }}>{t.side}</td><td style={{ padding: '6px 8px' }}>${t.entry_price}</td><td style={{ padding: '6px 8px' }}>${t.exit_price}</td><td style={{ padding: '6px 8px', color: signColor(t.pnl), fontWeight: 600 }}>${t.pnl}</td><td style={{ padding: '6px 8px', color: signColor(t.pnl_pct) }}>{t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct}%</td><td style={{ padding: '6px 8px' }}><Badge color={t.exit_reason === 'TP' ? tokens.success : t.exit_reason === 'SL' ? tokens.danger : tokens.textMuted}>{t.exit_reason}</Badge></td><td style={{ padding: '6px 8px' }}>{t.bars_held}</td></tr>)}</tbody></table></div>}</Card></>}

    {comparison && !error && <Card style={{ marginBottom: 14 }}><SectionTitle icon={<BarChart2 size={14} />}>Strategy Comparison — {comparison.ticker}</SectionTitle><div style={{ overflowX: 'auto' }}><table style={{ width: '100%', fontSize: 12 }}><thead><tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left', color: tokens.textMuted }}>{['Strategy', 'Return', 'Sharpe', 'Max DD', 'Win %', 'PF', 'Trades', 'Expectancy'].map(h => <th key={h} style={{ padding: '8px 10px', fontWeight: 500 }}>{h}</th>)}</tr></thead><tbody>{Object.entries(comparison.strategies).map(([sid, s]) => s.error ? <tr key={sid}><td style={{ padding: '8px 10px', color: tokens.text, fontWeight: 600 }}>{sid}</td><td colSpan={7} style={{ padding: '8px 10px', color: tokens.danger }}>{s.error}</td></tr> : <tr key={sid} style={{ borderBottom: `1px solid ${tokens.border}` }}><td style={{ padding: '8px 10px', color: tokens.text, fontWeight: 600, textTransform: 'capitalize' }}>{sid.replace(/_/g, ' ')}</td><td style={{ padding: '8px 10px', color: signColor(s.total_return_pct), fontWeight: 600 }}>{s.total_return_pct > 0 ? '+' : ''}{s.total_return_pct}%</td><td style={{ padding: '8px 10px', color: s.sharpe >= 1 ? tokens.success : tokens.text }}>{s.sharpe}</td><td style={{ padding: '8px 10px', color: tokens.danger }}>{s.max_drawdown}%</td><td style={{ padding: '8px 10px' }}>{s.win_rate}%</td><td style={{ padding: '8px 10px', color: s.profit_factor >= 1.5 ? tokens.success : tokens.text }}>{s.profit_factor}</td><td style={{ padding: '8px 10px' }}>{s.total_trades}</td><td style={{ padding: '8px 10px', color: signColor(s.expectancy) }}>${s.expectancy}</td></tr>)}</tbody></table></div></Card>}
    {history.length > 0 && !finalResult && !comparison && <Card><SectionTitle icon={<History size={14} />}>Recent Backtests</SectionTitle><div style={{ overflowX: 'auto' }}><table style={{ width: '100%', fontSize: 12, color: tokens.textMuted }}><thead><tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>{['Date', 'Ticker', 'Strategy', 'Return', 'Sharpe', 'Win %', 'Trades'].map(h => <th key={h} style={{ padding: '7px 10px', fontWeight: 500 }}>{h}</th>)}</tr></thead><tbody>{history.map((b, i) => <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}><td style={{ padding: '7px 10px' }}>{b.saved_at?.slice(0, 10)}</td><td style={{ padding: '7px 10px', color: tokens.text, fontWeight: 600 }}>{b.ticker}</td><td style={{ padding: '7px 10px', textTransform: 'capitalize' }}>{(b.strategy || 'ensemble').replace(/_/g, ' ')}</td><td style={{ padding: '7px 10px', color: signColor(b.total_return_pct), fontWeight: 600 }}>{b.total_return_pct >= 0 ? '+' : ''}{b.total_return_pct}%</td><td style={{ padding: '7px 10px' }}>{b.sharpe}</td><td style={{ padding: '7px 10px' }}>{b.win_rate}%</td><td style={{ padding: '7px 10px' }}>{b.total_trades}</td></tr>)}</tbody></table></div></Card>}
  </div>
}
