import React from 'react'
import { tokens } from './tokens'

// Card — base container
export const Card = ({ children, style = {}, ...rest }) => (
  <div
    style={{
      background: tokens.surface,
      border: `1px solid ${tokens.border}`,
      borderRadius: tokens.radiusLg,
      padding: '16px 18px',
      ...style,
    }}
    {...rest}
  >
    {children}
  </div>
)

// Button — variant: primary | secondary | danger | ghost
export const Button = ({ variant = 'primary', size = 'md', loading, disabled, children, leftIcon, style = {}, ...rest }) => {
  const variants = {
    primary: { bg: tokens.accent, hover: tokens.accentHover, color: '#fff', border: 'none' },
    secondary: { bg: tokens.surfaceAlt, hover: '#2d333b', color: tokens.text, border: `1px solid ${tokens.borderHover}` },
    danger: { bg: 'transparent', hover: 'rgba(248,81,73,0.1)', color: tokens.danger, border: `1px solid ${tokens.danger}` },
    ghost: { bg: 'transparent', hover: tokens.surfaceAlt, color: tokens.textMuted, border: '1px solid transparent' },
    success: { bg: tokens.success, hover: '#4ec560', color: '#fff', border: 'none' },
  }
  const v = variants[variant] || variants.primary
  const sizes = {
    sm: { padding: '5px 10px', fontSize: 11 },
    md: { padding: '8px 14px', fontSize: 13 },
    lg: { padding: '10px 18px', fontSize: 14 },
  }
  const s = sizes[size]
  return (
    <button
      disabled={disabled || loading}
      style={{
        background: v.bg,
        color: v.color,
        border: v.border,
        borderRadius: tokens.radiusMd,
        ...s,
        cursor: disabled || loading ? 'not-allowed' : 'pointer',
        fontWeight: 600,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        opacity: disabled || loading ? 0.55 : 1,
        transition: 'background 0.15s',
        whiteSpace: 'nowrap',
        ...style,
      }}
      onMouseEnter={e => !disabled && !loading && (e.currentTarget.style.background = v.hover)}
      onMouseLeave={e => !disabled && !loading && (e.currentTarget.style.background = v.bg)}
      {...rest}
    >
      {loading ? <Spinner size={12} /> : leftIcon}
      {children}
    </button>
  )
}

// Input
export const Input = ({ label, error, style = {}, fullWidth, ...rest }) => (
  <div style={{ display: fullWidth ? 'block' : 'inline-block', width: fullWidth ? '100%' : 'auto' }}>
    {label && <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>}
    <input
      style={{
        background: tokens.bg,
        border: `1px solid ${error ? tokens.danger : tokens.border}`,
        borderRadius: tokens.radiusSm + 1,
        padding: '7px 10px',
        color: tokens.text,
        fontSize: 13,
        outline: 'none',
        width: fullWidth ? '100%' : 'auto',
        boxSizing: 'border-box',
        ...style,
      }}
      {...rest}
    />
    {error && <div style={{ fontSize: 11, color: tokens.danger, marginTop: 3 }}>{error}</div>}
  </div>
)

// Select wrapper
export const Select = ({ label, children, fullWidth, style = {}, ...rest }) => (
  <div style={{ display: fullWidth ? 'block' : 'inline-block', width: fullWidth ? '100%' : 'auto' }}>
    {label && <div style={{ fontSize: 11, color: tokens.textMuted, marginBottom: 4, textTransform: 'uppercase', letterSpacing: 0.3 }}>{label}</div>}
    <select
      style={{
        background: tokens.bg,
        border: `1px solid ${tokens.border}`,
        borderRadius: tokens.radiusSm + 1,
        padding: '7px 10px',
        color: tokens.text,
        fontSize: 13,
        outline: 'none',
        width: fullWidth ? '100%' : 'auto',
        ...style,
      }}
      {...rest}
    >{children}</select>
  </div>
)

// Toggle
export const Toggle = ({ value, onChange, disabled, color = tokens.accent }) => (
  <div
    onClick={() => !disabled && onChange?.(!value)}
    style={{
      width: 36, height: 20, borderRadius: 10,
      background: value ? color : tokens.surfaceAlt,
      cursor: disabled ? 'not-allowed' : 'pointer',
      position: 'relative',
      transition: '0.2s',
      opacity: disabled ? 0.5 : 1,
    }}
  >
    <div style={{
      position: 'absolute',
      width: 16, height: 16,
      borderRadius: '50%',
      background: '#fff',
      top: 2,
      left: value ? 18 : 2,
      transition: '0.2s',
      boxShadow: '0 1px 2px rgba(0,0,0,0.3)',
    }} />
  </div>
)

// Metric tile
export const Metric = ({ label, value, color = tokens.text, sub, icon, style = {} }) => (
  <Card style={{ padding: '14px 16px', minHeight: 80, ...style }}>
    <div style={{ fontSize: 10, color: tokens.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
      {icon}{label}
    </div>
    <div style={{ fontSize: 22, fontWeight: 700, color, lineHeight: 1.1 }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: tokens.textMuted, marginTop: 4 }}>{sub}</div>}
  </Card>
)

// Spinner
export const Spinner = ({ size = 14, color = '#fff' }) => (
  <span style={{
    display: 'inline-block',
    width: size, height: size,
    border: `2px solid ${color}`,
    borderTopColor: 'transparent',
    borderRadius: '50%',
    animation: 'tradeai-spin 0.8s linear infinite',
  }} />
)

// Loading state
export const Loading = ({ message = 'Loading…', minHeight = 100 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight, gap: 10, color: tokens.textMuted, fontSize: 13 }}>
    <Spinner color={tokens.textMuted} size={20} />
    <span>{message}</span>
  </div>
)

// Error state
export const ErrorState = ({ message = 'Something went wrong', onRetry }) => (
  <Card style={{ borderColor: tokens.danger, padding: '14px 18px' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: tokens.danger }}>
      <span style={{ fontSize: 20 }}>⚠️</span>
      <div style={{ flex: 1, fontSize: 13 }}>{message}</div>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  </Card>
)

// Empty state
export const Empty = ({ message = 'No data yet', icon = '📭', action }) => (
  <div style={{ textAlign: 'center', padding: '40px 20px', color: tokens.textMuted }}>
    <div style={{ fontSize: 32, marginBottom: 8 }}>{icon}</div>
    <div style={{ fontSize: 13, marginBottom: action ? 12 : 0 }}>{message}</div>
    {action}
  </div>
)

// Badge
export const Badge = ({ children, color = tokens.info, bg }) => (
  <span style={{
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 10,
    padding: '2px 8px',
    borderRadius: tokens.radiusSm,
    background: bg || `${color}22`,
    color,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  }}>{children}</span>
)

// Section header
export const SectionTitle = ({ children, icon, action }) => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
    <div style={{ fontSize: 13, fontWeight: 600, color: tokens.text, display: 'flex', alignItems: 'center', gap: 6 }}>
      {icon}{children}
    </div>
    {action}
  </div>
)

// Page header
export const PageHeader = ({ title, subtitle, action }) => (
  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 18, flexWrap: 'wrap', gap: 10 }}>
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: tokens.text, margin: 0 }}>{title}</h1>
      {subtitle && <div style={{ fontSize: 12, color: tokens.textMuted, marginTop: 3 }}>{subtitle}</div>}
    </div>
    {action}
  </div>
)

// Grid
export const Grid = ({ cols = 4, gap = 10, children, minCol = 160 }) => (
  <div style={{ display: 'grid', gridTemplateColumns: `repeat(auto-fill, minmax(${minCol}px, 1fr))`, gap }}>
    {children}
  </div>
)

// Inject global CSS once
if (typeof document !== 'undefined' && !document.getElementById('tradeai-ui-css')) {
  const style = document.createElement('style')
  style.id = 'tradeai-ui-css'
  style.textContent = `
    @keyframes tradeai-spin { to { transform: rotate(360deg) } }
    @keyframes tradeai-pulse { 0%, 100% { opacity: 1 } 50% { opacity: 0.4 } }
    .tradeai-fade-in { animation: tradeai-fade 0.3s ease-out }
    @keyframes tradeai-fade { from { opacity: 0; transform: translateY(4px) } to { opacity: 1; transform: translateY(0) } }
    /* Mobile responsive */
    @media (max-width: 800px) {
      .tradeai-sidebar { transform: translateX(-100%); transition: 0.25s }
      .tradeai-sidebar.open { transform: translateX(0) }
      .tradeai-main { margin-left: 0 !important }
    }
  `
  document.head.appendChild(style)
}
