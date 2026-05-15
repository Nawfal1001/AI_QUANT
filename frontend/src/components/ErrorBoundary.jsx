import React from 'react'

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, info) {
    console.error('Frontend render error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div style={{ minHeight: '100vh', background: '#0d1117', color: '#e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
        <div style={{ maxWidth: 560, border: '1px solid #30363d', borderRadius: 12, padding: 24, background: '#161b22' }}>
          <h1 style={{ marginTop: 0 }}>Something went wrong</h1>
          <p>The interface hit an unexpected error. Your session is safe; refresh the page to retry.</p>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 12, padding: '10px 16px', borderRadius: 8, border: '1px solid #30363d', background: '#238636', color: 'white', cursor: 'pointer' }}
          >
            Reload app
          </button>
        </div>
      </div>
    )
  }
}
