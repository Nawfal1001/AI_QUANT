import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '@/store/auth'

export default function ProtectedRoute({ children }) {
  const { user, booted } = useAuthStore()
  // App.jsx blocks render until booted=true, so this is a belt-and-braces guard.
  if (!booted) return null
  return user ? children : <Navigate to="/auth" replace />
}
