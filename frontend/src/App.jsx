import React, { Suspense, lazy, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Toaster } from 'react-hot-toast'
import Layout from '@/components/Layout'
import ProtectedRoute from '@/components/ProtectedRoute'
import ErrorBoundary from '@/components/ErrorBoundary'
import { useAuthStore } from '@/store/auth'
import { Loading } from '@/components/ui'

const AuthPage = lazy(() => import('@/pages/AuthPage'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Portfolio = lazy(() => import('@/pages/Portfolio'))
const Signals = lazy(() => import('@/pages/Signals'))
const StrategyDashboard = lazy(() => import('@/pages/StrategyDashboard'))
const QuantDashboard = lazy(() => import('@/pages/QuantDashboard'))
const AutoTraderLive = lazy(() => import('@/pages/AutoTraderLive'))
const TradeInspector = lazy(() => import('@/pages/TradeInspector'))
const Learning = lazy(() => import('@/pages/Learning'))
const Backtest = lazy(() => import('@/pages/Backtest'))
const Rewards = lazy(() => import('@/pages/Rewards'))
const Brokers = lazy(() => import('@/pages/Brokers'))
const Alerts = lazy(() => import('@/pages/Alerts'))
const Settings = lazy(() => import('@/pages/Settings'))
const Research = lazy(() => import('@/pages/Research'))
const StrategyLab = lazy(() => import('@/pages/StrategyLab'))
const Bots = lazy(() => import('@/pages/Bots'))
const Calendar = lazy(() => import('@/pages/Calendar'))
const Logs = lazy(() => import('@/pages/Logs'))
const Diagnostics = lazy(() => import('@/pages/Diagnostics'))

const PageFallback = () => (
  <div style={{ padding: 24 }}>
    <Loading message="Loading page…" />
  </div>
)

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
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/auth" element={<AuthPage />} />
            <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard"  element={<Dashboard />} />
              <Route path="portfolio"  element={<Portfolio />} />
              <Route path="signals"    element={<Signals />} />
              <Route path="strategy"   element={<StrategyDashboard />} />
              <Route path="quant"      element={<QuantDashboard />} />
              <Route path="autotrader" element={<AutoTraderLive />} />
              <Route path="trade/:source/:tradeId" element={<TradeInspector />} />
              <Route path="learning"   element={<Learning />} />
              <Route path="backtest"   element={<Backtest />} />
              <Route path="rewards"    element={<Rewards />} />
              <Route path="brokers"    element={<Brokers />} />
              <Route path="alerts"     element={<Alerts />} />
              <Route path="settings"   element={<Settings />} />
              <Route path="research"   element={<Research />} />
              <Route path="strategy-lab" element={<StrategyLab />} />
              <Route path="bots"       element={<Bots />} />
              <Route path="calendar"   element={<Calendar />} />
              <Route path="logs"       element={<Logs />} />
              <Route path="diagnostics" element={<Diagnostics />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
