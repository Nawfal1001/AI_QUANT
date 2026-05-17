import React from 'react'
import { PageHeader } from '@/components/ui'
import LiveLogs from '@/components/LiveLogs'

export default function Logs() {
  return <div>
    <PageHeader title="🧾 System Logs" subtitle="Live debug logs for backtests, bots, signals, brokers, market data, AI and trading" />
    <LiveLogs title="All Live Logs" />
  </div>
}
