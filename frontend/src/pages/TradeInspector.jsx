import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { createChart } from 'lightweight-charts'
import { api } from '@/store/auth'
import { ArrowLeft, RefreshCw, X } from 'lucide-react'
import toast from 'react-hot-toast'
import { useLivePrices } from '@/hooks/useLivePrices'

const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const fmt = v => (Number.isFinite(Number(v)) ? Number(v).toFixed(4) : '—')
const pct = v => (Number.isFinite(Number(v)) ? `${Number(v).toFixed(2)}%` : '—')
const lineColor = k => (k === 'sl' ? '#f85149' : k === 'tp' ? '#3fb950' : k === 'exit' ? '#e3b341' : '#58a6ff')
const pill = (txt, bg = '#21262d', fg = '#e2e8f0') => (
  <span style={{ background: bg, color: fg, padding: '3px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700 }}>{txt}</span>
)

export default function TradeInspector() {
  const { source, tradeId } = useParams()
  const nav = useNavigate()
  const chartHostRef = useRef(null)
  const chartRef = useRef(null)
  const seriesRef = useRef(null)
  const livePriceLineRef = useRef(null)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)
  const [closing, setClosing] = useState(false)

  const trade = data?.trade || {}
  const ticker = trade.ticker
  const isOpen = String(trade.status || '').toLowerCase() === 'open' || source === 'open'

  // Subscribe to live price ticks for the trade's ticker. The hook is shared
  // with the dashboard ticker tape; one ws connection multiplexes both.
  const { prices: livePrices, connected: wsConnected } = useLivePrices(ticker ? [ticker] : [])
  const livePrice = ticker ? livePrices[ticker]?.price : null
  const liveTs = ticker ? livePrices[ticker]?.timestamp : null

  async function load() {
    setLoading(true); setErr(''); setData(null)
    try {
      const r = await api.get(`/trades/inspect/${encodeURIComponent(source)}/${encodeURIComponent(tradeId)}`, { timeout: 60000 })
      setData(r.data)
    } catch (e) {
      setErr(e?.response?.data?.detail || e.message || 'Failed to load trade')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [source, tradeId])

  // Build the chart once data arrives.
  useEffect(() => {
    if (!data || !chartHostRef.current) return
    chartHostRef.current.innerHTML = ''
    const chart = createChart(chartHostRef.current, {
      height: 520,
      width: chartHostRef.current.clientWidth || 600,
      layout: { background: { color: '#0d1117' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
    })
    const candles = chart.addCandlestickSeries({
      upColor: '#3fb950', downColor: '#f85149', borderVisible: false,
      wickUpColor: '#3fb950', wickDownColor: '#f85149',
    })
    const rows = (data.candles || []).map(c => ({
      time: c.time, open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close),
    })).filter(c => Number.isFinite(c.open) && Number.isFinite(c.high) && Number.isFinite(c.low) && Number.isFinite(c.close))
    candles.setData(rows)
    candles.setMarkers((data.markers || []).map(m => ({
      time: m.time, position: m.position || 'aboveBar', color: m.color || '#58a6ff',
      shape: m.shape || 'arrowUp', text: m.text || '',
    })))
    ;(data.price_lines || []).forEach(l => {
      if (Number.isFinite(Number(l.price))) {
        candles.createPriceLine({
          price: Number(l.price), color: l.color || lineColor(l.key),
          lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: l.title || l.key,
        })
      }
    })
    chart.timeScale().fitContent()
    chartRef.current = chart
    seriesRef.current = candles
    livePriceLineRef.current = null
    const ro = new ResizeObserver(() => chart.applyOptions({ width: chartHostRef.current?.clientWidth || 600 }))
    ro.observe(chartHostRef.current)
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null }
  }, [data])

  // Stream live ticks onto the chart: maintain a "live price" horizontal line
  // and extend the last candle's close so PnL on the page reacts in real time.
  useEffect(() => {
    if (!seriesRef.current || !Number.isFinite(Number(livePrice))) return
    const series = seriesRef.current
    const price = Number(livePrice)
    if (livePriceLineRef.current) {
      try { series.removePriceLine(livePriceLineRef.current) } catch (e) { void e }
    }
    livePriceLineRef.current = series.createPriceLine({
      price, color: '#1f6feb', lineWidth: 1, lineStyle: 0,
      axisLabelVisible: true, title: 'LIVE',
    })
  }, [livePrice])

  async function closeNow() {
    if (!trade._id && !tradeId) return
    if (!window.confirm(`Close ${ticker} at market?`)) return
    setClosing(true)
    try {
      const id = trade._id || tradeId
      const r = await api.post(`/autotrader/open-trades/${encodeURIComponent(id)}/close`, { reason: 'manual_inspector' }, { timeout: 30000 })
      toast.success(`Closed ${ticker} @ ${r.data?.close_price} (${r.data?.pnl_pct}%)`)
      await load()
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Close failed')
    } finally {
      setClosing(false)
    }
  }

  // Compute live unrealised PnL from the streamed price.
  const livePnlPct = useMemo(() => {
    if (!Number.isFinite(Number(livePrice)) || !Number.isFinite(Number(trade.entry_price))) return null
    const entry = Number(trade.entry_price); const cur = Number(livePrice)
    if (!entry) return null
    const dir = String(trade.signal || '').toUpperCase().includes('BUY') ? 1 : -1
    return ((cur - entry) / entry) * 100 * dir
  }, [livePrice, trade.entry_price, trade.signal])

  const candles = data?.candles || []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <button onClick={() => nav(-1)} style={{ background: 'transparent', border: 'none', color: '#8b949e', fontSize: 12, display: 'inline-flex', gap: 6, alignItems: 'center', padding: 0, cursor: 'pointer' }}>
            <ArrowLeft size={13} /> Back
          </button>
          <h1 style={{ fontSize: 22, color: '#e2e8f0', margin: '8px 0 0' }}>📈 Trade Inspector</h1>
          <div style={{ fontSize: 12, color: '#8b949e', display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
            {source} · {tradeId}
            {ticker && (wsConnected ? pill('LIVE', 'rgba(63,185,80,.12)', '#3fb950') : pill('OFFLINE', 'rgba(248,81,73,.12)', '#f85149'))}
            {liveTs && <span>last tick {new Date(liveTs).toLocaleTimeString()}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {isOpen && (
            <button onClick={closeNow} disabled={closing} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #da3633', background: 'rgba(218,54,51,0.08)', color: '#f85149', display: 'flex', gap: 6, alignItems: 'center', fontWeight: 700, cursor: 'pointer' }}>
              <X size={13} /> {closing ? 'Closing…' : 'Close Now'}
            </button>
          )}
          <button onClick={load} disabled={loading} style={{ padding: '8px 12px', borderRadius: 8, border: '1px solid #30363d', background: '#21262d', color: '#e2e8f0', display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <RefreshCw size={13} /> {loading ? 'Loading…' : 'Refresh'}
          </button>
        </div>
      </div>

      {loading && <div style={card}>Loading trade and candles…</div>}
      {err && <div style={{ ...card, borderColor: '#f85149', color: '#f85149' }}>{err}</div>}

      {data && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 10, marginBottom: 14 }}>
            {[
              ['Ticker', trade.ticker],
              ['Signal', trade.signal || trade.side],
              ['Status', trade.status],
              ['Live Price', Number.isFinite(Number(livePrice)) ? `$${Number(livePrice).toFixed(4)}` : '—'],
              ['Entry', fmt(trade.entry_price || trade.entry || trade.avg_entry || trade.fill_price)],
              ['Exit', fmt(trade.close_price || trade.exit_price)],
              ['SL', fmt(trade.sl || trade.stop_loss)],
              ['TP', fmt(trade.tp || trade.take_profit)],
              ['Live PnL', livePnlPct != null ? `${livePnlPct >= 0 ? '+' : ''}${livePnlPct.toFixed(2)}%` : pct(trade.pnl_pct || trade.unrealized_pnl_pct)],
              ['Outcome', trade.outcome || '—'],
              ['Timeframe', trade.timeframe || '—'],
            ].map(([k, v]) => (
              <div key={k} style={{ ...card, padding: '10px 12px' }}>
                <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'uppercase' }}>{k}</div>
                <div style={{ fontSize: 16, color: k === 'Live PnL' && livePnlPct != null ? (livePnlPct >= 0 ? '#3fb950' : '#f85149') : '#e2e8f0', fontWeight: 800, marginTop: 4 }}>{v ?? '—'}</div>
              </div>
            ))}
          </div>
          {candles.length === 0 && (
            <div style={{ ...card, marginBottom: 14, borderColor: '#e3b341', color: '#e3b341' }}>
              Trade loaded, but no candle data was returned for this symbol/timeframe yet. Live price ticks will still update above as the WebSocket streams.
            </div>
          )}
          <div style={card}><div ref={chartHostRef} style={{ width: '100%', height: 520 }} /></div>
          <div style={{ ...card, marginTop: 14 }}>
            <div style={{ fontSize: 14, fontWeight: 800, color: '#e2e8f0', marginBottom: 10 }}>Raw trade details</div>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, color: '#8b949e', margin: 0 }}>{JSON.stringify(trade, null, 2)}</pre>
          </div>
        </>
      )}
    </div>
  )
}
