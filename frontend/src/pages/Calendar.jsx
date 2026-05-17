import React, { useState, useEffect } from 'react'
import { api, useAuthStore } from '@/store/auth'
import { Card, Button, PageHeader, SectionTitle, Loading, Empty, Badge } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Calendar as CalendarIcon, RefreshCw, Sparkles, AlertCircle, Clock, ChevronRight } from 'lucide-react'
import toast from 'react-hot-toast'

const row = { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', padding: '10px 0', borderBottom: `1px solid ${tokens.border}`, gap: 12 }

const impactColor = (i) => ({
  high: tokens.danger, High: tokens.danger, HIGH: tokens.danger,
  medium: tokens.warning, Medium: tokens.warning,
  low: tokens.textMuted, Low: tokens.textMuted,
}[i] || tokens.textMuted)

const fmtTime = (iso) => {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso.slice(0, 16).replace('T', ' ')
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch { return iso.slice(0, 16) }
}

const isReleased = (event) => {
  const actual = event.actual
  if (actual !== null && actual !== undefined && actual !== '') return true
  try {
    return new Date(event.release_time).getTime() < Date.now()
  } catch { return false }
}


function AIBriefingCard({ ai }) {
  if (!ai) return null
  const pre = ai.pre
  const post = ai.post
  if (!pre?.available && !post?.available) {
    return (
      <div style={{ marginTop: 10, fontSize: 11, color: tokens.textMuted, display: 'flex', alignItems: 'center', gap: 6 }}>
        <AlertCircle size={11} />
        {pre?.reason || post?.reason || 'AI briefing unavailable'}
      </div>
    )
  }
  return (
    <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
      {pre?.available && (
        <div style={{ background: tokens.bg, border: `1px solid ${tokens.border}`, borderRadius: 8, padding: '10px 12px' }}>
          <div style={{ fontSize: 10, color: '#bc8cff', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Sparkles size={11} /> Gemini preview
          </div>
          <div style={{ fontSize: 12, color: tokens.text, marginBottom: 4 }}>{pre.summary}</div>
          {pre.expected && <div style={{ fontSize: 11, color: tokens.textMuted, lineHeight: 1.5 }}>{pre.expected}</div>}
          {pre.watch_for && (
            <div style={{ fontSize: 11, color: tokens.textMuted, lineHeight: 1.5, marginTop: 4 }}>
              <strong style={{ color: tokens.text }}>Watch for:</strong> {pre.watch_for}
            </div>
          )}
          {Array.isArray(pre.scenarios) && pre.scenarios.length > 0 && (
            <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {pre.scenarios.map((s, i) => (
                <div key={i} style={{ fontSize: 11, color: tokens.textMuted, lineHeight: 1.4 }}>
                  <Badge color={s.surprise?.includes('hawk') || s.surprise?.includes('upside') ? tokens.danger : s.surprise?.includes('dov') || s.surprise?.includes('downside') ? tokens.success : tokens.textMuted}>
                    {(s.surprise || 'scenario').replace(/_/g, ' ')}
                  </Badge>{' '}
                  {s.playbook}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {post?.available && (
        <div style={{ background: 'rgba(63,185,80,0.06)', border: `1px solid ${tokens.success}33`, borderRadius: 8, padding: '10px 12px' }}>
          <div style={{ fontSize: 10, color: tokens.success, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Sparkles size={11} /> Post-event read
          </div>
          <div style={{ fontSize: 12, color: tokens.text, marginBottom: 4 }}>{post.headline}</div>
          {post.surprise && (
            <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 4 }}>
              Surprise: <Badge color={post.surprise.includes('hawk') || post.surprise === 'inflationary' || post.surprise === 'growth_positive' ? tokens.danger : post.surprise.includes('dov') || post.surprise === 'disinflationary' || post.surprise === 'growth_negative' ? tokens.success : tokens.textMuted}>{post.surprise.replace(/_/g, ' ')}</Badge>
            </div>
          )}
          {post.cross_asset && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
              {Object.entries(post.cross_asset).map(([k, v]) => (
                <Badge key={k} color={v === 'bullish' ? tokens.success : v === 'bearish' ? tokens.danger : tokens.textMuted}>
                  {k}: {v}
                </Badge>
              ))}
            </div>
          )}
          {post.playbook && (
            <div style={{ fontSize: 11, color: tokens.textMuted, lineHeight: 1.5 }}>
              <strong style={{ color: tokens.text }}>Playbook:</strong> {post.playbook}
            </div>
          )}
          {post.invalidation && (
            <div style={{ fontSize: 11, color: tokens.textMuted, lineHeight: 1.5, marginTop: 4 }}>
              <strong style={{ color: tokens.text }}>Invalidation:</strong> {post.invalidation}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function EventRow({ event, expanded, onToggle }) {
  const released = isReleased(event)
  return (
    <div style={{ ...row, flexDirection: 'column', cursor: 'pointer' }} onClick={onToggle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%', gap: 12 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <Badge color={impactColor(event.impact)}>{event.impact || 'med'}</Badge>
            <span style={{ fontSize: 13, fontWeight: 600, color: tokens.text }}>{event.event_name}</span>
            <span style={{ fontSize: 11, color: tokens.textMuted }}>{event.currency || event.country}</span>
            {released && <Badge color={tokens.success}>released</Badge>}
          </div>
          <div style={{ fontSize: 11, color: tokens.textMuted, display: 'flex', alignItems: 'center', gap: 6 }}>
            <Clock size={10} /> {fmtTime(event.release_time)}
            {event.event_type && event.event_type !== 'ECONOMIC' && <span>· {event.event_type}</span>}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
          {(event.forecast || event.previous || event.actual !== undefined) && (
            <div style={{ fontSize: 11, color: tokens.textMuted, textAlign: 'right' }}>
              {event.actual != null && event.actual !== '' && (
                <div><strong style={{ color: tokens.text }}>Actual</strong> {event.actual}</div>
              )}
              {event.forecast && <div>Forecast {event.forecast}</div>}
              {event.previous && <div>Prev {event.previous}</div>}
            </div>
          )}
          <ChevronRight size={14} color={tokens.textMuted} style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0)', transition: '0.15s' }} />
        </div>
      </div>
      {expanded && <AIBriefingCard ai={event.ai} />}
    </div>
  )
}


export default function Calendar() {
  const { user } = useAuthStore()
  const isAdmin = user?.role === 'admin'
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [filter, setFilter] = useState('all') // all | upcoming | released
  const [expanded, setExpanded] = useState(null)
  const [aiStatus, setAiStatus] = useState(null)

  async function load(useAi = true) {
    setLoading(true)
    try {
      const [r, s] = await Promise.all([
        api.get(`/calendar/events?with_ai=${useAi}&limit=80`),
        api.get('/ai/status').catch(() => ({ data: null })),
      ])
      setEvents(r.data?.events || [])
      setAiStatus(s.data || null)
    } catch (e) {
      toast.error('Failed to load calendar')
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  async function syncNow() {
    if (!isAdmin) {
      toast.error('Calendar sync is admin-only')
      return
    }
    setSyncing(true)
    try {
      const r = await api.post('/calendar/sync')
      toast.success(`Synced ${r.data?.synced ?? 0} events from ${r.data?.provider ?? '?'}`)
      load()
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Sync failed'
      toast.error(msg)
    }
    setSyncing(false)
  }

  if (loading) return <Loading message="Loading economic calendar…" />

  const now = Date.now()
  const filtered = events.filter(ev => {
    if (filter === 'all') return true
    const released = isReleased(ev)
    return filter === 'released' ? released : !released
  })

  // Group by date for the rail
  const groups = {}
  for (const ev of filtered) {
    const day = (ev.release_time || '').slice(0, 10) || 'unknown'
    groups[day] = groups[day] || []
    groups[day].push(ev)
  }

  return (
    <div>
      <PageHeader
        title="🗓 Economic Calendar"
        subtitle="Macro releases with Gemini Flash playbooks — pre-event scenarios and post-release reads"
        action={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Badge color={aiStatus?.available ? tokens.success : tokens.warning}>
              {aiStatus?.available ? `AI: ${aiStatus.model}` : (aiStatus ? 'AI off' : '…')}
            </Badge>
            <Button variant="secondary" size="sm" onClick={() => load()} leftIcon={<RefreshCw size={11} />}>
              Reload
            </Button>
            {isAdmin && (
              <Button size="sm" onClick={syncNow} loading={syncing} leftIcon={<CalendarIcon size={11} />}>
                Sync from provider
              </Button>
            )}
          </div>
        }
      />

      {!aiStatus?.available && (
        <Card style={{ marginBottom: 14, borderColor: tokens.warning, background: 'rgba(227,179,65,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: tokens.warning, fontSize: 12 }}>
            <AlertCircle size={14} />
            <div>
              <strong>Gemini AI not connected.</strong>{' '}
              {aiStatus?.reason || 'Set GEMINI_API_KEY (or GEMINY_API_KEY / GOOGLE_API_KEY) in your environment. Events will still show, but without the AI playbook.'}
            </div>
          </div>
        </Card>
      )}

      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {['all', 'upcoming', 'released'].map(f => (
          <button key={f} onClick={() => setFilter(f)} style={{
            padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500,
            background: filter === f ? tokens.accent : tokens.surfaceAlt,
            color: filter === f ? '#fff' : tokens.textMuted, textTransform: 'capitalize',
          }}>{f}</button>
        ))}
      </div>

      {Object.keys(groups).length === 0 ? (
        <Empty
          message="No events on the calendar yet. An admin can hit “Sync from provider” to pull from Finnhub."
          icon="🗓"
          action={isAdmin && <Button onClick={syncNow} loading={syncing}>Sync now</Button>}
        />
      ) : (
        Object.entries(groups).sort().map(([day, list]) => (
          <Card key={day} style={{ marginBottom: 12 }}>
            <SectionTitle icon={<CalendarIcon size={14} />}>{day}</SectionTitle>
            {list.map((ev, i) => (
              <EventRow
                key={ev.event_id || `${day}-${i}`}
                event={ev}
                expanded={expanded === (ev.event_id || `${day}-${i}`)}
                onToggle={() => setExpanded(expanded === (ev.event_id || `${day}-${i}`) ? null : (ev.event_id || `${day}-${i}`))}
              />
            ))}
          </Card>
        ))
      )}
    </div>
  )
}
