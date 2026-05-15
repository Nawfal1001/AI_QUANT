import React from 'react'
import { tokens } from './tokens'

// Line chart — for equity curve, prices, etc.
export const LineChart = ({ data, xKey = 'date', yKey = 'value', height = 220, color, fillGradient = true, showAxis = true }) => {
  if (!data || data.length < 2) return <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: tokens.textMuted, fontSize: 12 }}>Not enough data points</div>

  const w = 800
  const padX = 40
  const padY = 18
  const values = data.map(d => d[yKey])
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const stepX = (w - padX * 2) / (data.length - 1)
  const points = data.map((d, i) => {
    const x = padX + i * stepX
    const y = height - padY - ((d[yKey] - min) / range) * (height - padY * 2)
    return `${x},${y}`
  }).join(' ')
  const lineColor = color || (values[values.length - 1] >= values[0] ? tokens.success : tokens.danger)
  const gradId = `grad-${Math.random().toString(36).slice(2, 8)}`

  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height }} preserveAspectRatio="none">
      {fillGradient && (
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
      )}
      {showAxis && [0.25, 0.5, 0.75].map(p => (
        <line key={p} x1={padX} y1={padY + p * (height - padY * 2)} x2={w - padX} y2={padY + p * (height - padY * 2)} stroke={tokens.border} strokeDasharray="3 3" />
      ))}
      {fillGradient && (
        <polygon points={`${padX},${height - padY} ${points} ${w - padX},${height - padY}`} fill={`url(#${gradId})`} />
      )}
      <polyline points={points} fill="none" stroke={lineColor} strokeWidth="2" />
      {showAxis && (
        <>
          <text x="6" y={padY + 4} fill={tokens.textMuted} fontSize="10">{max.toLocaleString('en', { maximumFractionDigits: 0 })}</text>
          <text x="6" y={height - padY + 4} fill={tokens.textMuted} fontSize="10">{min.toLocaleString('en', { maximumFractionDigits: 0 })}</text>
          <text x={padX} y={height - 4} fill={tokens.textMuted} fontSize="10">{data[0][xKey]}</text>
          <text x={w - padX - 60} y={height - 4} fill={tokens.textMuted} fontSize="10">{data[data.length - 1][xKey]}</text>
        </>
      )}
    </svg>
  )
}

// Drawdown chart — like area chart but always negative (underwater curve)
export const DrawdownChart = ({ data, xKey = 'date', yKey = 'dd_pct', height = 160 }) => {
  if (!data || data.length < 2) return null
  const w = 800
  const padX = 40
  const padY = 18
  const values = data.map(d => d[yKey])
  const min = Math.min(...values, 0)
  const max = 0
  const range = max - min || 1
  const stepX = (w - padX * 2) / (data.length - 1)
  const points = data.map((d, i) => {
    const x = padX + i * stepX
    const y = padY + ((max - d[yKey]) / range) * (height - padY * 2)
    return `${x},${y}`
  }).join(' ')
  const gradId = `dd-${Math.random().toString(36).slice(2, 8)}`

  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height }} preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tokens.danger} stopOpacity="0.05" />
          <stop offset="100%" stopColor={tokens.danger} stopOpacity="0.35" />
        </linearGradient>
      </defs>
      <line x1={padX} y1={padY} x2={w - padX} y2={padY} stroke={tokens.border} strokeDasharray="3 3" />
      <polygon points={`${padX},${padY} ${points} ${w - padX},${padY}`} fill={`url(#${gradId})`} />
      <polyline points={points} fill="none" stroke={tokens.danger} strokeWidth="1.5" />
      <text x="6" y={padY + 4} fill={tokens.textMuted} fontSize="10">0%</text>
      <text x="6" y={height - padY + 4} fill={tokens.textMuted} fontSize="10">{min.toFixed(1)}%</text>
    </svg>
  )
}

// Bar chart — for P&L history
export const BarChart = ({ data, xKey = 'date', yKey = 'value', height = 200, threshold = 0 }) => {
  if (!data || data.length === 0) return null
  const w = 800
  const padX = 40
  const padY = 18
  const values = data.map(d => d[yKey])
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const range = (max - min) || 1
  const barW = Math.max(2, (w - padX * 2) / data.length - 2)
  const zeroY = height - padY - ((0 - min) / range) * (height - padY * 2)

  return (
    <svg viewBox={`0 0 ${w} ${height}`} style={{ width: '100%', height }} preserveAspectRatio="none">
      <line x1={padX} y1={zeroY} x2={w - padX} y2={zeroY} stroke={tokens.border} />
      {data.map((d, i) => {
        const v = d[yKey]
        const x = padX + i * ((w - padX * 2) / data.length)
        const y = v >= threshold ? height - padY - ((v - min) / range) * (height - padY * 2) : zeroY
        const h = Math.abs(v - threshold) / range * (height - padY * 2)
        const color = v >= threshold ? tokens.success : tokens.danger
        return <rect key={i} x={x} y={y} width={barW} height={h} fill={color} opacity={0.85} />
      })}
      <text x="6" y={padY + 4} fill={tokens.textMuted} fontSize="10">{max.toFixed(0)}</text>
      <text x="6" y={height - padY + 4} fill={tokens.textMuted} fontSize="10">{min.toFixed(0)}</text>
    </svg>
  )
}

// Donut/Pie chart — portfolio allocation
export const DonutChart = ({ data, valueKey = 'value', labelKey = 'label', colorKey = 'color', size = 200, centerLabel }) => {
  if (!data || data.length === 0) return null
  const palette = [tokens.accent, tokens.success, tokens.warning, tokens.purple, tokens.orange, tokens.info, tokens.danger, '#5fb878']
  const total = data.reduce((s, d) => s + (d[valueKey] || 0), 0)
  if (total === 0) return <div style={{ color: tokens.textMuted, textAlign: 'center', padding: 30 }}>No allocation data</div>

  const radius = size / 2 - 12
  const innerR = radius * 0.6
  const cx = size / 2
  const cy = size / 2

  let cumulative = 0
  const slices = data.map((d, i) => {
    const value = d[valueKey] || 0
    const pct = value / total
    const startA = cumulative * 2 * Math.PI - Math.PI / 2
    cumulative += pct
    const endA = cumulative * 2 * Math.PI - Math.PI / 2
    const x1 = cx + radius * Math.cos(startA)
    const y1 = cy + radius * Math.sin(startA)
    const x2 = cx + radius * Math.cos(endA)
    const y2 = cy + radius * Math.sin(endA)
    const x3 = cx + innerR * Math.cos(endA)
    const y3 = cy + innerR * Math.sin(endA)
    const x4 = cx + innerR * Math.cos(startA)
    const y4 = cy + innerR * Math.sin(startA)
    const largeArc = pct > 0.5 ? 1 : 0
    const path = `M ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} L ${x3} ${y3} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x4} ${y4} Z`
    return { path, color: d[colorKey] || palette[i % palette.length], label: d[labelKey], value, pct }
  })

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap' }}>
      <svg viewBox={`0 0 ${size} ${size}`} style={{ width: size, height: size, flexShrink: 0 }}>
        {slices.map((s, i) => <path key={i} d={s.path} fill={s.color} stroke={tokens.bg} strokeWidth="1.5" />)}
        {centerLabel && (
          <>
            <text x={cx} y={cy - 2} textAnchor="middle" fill={tokens.textMuted} fontSize="10" textTransform="uppercase">total</text>
            <text x={cx} y={cy + 16} textAnchor="middle" fill={tokens.text} fontSize="18" fontWeight="700">{centerLabel}</text>
          </>
        )}
      </svg>
      <div style={{ flex: 1, minWidth: 160 }}>
        {slices.map((s, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: 12 }}>
            <div style={{ width: 10, height: 10, background: s.color, borderRadius: 2, flexShrink: 0 }} />
            <div style={{ color: tokens.text, flex: 1 }}>{s.label}</div>
            <div style={{ color: tokens.textMuted }}>{(s.pct * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>
    </div>
  )
}

// Heatmap — for signal accuracy by regime/strategy
export const Heatmap = ({ data, rowKey = 'row', colKey = 'col', valueKey = 'value', label = 'Win rate' }) => {
  if (!data || data.length === 0) return <div style={{ color: tokens.textMuted, padding: 20, textAlign: 'center', fontSize: 12 }}>No data</div>
  const rows = [...new Set(data.map(d => d[rowKey]))]
  const cols = [...new Set(data.map(d => d[colKey]))]
  const lookup = {}
  data.forEach(d => { lookup[`${d[rowKey]}|${d[colKey]}`] = d[valueKey] })

  const cell = (v) => {
    if (v == null) return tokens.surfaceAlt
    if (v >= 65) return tokens.success
    if (v >= 50) return tokens.warning
    if (v >= 35) return tokens.orange
    return tokens.danger
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 11 }}>
        <thead>
          <tr>
            <th style={{ padding: 6, color: tokens.textMuted, textAlign: 'left' }}></th>
            {cols.map(c => <th key={c} style={{ padding: 6, color: tokens.textMuted, fontWeight: 500 }}>{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r}>
              <td style={{ padding: 6, color: tokens.text, fontWeight: 500 }}>{r}</td>
              {cols.map(c => {
                const v = lookup[`${r}|${c}`]
                return (
                  <td key={c} style={{ padding: 4 }}>
                    <div style={{ background: cell(v), padding: '6px 10px', borderRadius: 4, color: '#fff', fontWeight: 600, opacity: v == null ? 0.3 : 0.85, minWidth: 50, textAlign: 'center' }}>
                      {v != null ? `${v.toFixed(0)}%` : '—'}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ fontSize: 10, color: tokens.textMuted, marginTop: 6 }}>{label}</div>
    </div>
  )
}
