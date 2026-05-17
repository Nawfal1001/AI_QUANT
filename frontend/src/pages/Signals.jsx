import React, { useState, useEffect, useRef, useCallback } from 'react'
import { api } from '@/store/auth'
import { Search, Zap, RefreshCw, Clock, Globe, List } from 'lucide-react'

const SCAN_INTERVAL_MS = 30 * 60 * 1000 // 30 minutes

const card  = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }
const sigColor = s => s?.includes('BUY')  ? '#3fb950' : s?.includes('SELL') ? '#f85149' : '#8b949e'
const sigBg    = s => s?.includes('BUY')  ? 'rgba(63,185,80,0.12)' : s?.includes('SELL') ? 'rgba(248,81,73,0.12)' : 'rgba(139,148,158,0.1)'

function ConfBar({ value }) {
  return (
    <div style={{ background: '#21262d', borderRadius: 4, height: 6, width: '100%', overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${Math.min(100, value)}%`,
        background: value > 70 ? '#3fb950' : value > 50 ? '#e3b341' : '#f85149', borderRadius: 4 }} />
    </div>
  )
}

function Countdown({ nextScan }) {
  const [remaining, setRemaining] = useState('')
  useEffect(() => {
    const tick = () => {
      const diff = nextScan - Date.now()
      if (diff <= 0) { setRemaining('Scanning…'); return }
      const m = Math.floor(diff / 60000)
      const s = Math.floor((diff % 60000) / 1000)
      setRemaining(`${m}m ${s.toString().padStart(2, '0')}s`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [nextScan])
  return <span style={{ color: '#8b949e', fontSize: 12 }}><Clock size={11} style={{ marginRight: 4 }} />{remaining}</span>
}

function SignalRow({ s, i, total }) {
  const side = s.signal?.includes('BUY') ? 'BUY' : s.signal?.includes('SELL') ? 'SELL' : 'HOLD'
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '36px 80px 80px 1fr 120px 90px 90px 90px',
      gap: 10, alignItems: 'center', padding: '10px 12px',
      borderBottom: i < total - 1 ? '1px solid #21262d' : 'none',
      background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
    }}>
      <div style={{ fontSize: 11, color: '#8b949e', textAlign: 'center' }}>#{i + 1}</div>
      <div style={{ fontWeight: 700, fontSize: 14, color: '#e2e8f0' }}>{s.ticker}</div>
      <div style={{
        fontSize: 12, fontWeight: 700, color: sigColor(s.signal),
        background: sigBg(s.signal), padding: '2px 8px', borderRadius: 8, textAlign: 'center',
      }}>{side}</div>
      <div style={{ minWidth: 0 }}>
        <ConfBar value={s.confidence} />
        <div style={{ fontSize: 10, color: '#8b949e', marginTop: 2 }}>{s.confidence}% confidence · {s.regime}</div>
      </div>
      <div style={{ fontSize: 12, color: '#e2e8f0', textAlign: 'right' }}>${s.price?.toFixed(s.price > 10 ? 2 : 4)}</div>
      <div style={{ fontSize: 11, color: '#3fb950', textAlign: 'right' }}>TP ${s.tp?.toFixed(s.tp > 10 ? 2 : 4)}</div>
      <div style={{ fontSize: 11, color: '#f85149', textAlign: 'right' }}>SL ${s.sl?.toFixed(s.sl > 10 ? 2 : 4)}</div>
      <div style={{ fontSize: 10, color: '#8b949e', textAlign: 'right' }}>{s.asset_type}</div>
    </div>
  )
}

// ─── Universe Scanner tab ─────────────────────────────────────────────────────
function UniverseScanner() {
  const [assetType,     setAssetType]     = useState('all')
  const [timeframe,     setTimeframe]     = useState('swing')
  const [minConf,       setMinConf]       = useState(60)
  const [result,        setResult]        = useState(null)
  const [loading,       setLoading]       = useState(false)
  const [autoRefresh,   setAutoRefresh]   = useState(true)
  const [nextScan,      setNextScan]      = useState(null)
  const timerRef = useRef(null)

  const scan = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get(
        `/signals/scan/universe?asset_type=${assetType}&timeframe=${timeframe}&min_confidence=${minConf}`
      )
      setResult(res.data)
    } catch (e) { console.error(e) }
    setLoading(false)
    setNextScan(Date.now() + SCAN_INTERVAL_MS)
  }, [assetType, timeframe, minConf])

  // auto-refresh loop
  useEffect(() => {
    if (!autoRefresh) { clearTimeout(timerRef.current); return }
    const schedule = () => {
      timerRef.current = setTimeout(() => { scan(); schedule() }, SCAN_INTERVAL_MS)
      setNextScan(Date.now() + SCAN_INTERVAL_MS)
    }
    scan()
    schedule()
    return () => clearTimeout(timerRef.current)
  }, [autoRefresh, assetType, timeframe, minConf]) // re-bind when params change

  const signals = result?.signals || []
  const buys  = signals.filter(s => s.signal?.includes('BUY'))
  const sells = signals.filter(s => s.signal?.includes('SELL'))

  return (
    <div>
      {/* Controls */}
      <div style={{ ...card, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>ASSET TYPE</div>
            <select value={assetType} onChange={e => setAssetType(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['all','stock','crypto','forex'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TIMEFRAME</div>
            <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['scalping','intraday','swing','position'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>MIN CONFIDENCE</div>
            <select value={minConf} onChange={e => setMinConf(Number(e.target.value))}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {[50,55,60,65,70,75,80].map(v => <option key={v} value={v}>{v}%+</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingBottom: 2 }}>
            <label style={{ fontSize: 12, color: '#8b949e', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
                style={{ accentColor: '#1f6feb' }} />
              Auto-refresh 30m
            </label>
          </div>
          <button onClick={scan} disabled={loading}
            style={{ padding: '9px 20px', borderRadius: 7, border: 'none', background: loading ? '#21262d' : '#1f6feb',
              color: loading ? '#8b949e' : '#fff', fontWeight: 600, fontSize: 13,
              cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
            <RefreshCw size={13} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            {loading ? 'Scanning universe…' : 'Scan Now'}
          </button>
          {nextScan && autoRefresh && !loading && <Countdown nextScan={nextScan} />}
        </div>
      </div>

      {/* Summary bar */}
      {result && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
          {[
            ['Scanned', result.scanned, '#8b949e'],
            ['Actionable', result.found, '#e3b341'],
            ['BUY signals', buys.length, '#3fb950'],
            ['SELL signals', sells.length, '#f85149'],
            ['Scanned at', new Date(result.scanned_at + 'Z').toLocaleTimeString(), '#8b949e'],
          ].map(([label, value, color]) => (
            <div key={label} style={{ ...card, padding: '10px 16px', flex: '0 0 auto' }}>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Signal table */}
      {loading && !result && (
        <div style={{ ...card, textAlign: 'center', color: '#8b949e', padding: 40 }}>
          <RefreshCw size={24} style={{ animation: 'spin 1s linear infinite', marginBottom: 10 }} />
          <div>Scanning {assetType === 'all' ? '~90' : assetType === 'stock' ? '~70' : '~20'} symbols…</div>
          <div style={{ fontSize: 12, marginTop: 6 }}>This may take 20–60 seconds on first run</div>
        </div>
      )}

      {result && signals.length === 0 && (
        <div style={{ ...card, textAlign: 'center', color: '#8b949e', padding: 40 }}>
          No signals above {minConf}% confidence found in this scan. Try lowering the threshold.
        </div>
      )}

      {signals.length > 0 && (
        <div style={card}>
          {/* Table header */}
          <div style={{
            display: 'grid', gridTemplateColumns: '36px 80px 80px 1fr 120px 90px 90px 90px',
            gap: 10, padding: '6px 12px 10px', borderBottom: '1px solid #21262d',
          }}>
            {['#','TICKER','SIDE','CONFIDENCE','PRICE','TP','SL','TYPE'].map(h => (
              <div key={h} style={{ fontSize: 10, color: '#8b949e', fontWeight: 600, textAlign: h === '#' ? 'center' : h === 'PRICE' || h === 'TP' || h === 'SL' ? 'right' : 'left' }}>{h}</div>
            ))}
          </div>
          {signals.map((s, i) => <SignalRow key={`${s.ticker}-${i}`} s={s} i={i} total={signals.length} />)}
        </div>
      )}

      <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
    </div>
  )
}

// ─── Single-ticker / Multi-TF tab ─────────────────────────────────────────────
function SingleScanner() {
  const [ticker,  setTicker]  = useState('AAPL')
  const [atype,   setAtype]   = useState('stock')
  const [tf,      setTf]      = useState('swing')
  const [signal,  setSignal]  = useState(null)
  const [multitf, setMultiTf] = useState(null)
  const [mode,    setMode]    = useState('single')
  const [loading, setLoading] = useState(false)

  async function run() {
    if (!ticker) return
    setLoading(true); setSignal(null); setMultiTf(null)
    try {
      if (mode === 'multi') {
        const res = await api.get(`/signals/multi/${ticker.toUpperCase()}?asset_type=${atype}`)
        setMultiTf(res.data)
      } else {
        const res = await api.get(`/signals/${ticker.toUpperCase()}?asset_type=${atype}&timeframe=${tf}`)
        setSignal(res.data)
      }
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  return (
    <div>
      <div style={{ ...card, marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TICKER</div>
            <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && run()}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 12px',
                color: '#e2e8f0', fontSize: 14, width: 110, outline: 'none' }} placeholder="AAPL" />
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>ASSET</div>
            <select value={atype} onChange={e => setAtype(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px',
                color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['stock','crypto','forex'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TIMEFRAME</div>
            <select value={tf} onChange={e => setTf(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px',
                color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['scalping','intraday','swing','position'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>MODE</div>
            <select value={mode} onChange={e => setMode(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px',
                color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              <option value="single">Single TF</option>
              <option value="multi">All Timeframes</option>
            </select>
          </div>
          <button onClick={run} disabled={loading}
            style={{ padding: '9px 20px', borderRadius: 7, border: 'none', background: loading ? '#21262d' : '#1f6feb',
              color: loading ? '#8b949e' : '#fff', fontWeight: 600, fontSize: 13,
              cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Search size={14} />{loading ? 'Scanning...' : 'Scan Signal'}
          </button>
        </div>
      </div>

      {signal && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <div style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#e2e8f0' }}>{signal.ticker}</div>
                <div style={{ fontSize: 12, color: '#8b949e' }}>${signal.price?.toFixed(4)} · {signal.timeframe} · {signal.regime}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 16, fontWeight: 700, color: sigColor(signal.signal),
                  background: sigBg(signal.signal), padding: '4px 12px', borderRadius: 10 }}>{signal.signal}</div>
                <div style={{ fontSize: 12, color: '#8b949e', marginTop: 4 }}>Confidence: {signal.confidence}%</div>
              </div>
            </div>
            <ConfBar value={signal.confidence} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 14 }}>
              {[['Price',`$${signal.price}`],['SL',`$${signal.sl}`],['TP',`$${signal.tp}`],
                ['ATR',`$${signal.atr}`],['Regime',signal.regime],
                ['Bayesian',`${Math.round((signal.bayesian?.p_buy||0.5)*100)}% BUY`]].map(([k,v]) => (
                <div key={k} style={{ background: '#0d1117', borderRadius: 7, padding: '8px 10px' }}>
                  <div style={{ fontSize: 10, color: '#8b949e' }}>{k}</div>
                  <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500, marginTop: 2 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>

          <div style={card}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Indicator Breakdown</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 320, overflowY: 'auto' }}>
              {signal.indicators?.map((ind, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '5px 8px', background: '#0d1117', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: '#8b949e', flex: 1 }}>{ind.indicator}</div>
                  <div style={{ fontSize: 11, color: sigColor(ind.signal), background: sigBg(ind.signal),
                    padding: '1px 7px', borderRadius: 8, marginRight: 6 }}>{ind.signal}</div>
                  <div style={{ fontSize: 10, color: '#8b949e', maxWidth: 120, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ind.reason}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {multitf && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(240px,1fr))', gap: 14 }}>
          {Object.entries(multitf).map(([tfKey, s]) => (
            <div key={tfKey} style={card}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', textTransform: 'capitalize' }}>{tfKey}</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: sigColor(s.signal),
                  background: sigBg(s.signal), padding: '2px 10px', borderRadius: 10 }}>{s.signal}</div>
              </div>
              <ConfBar value={s.confidence} />
              <div style={{ fontSize: 11, color: '#8b949e', marginTop: 8 }}>
                {s.confidence}% · {s.regime}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Watchlist Scanner tab ────────────────────────────────────────────────────
function WatchlistScanner() {
  const [tickers,   setTickers]   = useState('AAPL, NVDA, TSLA, MSFT, BTC')
  const [atype,     setAtype]     = useState('stock')
  const [timeframe, setTimeframe] = useState('swing')
  const [minConf,   setMinConf]   = useState(55)
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)

  async function scan() {
    const cleaned = tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean).join(',')
    if (!cleaned) return
    setLoading(true)
    try {
      const res = await api.get(
        `/signals/scan/watchlist?tickers=${encodeURIComponent(cleaned)}&asset_type=${atype}&timeframe=${timeframe}&min_confidence=${minConf}`
      )
      setResult(res.data)
    } catch (e) { console.error(e) }
    setLoading(false)
  }

  const signals = result?.signals || []
  const buys  = signals.filter(s => s.signal?.includes('BUY'))
  const sells = signals.filter(s => s.signal?.includes('SELL'))

  return (
    <div>
      <div style={{ ...card, marginBottom: 14 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: 1, minWidth: 260 }}>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TICKERS (comma separated, max 50)</div>
            <input value={tickers} onChange={e => setTickers(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && scan()}
              style={{ width: '100%', background: '#0d1117', border: '1px solid #21262d', borderRadius: 7,
                padding: '8px 12px', color: '#e2e8f0', fontSize: 13, outline: 'none', boxSizing: 'border-box' }}
              placeholder="AAPL, NVDA, BTC, ETH, ..." />
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>ASSET TYPE</div>
            <select value={atype} onChange={e => setAtype(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['stock','crypto','forex'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>TIMEFRAME</div>
            <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {['scalping','intraday','swing','position'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 4 }}>MIN CONF</div>
            <select value={minConf} onChange={e => setMinConf(Number(e.target.value))}
              style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '8px 10px', color: '#e2e8f0', fontSize: 13, outline: 'none' }}>
              {[50,55,60,65,70].map(v => <option key={v} value={v}>{v}%+</option>)}
            </select>
          </div>
          <button onClick={scan} disabled={loading}
            style={{ padding: '9px 20px', borderRadius: 7, border: 'none', background: loading ? '#21262d' : '#1f6feb',
              color: loading ? '#8b949e' : '#fff', fontWeight: 600, fontSize: 13,
              cursor: loading ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}>
            <Search size={13} />{loading ? 'Scanning…' : 'Scan'}
          </button>
        </div>
      </div>

      {result && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
          {[['Scanned', result.scanned, '#8b949e'], ['Found', result.found, '#e3b341'],
            ['BUY', buys.length, '#3fb950'], ['SELL', sells.length, '#f85149']].map(([l,v,c]) => (
            <div key={l} style={{ ...card, padding: '10px 16px', flex: '0 0 auto' }}>
              <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 2 }}>{l}</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: c }}>{v}</div>
            </div>
          ))}
        </div>
      )}

      {loading && !result && (
        <div style={{ ...card, textAlign: 'center', color: '#8b949e', padding: 40 }}>
          <RefreshCw size={22} style={{ animation: 'spin 1s linear infinite', marginBottom: 10 }} />
          <div>Scanning your watchlist…</div>
        </div>
      )}
      {result && signals.length === 0 && (
        <div style={{ ...card, textAlign: 'center', color: '#8b949e', padding: 40 }}>
          No signals above {minConf}% found. Try lowering the minimum confidence.
        </div>
      )}
      {signals.length > 0 && (
        <div style={card}>
          <div style={{ display: 'grid', gridTemplateColumns: '36px 80px 80px 1fr 120px 90px 90px 90px',
            gap: 10, padding: '6px 12px 10px', borderBottom: '1px solid #21262d' }}>
            {['#','TICKER','SIDE','CONFIDENCE','PRICE','TP','SL','TYPE'].map(h => (
              <div key={h} style={{ fontSize: 10, color: '#8b949e', fontWeight: 600,
                textAlign: h === '#' || h === 'PRICE' || h === 'TP' || h === 'SL' ? 'center' : 'left' }}>{h}</div>
            ))}
          </div>
          {signals.map((s, i) => <SignalRow key={`${s.ticker}-${i}`} s={s} i={i} total={signals.length} />)}
        </div>
      )}
      <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function Signals() {
  const [tab, setTab] = useState('universe') // universe | watchlist | single

  const tabs = [
    { id: 'universe',  label: 'Universe Scanner', icon: <Globe size={13} /> },
    { id: 'watchlist', label: 'Watchlist',         icon: <List size={13} /> },
    { id: 'single',    label: 'Single Ticker',     icon: <Search size={13} /> },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', margin: 0 }}>
          <Zap size={18} style={{ marginRight: 8, verticalAlign: 'middle' }} />
          Signal Scanner
        </h1>
        <div style={{ display: 'flex', gap: 6 }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              style={{
                padding: '7px 16px', borderRadius: 8, border: '1px solid',
                borderColor: tab === t.id ? '#1f6feb' : '#21262d',
                background: tab === t.id ? 'rgba(31,111,235,0.15)' : 'transparent',
                color: tab === t.id ? '#58a6ff' : '#8b949e',
                fontWeight: tab === t.id ? 600 : 400, fontSize: 13, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
              {t.icon}{t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'universe'  && <UniverseScanner />}
      {tab === 'watchlist' && <WatchlistScanner />}
      {tab === 'single'    && <SingleScanner />}
    </div>
  )
}
