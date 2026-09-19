import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  LayoutDashboard, Boxes, ShoppingCart, Warehouse, Factory, ShoppingBag,
  Truck, Users, Package, FileDown, ShieldCheck, LogOut, ListChecks,
  AlertTriangle, Store, BellRing, ClipboardList, GitBranch, LayoutGrid,
  ChevronsLeft, ChevronsRight, Menu, X, Layers, ArrowLeftRight, FileSpreadsheet, PackagePlus,
} from 'lucide-react'
import api from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { RoleBadge, initials } from '../lib/format'

const SECTIONS = [
  {
    label: 'Overview',
    items: [{ to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true }],
  },
  {
    label: 'Operations',
    items: [
      { to: '/orders', label: 'Orders', icon: ShoppingBag },
      { to: '/dispatch', label: 'Dispatch', icon: Truck },
      { to: '/production', label: 'Production', icon: Factory },
      { to: '/local-orders', label: 'Local Orders', icon: Store },
      { to: '/pending-po', label: 'Pending PO', icon: ListChecks },
    ],
  },
  {
    label: 'Inventory',
    items: [
      { to: '/raw-materials', label: 'Raw Materials', icon: Boxes },
      { to: '/inventory', label: 'Inventory', icon: Warehouse },
      { to: '/stock-movements', label: 'Stock Movements', icon: ArrowLeftRight },
    ],
  },
  {
    label: 'Procurement',
    items: [
      { to: '/purchases', label: 'Purchases', icon: ShoppingCart },
      { to: '/requirements', label: 'Requirements', icon: AlertTriangle },
      { to: '/material-requirements', label: 'Material Req', icon: ClipboardList },
      { to: '/fulfilment', label: 'Fulfilment', icon: LayoutGrid },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/bom', label: 'BOM / Recipe', icon: GitBranch },
      { to: '/alerts', label: 'Alert Center', icon: BellRing, badge: 'alerts' },
      { to: '/reports', label: 'Reports', icon: FileDown, headerIcon: FileSpreadsheet },
    ],
  },
  {
    label: 'Master Data',
    items: [
      { to: '/customers', label: 'Customers', icon: Users },
      { to: '/suppliers', label: 'Suppliers', icon: Package },
    ],
  },
]

const TITLE_MAP = {
  '/': { title: 'Dashboard', sub: 'Business overview' },
  '/orders': { title: 'Orders', sub: 'Sales orders & pipeline' },
  '/dispatch': { title: 'Dispatch', sub: 'Customer-wise dispatch tracking' },
  '/production': { title: 'Production', sub: 'Schedule, actual output & reports' },
  '/local-orders': { title: 'Local Orders', sub: 'Local orders & plans' },
  '/pending-po': { title: 'Pending PO', sub: 'Order fulfilment ledger' },
  '/raw-materials': { title: 'Raw Materials', sub: 'Polymer position & balances' },
  '/inventory': { title: 'Inventory', sub: 'Stock levels & status' },
  '/stock-movements': { title: 'Stock Movements', sub: 'Every stock transaction' },
  '/purchases': { title: 'Purchases', sub: 'Purchase orders' },
  '/requirements': { title: 'Requirements', sub: 'Requirement decisions' },
  '/material-requirements': { title: 'Material Requirements', sub: 'BOM-driven shortages' },
  '/fulfilment': { title: 'Fulfilment', sub: 'Stock → decision per line' },
  '/bom': { title: 'BOM / Recipe', sub: 'Bill of materials' },
  '/alerts': { title: 'Alert Center', sub: 'System notifications' },
  '/customers': { title: 'Customers', sub: 'Customer master' },
  '/suppliers': { title: 'Suppliers', sub: 'Supplier master' },
  '/reports': { title: 'Reports', sub: 'Business summaries & exports' },
  '/users': { title: 'Users', sub: 'User administration' },
}

export default function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(() => window.innerWidth >= 1024 && false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [unreadAlerts, setUnreadAlerts] = useState(0)
  const [period, setPeriod] = useState(null)

  useEffect(() => {
    const fetchMeta = () => {
      api.get('/alerts/count').then((r) => setUnreadAlerts(r.data.unread || 0)).catch(() => {})
    }
    const fetchPeriod = () => {
      api.get('/dashboard/summary').then((r) => setPeriod(r.data.report_date || null)).catch(() => {})
    }
    fetchMeta(); fetchPeriod()
    const t = setInterval(fetchMeta, 30000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  const headerMeta = TITLE_MAP[location.pathname] || TITLE_MAP['/']

  const onLogout = () => {
    logout(); navigate('/login')
  }

  const handleCollapse = () => {
    setCollapsed((c) => !c)
  }

  const navContent = () => (
    <nav className="flex-1 overflow-y-auto py-3 px-3">
      {SECTIONS.map((sec) => (
        <div key={sec.label} className="mb-2">
          <div className={`sidebar-group-label ${collapsed ? 'sr-only' : ''}`}>{sec.label}</div>
          {sec.items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
            >
              <span className="icon-holder"><item.icon size={17} /></span>
              <span className={collapsed ? 'sr-only' : 'flex-1 text-left truncate'}>{item.label}</span>
              {item.to === '/alerts' && !collapsed && unreadAlerts > 0 && (
                <span className="ml-auto bg-red-500 text-white text-[10px] font-bold rounded-full h-4 min-w-4 px-1 flex items-center justify-center">{unreadAlerts}</span>
              )}
              {item.to === '/alerts' && collapsed && unreadAlerts > 0 && (
                <span className="absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-red-500" />
              )}
            </NavLink>
          ))}
        </div>
      ))}
      {user?.role === 'admin' && (
        <div className="mt-2">
          <div className={`sidebar-group-label ${collapsed ? 'sr-only' : ''}`}>Administration</div>
          <NavLink to="/users" title={collapsed ? 'Users' : undefined}
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
            <span className="icon-holder"><ShieldCheck size={17} /></span>
            <span className={collapsed ? 'sr-only' : 'flex-1 text-left truncate'}>Users</span>
          </NavLink>
        </div>
      )}
    </nav>
  )

  return (
    <div className="flex min-h-screen bg-[#f6f7f9]">
      {/* Desktop sidebar */}
      <aside
        className={`hidden lg:flex flex-col fixed inset-y-0 left-0 z-30 bg-slate-900 text-slate-300 transition-all duration-300 ${
          collapsed ? 'w-[68px]' : 'w-64'
        }`}
      >
        {/* Brand */}
        <div className={`flex items-center gap-3 px-4 py-5 border-b border-slate-800 ${collapsed ? 'justify-center px-2' : ''}`}>
          {collapsed ? (
            <div className="h-9 w-9 rounded-lg brand-gradient flex items-center justify-center shrink-0 shadow-md">
              <Factory2Icon />
            </div>
          ) : (
            <>
              <div className="h-10 w-10 rounded-xl brand-gradient flex items-center justify-center shrink-0 shadow-lg">
                <Factory2Icon />
              </div>
              <div className="min-w-0">
                <div className="text-white font-bold text-[0.9375rem] leading-tight tracking-tight">Kalika ERP</div>
                <div className="text-[0.625rem] text-slate-400 truncate">Enterprise Resource Mgmt</div>
              </div>
            </>
          )}
        </div>

        {navContent()}

        {/* Collapse toggle + user */}
        <div className="border-t border-slate-800 px-3 py-3">
          {!collapsed && (
            <div className="flex items-center gap-3 px-2 mb-3">
              <div className="h-9 w-9 rounded-full bg-slate-700 flex items-center justify-center text-white text-xs font-bold shrink-0">
                {initials(user?.full_name || user?.username)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-white font-medium truncate">{user?.full_name || user?.username}</div>
                <RoleBadge role={user?.role} />
              </div>
              <button onClick={onLogout} title="Logout" className="text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg p-1.5">
                <LogOut size={16} />
              </button>
            </div>
          )}
          <button onClick={handleCollapse} title={collapsed ? 'Expand' : 'Collapse'}
            className="w-full flex items-center justify-center gap-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg py-2 text-xs transition">
            {collapsed ? <ChevronsRight size={16} /> : <><ChevronsLeft size={16} /> Collapse</>}
          </button>
        </div>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-slate-900 text-slate-300 flex flex-col shadow-2xl animate-slide-in-right">
            <div className="flex items-center justify-between px-4 py-5 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl brand-gradient flex items-center justify-center shrink-0 shadow-lg"><Factory2Icon /></div>
                <div>
                  <div className="text-white font-bold text-[0.9375rem] leading-tight">Kalika ERP</div>
                  <div className="text-[0.625rem] text-slate-400">Enterprise Resource Mgmt</div>
                </div>
              </div>
              <button onClick={() => setMobileOpen(false)} className="text-slate-400 hover:text-white p-2" aria-label="Close menu">
                <X size={20} />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto py-3 px-3">
              {SECTIONS.map((sec) => (
                <div key={sec.label} className="mb-1">
                  <div className="sidebar-group-label">{sec.label}</div>
                  {sec.items.map((item) => (
                    <NavLink key={item.to} to={item.to} end={item.end}
                      className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
                      <span className="icon-holder"><item.icon size={17} /></span>
                      <span className="flex-1 text-left truncate">{item.label}</span>
                      {item.to === '/alerts' && unreadAlerts > 0 && (
                        <span className="bg-red-500 text-white text-[10px] font-bold rounded-full h-4 min-w-4 px-1 flex items-center justify-center">{unreadAlerts}</span>
                      )}
                    </NavLink>
                  ))}
                </div>
              ))}
              {user?.role === 'admin' && (
                <div className="mt-1">
                  <div className="sidebar-group-label">Administration</div>
                  <NavLink to="/users" className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}>
                    <span className="icon-holder"><ShieldCheck size={17} /></span>
                    <span className="flex-1 text-left truncate">Users</span>
                  </NavLink>
                </div>
              )}
            </nav>
            <div className="border-t border-slate-800 px-4 py-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-slate-700 flex items-center justify-center text-white text-sm font-bold shrink-0">
                  {initials(user?.full_name || user?.username)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm text-white font-medium truncate">{user?.full_name || user?.username}</div>
                  <RoleBadge role={user?.role} />
                </div>
                <button onClick={onLogout} title="Logout" className="text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg p-2"><LogOut size={18} /></button>
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* Main column with header */}
      <div className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${collapsed ? 'lg:ml-[68px]' : 'lg:ml-64'}`}>
        {/* Top header */}
        <header className="sticky top-0 z-20 bg-white/85 backdrop-blur border-b border-gray-200 px-4 sm:px-6 py-3 flex items-center gap-3">
          <button onClick={() => setMobileOpen(true)} className="lg:hidden text-slate-600 hover:bg-gray-100 rounded-lg p-2" aria-label="Open menu">
            <Menu size={20} />
          </button>
          <div className="min-w-0">
            <h1 className="font-bold text-slate-900 text-[1.05rem] truncate leading-tight">{headerMeta.title}</h1>
            {headerMeta.sub && <p className="text-[0.6875rem] text-slate-400 truncate">{headerMeta.sub}</p>}
          </div>
          <div className="ml-auto flex items-center gap-2">
            {period && (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[0.6875rem] font-medium text-slate-500 border border-gray-200 rounded-full px-3 py-1.5 bg-white">
                <span className="badge-dot bg-amber-500" />
                Period: {period}
              </span>
            )}
            <NavLink to="/alerts" className="relative text-slate-500 hover:bg-gray-100 rounded-lg p-2" title="Alerts">
              <BellRing size={18} />
              {unreadAlerts > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-red-500 text-white text-[9px] font-bold rounded-full h-4 min-w-4 px-1 flex items-center justify-center">{unreadAlerts}</span>
              )}
            </NavLink>
            <div className="hidden md:flex items-center gap-2 pl-2 border-l border-gray-200">
              <div className="h-8 w-8 rounded-full bg-slate-800 flex items-center justify-center text-white text-[0.6875rem] font-bold">
                {initials(user?.full_name || user?.username)}
              </div>
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 sm:p-6 animate-fade-in-up">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

function Factory2Icon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="text-slate-900">
      <path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z" />
      <path d="M17 18h1" /><path d="M12 18h1" /><path d="M7 18h1" />
    </svg>
  )
}