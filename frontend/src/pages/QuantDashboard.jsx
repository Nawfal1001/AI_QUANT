import React, { useState } from 'react'
import { api } from '@/store/auth'
import { Calculator, Target, BarChart2, TrendingUp, BookOpen } from 'lucide-react'
const card = { background: '#161b22', border: '1px solid #21262d', borderRadius: 12, padding: '16px 18px' }

const PAPERS = [
  { title: 'Kelly Criterion', author: 'Kelly (1956)', desc: 'Optimal fraction of capital to bet given edge and odds' },
  { title: 'Monte Carlo Portfolio Risk', author: 'Thorp (1969)', desc: 'Simulation-based drawdown analysis' },
  { title: 'Kalman Filter', author: 'Kalman (1960)', desc: 'Optimal noise-filtered price estimation' },
  { title: 'Hurst Exponent', author: 'Hurst (1951)', desc: 'Measure of long-range dependence in time series' },
  { title: "Bayes' Theorem", author: 'Bayes (1763)', desc: 'Probabilistic signal combination' },
  { title: 'FRAMA', author: 'Ehlers (2001)', desc: 'Fractal Adaptive Moving Average' },
  { title: 'Hilbert Transform', author: 'Ehlers (2002)', desc: 'Dominant cycle measurement for adaptive indicators' },
  { title: 'Shannon Entropy', author: 'Shannon (1948)', desc: 'Market randomness / predictability filter' },
  { title: 'Hidden Markov Model', author: 'Viterbi (1967)', desc: 'Regime detection via latent state inference' },
  { title: 'Shiryaev Optimal Stopping', author: 'Shiryaev', desc: 'Optimal trailing stop placement' },
  { title: 'Order Flow Imbalance', author: 'Cont et al (2014)', desc: 'Buy/sell pressure from order book depth' },
  { title: 'Drawdown at Risk', author: 'Chekhlov et al', desc: 'Probabilistic drawdown measurement, like VaR for DDs' },
]

export default function QuantDashboard() {
  const [tab, setTab] = useState('kelly')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  // Kelly form
  const [wr, setWr] = useState(0.55)
  const [aw, setAw] = useState(2.0)
  const [al, setAl] = useState(-1.5)
  const [frac, setFrac] = useState(0.5)
  // MC form
  const [capital, setCapital] = useState(10000)
  const [posPct, setPosPct] = useState(5)
  const [maxDd, setMaxDd] = useState(20)
  const [hist, setHist] = useState('2,2.5,-1.5,3,-2,1.8,-1,2.2,2.8,-1.2,1.5,3.2')
  // MTF form
  const [mtfTicker, setMtfTicker] = useState('AAPL')
  const [mtfAsset, setMtfAsset] = useState('stock')
  const [mtfMode, setMtfMode] = useState('swing')
  // Trailing stop form
  const [entry, setEntry] = useState(100)
  const [current, setCurrent] = useState(108)
  const [atr, setAtr] = useState(2.5)
  const [elapsed, setElapsed] = useState(20)
  const [maxBars, setMaxBars] = useState(100)

  async function runKelly() {
    setLoading(true); setResult(null)
    try { const r = await api.post('/quant/kelly', { win_rate: wr, avg_win_pct: aw, avg_loss_pct: al, fraction: frac }); setResult(r.data) } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  async function runMC() {
    setLoading(true); setResult(null)
    try {
      const history = hist.split(',').map(parseFloat).filter(x => !isNaN(x))
      const r = await api.post('/quant/monte-carlo', { trade_history: history, capital, proposed_position_pct: posPct, max_acceptable_drawdown: maxDd })
      setResult(r.data)
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  async function runMTF() {
    setLoading(true); setResult(null)
    try { const r = await api.post('/quant/mtf', { ticker: mtfTicker.toUpperCase(), asset_type: mtfAsset, mode: mtfMode }); setResult(r.data) } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  async function runTrail() {
    setLoading(true); setResult(null)
    try { const r = await api.post('/quant/trailing-stop', { entry_price: entry, current_price: current, atr, elapsed_bars: elapsed, max_bars: maxBars, side: 'long' }); setResult(r.data) } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  async function loadLikelihoods() {
    setLoading(true); setResult(null)
    try { const r = await api.get('/quant/bayesian/likelihoods'); setResult(r.data) } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }

  const inp = { background: '#0d1117', border: '1px solid #21262d', borderRadius: 7, padding: '7px 10px', color: '#e2e8f0', fontSize: 13, width: '100%', outline: 'none', marginBottom: 8 }
  const lbl = { fontSize: 11, color: '#8b949e', marginBottom: 3, display: 'block' }

  const TABS = [
    { id: 'kelly',     label: '📐 Kelly'        },
    { id: 'mc',        label: '🎲 Monte Carlo'  },
    { id: 'mtf',       label: '📊 MTF'          },
    { id: 'trailing',  label: '🛑 Trailing Stop'},
    { id: 'bayesian',  label: '🧮 Bayesian'     },
    { id: 'theory',    label: '📚 Theory'       },
  ]

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e2e8f0', marginBottom: 20 }}>🧮 Quant Dashboard</h1>

      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {TABS.map(t => <button key={t.id} onClick={() => { setTab(t.id); setResult(null) }}
          style={{ padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, background: tab === t.id ? '#1f6feb' : '#21262d', color: tab === t.id ? '#fff' : '#8b949e' }}>
          {t.label}
        </button>)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 14, alignItems: 'start' }}>
        {/* Input Panel */}
        <div style={card}>
          {tab === 'kelly' && <>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Kelly Criterion</div>
            <label style={lbl}>Win Rate: {Math.round(wr * 100)}%</label>
            <input type="range" min={0.1} max={0.9} step={0.01} value={wr} onChange={e => setWr(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 12 }} />
            <label style={lbl}>Avg Win %: {aw}</label>
            <input type="range" min={0.5} max={10} step={0.1} value={aw} onChange={e => setAw(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 12 }} />
            <label style={lbl}>Avg Loss % (negative): {al}</label>
            <input type="range" min={-10} max={-0.1} step={0.1} value={al} onChange={e => setAl(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 12 }} />
            <label style={lbl}>Kelly Fraction: {Math.round(frac * 100)}%</label>
            <input type="range" min={0.1} max={1} step={0.05} value={frac} onChange={e => setFrac(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 14 }} />
            <button onClick={runKelly} disabled={loading} style={{ width: '100%', padding: '9px 0', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>
              {loading ? 'Calculating...' : 'Calculate Kelly'}
            </button>
          </>}

          {tab === 'mc' && <>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Monte Carlo</div>
            <label style={lbl}>Capital ($)</label>
            <input type="number" value={capital} onChange={e => setCapital(parseFloat(e.target.value))} style={inp} />
            <label style={lbl}>Proposed Position (%)</label>
            <input type="range" min={0.5} max={20} step={0.5} value={posPct} onChange={e => setPosPct(parseFloat(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 4 }} />
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 12 }}>{posPct}%</div>
            <label style={lbl}>Max Acceptable DD (%)</label>
            <input type="range" min={5} max={50} step={1} value={maxDd} onChange={e => setMaxDd(parseInt(e.target.value))} style={{ width: '100%', accentColor: '#1f6feb', marginBottom: 4 }} />
            <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 12 }}>{maxDd}%</div>
            <label style={lbl}>Trade History (% returns, comma-separated)</label>
            <textarea value={hist} onChange={e => setHist(e.target.value)} style={{ ...inp, height: 70, resize: 'vertical', fontFamily: 'monospace', fontSize: 11 }} />
            <button onClick={runMC} disabled={loading} style={{ width: '100%', padding: '9px 0', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>
              {loading ? 'Simulating...' : 'Run 1000 Simulations'}
            </button>
          </>}

          {tab === 'mtf' && <>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Multi-Timeframe Confluence</div>
            <label style={lbl}>Ticker</label>
            <input value={mtfTicker} onChange={e => setMtfTicker(e.target.value.toUpperCase())} style={inp} />
            <label style={lbl}>Asset Type</label>
            <select value={mtfAsset} onChange={e => setMtfAsset(e.target.value)} style={{ ...inp, cursor: 'pointer' }}>
              {['stock','crypto','forex'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <label style={lbl}>Mode</label>
            <select value={mtfMode} onChange={e => setMtfMode(e.target.value)} style={{ ...inp, cursor: 'pointer' }}>
              <option value="scalping">Scalping (1m+5m+15m) — Crypto/Forex</option>
              <option value="day_trading">Day Trading (15m+1h+4h) — Stocks</option>
              <option value="swing">Swing (1h+4h+1d)</option>
              <option value="position">Position (4h+1d+1w)</option>
            </select>
            <button onClick={runMTF} disabled={loading} style={{ width: '100%', padding: '9px 0', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>
              {loading ? 'Analyzing...' : 'Run MTF Analysis'}
            </button>
          </>}

          {tab === 'trailing' && <>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Optimal Trailing Stop</div>
            {[['Entry Price', entry, setEntry], ['Current Price', current, setCurrent], ['ATR Value', atr, setAtr], ['Elapsed Bars', elapsed, setElapsed], ['Max Bars', maxBars, setMaxBars]].map(([label, val, setVal]) => (
              <div key={label}>
                <label style={lbl}>{label}</label>
                <input type="number" step={label.includes('Bars') ? 1 : 0.01} value={val} onChange={e => setVal(parseFloat(e.target.value))} style={inp} />
              </div>
            ))}
            <button onClick={runTrail} disabled={loading} style={{ width: '100%', padding: '9px 0', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>
              {loading ? 'Calculating...' : 'Calculate Stop'}
            </button>
          </>}

          {tab === 'bayesian' && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 }}>Bayesian Likelihoods</div>
              <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 14 }}>Regime-conditional indicator accuracy learned from trade outcomes</div>
              <button onClick={loadLikelihoods} disabled={loading} style={{ width: '100%', padding: '9px 0', borderRadius: 7, border: 'none', background: '#1f6feb', color: '#fff', fontWeight: 600, cursor: 'pointer' }}>
                {loading ? 'Loading...' : 'Load Likelihoods'}
              </button>
            </div>
          )}

          {tab === 'theory' && <div style={{ fontSize: 13, color: '#8b949e' }}>Browse academic papers on the right →</div>}
        </div>

        {/* Result Panel */}
        <div style={card}>
          {tab === 'theory' ? (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>📚 Academic Foundations</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {PAPERS.map((p, i) => (
                  <div key={i} style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{p.title}</div>
                    <div style={{ fontSize: 11, color: '#1f6feb', marginTop: 2 }}>{p.author}</div>
                    <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4 }}>{p.desc}</div>
                  </div>
                ))}
              </div>
            </div>
          ) : !result ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 300, color: '#8b949e' }}>
              <Calculator size={40} style={{ marginBottom: 12, opacity: 0.3 }} />
              <div style={{ fontSize: 13 }}>Run a calculation to see results here</div>
            </div>
          ) : (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0', marginBottom: 14 }}>Results</div>
              {/* MTF specific display */}
              {result.timeframes && (
                <div>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
                    <div style={{ background: result.aligned ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)', border: `1px solid ${result.aligned ? '#3fb950' : '#f85149'}`, borderRadius: 8, padding: '8px 14px' }}>
                      <div style={{ fontSize: 11, color: '#8b949e' }}>Final Signal</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color: result.aligned ? '#3fb950' : '#8b949e' }}>{result.signal}</div>
                      <div style={{ fontSize: 11, color: '#8b949e' }}>{result.confidence}% · {result.recommendation}</div>
                    </div>
                  </div>
                  {Object.entries(result.timeframes).map(([label, tf]) => (
                    <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', background: '#0d1117', borderRadius: 8, marginBottom: 6 }}>
                      <div><span style={{ fontSize: 12, color: '#8b949e', textTransform: 'capitalize' }}>{label}</span> <span style={{ fontSize: 11, color: '#8b949e' }}>({tf.timeframe})</span></div>
                      <div style={{ fontSize: 12, fontWeight: 600, color: tf.signal?.includes('BUY') ? '#3fb950' : tf.signal?.includes('SELL') ? '#f85149' : '#8b949e' }}>{tf.signal}</div>
                    </div>
                  ))}
                </div>
              )}
              {/* General key-value display */}
              {!result.timeframes && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(160px,1fr))', gap: 10 }}>
                  {Object.entries(result).filter(([k]) => typeof result[k] !== 'object').map(([k, v]) => (
                    <div key={k} style={{ background: '#0d1117', borderRadius: 8, padding: '10px 12px' }}>
                      <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'capitalize' }}>{k.replace(/_/g, ' ')}</div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: k === 'recommendation' ? (v === 'TRADE' ? '#3fb950' : '#f85149') : '#e2e8f0', marginTop: 4 }}>{typeof v === 'number' ? v.toFixed(4) : String(v)}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
