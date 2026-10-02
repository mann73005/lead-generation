/** Session state: who is signed in, and the two actions that change it. */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { ApiError, api, tokens, type User } from './api'

type AuthState = {
  user: User | null
  /** True until the stored token has been checked, so the router does not
   * bounce a signed-in user to the login screen on first paint. */
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tokens.access()) {
      setLoading(false)
      return
    }
    api
      .get<User>('/api/v1/users/me/profile')
      .then(setUser)
      .catch(() => tokens.clear())
      .finally(() => setLoading(false))
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await api.post<{ access_token: string; refresh_token: string }>(
      '/api/v1/auth/login',
      { email, password },
    )
    tokens.set(result.access_token, result.refresh_token)
    setUser(await api.get<User>('/api/v1/users/me/profile'))
  }, [])

  const signOut = useCallback(() => {
    tokens.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    // A 401 that survives the client's refresh-and-retry means the session is
    // genuinely over; clearing it here keeps every page from writing its own
    // logout branch.
    const onRejection = (event: PromiseRejectionEvent) => {
      if (event.reason instanceof ApiError && event.reason.status === 401 && user) {
        signOut()
      }
    }
    window.addEventListener('unhandledrejection', onRejection)
    return () => window.removeEventListener('unhandledrejection', onRejection)
  }, [user, signOut])

  const value = useMemo(
    () => ({ user, loading, signIn, signOut }),
    [user, loading, signIn, signOut],
  )
  return <AuthContext value={value}>{children}</AuthContext>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
