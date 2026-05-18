import React from 'react'
import AutoTrader from './AutoTrader'
import AutoTraderLiveOpenTrades from '@/components/AutoTraderLiveOpenTrades'

export default function AutoTraderLive(){
  return <div><AutoTrader/><div style={{marginTop:16}}><AutoTraderLiveOpenTrades/></div></div>
}
