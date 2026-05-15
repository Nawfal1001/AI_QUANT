import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Card, Button, Input, Select, PageHeader, SectionTitle, Loading, Empty, Badge, Grid, Metric, ErrorState } from '@/components/ui'
import { tokens, fmtPct } from '@/components/ui/tokens'
import { Plus, Trash2, Save, Play, ChevronRight, BookOpen, Code, X, Sparkles, Flag } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'

const EMPTY = { name: '', description: '', min_confidence: 50, rules: [{ when: 'rsi < 30', weight: 60, side: 'BUY' }] }

const STARTER_TEMPLATES = [
  {
    name: 'RSI mean reversion',
    description: 'Buy oversold, sell overbought',
    min_confidence: 50,
    rules: [
      { when: 'rsi < 30', weight: 60, side: 'BUY' },
      { when: 'close < bb_lower', weight: 30, side: 'BUY' },
      { when: 'rsi > 70', weight: 60, side: 'SELL' },
      { when: 'close > bb_upper', weight: 30, side: 'SELL' },
    ],
  },
  {
    name: '20-day breakout',
    description: 'Buy 20-day highs with volume',
    min_confidence: 60,
    rules: [
      { when: 'close > max(highs[-21:-1])', weight: 60, side: 'BUY' },
      { when: 'volume > avg_volume(20) * 1.3', weight: 25, side: 'BUY' },
      { when: 'close < min(lows[-21:-1])', weight: 60, side: 'SELL' },
      { when: 'volume > avg_volume(20) * 1.3', weight: 25, side: 'SELL' },
    ],
  },
  {
    name: 'Trend pullback',
    description: 'Buy pullbacks in established uptrends',
    min_confidence: 55,
    rules: [
      { when: 'close > ema(50)', weight: 30, side: 'BUY' },
      { when: 'close <= ema(20) * 1.01', weight: 30, side: 'BUY' },
      { when: 'rsi < 50 and rsi > 35', weight: 25, side: 'BUY' },
    ],
  },
]

export default function StrategyLab() {
  const [strategies, setStrategies] = useState([])
  const [reference, setReference] = useState(null)
  const [editing, setEditing] = useState(null)         // strategy object being edited
  const [testResult, setTestResult] = useState(null)
  const [testTicker, setTestTicker] = useState('AAPL')
  const [testAssetType, setTestAssetType] = useState('stock')
  const [testDays, setTestDays] = useState(180)
  const [ruleErrors, setRuleErrors] = useState({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [showReference, setShowReference] = useState(false)
  const navigate = useNavigate()

  async function load() {
    setLoading(true)
    try {
      const [s, r] = await Promise.all([
        api.get('/strategy-lab/'),
        api.get('/strategy-lab/reference'),
      ])
      setStrategies(s.data?.strategies || [])
      setReference(r.data)
    } catch (e) {
      console.warn('strategy lab load:', e)
    }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  // Live rule validation as user types
  async function validateRule(idx, expr) {
    if (!expr || !expr.trim()) {
      setRuleErrors(r => ({ ...r, [idx]: null }))
      return
    }
    try {
      const r = await api.post('/strategy-lab/validate-rule', { when: expr })
      setRuleErrors(prev => ({ ...prev, [idx]: r.data?.ok ? null : r.data?.error }))
    } catch (e) {
      setRuleErrors(prev => ({ ...prev, [idx]: 'Validation failed' }))
    }
  }

  function startNew(template) {
    setEditing(template ? structuredClone(template) : structuredClone(EMPTY))
    setTestResult(null)
    setRuleErrors({})
  }

  function startEdit(s) {
    setEditing({ id: s._id, name: s.name, description: s.description || '', min_confidence: s.min_confidence, rules: structuredClone(s.rules) })
    setTestResult(null)
    setRuleErrors({})
  }

  async function save() {
    if (!editing) return
    if (!editing.name?.trim()) { toast.error('Name required'); return }
    if (Object.values(ruleErrors).some(e => e)) { toast.error('Fix rule errors before saving'); return }
    setSaving(true)
    try {
      const payload = { ...editing }
      await api.post('/strategy-lab/', payload)
      toast.success(editing.id ? 'Strategy updated' : 'Strategy created')
      setEditing(null)
      setTestResult(null)
      load()
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Save failed')
    }
    setSaving(false)
  }

  async function remove(id) {
    if (!window.confirm('Delete this strategy?')) return
    try {
      await api.delete(`/strategy-lab/${id}`)
      toast.success('Deleted')
      load()
    } catch (e) { toast.error(e?.response?.data?.detail || 'Failed') }
  }

  async function test() {
    if (!editing) return
    if (Object.values(ruleErrors).some(e => e)) { toast.error('Fix rule errors first'); return }
    setTesting(true)
    setTestResult(null)
    try {
      const r = await api.post('/strategy-lab/test', {
        strategy: editing,
        ticker: testTicker,
        asset_type: testAssetType,
        days: testDays,
      })
      setTestResult(r.data)
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Test failed')
    }
    setTesting(false)
  }

  async function runBacktest() {
    if (!editing?.id) { toast.error('Save first, then backtest'); return }
    try {
      // Just navigate — the Backtest page accepts a user_strategy_id query
      navigate(`/backtest?user_strategy_id=${editing.id}`)
    } catch (e) { console.warn(e) }
  }

  function updateRule(idx, patch) {
    setEditing(e => {
      const rules = e.rules.map((r, i) => i === idx ? { ...r, ...patch } : r)
      return { ...e, rules }
    })
    if (patch.when !== undefined) {
      validateRule(idx, patch.when)
    }
  }

  function addRule() {
    setEditing(e => ({ ...e, rules: [...e.rules, { when: '', weight: 30, side: 'BUY' }] }))
  }

  function removeRule(idx) {
    setEditing(e => ({ ...e, rules: e.rules.filter((_, i) => i !== idx) }))
    setRuleErrors(prev => {
      const copy = { ...prev }
      delete copy[idx]
      return copy
    })
  }

  if (loading) return <Loading message="Loading strategy lab…" />

  return (
    <div>
      <PageHeader
        title="🧪 Strategy Lab"
        subtitle="Build, test, and deploy custom trading strategies — no code needed"
        action={
          !editing && (
            <div style={{ display: 'flex', gap: 8 }}>
              <Button variant="secondary" leftIcon={<BookOpen size={13} />} onClick={() => setShowReference(true)}>Reference</Button>
              <Button leftIcon={<Plus size={14} />} onClick={() => startNew()}>New Strategy</Button>
            </div>
          )
        }
      />

      {/* Editor view */}
      {editing && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: 14 }}>

          {/* Left: editor */}
          <Card>
            <SectionTitle
              icon={<Code size={14} />}
              action={
                <div style={{ display: 'flex', gap: 6 }}>
                  <Button variant="ghost" size="sm" onClick={() => { setEditing(null); setTestResult(null) }}>Cancel</Button>
                  <Button variant="secondary" size="sm" onClick={test} loading={testing} leftIcon={<Play size={11} />}>Test</Button>
                  <Button size="sm" onClick={save} loading={saving} leftIcon={<Save size={11} />}>Save</Button>
                </div>
              }
            >
              {editing.id ? 'Edit Strategy' : 'New Strategy'}
            </SectionTitle>

            <Grid cols={2} minCol={180} gap={12}>
              <Input
                label="Name"
                value={editing.name}
                onChange={e => setEditing({ ...editing, name: e.target.value })}
                placeholder="My Strategy"
                fullWidth
              />
              <Input
                label="Min Confidence"
                type="number"
                value={editing.min_confidence}
                onChange={e => setEditing({ ...editing, min_confidence: Number(e.target.value) })}
                min="0" max="100"
                fullWidth
              />
            </Grid>
            <div style={{ marginTop: 10 }}>
              <Input
                label="Description"
                value={editing.description}
                onChange={e => setEditing({ ...editing, description: e.target.value })}
                placeholder="What does this strategy do?"
                fullWidth
              />
            </div>

            {/* Rules */}
            <div style={{ marginTop: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ fontSize: 12, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, fontWeight: 600 }}>
                  Rules ({editing.rules.length})
                </div>
                <Button size="sm" variant="ghost" leftIcon={<Plus size={11} />} onClick={addRule}>Add rule</Button>
              </div>
              <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 12, lineHeight: 1.5 }}>
                Each rule fires when its expression is true on the latest closed bar. Weights for the same side stack — total ≥80 = STRONG_BUY/SELL, ≥50 = BUY/SELL.
              </div>

              {editing.rules.map((rule, idx) => (
                <div key={idx} style={{ background: tokens.bg, borderRadius: 8, padding: '10px 12px', marginBottom: 8, border: `1px solid ${ruleErrors[idx] ? tokens.danger : tokens.border}` }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 11, color: tokens.textFaint, width: 18 }}>{idx + 1}.</span>
                    <input
                      value={rule.when}
                      onChange={e => updateRule(idx, { when: e.target.value })}
                      placeholder="e.g. rsi < 30"
                      style={{
                        flex: 1,
                        background: tokens.surface,
                        border: `1px solid ${ruleErrors[idx] ? tokens.danger : tokens.border}`,
                        borderRadius: 6,
                        padding: '6px 10px',
                        color: tokens.text,
                        fontSize: 12,
                        fontFamily: 'monospace',
                        outline: 'none',
                      }}
                    />
                    <select
                      value={rule.side}
                      onChange={e => updateRule(idx, { side: e.target.value })}
                      style={{ background: tokens.surface, border: `1px solid ${tokens.border}`, borderRadius: 6, padding: '6px 8px', color: rule.side === 'BUY' ? tokens.success : tokens.danger, fontSize: 12, fontWeight: 600, outline: 'none' }}
                    >
                      <option value="BUY">BUY</option>
                      <option value="SELL">SELL</option>
                    </select>
                    <input
                      type="number"
                      value={rule.weight}
                      onChange={e => updateRule(idx, { weight: Number(e.target.value) })}
                      style={{ width: 60, background: tokens.surface, border: `1px solid ${tokens.border}`, borderRadius: 6, padding: '6px 8px', color: tokens.text, fontSize: 12, textAlign: 'center', outline: 'none' }}
                      min="1" max="100"
                    />
                    <button onClick={() => removeRule(idx)} style={{ background: 'none', border: 'none', color: tokens.danger, cursor: 'pointer', padding: 4 }}>
                      <Trash2 size={13} />
                    </button>
                  </div>
                  {ruleErrors[idx] && (
                    <div style={{ fontSize: 11, color: tokens.danger, marginTop: 4, fontFamily: 'monospace' }}>
                      ⚠ {ruleErrors[idx]}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* Right: test panel + reference */}
          <div>
            <Card style={{ marginBottom: 14 }}>
              <SectionTitle icon={<Play size={14} />}>Test on history</SectionTitle>
              <Grid cols={3} minCol={100} gap={8}>
                <Input label="Ticker" value={testTicker} onChange={e => setTestTicker(e.target.value.toUpperCase())} fullWidth />
                <Select label="Asset" value={testAssetType} onChange={e => setTestAssetType(e.target.value)} fullWidth>
                  <option value="stock">Stock</option>
                  <option value="crypto">Crypto</option>
                </Select>
                <Input label="Days" type="number" value={testDays} onChange={e => setTestDays(Number(e.target.value))} fullWidth />
              </Grid>
              <div style={{ marginTop: 10 }}>
                <Button variant="secondary" size="sm" onClick={test} loading={testing} leftIcon={<Play size={11} />}>Run Test</Button>
                {editing?.id && (
                  <Button variant="ghost" size="sm" onClick={runBacktest} leftIcon={<ChevronRight size={11} />} style={{ marginLeft: 6 }}>
                    Full Backtest →
                  </Button>
                )}
              </div>

              {testResult && (
                <div style={{ marginTop: 14 }}>
                  {/* Latest signal */}
                  <div style={{ padding: '10px 12px', background: tokens.bg, borderRadius: 8, borderLeft: `3px solid ${
                    testResult.latest?.signal?.includes('BUY') ? tokens.success :
                    testResult.latest?.signal?.includes('SELL') ? tokens.danger : tokens.textMuted
                  }` }}>
                    <div style={{ fontSize: 10, color: tokens.textMuted, textTransform: 'uppercase', marginBottom: 4 }}>Latest bar signal</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: testResult.latest?.signal?.includes('BUY') ? tokens.success : testResult.latest?.signal?.includes('SELL') ? tokens.danger : tokens.textMuted }}>
                      {testResult.latest?.signal} <span style={{ fontSize: 12, color: tokens.textMuted, fontWeight: 400 }}>· {testResult.latest?.confidence}% confidence</span>
                    </div>
                  </div>

                  {/* Distribution */}
                  <div style={{ marginTop: 12 }}>
                    <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.3 }}>Signals over {testResult.bars_tested} bars</div>
                    {Object.entries(testResult.signal_distribution || {}).filter(([_, c]) => c > 0).map(([sig, count]) => {
                      const pct = testResult.bars_tested ? (count / testResult.bars_tested * 100) : 0
                      const color = sig.includes('BUY') ? tokens.success : sig.includes('SELL') ? tokens.danger : tokens.textMuted
                      return (
                        <div key={sig} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                          <div style={{ width: 90, fontSize: 11, color }}>{sig}</div>
                          <div style={{ flex: 1, height: 6, background: tokens.surface, borderRadius: 3, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: color }} />
                          </div>
                          <div style={{ fontSize: 11, color: tokens.textMuted, minWidth: 55, textAlign: 'right' }}>{count} ({pct.toFixed(0)}%)</div>
                        </div>
                      )
                    })}
                  </div>

                  {/* Rule fires */}
                  <div style={{ marginTop: 14 }}>
                    <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.3 }}>Rule fire counts</div>
                    {testResult.rule_fire_counts?.map((rf, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, fontSize: 11 }}>
                        <Badge color={rf.side === 'BUY' ? tokens.success : tokens.danger}>{rf.side}</Badge>
                        <code style={{ flex: 1, fontFamily: 'monospace', color: tokens.text, fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{rf.rule}</code>
                        <span style={{ color: tokens.textMuted, minWidth: 60, textAlign: 'right' }}>{rf.fires}× fires</span>
                      </div>
                    ))}
                  </div>

                  {testResult.actionable_signals === 0 && (
                    <div style={{ marginTop: 12, padding: '8px 10px', background: 'rgba(227,179,65,0.1)', borderRadius: 6, fontSize: 11, color: tokens.warning }}>
                      <Flag size={11} style={{ display: 'inline', marginRight: 4 }} />
                      Strategy fired 0 actionable signals. Try lowering weights or relaxing rules.
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* List view */}
      {!editing && (
        <>
          {/* Starter templates */}
          <Card style={{ marginBottom: 14 }}>
            <SectionTitle icon={<Sparkles size={14} color={tokens.purple} />}>Start from a template</SectionTitle>
            <Grid cols={3} minCol={220} gap={10}>
              {STARTER_TEMPLATES.map(t => (
                <Card key={t.name} style={{ background: tokens.bg, padding: '12px 14px', cursor: 'pointer' }} onClick={() => startNew(t)}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: tokens.text, marginBottom: 4 }}>{t.name}</div>
                  <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 8 }}>{t.description}</div>
                  <Badge color={tokens.accent}>{t.rules.length} rules</Badge>
                </Card>
              ))}
            </Grid>
          </Card>

          {/* My strategies */}
          <Card>
            <SectionTitle>My Strategies ({strategies.length})</SectionTitle>
            {strategies.length === 0 ? (
              <Empty
                message="No custom strategies yet. Start from a template above or create one from scratch."
                icon="🧪"
                action={<Button leftIcon={<Plus size={13} />} onClick={() => startNew()}>New Strategy</Button>}
              />
            ) : (
              <div>
                {strategies.map(s => (
                  <div key={s._id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 0', borderBottom: `1px solid ${tokens.border}` }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: tokens.text }}>{s.name}</div>
                      <div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 2 }}>
                        {s.description || 'No description'} · {s.rules?.length || 0} rules · min {s.min_confidence}%
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <Button variant="secondary" size="sm" onClick={() => startEdit(s)}>Edit</Button>
                      <Button variant="danger" size="sm" onClick={() => remove(s._id)} leftIcon={<Trash2 size={11} />}>Delete</Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}

      {/* Reference modal */}
      {showReference && reference && (
        <div onClick={() => setShowReference(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100, padding: 20 }}>
          <Card onClick={e => e.stopPropagation()} style={{ maxWidth: 720, width: '100%', maxHeight: '90vh', overflowY: 'auto' }}>
            <SectionTitle icon={<BookOpen size={14} />} action={<Button variant="ghost" size="sm" onClick={() => setShowReference(false)}><X size={14} /></Button>}>
              Variable & Function Reference
            </SectionTitle>

            <div style={{ fontSize: 12, color: tokens.textMuted, marginBottom: 14, lineHeight: 1.6 }}>
              Use these names in your rule expressions. Rules are Python-like boolean expressions that get evaluated on the latest closed bar.
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, color: tokens.text, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.4 }}>Variables</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 18 }}>
              {reference.variables?.map(v => (
                <div key={v.name} style={{ display: 'flex', gap: 8, fontSize: 12, padding: '4px 0' }}>
                  <code style={{ color: tokens.purple, minWidth: 100, fontFamily: 'monospace' }}>{v.name}</code>
                  <span style={{ color: tokens.textMuted }}>{v.desc}</span>
                </div>
              ))}
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, color: tokens.text, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.4 }}>Functions</div>
            <div style={{ marginBottom: 18 }}>
              {reference.functions?.map(f => (
                <div key={f.name} style={{ display: 'flex', gap: 8, fontSize: 12, padding: '4px 0' }}>
                  <code style={{ color: tokens.purple, minWidth: 160, fontFamily: 'monospace' }}>{f.name}</code>
                  <span style={{ color: tokens.textMuted }}>{f.desc}</span>
                </div>
              ))}
            </div>

            <div style={{ fontSize: 12, fontWeight: 700, color: tokens.text, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.4 }}>Examples</div>
            {reference.examples?.map((ex, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, padding: '6px 0', borderBottom: `1px solid ${tokens.border}` }}>
                <Badge color={ex.side === 'BUY' ? tokens.success : tokens.danger}>{ex.side}</Badge>
                <code style={{ flex: 1, color: tokens.text, fontFamily: 'monospace' }}>{ex.when}</code>
                <span style={{ color: tokens.textMuted, minWidth: 50, textAlign: 'right' }}>w {ex.weight}</span>
              </div>
            ))}
          </Card>
        </div>
      )}
    </div>
  )
}
