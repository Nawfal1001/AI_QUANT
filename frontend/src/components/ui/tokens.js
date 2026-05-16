// Shared design tokens — all components import from here
export const tokens = {
  // Colors
  bg: '#0d1117',
  surface: '#161b22',
  surfaceAlt: '#1c2128',
  border: '#21262d',
  borderHover: '#30363d',

  text: '#e2e8f0',
  textMuted: '#8b949e',
  textFaint: '#6e7681',

  accent: '#1f6feb',
  accentHover: '#388bfd',
  success: '#3fb950',
  warning: '#e3b341',
  danger: '#f85149',
  info: '#58a6ff',
  purple: '#bc8cff',
  orange: '#f78166',

  // Spacing
  s: 6,
  m: 10,
  l: 14,
  xl: 20,

  // Radius
  radiusSm: 6,
  radiusMd: 8,
  radiusLg: 12,

  // Shadows
  glow: '0 0 0 1px',
}

// Returns a status color based on a value vs threshold
export const statusColor = (value, good = 0, warn = -3, bad = -8) => {
  if (value >= good) return tokens.success
  if (value >= warn) return tokens.warning
  if (value >= bad) return tokens.orange
  return tokens.danger
}

// Returns green for positive, red for negative, muted for zero/invalid
export const signColor = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n) || n === 0) return tokens.textMuted
  return n > 0 ? tokens.success : tokens.danger
}

// Format currency
export const fmt$ = (v, opts = {}) => {
  if (v == null || isNaN(v)) return '—'
  return '$' + Number(v).toLocaleString('en', { maximumFractionDigits: 2, ...opts })
}

// Format percentage with +/- sign
export const fmtPct = (v, decimals = 2) => {
  if (v == null || isNaN(v)) return '—'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(decimals) + '%'
}

// Format number with commas
export const fmtNum = (v, decimals = 0) => {
  if (v == null || isNaN(v)) return '—'
  return Number(v).toLocaleString('en', { maximumFractionDigits: decimals })
}
