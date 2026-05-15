import { create } from 'zustand'
import axios from 'axios'
const BASE = import.meta.env.VITE_API_URL ? `${import.meta.env.VITE_API_URL}/api` : '/api'
const api = axios.create({ baseURL: BASE })
api.interceptors.request.use(cfg => {
  const t = localStorage.getItem('access_token')
  if (t) cfg.headers.Authorization = `Bearer ${t}`
  return cfg
})
api.interceptors.response.use(r => r, async err => {
  const orig = err.config
  if (err.response?.status === 401 && !orig._retry) {
    orig._retry = true
    try {
      const refresh = localStorage.getItem('refresh_token')
      if (refresh) {
        const res = await axios.post(`${BASE}/auth/refresh`, { refresh_token: refresh })
        const token = res.data.access_token
        localStorage.setItem('access_token', token)
        orig.headers.Authorization = `Bearer ${token}`
        return api(orig)
      }
    } catch { useAuthStore.getState().logout() }
  }
  return Promise.reject(err)
})
export { api }
export const useAuthStore = create((set) => ({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
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
  // Validate token on app boot — hits /auth/me. If the token is rejected, log out.
  validateToken: async () => {
    const t = localStorage.getItem('access_token')
    if (!t) { set({ booted: true }); return false }
    set({ booting: true })
    try {
      const res = await api.get('/auth/me')
      const user = res.data
      localStorage.setItem('user', JSON.stringify(user))
      set({ user, booting: false, booted: true })
      return true
    } catch (e) {
      // Token invalid or expired
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
