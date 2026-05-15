import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { err: null }
  }

  static getDerivedStateFromError(err) {
    return { err }
  }

  componentDidCatch(err, info) {
    console.error('UI error caught by boundary:', err, info)
  }

  reset = () => this.setState({ err: null })

  render() {
    if (!this.state.err) return this.props.children
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0d1117', color: '#e2e8f0', padding: 24 }}>
        <div style={{ maxWidth: 560, background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: 24 }}>
          <h2 style={{ marginTop: 0, color: '#f85149' }}>Something went wrong</h2>
          <p style={{ color: '#8b949e', fontSize: 13, marginBottom: 12 }}>
            A page crashed while rendering. Your session is safe; you can try again or reload.
          </p>
          <pre style={{ background: '#0d1117', padding: 12, borderRadius: 6, fontSize: 12, color: '#e3b341', overflow: 'auto', maxHeight: 200 }}>
            {String(this.state.err?.message || this.state.err)}
          </pre>
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button onClick={this.reset} style={{ background: '#1f6feb', color: '#fff', border: 'none', borderRadius: 6, padding: '8px 14px', cursor: 'pointer' }}>Try again</button>
            <button onClick={() => window.location.reload()} style={{ background: 'transparent', color: '#e2e8f0', border: '1px solid #30363d', borderRadius: 6, padding: '8px 14px', cursor: 'pointer' }}>Reload</button>
          </div>
        </div>
      </div>
    )
  }
}
