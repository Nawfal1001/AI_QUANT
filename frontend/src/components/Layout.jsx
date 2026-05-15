import React, { useState, useEffect } from 'react'
import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useStore } from '@/store'
import { useAuthStore } from '@/store/auth'
import { useLivePrices } from '@/hooks/useLivePrices'
import { SafetyBar } from '@/components/SafetyBar'
import { LayoutDashboard, Briefcase, Zap, Brain, Calculator, Bot, BarChart2, Trophy, Link2, Bell, Settings, ChevronRight, TrendingUp, LogOut, Activity, Search, Menu, X, FlaskConical, Cpu } from 'lucide-react'

const NAV = [
  { to: '/dashboard',   icon: LayoutDashboard, label: 'Dashboard'   },
  { to: '/portfolio',   icon: Briefcase,        label: 'Portfolio'   },
  { to: '/signals',     icon: Zap,              label: 'Signals'     },
  { to: '/strategy',    icon: Brain,            label: 'Strategy'    },
  { to: '/strategy-lab', icon: FlaskConical,    label: 'Strategy Lab' },
  { to: '/bots',        icon: Cpu,              label: 'Trading Bots' },
  { to: '/quant',       icon: Calculator,       label: 'Quant'       },
  { to: '/autotrader',  icon: Bot,              label: 'Auto-Trader' },
  { to: '/learning',    icon: Activity,         label: 'Self-Learning' },
  { to: '/backtest',    icon: BarChart2,        label: 'Backtest'    },
  { to: '/research',    icon: Search,           label: 'AI Research' },
  { to: '/rewards',     icon: Trophy,           label: 'Rewards'     },
  { to: '/brokers',     icon: Link2,            label: 'Brokers'     },
  { to: '/alerts',      icon: Bell,             label: 'Alerts'      },
  { to: '/settings',    icon: Settings,         label: 'Settings'    },
]

export default function Layout() {
  const { tradingMode, setTradingMode } = useStore()
  const { user, logout } = useAuthStore()
  const { connected } = useLivePrices(['AAPL', 'BTC', 'ETH', 'NVDA'])
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 799px)').matches)
  const navigate = useNavigate()

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia('(max-width: 799px)')
    const onChange = (e) => setIsMobile(e.matches)
    // Safari < 14 still needs addListener
    if (mq.addEventListener) mq.addEventListener('change', onChange)
    else mq.addListener(onChange)
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', onChange)
      else mq.removeListener(onChange)
    }
  }, [])

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#0d1117', color: '#e2e8f0', fontFamily: 'Inter,system-ui,sans-serif' }}>
      {/* Mobile overlay */}
      {mobileOpen && isMobile && (
        <div onClick={() => setMobileOpen(false)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 50 }} />
      )}

      <aside
        className={`tradeai-sidebar ${mobileOpen ? 'open' : ''}`}
        style={{
          width: collapsed ? 58 : 220,
          transition: 'width 0.2s',
          background: '#161b22',
          borderRight: '1px solid #21262d',
          display: 'flex',
          flexDirection: 'column',
          flexShrink: 0,
          overflow: 'hidden',
          position: isMobile ? 'fixed' : 'relative',
          height: isMobile ? '100vh' : 'auto',
          zIndex: 51,
        }}
      >
        <div style={{ padding: '14px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #21262d', minHeight: 52 }}>
          {!collapsed && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <TrendingUp size={17} color="#3fb950" />
              <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: -0.5 }}>trade<span style={{ color: '#3fb950' }}>AI</span></span>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: connected ? '#3fb950' : '#e3b341', marginLeft: 2 }} title={connected ? 'Live' : 'Reconnecting'} />
            </div>
          )}
          <button onClick={() => isMobile ? setMobileOpen(false) : setCollapsed(!collapsed)} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', padding: 4, display: 'flex' }}>
            {isMobile ? <X size={16} /> : <ChevronRight size={15} style={{ transform: collapsed ? 'rotate(0)' : 'rotate(180deg)', transition: '0.2s' }} />}
          </button>
        </div>

        {!collapsed && (
          <div style={{ padding: '8px 10px', borderBottom: '1px solid #21262d' }}>
            <div style={{ display: 'flex', background: '#0d1117', borderRadius: 7, padding: 2, gap: 2 }}>
              {[['paper', '📄 Paper'], ['live', '⚡ Live']].map(([m, label]) => (
                <button key={m} onClick={() => { if (m === 'live' && !window.confirm('Switch to LIVE trading?')) return; setTradingMode(m) }}
                  style={{ flex: 1, padding: '4px 0', borderRadius: 5, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 500, background: tradingMode === m ? (m === 'live' ? '#da3633' : '#1f6feb') : 'transparent', color: tradingMode === m ? '#fff' : '#8b949e' }}>
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        <nav style={{ flex: 1, padding: '6px', overflowY: 'auto' }}>
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} title={collapsed ? label : undefined} onClick={() => isMobile && setMobileOpen(false)}
              style={({ isActive }) => ({ display: 'flex', alignItems: 'center', gap: 9, padding: collapsed ? '9px 12px' : '8px 10px', borderRadius: 7, marginBottom: 2, textDecoration: 'none', fontSize: 13, fontWeight: 500, background: isActive ? '#21262d' : 'transparent', color: isActive ? '#e2e8f0' : '#8b949e', transition: '0.12s', justifyContent: collapsed ? 'center' : 'flex-start' })}>
              <Icon size={15} style={{ flexShrink: 0 }} />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {!collapsed && user && (
          <div style={{ padding: '10px 12px', borderTop: '1px solid #21262d', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontSize: 12, color: '#e2e8f0', fontWeight: 500 }}>{user.username}</div>
              <div style={{ fontSize: 10, color: '#8b949e', textTransform: 'capitalize' }}>{user.role}</div>
            </div>
            <button onClick={() => { logout(); navigate('/auth') }} style={{ background: 'none', border: 'none', color: '#8b949e', cursor: 'pointer', padding: 4, display: 'flex' }}>
              <LogOut size={14} />
            </button>
          </div>
        )}
      </aside>

      <main className="tradeai-main" style={{ flex: 1, overflow: 'auto', padding: '14px 18px 22px', minWidth: 0 }}>
        {/* Mobile menu button */}
        {isMobile && (
          <button onClick={() => setMobileOpen(true)} style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 8, padding: 8, color: '#e2e8f0', cursor: 'pointer', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <Menu size={16} /> Menu
          </button>
        )}
        <SafetyBar />
        <Outlet />
      </main>
    </div>
  )
}
