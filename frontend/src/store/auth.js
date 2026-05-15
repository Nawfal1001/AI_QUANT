import { create } from 'zustand'
import axios from 'axios'
const BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api'
const api = axios.create({ baseURL: BASE })
api.interceptors.request.use(cfg => {
  const t = localStorage.getItem('access_token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})
// Single-flight refresh so a burst of 401s only triggers one /auth/refresh call.
let _refreshInFlight = null
async function _doRefresh() {
  if (_refreshInFlight) return _refreshInFlight
  _refreshInFlight = (async () => {
    const refresh = localStorage.getItem('refresh_token')
    if (!refresh) throw new Error('no_refresh_token')
    const res = await axios.post(`${BASE}/auth/refresh`, { refresh_token: refresh })
    const token = res.data.access_token
    localStorage.setItem('access_token', token)
    return token
  })()
  try { return await _refreshInFlight }
  finally { _refreshInFlight = null }
}

api.interceptors.response.use(r => r, async err => {
  const orig = err.config
  if (err.response?.status === 401 && !orig._retry) {
    orig._retry = true
    try {
      const token = await _doRefresh()
      orig.headers.Authorization = `Bearer ${token}`
      return api(orig)
    } catch {
      useAuthStore.getState().logout()
    }
  }
  return Promise.reject(err)
})
export { api }

// Only hydrate the user object from localStorage if we ALSO have an access token —
// otherwise a stale `user` key alone would let ProtectedRoute briefly render
// authenticated pages before validateToken finishes / rejects.
const _hydratedUser = (() => {
  try {
    if (!localStorage.getItem('access_token')) return null
    return JSON.parse(localStorage.getItem('user') || 'null')
  } catch { return null }
})()

export const useAuthStore = create((set) => ({
  user: _hydratedUser,
  loading: false, error: null,
  login: async (email, password) => {
    set({ loading: true, error: null })
    try {
      const res = await api.post('/auth/login', { email, password })
      const { access_token, refresh_token, user } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', refresh_token)
      localStorage.setItem('user', JSON.stringify(user))
      set({ user, loading: false }); return { success: true }
    } catch (e) {
      const msg = e.response?.data?.detail || 'Login failed'
      set({ error: msg, loading: false }); return { success: false, error: msg }
    }
  },
  register: async (email, password, username) => {
    set({ loading: true, error: null })
    try {
      const res = await api.post('/auth/register', { email, password, username })
      const { access_token, refresh_token, user } = res.data
      localStorage.setItem('access_token', access_token)
      localStorage.setItem('refresh_token', refresh_token)
      localStorage.setItem('user', JSON.stringify(user))
      set({ user, loading: false }); return { success: true }
    } catch (e) {
      const msg = e.response?.data?.detail || 'Registration failed'
      set({ error: msg, loading: false }); return { success: false, error: msg }
    }
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    set({ user: null })
  },
  // Validate token on app boot — hits /auth/me. If there's no token (or the
  // server rejects it), clear any stale user state too so ProtectedRoute can't
  // render protected content based on a leftover localStorage.user blob.
  validateToken: async () => {
    const t = localStorage.getItem('access_token')
    if (!t) {
      localStorage.removeItem('user')
      set({ user: null, booting: false, booted: true })
      return false
    }
    set({ booting: true })
    try {
      const res = await api.get('/auth/me')
      const user = res.data
      localStorage.setItem('user', JSON.stringify(user))
      set({ user, booting: false, booted: true })
      return true
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      localStorage.removeItem('user')
      set({ user: null, booting: false, booted: true })
      return false
    }
  },
  booting: false,
  booted: false,
}))
