import { createContext, useContext } from 'react'
import type { StatusResponse } from './api'

export interface AppState {
  status: StatusResponse | null
  loading: boolean
  error: unknown
  reload: () => void
}

export const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function useMode(): 'demo' | 'real' {
  return useApp().status?.mode ?? 'demo'
}
