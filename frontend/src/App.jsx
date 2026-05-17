import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Layout from '@/components/Layout'
import ProtectedRoute from '@/components/ProtectedRoute'
import ErrorBoundary from '@/components/ErrorBoundary'
import { useAuthStore } from '@/store/auth'
import { Loading } from '@/components/ui'
import AuthPage from '@/pages/AuthPage'
import Dashboard from '@/pages/Dashboard'
import Portfolio from '@/pages/Portfolio'
import Signals from '@/pages/Signals'
import StrategyDashboard from '@/pages/StrategyDashboard'
import QuantDashboard from '@/pages/QuantDashboard'
import AutoTrader from '@/pages/AutoTrader'
import Learning from '@/pages/Learning'
import Backtest from '@/pages/Backtest'
import Rewards from '@/pages/Rewards'
import Brokers from '@/pages/Brokers'
import Alerts from '@/pages/Alerts'
import Settings from '@/pages/Settings'
import Research from '@/pages/Research'
import StrategyLab from '@/pages/StrategyLab'
import Bots from '@/pages/Bots'
import Logs from '@/pages/Logs'

export default function App() {
  const { validateToken, booting, booted } = useAuthStore()

  useEffect(() => {
    validateToken()
  }, [])

  if (booting || !booted) {
    return (
      <div style={{ background: '#0d1117', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Loading message="Loading TradeAI…" />
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Toaster position="top-right" toastOptions={{ style: { background: '#161b22', color: '#e2e8f0', border: '1px solid #21262d' } }} />
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="portfolio" element={<Portfolio />} />
            <Route path="signals" element={<Signals />} />
            <Route path="strategy" element={<StrategyDashboard />} />
            <Route path="quant" element={<QuantDashboard />} />
            <Route path="autotrader" element={<AutoTrader />} />
            <Route path="learning" element={<Learning />} />
            <Route path="backtest" element={<Backtest />} />
            <Route path="rewards" element={<Rewards />} />
            <Route path="brokers" element={<Brokers />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="settings" element={<Settings />} />
            <Route path="research" element={<Research />} />
            <Route path="strategy-lab" element={<StrategyLab />} />
            <Route path="bots" element={<Bots />} />
            <Route path="logs" element={<Logs />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
