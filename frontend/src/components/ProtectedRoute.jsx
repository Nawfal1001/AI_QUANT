import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'
export default function ProtectedRoute({ children }) {
  const { user } = useAuthStore()
  return user ? children : <Navigate to="/auth" replace />
}
