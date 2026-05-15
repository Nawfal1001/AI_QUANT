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
  const subscribedRef = useRef([])
  const key = [...tickers].sort().join(',')

  const sendSubscription = useCallback((ws) => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    const previous = subscribedRef.current
    if (previous.length > 0) {
      ws.send(JSON.stringify({ action: 'unsubscribe', tickers: previous }))
    }
    if (tickers.length > 0) {
      ws.send(JSON.stringify({ action: 'subscribe', tickers }))
    }
    subscribedRef.current = tickers
  }, [key])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      sendSubscription(wsRef.current)
      return
    }
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
        sendSubscription(ws)
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
          console.warn('WS bad message', err)
        }
      }

      ws.onclose = (event) => {
        setConnected(false)
        subscribedRef.current = []
        if (event.code === 4401) {
          setError('auth_failed')
          return
        }
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
  }, [key, sendSubscription])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { prices, connected, error }
}
