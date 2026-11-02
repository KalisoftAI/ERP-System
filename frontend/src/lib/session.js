// Central session store for Kalika ERP.
//
// The backend authenticates every request with a stateless JWT bearer token
// (Authorization: Bearer <token>). There is no cookie-based session, so the
// browser-side session is held in `sessionStorage` — the web-storage equivalent
// of a session cookie. sessionStorage survives page navigation and refresh but
// is discarded when the browser session ends (browser/window closed), which
// gives the required browser-close behaviour without logging users out on
// refresh or navigation.

const TOKEN_KEY = 'kalika_token'
const USER_KEY = 'kalika_user'
const ACTIVITY_KEY = 'kalika_last_activity'
const INACTIVITY_KEY = 'kalika_inactivity_ms'

// Fallback inactivity window if the server did not supply one. Kept below the
// JWT absolute lifetime (JWT_EXPIRE_MINUTES = 480 in the backend config) so the
// inactivity policy is the primary expiry mechanism.
export const DEFAULT_INACTIVITY_MS = 30 * 60 * 1000 // 30 minutes

// In-memory fallback for private-mode / storage-denied browsers so the app
// still functions for the lifetime of the page.
const memory = {}

function read(key) {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return memory[key] ?? null
  }
}

function write(key, value) {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    memory[key] = value
  }
}

function drop(key) {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    delete memory[key]
  }
}

// One-time cleanup of legacy persistent (localStorage) credentials from the
// previous implementation. They must not revive a session that is intentionally
// session-scoped.
export function clearLegacyStorage() {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
  } catch {
    /* ignore */
  }
}

export function getToken() {
  return read(TOKEN_KEY)
}

export function getUser() {
  const raw = read(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function getInactivityMs() {
  const value = Number(read(INACTIVITY_KEY))
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_INACTIVITY_MS
}

export function getLastActivity() {
  const value = Number(read(ACTIVITY_KEY))
  return Number.isFinite(value) && value > 0 ? value : 0
}

export function touchActivity() {
  const now = Date.now()
  write(ACTIVITY_KEY, String(now))
  return now
}

export function setSession(token, user, inactivityMs) {
  clearLegacyStorage()
  write(TOKEN_KEY, token)
  write(USER_KEY, JSON.stringify(user))
  if (Number.isFinite(inactivityMs) && inactivityMs > 0) {
    write(INACTIVITY_KEY, String(inactivityMs))
  }
  touchActivity()
}

export function clearSession() {
  drop(TOKEN_KEY)
  drop(USER_KEY)
  drop(ACTIVITY_KEY)
  drop(INACTIVITY_KEY)
  clearLegacyStorage()
}

// Decode the (already-issued) JWT payload WITHOUT verification. Used only
// client-side for UX (knowing when the token expires) — the backend still
// verifies the signature and expiry on every request.
export function decodeToken(token) {
  if (!token || typeof token !== 'string') return null
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const binary = atob(padded)
    const json = decodeURIComponent(
      binary.split('').map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''),
    )
    return JSON.parse(json)
  } catch {
    return null
  }
}

// Absolute expiry (epoch ms) from the token's `exp` claim, or null if unknown.
export function getAbsoluteExpiry() {
  const payload = decodeToken(getToken())
  if (!payload || typeof payload.exp !== 'number') return null
  return payload.exp * 1000
}

// Evaluate the current session.
// Returns { valid, reason, expiresAt, idleDeadline }.
export function sessionStatus() {
  const token = getToken()
  if (!token) return { valid: false, reason: 'no-token' }

  const now = Date.now()
  const expiresAt = getAbsoluteExpiry()
  if (expiresAt !== null && now >= expiresAt) {
    return { valid: false, reason: 'expired', expiresAt }
  }

  const last = getLastActivity()
  const idleMs = getInactivityMs()
  if (last && now - last >= idleMs) {
    return { valid: false, reason: 'idle', expiresAt }
  }

  return {
    valid: true,
    reason: 'ok',
    expiresAt,
    idleDeadline: last ? last + idleMs : null,
  }
}

export function isSessionValid() {
  return sessionStatus().valid
}
