import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { useLivePrices } from '@/hooks/useLivePrices'
import { Card, Button, Input, Select, Metric, PageHeader, SectionTitle, Loading, Empty, Badge, Grid } from '@/components/ui'
import { DonutChart, LineChart } from '@/components/ui/charts'
import { tokens, fmt$, fmtPct } from '@/components/ui/tokens'
import { Plus, Trash2, RefreshCw, ShoppingCart, X, Briefcase } from 'lucide-react'
import toast from 'react-hot-toast'

export default function Portfolio() {
  const [summary, setSummary] = useState(null)
  const [positions, setPositions] = useState([])
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [showOrder, setShowOrder] = useState(false)
  const [orderForm, setOrderForm] = useState({ ticker: '', side: 'buy', qty: 1, price: 100, asset_type: 'stock' })
  const [placing, setPlacing] = useState(false)

  const tickers = positions.map(p => p.ticker)
  const { prices } = useLivePrices(tickers)

  async function load() {
    setLoading(true)
    try {
      const [s, p, o] = await Promise.all([
        api.get('/paper/summary'),
        api.get('/paper/positions'),
        api.get('/paper/orders?limit=30'),
      ])
      setSummary(s.data)
      setPositions(p.data?.positions || [])
      setOrders(o.data?.orders || [])
    } catch (e) { console.error(e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function placeOrder() {
    if (!orderForm.ticker || !orderForm.qty || !orderForm.price) { toast.error('Fill all fields'); return }
    setPlacing(true)
    try {
      const r = await api.post('/paper/order', {
        ticker: orderForm.ticker.toUpperCase(),
        side: orderForm.side,
        qty: Number(orderForm.qty),
        order_type: 'market',
        current_price: Number(orderForm.price),
        asset_type: orderForm.asset_type,
        skip_freshness: true,
      })
      toast.success(`${orderForm.side.toUpperCase()} ${orderForm.qty} ${orderForm.ticker} filled @ $${r.data?.order?.fill_price?.toFixed(4)}`)
      setShowOrder(false)
      setOrderForm({ ticker: '', side: 'buy', qty: 1, price: 100, asset_type: 'stock' })
      load()
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Order rejected')
    }
    setPlacing(false)
  }

  async function closePosition(p) {
    const price = prices[p.ticker]?.price || p.current_price
    if (!window.confirm(`Sell ${p.qty} ${p.ticker} @ market ($${price?.toFixed(2)})?`)) return
    try {
      await api.post('/paper/order', {
        ticker: p.ticker, side: 'sell', qty: p.qty,
        order_type: 'market', current_price: price,
        asset_type: p.asset_type, skip_freshness: true,
      })
      toast.success(`Closed ${p.ticker}`)
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
  }

  async function resetPaper() {
    if (!window.confirm('Reset paper account? All positions and history will be wiped.')) return
    try {
      await api.post('/paper/reset', { starting_capital: 10000 })
      toast.success('Paper account reset to $10,000')
      load()
    } catch { toast.error('Failed') }
  }

  const allocation = positions.map(p => ({ label: p.ticker, value: p.market_value || (p.qty * p.avg_entry) })).filter(a => a.value > 0)

  if (loading) return <Loading message="Loading portfolio…" />

  return (
    <div>
      <PageHeader
        title="💼 Portfolio"
        subtitle="Paper trading account · Real fills with fees, slippage, spread"
        action={
          <div style={{ display: 'flex', gap: 8 }}>
            <Button variant="secondary" size="sm" leftIcon={<RefreshCw size={12} />} onClick={load}>Refresh</Button>
            <Button variant="ghost" size="sm" onClick={resetPaper}>Reset Paper</Button>
            <Button leftIcon={<ShoppingCart size={13} />} onClick={() => setShowOrder(true)}>Place Order</Button>
          </div>
        }
      />

      {/* Account summary */}
      {summary && (
        <Grid cols={5} minCol={150} gap={10}>
          <Metric label="Equity" value={fmt$(summary.equity)} icon={<Briefcase size={11} />} sub={fmtPct(summary.total_return_pct)} color={summary.total_return_pct >= 0 ? tokens.success : tokens.danger} />
          <Metric label="Cash" value={fmt$(summary.cash)} />
          <Metric label="Market Value" value={fmt$(summary.market_value)} sub={`${summary.open_positions} positions`} />
          <Metric label="Realized P&L" value={fmt$(summary.realized_pnl)} color={summary.realized_pnl >= 0 ? tokens.success : tokens.danger} sub={`${summary.closed_trades} trades`} />
          <Metric label="Unrealized P&L" value={fmt$(summary.unrealized_pnl)} color={summary.unrealized_pnl >= 0 ? tokens.success : tokens.danger} />
        </Grid>
      )}

      {/* Allocation */}
      {allocation.length > 0 && (
        <Card style={{ marginTop: 14 }}>
          <SectionTitle>Allocation</SectionTitle>
          <DonutChart data={allocation} size={200} centerLabel={fmt$(summary?.market_value || 0)} />
        </Card>
      )}

      {/* Positions */}
      <Card style={{ marginTop: 14 }}>
        <SectionTitle>Open Positions</SectionTitle>
        {positions.length === 0 ? (
          <Empty message="No open positions. Place an order to get started." icon="📭" action={<Button onClick={() => setShowOrder(true)} leftIcon={<Plus size={13} />}>Place Order</Button>} />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', fontSize: 12, color: tokens.textMuted }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                  {['Ticker', 'Type', 'Qty', 'Avg Entry', 'Current', 'Cost', 'Value', 'Unrealized', 'Unreal %', 'Age', ''].map(h =>
                    <th key={h} style={{ padding: '8px 10px', fontWeight: 500 }}>{h}</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => {
                  const live = prices[p.ticker]?.price || p.current_price
                  return (
                    <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                      <td style={{ padding: '10px', color: tokens.text, fontWeight: 600 }}>{p.ticker}</td>
                      <td style={{ padding: '10px' }}><Badge color={tokens.info}>{p.asset_type}</Badge></td>
                      <td style={{ padding: '10px' }}>{p.qty.toFixed(4)}</td>
                      <td style={{ padding: '10px' }}>${p.avg_entry?.toFixed(4)}</td>
                      <td style={{ padding: '10px', color: tokens.text }}>${live?.toFixed(4)}</td>
                      <td style={{ padding: '10px' }}>{fmt$(p.cost_basis)}</td>
                      <td style={{ padding: '10px', color: tokens.text }}>{fmt$(p.market_value)}</td>
                      <td style={{ padding: '10px', color: p.unrealized_pnl >= 0 ? tokens.success : tokens.danger, fontWeight: 600 }}>{fmt$(p.unrealized_pnl)}</td>
                      <td style={{ padding: '10px', color: p.unrealized_pnl_pct >= 0 ? tokens.success : tokens.danger, fontWeight: 600 }}>{fmtPct(p.unrealized_pnl_pct)}</td>
                      <td style={{ padding: '10px', fontSize: 11 }}>{(p.opened_at || '').slice(0, 10)}</td>
                      <td style={{ padding: '10px' }}><Button variant="danger" size="sm" onClick={() => closePosition(p)} leftIcon={<X size={11} />}>Close</Button></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Recent orders */}
      <Card style={{ marginTop: 14 }}>
        <SectionTitle>Recent Orders</SectionTitle>
        {orders.length === 0 ? <Empty message="No orders yet" icon="📜" /> : (
          <div style={{ overflowX: 'auto', maxHeight: 320 }}>
            <table style={{ width: '100%', fontSize: 11, color: tokens.textMuted }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.border}`, textAlign: 'left' }}>
                  {['When', 'Ticker', 'Side', 'Qty', 'Fill $', 'Slip bps', 'Realized', 'Status'].map(h =>
                    <th key={h} style={{ padding: '7px 10px', fontWeight: 500, position: 'sticky', top: 0, background: tokens.surface }}>{h}</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {orders.map((o, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${tokens.border}` }}>
                    <td style={{ padding: '7px 10px' }}>{(o.placed_at || '').slice(5, 16)}</td>
                    <td style={{ padding: '7px 10px', color: tokens.text, fontWeight: 600 }}>{o.ticker}</td>
                    <td style={{ padding: '7px 10px' }}><Badge color={o.side === 'buy' ? tokens.success : tokens.danger}>{o.side}</Badge></td>
                    <td style={{ padding: '7px 10px' }}>{o.qty}</td>
                    <td style={{ padding: '7px 10px' }}>${o.fill_price?.toFixed(4) || '—'}</td>
                    <td style={{ padding: '7px 10px' }}>{o.slippage_bps?.toFixed(1) || '—'}</td>
                    <td style={{ padding: '7px 10px', color: (o.realized_pnl || 0) >= 0 ? tokens.success : tokens.danger }}>{o.realized_pnl ? fmt$(o.realized_pnl) : '—'}</td>
                    <td style={{ padding: '7px 10px' }}><Badge color={o.status === 'filled' ? tokens.success : o.status === 'cancelled' ? tokens.textMuted : tokens.warning}>{o.status}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Order modal */}
      {showOrder && (
        <div onClick={() => setShowOrder(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
          <Card onClick={e => e.stopPropagation()} style={{ maxWidth: 460, width: '90%' }}>
            <SectionTitle action={<Button variant="ghost" size="sm" onClick={() => setShowOrder(false)}><X size={14} /></Button>}>
              Place Paper Order
            </SectionTitle>
            <Grid cols={2} minCol={140} gap={10}>
              <Input label="Ticker" value={orderForm.ticker} onChange={e => setOrderForm({ ...orderForm, ticker: e.target.value.toUpperCase() })} fullWidth />
              <Select label="Asset" value={orderForm.asset_type} onChange={e => setOrderForm({ ...orderForm, asset_type: e.target.value })} fullWidth>
                <option value="stock">Stock</option>
                <option value="crypto">Crypto</option>
              </Select>
              <Select label="Side" value={orderForm.side} onChange={e => setOrderForm({ ...orderForm, side: e.target.value })} fullWidth>
                <option value="buy">BUY</option>
                <option value="sell">SELL</option>
              </Select>
              <Input label="Quantity" type="number" step="0.0001" value={orderForm.qty} onChange={e => setOrderForm({ ...orderForm, qty: e.target.value })} fullWidth />
              <Input label="Price ($)" type="number" step="0.01" value={orderForm.price} onChange={e => setOrderForm({ ...orderForm, price: e.target.value })} fullWidth />
            </Grid>
            <div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 10, padding: '8px 10px', background: tokens.bg, borderRadius: 6 }}>
              Order will be checked against your risk limits and idempotency window before fill. Fees, slippage, and spread will be applied automatically.
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
              <Button variant="ghost" onClick={() => setShowOrder(false)}>Cancel</Button>
              <Button onClick={placeOrder} loading={placing}>Place Order</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
