import React, { useState, useEffect } from 'react'
import { api } from '@/store/auth'
import { Card, Button, PageHeader, SectionTitle, Loading, Empty, Badge, Grid, Metric } from '@/components/ui'
import { tokens } from '@/components/ui/tokens'
import { Trophy, Zap, Star, Award } from 'lucide-react'
import toast from 'react-hot-toast'

const LEVELS = [
  { name: 'Beginner', min_xp: 0, color: tokens.textMuted },
  { name: 'Novice', min_xp: 100, color: tokens.info },
  { name: 'Intermediate', min_xp: 500, color: tokens.success },
  { name: 'Advanced', min_xp: 1500, color: tokens.warning },
  { name: 'Expert', min_xp: 5000, color: tokens.orange },
  { name: 'Master', min_xp: 15000, color: tokens.purple },
]

export default function Rewards() {
  const [profile, setProfile] = useState(null)
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    try {
      const [p, s] = await Promise.all([
        api.get('/reward/profile'),
        api.get('/reward/signals-log?limit=30'),
      ])
      setProfile(p.data)
      setSignals(s.data?.signals || [])
    } catch (e) { console.warn("caught:", e) }
    setLoading(false)
  }
  useEffect(() => { load() }, [])

  async function claimDaily() {
    try {
      const r = await api.post('/reward/daily-login')
      if (r.data?.xp_gained > 0) toast.success(`+${r.data.xp_gained} XP`)
      else toast(r.data?.message || 'Already claimed today')
      load()
    } catch { toast.error('Failed') }
  }

  if (loading) return <Loading message="Loading rewards…" />
  if (!profile) return <Empty message="No profile yet" icon="🏆" />

  const xp = profile.xp || 0
  const current = LEVELS.find(l => l.name === profile.level_name) || LEVELS[0]
  const next = LEVELS[LEVELS.indexOf(current) + 1] || current
  const progress = next.min_xp > current.min_xp ? Math.min(100, ((xp - current.min_xp) / (next.min_xp - current.min_xp)) * 100) : 100

  return (
    <div>
      <PageHeader
        title="🏆 Rewards"
        subtitle="Earn XP, unlock badges, level up"
        action={<Button leftIcon={<Zap size={13} />} onClick={claimDaily}>Claim Daily +15 XP</Button>}
      />

      <Card style={{ marginBottom: 14, background: `linear-gradient(135deg, ${current.color}22 0%, ${tokens.surface} 100%)`, borderColor: current.color + '50' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 11, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 4 }}>Current Level</div>
            <div style={{ fontSize: 28, fontWeight: 800, color: current.color }}>{current.name}</div>
          </div>
          <Trophy size={48} color={current.color} style={{ opacity: 0.4 }} />
        </div>
        <div style={{ marginBottom: 6, display: 'flex', justifyContent: 'space-between', fontSize: 11, color: tokens.textMuted }}>
          <span>{xp.toLocaleString()} XP</span>
          <span>{profile.xp_to_next ? `${profile.xp_to_next.toLocaleString()} XP to ${profile.next_level}` : 'Max level'}</span>
        </div>
        <div style={{ background: tokens.surfaceAlt, borderRadius: 4, height: 8, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${progress}%`, background: `linear-gradient(90deg, ${current.color}, ${next.color})`, transition: '0.4s' }} />
        </div>
      </Card>

      <Grid cols={4} minCol={170} gap={10}>
        <Metric label="Total Signals" value={profile.total_signals || 0} />
        <Metric label="Win Rate" value={`${profile.win_rate || 0}%`} color={(profile.win_rate || 0) >= 50 ? tokens.success : tokens.warning} sub={`${profile.correct_signals || 0} correct`} />
        <Metric label="Streak" value={`🔥 ${profile.streak || 0}`} color={tokens.orange} />
        <Metric label="Badges" value={profile.badges?.length || 0} icon={<Award size={11} />} />
      </Grid>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle icon={<Award size={14} />}>Level Progression</SectionTitle>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, overflowX: 'auto' }}>
          {LEVELS.map(lvl => {
            const reached = xp >= lvl.min_xp
            const isCurr = lvl.name === current.name
            return (
              <div key={lvl.name} style={{ flex: 1, minWidth: 90, textAlign: 'center', padding: '10px 6px', border: `1px solid ${isCurr ? lvl.color : tokens.border}`, borderRadius: 8, background: isCurr ? `${lvl.color}15` : 'transparent', opacity: reached ? 1 : 0.4 }}>
                <Star size={16} color={lvl.color} style={{ marginBottom: 4 }} />
                <div style={{ fontSize: 11, fontWeight: 600, color: lvl.color }}>{lvl.name}</div>
                <div style={{ fontSize: 9, color: tokens.textMuted, marginTop: 2 }}>{lvl.min_xp.toLocaleString()} XP</div>
              </div>
            )
          })}
        </div>
      </Card>

      <Card style={{ marginTop: 14 }}>
        <SectionTitle>Recent Signals Log</SectionTitle>
        {signals.length === 0 ? <Empty message="No signals tracked yet" icon="📝" /> : (
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            {signals.map((s, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 0', borderBottom: i < signals.length - 1 ? `1px solid ${tokens.border}` : 'none' }}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: tokens.text }}>
                    {s.ticker} <Badge color={s.signal?.includes('BUY') ? tokens.success : s.signal?.includes('SELL') ? tokens.danger : tokens.textMuted}>{s.signal}</Badge>
                  </div>
                  <div style={{ fontSize: 10, color: tokens.textMuted, marginTop: 3 }}>
                    {(s.emitted_at || '').slice(0, 16)} · {s.confidence}% · {s.strategy || 'default'}
                  </div>
                </div>
                {s.outcome && <Badge color={s.outcome === 'win' ? tokens.success : tokens.danger}>{s.outcome}</Badge>}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
