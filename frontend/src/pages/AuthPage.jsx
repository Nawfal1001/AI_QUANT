import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'
import { TrendingUp } from 'lucide-react'
import toast from 'react-hot-toast'

const inp = { background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: '10px 12px', color: '#e2e8f0', fontSize: 14, width: '100%', outline: 'none', marginBottom: 12, transition: '0.15s' }

export default function AuthPage() {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('')
  const { login, register, loading, error } = useAuthStore()
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    let result
    if (mode === 'login') result = await login(email, password)
    else {
      if (!username) { toast.error('Username required'); return }
      result = await register(email, password, username)
    }
    if (result.success) { toast.success(mode === 'login' ? '👋 Welcome back!' : '🎉 Account created!'); navigate('/dashboard') }
    else toast.error(result.error)
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0d1117', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'Inter,sans-serif' }}>
      <div style={{ width: 380, padding: 36, background: '#161b22', border: '1px solid #21262d', borderRadius: 16, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'center', marginBottom: 6 }}>
            <TrendingUp size={24} color="#3fb950" />
            <span style={{ fontWeight: 700, fontSize: 22, color: '#e2e8f0' }}>trade<span style={{ color: '#3fb950' }}>AI</span></span>
          </div>
          <div style={{ fontSize: 12, color: '#8b949e' }}>AI-powered trading platform</div>
        </div>

        <div style={{ display: 'flex', background: '#0d1117', borderRadius: 8, padding: 3, gap: 3, marginBottom: 24 }}>
          {[['login', 'Sign In'], ['register', 'Register']].map(([m, label]) => (
            <button key={m} onClick={() => setMode(m)}
              style={{ flex: 1, padding: '7px 0', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 500, background: mode === m ? '#1f6feb' : 'transparent', color: mode === m ? '#fff' : '#8b949e', transition: '0.15s' }}>
              {label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          {mode === 'register' && <input type="text" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} style={inp} />}
          <input type="email" placeholder="Email address" value={email} onChange={e => setEmail(e.target.value)} style={inp} required />
          <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} style={{ ...inp, marginBottom: error ? 8 : 18 }} required />
          {error && <div style={{ fontSize: 12, color: '#f85149', marginBottom: 12, textAlign: 'center' }}>{error}</div>}
          <button type="submit" disabled={loading}
            style={{ width: '100%', padding: 12, borderRadius: 8, border: 'none', background: loading ? '#21262d' : '#1f6feb', color: loading ? '#8b949e' : '#fff', fontSize: 14, fontWeight: 600, cursor: loading ? 'not-allowed' : 'pointer', transition: '0.15s' }}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>
        <div style={{ marginTop: 14, fontSize: 12, color: '#8b949e', textAlign: 'center' }}>
          {mode === 'login'
            ? <>No account? <button onClick={() => setMode('register')} style={{ background: 'none', border: 'none', color: '#1f6feb', cursor: 'pointer', fontSize: 12 }}>Register free</button></>
            : <>Have account? <button onClick={() => setMode('login')} style={{ background: 'none', border: 'none', color: '#1f6feb', cursor: 'pointer', fontSize: 12 }}>Sign in</button></>}
        </div>
      </div>
    </div>
  )
}
