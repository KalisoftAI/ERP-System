import axios from 'axios'
import * as session from './session'

// Dev: Vite proxy forwards /api -> backend (strips prefix).
// Prod (Cloud Run): FastAPI serves frontend + backend from same origin, no /api prefix.
const api = axios.create({
  baseURL: import.meta.env.PROD ? '/' : '/api',
})

api.interceptors.request.use((config) => {
  const token = session.getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // Prevent the browser from serving a stale HTML fallback response for API
  // GET requests (e.g. /quotations) that was cached before the backend route
  // existed. FastAPI ignores the extra query parameter.
  if (config.method?.toLowerCase() === 'get') {
    config.params = { ...config.params, _t: Date.now() }
  }
  return config
})

// Notify the app exactly once per expiry so the auth context can sign out and
// the router can redirect — no hard reloads and no repeated redirect loops.
let expiredNotified = false

api.interceptors.response.use(
  (res) => {
    expiredNotified = false
    return res
  },
  (err) => {
    const status = err.response?.status
    const url = err.config?.url || ''
    // A 401 from /auth/login is a credential error handled by the login form,
    // not an expired session.
    if (status === 401 && !url.includes('/auth/login')) {
      session.clearSession()
      if (!expiredNotified) {
        expiredNotified = true
        window.dispatchEvent(new Event('kalika:session-expired'))
      }
    }
    return Promise.reject(err)
  },
)

export async function downloadFile(url, fallbackName = 'download') {
  try {
    const res = await api.get(url, { responseType: 'blob' })
    const cd = res.headers?.['content-disposition'] || ''
    const m = cd.match(/filename=(.+)/)
    const filename = m ? m[1].replace(/["']/g, '').trim() : fallbackName
    const blobUrl = window.URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(blobUrl)
  } catch (err) {
    if (!err.response || err.response.status !== 401) {
      alert(err.response?.data?.detail || 'Download failed')
    }
  }
}

export default api