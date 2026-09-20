import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Lock, User, ShieldCheck, Boxes, Truck, ChartBar, Eye, EyeOff } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  const features = [
    { icon: <Boxes size={16} />, t: 'Inventory & Stock', d: 'Live stock across locations' },
    { icon: <Truck size={16} />, t: 'Dispatch Tracking', d: 'Order-wise fulfilment' },
    { icon: <ChartBar size={16} />, t: 'Management Reports', d: 'Business-ready summaries' },
  ]

  const inputBase = 'input input-icon input-icon-right'
  const toggleBtn = 'absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700 p-1'

  return (
    <div className="relative min-h-screen flex items-center justify-center bg-slate-950 p-4 overflow-hidden">
      {/* Background decoration */}
      <div className="absolute -top-24 -left-24 h-72 w-72 rounded-full bg-amber-500/20 blur-3xl" />
      <div className="absolute -bottom-24 -right-24 h-72 w-72 rounded-full bg-amber-700/20 blur-3xl" />

      <div className="relative w-full max-w-4xl grid md:grid-cols-2 rounded-2xl overflow-hidden shadow-2xl">
        {/* Brand panel */}
        <div className="hidden md:flex flex-col justify-between bg-gradient-to-br from-amber-500 via-amber-600 to-amber-700 p-10 text-white">
          <div className="flex items-center gap-3">
            <div className="h-12 rounded-xl bg-white px-3 flex items-center justify-center shadow">
              <img src="/kalika-logo.jpeg" alt="Kalika Enterprises" className="h-7 w-auto" />
            </div>
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight">Kalika ERP</h1>
              <p className="text-xs text-amber-100">Enterprise Resource Management</p>
            </div>
          </div>
          <div className="space-y-5">
            <h2 className="text-2xl font-bold leading-snug">Manage orders, stock and dispatches in one place.</h2>
            <div className="space-y-3">
              {features.map((f) => (
                <div key={f.t} className="flex items-start gap-3 bg-white/10 rounded-xl p-3">
                  <span className="mt-0.5">{f.icon}</span>
                  <div>
                    <div className="text-sm font-semibold">{f.t}</div>
                    <div className="text-xs text-amber-100">{f.d}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs text-amber-100/80">© {new Date().getFullYear()} Kalika Industries</p>
        </div>

        {/* Form panel */}
        <div className="bg-white p-8 sm:p-10">
          <div className="md:hidden flex items-center gap-3 mb-6">
            <div className="h-11 rounded-lg bg-white border border-slate-200 px-2.5 flex items-center justify-center">
              <img src="/kalika-logo.jpeg" alt="Kalika Enterprises" className="h-6 w-auto" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900">Kalika ERP</h1>
              <p className="text-xs text-slate-500">Enterprise Resource Management</p>
            </div>
          </div>

          <div className="mb-6">
            <h2 className="text-xl font-bold text-slate-900">Sign in</h2>
            <p className="text-sm text-slate-500 mt-1">Welcome back — enter your credentials</p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Username</label>
              <div className="relative">
                <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                <input
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="input input-icon"
                  required
                />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
              <div className="relative">
                <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                <input
                  type={showPw ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={inputBase}
                  required
                />
                <button type="button" onClick={() => setShowPw((v) => !v)} className={toggleBtn} tabIndex={-1} aria-label={showPw ? 'Hide password' : 'Show password'}>
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>
            {error && <div className="text-sm state-box bg-red-50 text-red-700 border border-red-200">{error}</div>}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 inline-flex items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-amber-500 to-amber-600 text-white font-semibold text-sm hover:from-amber-600 hover:to-amber-700 shadow-md hover:shadow-amber-500/40 transition disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <ShieldCheck size={16} className="transition-transform group-hover:scale-110" />
              {loading ? (
                <span className="inline-flex items-center gap-1.5"><span className="h-3.5 w-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />Signing in…</span>
              ) : 'Sign in'}
            </button>
            <p className="text-center text-xs text-slate-400">Kalika Industries · ERP</p>
          </form>
        </div>
      </div>
    </div>
  )
}