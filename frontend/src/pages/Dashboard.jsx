import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ShoppingBag, Truck, Factory, Boxes, AlertTriangle, TrendingUp, ArrowRight,
  BellRing, PackageX, TimerReset,
} from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import api from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Card, StatCard, Loading, LoadingSkeleton } from '../components/ui'
import { fmtNum, FlowBadge } from '../lib/format'

const TREND_COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#06b6d4']

function TrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold text-slate-700 mb-1">{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full" style={{ background: p.color || p.fill }} />
          <span className="text-slate-500">{p.name}:</span>
          <span className="font-medium text-slate-700">{fmtNum(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

function DonutTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold text-slate-700">{p.name}</div>
      <div className="text-slate-500">count: <span className="font-medium text-slate-700">{fmtNum(p.value)}</span></div>
    </div>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null)
  const [byPlant, setByPlant] = useState([])
  const [byProduct, setByProduct] = useState([])
  const [pipeline, setPipeline] = useState([])
  const [invStatus, setInvStatus] = useState([])
  const [trends, setTrends] = useState([])
  const [lowStock, setLowStock] = useState([])
  const [alerts, setAlerts] = useState({ unread: 0, total_open: 0, critical_unread: 0 })
  const [rmShortage, setRmShortage] = useState([])
  const [loading, setLoading] = useState(true)
  const { user } = useAuth()
  const [kaliflowEnabled, setKaliflowEnabled] = useState(false)
  const [kaliflowSrc, setKaliflowSrc] = useState('')
  const [kaliflowBusy, setKaliflowBusy] = useState(false)

  useEffect(() => {
    Promise.all([
      api.get('/dashboard/summary'),
      api.get('/dashboard/dispatch-by-plant'),
      api.get('/dashboard/production-by-product'),
      api.get('/dashboard/order-pipeline'),
      api.get('/dashboard/inventory-status'),
      api.get('/dashboard/daily-trends'),
      api.get('/dashboard/low-stock-list'),
      api.get('/alerts/count'),
      api.get('/material-requirements/rm-shortage'),
    ])
      .then(([s, bp, bpr, op, iv, tr, ls, al, rms]) => {
        setSummary(s.data)
        setByPlant(bp.data.items || [])
        setByProduct((bpr.data.items || []).slice(0, 10))
        setPipeline(op.data.items || [])
        setInvStatus(iv.data.items || [])
        setTrends((tr.data.items || []).slice(-30))
        setLowStock(ls.data.items || [])
        setAlerts(al.data || { unread: 0, total_open: 0, critical_unread: 0 })
        setRmShortage(Array.isArray(rms.data) ? rms.data : [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    api.get('/kaliflow/toggle')
      .then((res) => setKaliflowEnabled(Boolean(res.data.enabled)))
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!kaliflowEnabled) {
      setKaliflowSrc('')
      return undefined
    }
    let cancelled = false
    let objectUrl = ''
    api.get('/kaliflow/dashboard', { responseType: 'text' })
      .then((res) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(new Blob([res.data], { type: 'text/html' }))
        setKaliflowSrc(objectUrl)
      })
      .catch(() => {
        if (!cancelled) setKaliflowSrc('')
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [kaliflowEnabled])

  const toggleKaliflow = async () => {
    setKaliflowBusy(true)
    try {
      const { data } = await api.patch('/kaliflow/toggle', { enabled: !kaliflowEnabled })
      setKaliflowEnabled(Boolean(data.enabled))
    } catch {
      return
    } finally {
      setKaliflowBusy(false)
    }
  }

  if (loading && !summary) return (
    <div>
      <h2 className="page-title mb-1">Dashboard</h2>
      <p className="page-subtitle mb-6">Loading overview…</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }).map((_, i) => <div key={i} className="card p-5"><div className="skeleton h-3 w-24 mb-4" /><div className="skeleton h-8 w-32" /></div>)}
      </div>
      <Card><div className="h-64"><LoadingSkeleton rows={6} /></div></Card>
    </div>
  )
  if (!summary) return <Loading />

  return (
    <div className="animate-fade-in-up">
      <h2 className="page-title mb-1">Dashboard</h2>
      <p className="page-subtitle mb-6">Overview for <span className="font-semibold text-slate-700">{summary.report_date}</span></p>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4 mb-6">
        <StatCard label="Total Orders" value={fmtNum(summary.total_orders)} sub={`${fmtNum(summary.completed_orders)} completed`} icon={ShoppingBag} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Pending Orders" value={fmtNum(summary.pending_orders)} sub="not yet completed" icon={TimerReset} iconClass="bg-orange-50 text-orange-600" />
        <StatCard label="Dispatch" value={fmtNum(summary.dispatch_done)} sub={`of ${fmtNum(summary.dispatch_scheduled)} scheduled`} icon={Truck} iconClass="bg-cyan-50 text-cyan-600" />
        <StatCard label="Production Output" value={fmtNum(summary.production_produced_qty)} sub={`${fmtNum(summary.production_pending_qty)} pending`} icon={Factory} iconClass="bg-violet-50 text-violet-600" />
      </div>

      {/* Secondary KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 sm:gap-4 mb-6">
        <StatCard label="Raw Material Stock" value={fmtNum(summary.raw_material_stock)} sub={`${summary.raw_material_count} materials`} icon={Boxes} iconClass="bg-blue-50 text-blue-600" />
        <StatCard
          label="Open Alerts"
          value={alerts.total_open}
          sub={`${alerts.unread} unread · ${alerts.critical_unread} critical`}
          icon={BellRing}
          iconClass={alerts.total_open > 0 ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'}
          valueClass={alerts.total_open > 0 ? 'text-red-600' : ''}
        />
        <StatCard label="RM Shortages" value={rmShortage.length} sub="BOM-driven materials short" icon={PackageX} iconClass={rmShortage.length > 0 ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'} valueClass={rmShortage.length > 0 ? 'text-red-600' : ''} />
        <StatCard
          label="Stock Alerts"
          value={lowStock.length}
          sub="items below min level"
          icon={AlertTriangle}
          iconClass={lowStock.length > 0 ? 'bg-amber-50 text-amber-600' : 'bg-green-50 text-green-600'}
          valueClass={lowStock.length > 0 ? 'text-amber-600' : 'text-green-600'}
        />
      </div>

      {/* Trends row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card title="Production Trend" subtitle="Daily production output (last 30 days)">
          {trends.length === 0 ? <div className="h-56 flex items-center justify-center text-sm text-slate-400">No trend data</div> : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={trends} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="gProd" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.5} />
                    <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} width={50} />
                <Tooltip content={<TrendTooltip />} />
                <Area type="monotone" dataKey="production" stroke="#8b5cf6" strokeWidth={2.5} fill="url(#gProd)" name="Production" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Dispatch Trend" subtitle="Daily dispatch output (last 30 days)">
          {trends.length === 0 ? <div className="h-56 flex items-center justify-center text-sm text-slate-400">No trend data</div> : (
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart data={trends} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="gDisp" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.5} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} width={50} />
                <Tooltip content={<TrendTooltip />} />
                <Area type="monotone" dataKey="dispatch" stroke="#06b6d4" strokeWidth={2.5} fill="url(#gDisp)" name="Dispatch" />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* Pipeline + inventory donut */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card title="Orders Pipeline" subtitle="By status">
          {pipeline.length === 0 ? <div className="h-56 flex items-center justify-center text-sm text-slate-400">No pipeline data</div> : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={pipeline} dataKey="count" nameKey="status" cx="50%" cy="50%" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="#fff">
                  {pipeline.map((_, i) => <Cell key={i} fill={TREND_COLORS[i % TREND_COLORS.length]} />)}
                </Pie>
                <Tooltip content={<DonutTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card title="Inventory Status" subtitle="Stock levels">
          {invStatus.length === 0 ? <div className="h-56 flex items-center justify-center text-sm text-slate-400">No inventory data</div> : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={invStatus} dataKey="count" nameKey="status" cx="50%" cy="50%" innerRadius={52} outerRadius={78} paddingAngle={2} stroke="#fff">
                  {invStatus.map((_, i) => <Cell key={i} fill={['#10b981', '#f59e0b', '#ef4444'][i % 3]} />)}
                </Pie>
                <Tooltip content={<DonutTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </Card>

        <Card
          title="Dispatch by Plant"
          subtitle="Scheduled vs dispatched"
        >
          {byPlant.length === 0 ? <div className="h-56 flex items-center justify-center text-sm text-slate-400">No plant data</div> : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={byPlant.slice(0, 8)} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
                <XAxis dataKey="plant" tick={{ fontSize: 10, fill: '#94a3b8' }} tickLine={false} axisLine={false} interval={0} angle={-22} textAnchor="end" height={46} />
                <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} tickLine={false} axisLine={false} width={50} />
                <Tooltip content={<TrendTooltip />} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="scheduled" fill="#cbd5e1" name="Scheduled" radius={[3, 3, 0, 0]} />
                <Bar dataKey="dispatched" fill="#f59e0b" name="Dispatched" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>

      {/* Lower row: production by product + low stock + alerts/shortages */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card title="Production by Product" subtitle="Top finished goods" className="lg:col-span-2"
          actions={<Link to="/production" className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1">View all <ArrowRight size={14} /></Link>}>
          {byProduct.length === 0 ? <div className="text-sm text-slate-400 py-10 text-center">No production data</div> : (
            <div className="space-y-3">
              {byProduct.slice(0, 8).map((p) => {
                const pct = p.planned > 0 ? Math.min(100, (p.produced / p.planned) * 100) : 0
                return (
                  <div key={p.product} className="flex items-center gap-3" title={p.product}>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-700 truncate">{p.product}</div>
                      <div className="h-2 bg-slate-100 rounded-full mt-1 overflow-hidden">
                        <div className={`h-full rounded-full ${pct >= 100 ? 'bg-green-500' : 'bg-amber-400'}`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                    <div className="text-sm font-semibold text-slate-600 shrink-0">{fmtNum(p.produced)}</div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>

        <Card title="Stock Alerts" subtitle="Items below minimum level"
          actions={<Link to="/inventory" className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1">Inventory <ArrowRight size={14} /></Link>}>
          {lowStock.length === 0 ? (
            <div className="flex flex-col items-center justify-center text-sm text-slate-400 py-10 gap-2">
              <TrendingUp size={22} className="text-green-400" /> All stock levels are healthy
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {lowStock.slice(0, 10).map((item) => (
                <div key={`${item.product}-${item.plant}`} className="flex items-center justify-between px-3 py-2 rounded-lg bg-red-50 border border-red-100" title={item.product}>
                  <div className="flex items-center gap-2 min-w-0">
                    <AlertTriangle size={15} className="text-red-500 shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-700 truncate">{item.product}</div>
                      <div className="text-xs text-slate-400 truncate">{item.plant}</div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-semibold text-red-600">{fmtNum(item.current_stock)}</div>
                    <div className="text-xs text-slate-400">min {fmtNum(item.min_level)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* alerts + shortages */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card title="Raw Material Shortages" subtitle="Required less available via BOM engine"
          actions={<Link to="/material-requirements" className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1">Material Req <ArrowRight size={14} /></Link>}>
          {rmShortage.length === 0 ? (
            <div className="flex flex-col items-center justify-center text-sm text-slate-400 py-10 gap-2">
              <TrendingUp size={22} className="text-green-400" /> No material shortages
            </div>
          ) : (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {rmShortage.slice(0, 10).map((it, i) => (
                <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-amber-50 border border-amber-100" title={`Required ${it.required_quantity}, available ${it.available_quantity}`}>
                  <div className="flex items-center gap-2 min-w-0">
                    <PackageX size={15} className="text-amber-500 shrink-0" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-slate-700 truncate">{it.raw_material_name}</div>
                      <div className="text-xs text-slate-400 truncate">{it.uom || ''} · {(it.products || []).join(', ').slice(0, 36)}</div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-semibold text-red-600">{fmtNum(it.shortage_quantity)}</div>
                    <div className="text-xs text-slate-400">short</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Open Alerts" subtitle="Unresolved system notifications"
          actions={<Link to="/alerts" className="text-xs text-amber-600 hover:text-amber-700 flex items-center gap-1">Alert Center <ArrowRight size={14} /></Link>}>
          {alerts.total_open === 0 ? (
            <div className="flex flex-col items-center justify-center text-sm text-slate-400 py-10 gap-2">
              <BellRing size={22} className="text-green-400" /> All clear
            </div>
          ) : (
            <div className="space-y-2">
              {[
                { k: 'Total open alerts', v: alerts.total_open, cls: 'bg-purple-50 border-purple-100 text-purple-700', vc: 'text-purple-700' },
                { k: 'Unread', v: alerts.unread, cls: 'bg-slate-50 border-slate-100 text-slate-700', vc: 'text-slate-800' },
                { k: 'Critical unread', v: alerts.critical_unread, cls: 'bg-red-50 border-red-100 text-red-600', vc: 'text-red-600' },
              ].map((r) => (
                <div key={r.k} className={`flex items-center justify-between px-3 py-2 rounded-lg border ${r.cls}`}>
                  <span className="text-sm">{r.k}</span>
                  <span className={`text-sm font-semibold ${r.vc}`}>{r.v}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {(kaliflowEnabled || user?.role === 'admin') && (
        <section className="mt-6" aria-label="Kaliflow 3D plant view">
          <Card
            title="Kaliflow Plant View"
            subtitle="Interactive 3D stretch-film plant demo"
            actions={user?.role === 'admin' ? (
              <button
                type="button"
                onClick={toggleKaliflow}
                disabled={kaliflowBusy}
                className="text-xs text-amber-600 hover:text-amber-700 disabled:opacity-50 flex items-center gap-1"
              >
                {kaliflowEnabled ? 'Disable' : 'Enable'} <ArrowRight size={14} />
              </button>
            ) : undefined}
          >
            {!kaliflowEnabled ? (
              <div className="py-10 text-center text-sm text-slate-400">Kaliflow view is disabled.</div>
            ) : kaliflowSrc ? (
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
                <iframe
                  src={kaliflowSrc}
                  title="Kaliflow 3D manufacturing dashboard"
                  className="h-[70vh] w-full border-0"
                  allow="fullscreen"
                />
              </div>
            ) : (
              <div className="py-10 text-center text-sm text-slate-400">Loading Kaliflow view…</div>
            )}
          </Card>
        </section>
      )}
    </div>
  )
}
