import { create } from 'zustand'
export const useStore = create(set => ({
  tradingMode: 'paper',
  setTradingMode: mode => set({ tradingMode: mode }),
  notifications: [],
  addNotification: n => set(s => ({ notifications: [n, ...s.notifications].slice(0, 50) })),
}))
