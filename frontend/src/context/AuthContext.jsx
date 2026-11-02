import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import api from '../lib/api'
import * as session from '../lib/session'

const AuthContext = createContext(null)

// How often the guard re-checks idle/absolute expiry while a session is open.
const EXPIRY_CHECK_MS = 30 * 1000
// Throttle activity writes so tracking user input is cheap.
const ACTIVITY_THROTTLE_MS = 15 * 1000

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    // Only trust a still-valid session on load; otherwise force a clean sign-in.
    // This is what prevents an expired token from presenting a "logged-in" shell.
    if (!session.isSessionValid()) {
      session.clearSession()
      return null
    }
    return session.getUser()
  })

  const login = useCallback(async (username, password) => {
    const { data } = await api.post('/auth/login', { username, password })
    session.setSession(data.access_token, data.user, (data.inactivity_seconds || 0) * 1000)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    // Best-effort server-side audit; the client session is cleared regardless
    // so the user is signed out even if the call fails.
    const token = session.getToken()
    if (token) {
      api
        .post('/auth/logout', null, { headers: { Authorization: `Bearer ${token}` } })
        .catch(() => {})
    }
    session.clearSession()
    setUser(null)
  }, [])

  // Track genuine user activity (throttled) so idle time reflects real usage.
  // API polling and background renders deliberately do NOT reset the timer.
  useEffect(() => {
    if (!user) return undefined
    session.touchActivity()
    let lastWrite = 0
    const onActivity = () => {
      const now = Date.now()
      if (now - lastWrite < ACTIVITY_THROTTLE_MS) return
      lastWrite = now
      session.touchActivity()
    }
    const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel']
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }))
    return () => events.forEach((e) => window.removeEventListener(e, onActivity))
  }, [user])

  // Guard: enforce inactivity + absolute expiry. Also re-checked on focus and
  // visibility change because background tabs throttle timers, so a session can
  // otherwise lapse silently while the tab is hidden.
  useEffect(() => {
    if (!user) return undefined
    const enforce = () => {
      if (!session.isSessionValid()) {
        session.clearSession()
        setUser(null)
      }
    }
    const id = window.setInterval(enforce, EXPIRY_CHECK_MS)
    const onVisible = () => {
      if (document.visibilityState === 'visible') enforce()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', enforce)
    return () => {
      window.clearInterval(id)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', enforce)
    }
  }, [user])

  // Single source of truth for signing out when the API reports an expired or
  // invalid token. Clearing state makes RequireAuth redirect to /login via the
  // router — no hard reload, no redirect loop.
  useEffect(() => {
    const onExpired = () => {
      session.clearSession()
      setUser(null)
    }
    window.addEventListener('kalika:session-expired', onExpired)
    return () => window.removeEventListener('kalika:session-expired', onExpired)
  }, [])

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
