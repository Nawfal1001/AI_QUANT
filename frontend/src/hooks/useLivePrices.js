import { useEffect, useRef, useCallback, useState } from 'react'

function getWsBase() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:') + '/ws/prices'
  }
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/prices`
}

function buildWsUrl() {
  const base = getWsBase()
  const token = localStorage.getItem('access_token')
  if (!token) return null
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}token=${encodeURIComponent(token)}`
}

export function useLivePrices(tickers = []) {
  const [prices, setPrices] = useState({})
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)
  const retryRef = useRef(null)
  const key = [...tickers].sort().join(',')

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    const url = buildWsUrl()
    if (!url) {
      setError('not_authenticated')
      return
    }
    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        setError(null)
        if (tickers.length > 0) {
          ws.send(JSON.stringify({ action: 'subscribe', tickers }))
        }
      }

      ws.onmessage = e => {
        try {
          const d = JSON.parse(e.data)
          if (d.type === 'price' && d.ticker) {
            setPrices(p => ({
              ...p,
              [d.ticker]: { price: d.price, change_pct: d.change_pct || 0, timestamp: d.timestamp },
            }))
          } else if (d.type === 'error') {
            setError(d.message || 'ws error')
          }
        } catch (err) {
          // Bad JSON — log and continue
          console.warn('WS bad message', err)
        }
      }

      ws.onclose = (event) => {
        setConnected(false)
        // 4401 = auth failed; don't auto-retry
        if (event.code === 4401) {
          setError('auth_failed')
          return
        }
        // Otherwise reconnect with backoff
        retryRef.current = setTimeout(connect, 5000)
      }

      ws.onerror = (e) => {
        console.warn('WS error', e)
        ws.close()
      }
    } catch (err) {
      console.error('WS connect failed', err)
      setError('connect_failed')
    }
  }, [key])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { prices, connected, error }
}
