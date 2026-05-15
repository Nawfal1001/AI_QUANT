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

const MIN_BACKOFF_MS = 1000
const MAX_BACKOFF_MS = 60_000

export function useLivePrices(tickers = []) {
  const [prices, setPrices] = useState({})
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)
  const retryRef = useRef(null)
  const attemptsRef = useRef(0)
  const cancelledRef = useRef(false)
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
    if (cancelledRef.current) return
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // Already connected — just push the new subscription delta.
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
        attemptsRef.current = 0  // reset backoff on successful open
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
        if (cancelledRef.current) return
        // 4401 = auth failed; don't auto-retry.
        if (event.code === 4401) {
          setError('auth_failed')
          return
        }
        // Exponential backoff: 1s, 2s, 4s, ... capped at 60s.
        const delay = Math.min(MAX_BACKOFF_MS, MIN_BACKOFF_MS * Math.pow(2, attemptsRef.current))
        attemptsRef.current += 1
        retryRef.current = setTimeout(() => {
          if (!cancelledRef.current) connect()
        }, delay)
      }

      ws.onerror = (e) => {
        console.warn('WS error', e)
        try { ws.close() } catch {}
      }
    } catch (err) {
      console.error('WS connect failed', err)
      setError('connect_failed')
    }
  }, [key, sendSubscription])

  useEffect(() => {
    cancelledRef.current = false
    connect()
    return () => {
      cancelledRef.current = true
      if (retryRef.current) clearTimeout(retryRef.current)
      retryRef.current = null
      try { wsRef.current?.close() } catch {}
    }
  }, [connect])

  return { prices, connected, error }
}
