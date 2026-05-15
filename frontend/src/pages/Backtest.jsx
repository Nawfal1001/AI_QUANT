import React, { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, PageHeader, SectionTitle, Loading, Empty, Metric, Grid, Badge } from '@/components/ui'
import { LineChart, DrawdownChart } from '@/components/ui/charts'
import { tokens, signColor } from '@/components/ui/tokens'
import { Play, RefreshCw, History, AlertCircle, ChevronDown, ChevronUp, BarChart2, FlaskConical } from 'lucide-react'
import toast from 'react-hot-toast'

export default function Backtest() {
  const [searchParams] = useSearchParams()
  const initialUserStrategy = searchParams.get('user_strategy_id') || ''

  // Config
  const [ticker, setTicker] = useState('AAPL')
  const [assetType, setAssetType] = useState('stock')
  const [capital, setCapital] = useState(10000)
  const [days, setDays] = useState(365)
  const [interval, setInterval_] = useState('1d')
  const [strategy, setStrategy] = useState('ensemble')
  const [minConf, setMinConf] = useState(55)
  const [risk, setRisk] = useState(2)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [slMult, setSlMult] = useState(2.0)
  const [tpMult, setTpMult] = useState(3.0)
  const [feeBps, setFeeBps] = useState(5)
  const [slipBps, setSlipBps] = useState(3)
  const [spreadBps, setSpreadBps] = useState(2)

  // Strategies list
  const [strategies, setStrategies] = useState([])

  // Run state
  const [result, setResult] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const [history, setHistory] = useState([])
  const [showTrades, setShowTrades] = useState(false)

  // Compare mode
  const [compareMode, setCompareMode] = useState(false)
  const [comparison, setComparison] = useState(null)

  // User strategies from Strategy Lab
  const [userStrategies, setUserStrategies] = useState([])
  const [userStrategyId, setUserStrategyId] = useState(initialUserStrategy)

  useEffect(() => {
    api.get('/backtest/strategies').then(r => setStrategies(r.data?.strategies || [])).catch(e => console.warn("caught:", e))
    api.get('/strategy-lab/').then(r => setUserStrategies(r.data?.strategies || [])).catch(e => console.warn("caught:", e))
    loadHistory()
  }, [])

  async function loadHistory() {
    try {
      const r = await api.get('/backtest/history?limit=10')
      setHistory(r.data?.backtests || [])
    } catch (e) { console.warn("caught:", e) }
  }

  async function runBacktest() {
    setRunning(true); setError(null); setResult(null); setComparison(null)
    try {
      if (compareMode) {
        const r = await api.post('/backtest/compare', {
          ticker, asset_type: assetType, capital: Number(capital), days: Number(days), interval,
          min_confidence: Number(minConf), risk_per_trade: Number(risk) / 100,
        })
        setComparison(r.data)
      } else {
        const payload = {
          ticker, asset_type: assetType, capital: Number(capital), days: Number(days), interval, strategy,
          min_confidence: Number(minConf), risk_per_trade: Number(risk) / 100,
          sl_atr_mult: Number(slMult), tp_atr_mult: Number(tpMult),
          fee_bps: Number(feeBps), slippage_bps: Number(slipBps), spread_bps: Number(spreadBps)
        }
        if (userStrategyId) payload.user_strategy_id = userStrategyId
        const r = await api.post('/backtest/run', payload)
        if (r.data?.error) setError(r.data.error)
        else { setResult(r.data); loadHistory() }
      }
    } catch (e) { setError(e?.response?.data?.detail || e?.message || 'Backtest failed') }
    setRunning(false)
  }

  return (
    <div>
      <PageHeader title="📊 Backtesting" subtitle="Real historical simulation with fees, slippage, spread, multi-strategy compare" />

      <Card style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', background: tokens.bgInput, borderRadius: tokens.r1, padding: 2 }}>
            <button onClick={() => setCompareMode(false)} style={{
              padding: '6px 14px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12,
              background: !compareMode ? tokens.primary : 'transparent', color: !compareMode ? '#fff' : tokens.textMuted,
            }}>Single Strategy</button>
            <button onClick={() => setCompareMode(true)} style={{
              padding: '6px 14px', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 12,
              background: compareMode ? tokens.primary : 'transparent', color: compareMode ? '#fff' : tokens.textMuted,
            }}>Compare All Strategies</button>
          </div>
        </div>

        <Grid cols={4} minCol={130} gap={12}>
          <Input label="Ticker" value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="AAPL or BTC" />
          <Select label="Asset" value={assetType} onChange={e => setAssetType(e.target.value)}>
            <option value="stock">Stock</option><option value="crypto">Crypto</option>
          </Select>
          <Input label="Capital ($)" type="number" value={capital} onChange={e => setCapital(e.target.value)} />
          <Select label="Period" value={days} onChange={e => setDays(Number(e.target.value))}>
            <option value={90}>90 days</option><option value={180}>6 months</option>
            <option value={365}>1 year</option><option value={730}>2 years</option>
          </Select>
          <Select label="Interval" value={interval} onChange={e => setInterval_(e.target.value)}>
            <option value="1d">Daily</option>
            {assetType === 'crypto' && <>
              <option value="4h">4 Hour</option>
              <option value="1h">1 Hour</option>
              <option value="15m">15 Min</option>
            </>}
          </Select>
          {!compareMode && (
            <Select label="Strategy" value={userStrategyId ? `__user__${userStrategyId}` : strategy} onChange={e => {
              const val = e.target.value
              if (val.startsWith('__user__')) {
                setUserStrategyId(val.replace('__user__', ''))
              } else {
                setUserStrategyId('')
                setStrategy(val)
              }
            }}>
              <optgroup label="Built-in">
                {strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </optgroup>
              {userStrategies.length > 0 && (
                <optgroup label="My Custom Strategies">
                  {userStrategies.map(s => <option key={s._id} value={`__user__${s._id}`}>🧪 {s.name}</option>)}
                </optgroup>
              )}
            </Select>
          )}
          <Input label="Min Confidence (%)" type="number" value={minConf} onChange={e => setMinConf(e.target.value)} />
          <Input label="Risk Per Trade (%)" type="number" step="0.5" value={risk} onChange={e => setRisk(e.target.value)} />
        </Grid>

        {!compareMode && (
          <div style={{ marginTop: 12 }}>
            <button onClick={() => setShowAdvanced(!showAdvanced)} style={{
              background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, color: tokens.textMuted,
              display: 'flex', alignItems: 'center', gap: 5, padding: '4px 0',
            }}>
              {showAdvanced ? <ChevronUp size={13} /> : <ChevronDown size={13} />} Advanced
            </button>
            {showAdvanced && (
              <Grid cols={5} minCol={120} gap={10} style={{ marginTop: 8 }}>
                <Input label="SL ATR Mult" type="number" step="0.5" value={slMult} onChange={e => setSlMult(e.target.value)} />
                <Input label="TP ATR Mult" type="number" step="0.5" value={tpMult} onChange={e => setTpMult(e.target.value)} />
                <Input label="Fee (bps)" type="number" value={feeBps} onChange={e => setFeeBps(e.target.value)} />
                <Input label="Slippage (bps)" type="number" value={slipBps} onChange={e => setSlipBps(e.target.value)} />
                <Input label="Spread (bps)" type="number" value={spreadBps} onChange={e => setSpreadBps(e.target.value)} />
              </Grid>
            )}
          </div>
        )}

        <div style={{ marginTop: 14 }}>
          <Button onClick={runBacktest} disabled={running} loading={running} leftIcon={<Play size={14} />}>
            {running ? 'Running…' : compareMode ? 'Compare Strategies' : 'Run Backtest'}
          </Button>
        </div>
      </Card>

      {error && (
        <Card style={{ borderColor: tokens.danger, marginBottom: 14, color: tokens.danger, display: 'flex', gap: 8, alignItems: 'center' }}>
          <AlertCircle size={14} /> <div style={{ fontSize: 13 }}>{error}</div>
        </Card>
      )}

      {/* Single result */}
      {result && !error && (
        <>
          <Grid cols={4} minCol={150} gap={10} style={{ marginBottom: 14 }}>
            <Metric label="Total Return" value={`${result.total_return_pct >= 0 ? '+' : ''}${result.total_return_pct}%`}
              color={signColor(result.total_return_pct)}
              sub={`$${result.capital_start.toLocaleString()} → $${result.capital_end.toLocaleString()}`} />
            <Metric label="CAGR" value={`${result.cagr_pct}%`} color={signColor(result.cagr_pct)} />
            <Metric label="Sharpe" value={result.sharpe}
              color={result.sharpe >= 1 ? tokens.success : result.sharpe >= 0 ? tokens.warning : tokens.danger}
              sub={`Sortino ${result.sortino}`} />
            <Metric label="Max Drawdown" value={`${result.max_drawdown}%`} color={tokens.danger} />
            <Metric label="Win Rate" value={`${result.win_rate}%`}
              color={result.win_rate >= 50 ? tokens.success : tokens.warning}
              sub={`${result.wins}W / ${result.losses}L`} />
            <Metric label="Profit Factor" value={result.profit_factor}
              color={result.profit_factor >= 1.5 ? tokens.success : result.profit_factor >= 1 ? tokens.warning : tokens.danger} />
            <Metric label="Expectancy" value={`$${result.expectancy}`} color={signColor(result.expectancy)} sub="per trade" />
            <Metric label="Total Trades" value={result.total_trades} sub={`${result.bars} bars`} />
          </Grid>

          <Card style={{ marginBottom: 14 }}>
            <SectionTitle>📈 Equity Curve</SectionTitle>
            <LineChart data={result.equity_curve} xKey="date" yKey="equity" height={220} />
          </Card>

          <Card style={{ marginBottom: 14 }}>
            <SectionTitle>📉 Drawdown</SectionTitle>
            <DrawdownChart data={result.drawdown_curve} xKey="date" yKey="dd_pct" height={160} />
          </Card>

          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <SectionTitle>📋 Trades ({result.trades?.length || 0})</SectionTitle>
              <Button size="sm" variant="secondary" onClick={() => setShowTrades(!showTrades)}>
                {showTrades ? 'Hide' : 'Show'}
              </Button>
            </div>
            {showTrades && (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', fontSize: 11, color: tokens.textMuted }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                      {['#', 'Entry', 'Exit', 'Side', 'Entry $', 'Exit $', 'PnL', 'PnL %', 'Reason', 'Bars'].map(h =>
                        <th key={h} style={{ padding: '6px 8px', fontWeight: 500 }}>{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades?.map((t, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                        <td style={{ padding: '6px 8px' }}>{i + 1}</td>
                        <td style={{ padding: '6px 8px' }}>{t.entry_date}</td>
                        <td style={{ padding: '6px 8px' }}>{t.exit_date}</td>
                        <td style={{ padding: '6px 8px', color: t.side === 'BUY' ? tokens.success : tokens.danger, fontWeight: 600 }}>{t.side}</td>
                        <td style={{ padding: '6px 8px' }}>${t.entry_price}</td>
                        <td style={{ padding: '6px 8px' }}>${t.exit_price}</td>
                        <td style={{ padding: '6px 8px', color: signColor(t.pnl), fontWeight: 600 }}>${t.pnl}</td>
                        <td style={{ padding: '6px 8px', color: signColor(t.pnl_pct) }}>{t.pnl_pct > 0 ? '+' : ''}{t.pnl_pct}%</td>
                        <td style={{ padding: '6px 8px' }}>
                          <Badge color={t.exit_reason === 'TP' ? tokens.success : t.exit_reason === 'SL' ? tokens.danger : tokens.textMuted}>
                            {t.exit_reason}
                          </Badge>
                        </td>
                        <td style={{ padding: '6px 8px' }}>{t.bars_held}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}

      {/* Compare results */}
      {comparison && !error && (
        <>
          <Card style={{ marginBottom: 14 }}>
            <SectionTitle icon={<BarChart2 size={14} />}>Strategy Comparison — {comparison.ticker}</SectionTitle>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left', color: tokens.textMuted }}>
                    {['Strategy', 'Return', 'Sharpe', 'Max DD', 'Win %', 'PF', 'Trades', 'Expectancy'].map(h =>
                      <th key={h} style={{ padding: '8px 10px', fontWeight: 500 }}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(comparison.strategies).map(([sid, s]) => {
                    if (s.error) return (
                      <tr key={sid} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                        <td style={{ padding: '8px 10px', color: tokens.text, fontWeight: 600 }}>{sid}</td>
                        <td colSpan={7} style={{ padding: '8px 10px', color: tokens.danger }}>{s.error}</td>
                      </tr>
                    )
                    return (
                      <tr key={sid} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                        <td style={{ padding: '8px 10px', color: tokens.text, fontWeight: 600, textTransform: 'capitalize' }}>{sid.replace(/_/g, ' ')}</td>
                        <td style={{ padding: '8px 10px', color: signColor(s.total_return_pct), fontWeight: 600 }}>{s.total_return_pct > 0 ? '+' : ''}{s.total_return_pct}%</td>
                        <td style={{ padding: '8px 10px', color: s.sharpe >= 1 ? tokens.success : tokens.text }}>{s.sharpe}</td>
                        <td style={{ padding: '8px 10px', color: tokens.danger }}>{s.max_drawdown}%</td>
                        <td style={{ padding: '8px 10px' }}>{s.win_rate}%</td>
                        <td style={{ padding: '8px 10px', color: s.profit_factor >= 1.5 ? tokens.success : tokens.text }}>{s.profit_factor}</td>
                        <td style={{ padding: '8px 10px' }}>{s.total_trades}</td>
                        <td style={{ padding: '8px 10px', color: signColor(s.expectancy) }}>${s.expectancy}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Overlay equity curves */}
          <Card style={{ marginBottom: 14 }}>
            <SectionTitle>📈 Equity Curves (Compared)</SectionTitle>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 14 }}>
              {Object.entries(comparison.strategies).map(([sid, s]) => {
                if (s.error || !s.equity_curve) return null
                return (
                  <div key={sid}>
                    <div style={{ fontSize: 12, color: tokens.textMuted, marginBottom: 6, textTransform: 'capitalize' }}>{sid.replace(/_/g, ' ')}</div>
                    <LineChart data={s.equity_curve} xKey="date" yKey="equity" height={160} />
                  </div>
                )
              })}
            </div>
          </Card>
        </>
      )}

      {/* History */}
      {history.length > 0 && !result && !comparison && (
        <Card>
          <SectionTitle icon={<History size={14} />}>Recent Backtests</SectionTitle>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, color: tokens.textMuted }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                  {['Date', 'Ticker', 'Strategy', 'Return', 'Sharpe', 'Win %', 'Trades'].map(h =>
                    <th key={h} style={{ padding: '7px 10px', fontWeight: 500 }}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {history.map((b, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                    <td style={{ padding: '7px 10px' }}>{b.saved_at?.slice(0, 10)}</td>
                    <td style={{ padding: '7px 10px', color: tokens.text, fontWeight: 600 }}>{b.ticker}</td>
                    <td style={{ padding: '7px 10px', textTransform: 'capitalize' }}>{(b.strategy || 'ensemble').replace(/_/g, ' ')}</td>
                    <td style={{ padding: '7px 10px', color: signColor(b.total_return_pct), fontWeight: 600 }}>
                      {b.total_return_pct >= 0 ? '+' : ''}{b.total_return_pct}%
                    </td>
                    <td style={{ padding: '7px 10px' }}>{b.sharpe}</td>
                    <td style={{ padding: '7px 10px' }}>{b.win_rate}%</td>
                    <td style={{ padding: '7px 10px' }}>{b.total_trades}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
