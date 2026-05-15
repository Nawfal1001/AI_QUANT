import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { useLivePrices } from '@/hooks/useLivePrices'
import { Card, Metric, PageHeader, SectionTitle, Loading, Empty, Grid, Badge } from '@/components/ui'
import { LineChart, DonutChart, BarChart, Heatmap } from '@/components/ui/charts'
import { tokens, fmt$, fmtPct } from '@/components/ui/tokens'
import { TrendingUp, TrendingDown, Activity, Zap, Briefcase, Target } from 'lucide-react'

export default function Dashboard() {
  const [paper, setPaper] = useState(null)
  const [risk, setRisk] = useState(null)
  const [positions, setPositions] = useState([])
  const [signals, setSignals] = useState([])
  const [signalStats, setSignalStats] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)

  const tickers = positions.map(p => p.ticker)
  const { prices } = useLivePrices(tickers)

  async function load() {
    try {
      const [p, r, pos, sigs, stats, ord] = await Promise.all([
        api.get('/paper/summary').catch(() => null),
        api.get('/risk/status').catch(() => null),
        api.get('/paper/positions').catch(() => null),
        api.get('/signal-perf/recent?limit=10').catch(() => null),
        api.get('/signal-perf/stats/strategy').catch(() => null),
        api.get('/paper/orders?limit=10').catch(() => null),
      ])
      setPaper(p?.data || null)
      setRisk(r?.data || null)
      setPositions(pos?.data?.positions || [])
      setSignals(sigs?.data?.signals || [])
      setSignalStats(stats?.data?.stats || [])
      setOrders(ord?.data?.orders || [])
    } catch (e) { console.error(e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  if (loading) return <Loading message="Loading dashboard…" />

  // Build equity history from closed orders + summary
  const equityCurve = []
  if (paper) {
    const closedOrders = orders.filter(o => o.status === 'filled' && o.realized_pnl != null).reverse()
    let runningCapital = paper.starting_capital
    equityCurve.push({ date: 'Start', equity: runningCapital })
    closedOrders.forEach(o => {
      runningCapital += (o.realized_pnl || 0)
      equityCurve.push({ date: (o.filled_at || '').slice(5, 10), equity: runningCapital })
    })
    if (equityCurve.length < 2) {
      equityCurve.push({ date: 'Now', equity: paper.equity })
    }
  }

  // Portfolio allocation
  const allocation = positions.map(p => ({
    label: p.ticker,
    value: p.market_value || (p.qty * (p.current_price || p.avg_entry)),
  })).filter(a => a.value > 0)

  // P&L history bars
  const pnlBars = orders.filter(o => o.realized_pnl != null && o.realized_pnl !== 0).slice(0, 20).reverse().map(o => ({
    date: (o.filled_at || '').slice(5, 10),
    value: o.realized_pnl,
  }))

  return (
    <div>
      <PageHeader title="📊 Dashboard" subtitle="Live trading overview" />

      {/* Top metrics */}
      <Grid cols={4} minCol={160} gap={10}>
        <Metric label="Equity" value={fmt$(paper?.equity || risk?.equity || 0)} icon={<Briefcase size={11} />} />
        <Metric
          label="Today P&L"
          value={paper ? `${paper.total_pnl >= 0 ? '+' : ''}${fmt$(paper.total_pnl)}` : '—'}
          color={paper?.total_pnl >= 0 ? tokens.success : tokens.danger}
          sub={paper ? fmtPct(paper.total_return_pct) : ''}
        />
        <Metric label="Open Positions" value={positions.length} sub={`${orders.filter(o => o.status === 'filled').length} fills`} icon={<Activity size={11} />} />
        <Metric label="Closed Trades" value={paper?.closed_trades || 0} sub={`Realized ${fmt$(paper?.realized_pnl || 0)}`} />
      </Grid>

      {/* Charts row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 14, marginTop: 14 }}>
        <Card>
          <SectionTitle icon={<TrendingUp size={14} />}>Equity Curve</SectionTitle>
          {equityCurve.length >= 2 ? (
            <LineChart data={equityCurve} yKey="equity" height={200} />
          ) : (
            <Empty message="No closed trades yet. Place a paper trade to see your equity curve." icon="📈" />
          )}
        </Card>

        <Card>
          <SectionTitle icon={<Briefcase size={14} />}>Allocation</SectionTitle>
          {allocation.length > 0 ? (
            <DonutChart data={allocation} size={180} centerLabel={fmt$(paper?.market_value || 0)} />
          ) : (
            <Empty message="No open positions" icon="💼" />
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 14, marginTop: 14 }}>
        <Card>
          <SectionTitle icon={<TrendingDown size={14} />}>P&L per Trade</SectionTitle>
          {pnlBars.length > 0 ? (
            <BarChart data={pnlBars} yKey="value" height={200} />
          ) : (
            <Empty message="No realized P&L yet" icon="💸" />
          )}
        </Card>

        <Card>
          <SectionTitle icon={<Target size={14} />}>Strategy Win Rates</SectionTitle>
          {signalStats.length > 0 ? (
            <div>
              {signalStats.slice(0, 5).map(s => (
                <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: `1px solid ${tokens.border}` }}>
                  <div style={{ flex: 1, fontSize: 13, color: tokens.text, fontWeight: 500 }}>{s.key}</div>
                  <div style={{ fontSize: 11, color: tokens.textMuted, minWidth: 70 }}>{s.wins}W / {s.losses}L</div>
                  <div style={{ width: 100, background: tokens.bg, borderRadius: 4, height: 8, overflow: 'hidden' }}>
                    <div style={{
                      width: `${Math.min(100, s.win_rate)}%`,
                      height: '100%',
                      background: s.win_rate >= 60 ? tokens.success : s.win_rate >= 45 ? tokens.warning : tokens.danger,
                    }} />
                  </div>
                  <div style={{ fontSize: 12, color: tokens.text, fontWeight: 600, minWidth: 50, textAlign: 'right' }}>{s.win_rate}%</div>
                </div>
              ))}
            </div>
          ) : (
            <Empty message="No signal stats yet. Generate some signals first." icon="🎯" />
          )}
        </Card>
      </div>

      {/* Recent signals */}
      <Card style={{ marginTop: 14 }}>
        <SectionTitle icon={<Zap size={14} />}>Recent Signals</SectionTitle>
        {signals.length === 0 ? (
          <Empty message="No signals yet — go to the Signals page to generate one" icon="⚡" />
        ) : (
          <div>
            {signals.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: i < signals.length - 1 ? `1px solid ${tokens.border}` : 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{s.ticker}</div>
                  <Badge color={s.signal?.includes('BUY') ? tokens.success : s.signal?.includes('SELL') ? tokens.danger : tokens.textMuted}>{s.signal}</Badge>
                  <span style={{ fontSize: 11, color: tokens.textMuted }}>{s.confidence}% · {s.strategy || 'default'} · {s.timeframe || 'swing'}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {s.status === 'resolved' && (
                    <Badge color={s.outcome === 'win' ? tokens.success : tokens.danger}>{s.outcome}</Badge>
                  )}
                  <div style={{ fontSize: 10, color: tokens.textMuted }}>{(s.emitted_at || '').slice(0, 16)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
