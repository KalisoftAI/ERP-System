import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X, AlertCircle, SearchX } from 'lucide-react'

export function Card({ title, subtitle, actions, children, className = '', bodyClass = '' }) {
  return (
    <div className={`card ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <div>
            <h3 className="font-semibold text-slate-800">{title}</h3>
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
        </div>
      )}
      <div className={`p-5 ${bodyClass}`}>{children}</div>
    </div>
  )
}

export function KpiCard({ label, value, sub, icon: Icon, color = 'text-slate-900' }) {
  return (
    <div className="card card-hover px-5 py-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[0.6875rem] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
          <div className={`text-2xl font-bold mt-2 tracking-tight ${color}`}>{value}</div>
          {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
        </div>
        {Icon && (
          <div className="h-11 w-11 rounded-xl brand-gradient flex items-center justify-center shadow-sm shrink-0">
            <Icon className="text-slate-900" size={20} />
          </div>
        )}
      </div>
    </div>
  )
}

export function StatCard({ label, value, sub, icon: Icon, iconClass = 'bg-amber-50 text-amber-600', valueClass = '' }) {
  return (
    <div className="stat-card">
      <div className="min-w-0">
        <div className="stat-label truncate">{label}</div>
        <div className={`stat-value mt-1 ${valueClass}`}>{value}</div>
        {sub && <div className="text-[0.6875rem] text-slate-400 mt-0.5 truncate">{sub}</div>}
      </div>
      {Icon && <div className={`stat-icon ${iconClass}`}><Icon size={20} /></div>}
    </div>
  )
}

export function Modal({ open, title, subtitle, onClose, children, wide = false, xwide = false, footer }) {
  const [visible, setVisible] = useState(false)
  const onCloseRef = useRef(onClose)
  const openRef = useRef(open)

  useEffect(() => { onCloseRef.current = onClose })
  useEffect(() => { openRef.current = open })

  useEffect(() => {
    if (open) {
      setVisible(true)
      document.body.style.overflow = 'hidden'
    } else {
      setVisible(false)
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && openRef.current) onCloseRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!visible) return null

  return createPortal(
    <div className="modal-overlay">
      <div
        className={`modal-panel ${wide ? 'modal-wide' : ''} ${xwide ? 'modal-xwide' : ''}`}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <div>
            <h3 className="font-semibold text-slate-800">{title}</h3>
            {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 hover:bg-gray-100 rounded-lg p-1.5 transition" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body p-5">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body
  )
}

export function PageHeader({ title, subtitle, crumbs, actions }) {
  return (
    <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 animate-fade-in">
      <div>
        {crumbs && <div className="text-[0.6875rem] text-slate-400 uppercase tracking-wide mb-1">{crumbs}</div>}
        <h2 className="page-title">{title}</h2>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}

export function Loading({ text = 'Loading…' }) {
  return (
    <div className="flex items-center justify-center py-16 text-slate-400 text-sm gap-3">
      <span className="h-5 w-5 inline-block rounded-full border-2 border-current border-t-transparent animate-spin" />
      {text}
    </div>
  )
}

export function LoadingSkeleton({ rows = 5 }) {
  return (
    <div className="py-2 space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="skeleton h-4 w-24" />
          <div className="skeleton h-4 flex-1" />
          <div className="skeleton h-4 w-16" />
        </div>
      ))}
    </div>
  )
}

export function Empty({ text = 'No data found', icon: Icon = SearchX }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400">
      <div className="h-14 w-14 rounded-full bg-slate-100 flex items-center justify-center mb-3">
        <Icon size={24} />
      </div>
      <div className="text-sm">{text}</div>
    </div>
  )
}

export function ErrorState({ message = 'Something went wrong loading this data.' }) {
  return (
    <div className="flex items-start gap-3 justify-center py-12 text-red-600 flex-col items-center text-center">
      <div className="h-12 w-12 rounded-full bg-red-50 flex items-center justify-center">
        <AlertCircle size={22} />
      </div>
      <div className="text-sm max-w-md">{message}</div>
    </div>
  )
}

export function Badge({ children, className = 'bg-gray-100 text-gray-600', dot = false }) {
  return (
    <span className={`badge ${className}`}>
      {dot && <span className="badge-dot" />}
      {children}
    </span>
  )
}

/**
 * Combobox: type-to-search over master data (via native <datalist>) AND free
 * text entry. `onChange(id, manual)` is called with the matched option id
 * (manual = '') when the typed text matches an existing option, or with
 * (null, typedText) when the user entered a custom value.
 *
 * options: [{ id, label }]   value: selected id (number|string|null)
 * initialLabel: text to show when editing a free-text value with no id.
 */
export function SearchSelect({ options = [], value = null, initialLabel = '', onChange, placeholder = 'Type to search…', className = 'input', allowCustom = true }) {
  const listId = useId()
  const [text, setText] = useState(() => {
    const m = options.find((o) => String(o.id) === String(value))
    return m ? m.label : (initialLabel || '')
  })

  // When master-data options finish loading (async), backfill the label for an
  // already-selected id — but never clobber a manually typed free-text value.
  useEffect(() => {
    if (!text && value != null && value !== '') {
      const m = options.find((o) => String(o.id) === String(value))
      if (m) setText(m.label)
    }
  }, [options])

  const handleChange = (e) => {
    const t = e.target.value
    setText(t)
    const m = options.find((o) => o.label.toLowerCase() === t.trim().toLowerCase())
    if (m) onChange(m.id, '')
    else onChange(null, allowCustom ? t : '')
  }

  return (
    <>
      <input
        list={listId}
        value={text}
        onChange={handleChange}
        placeholder={placeholder}
        className={className}
        autoComplete="off"
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o.id} value={o.label} />
        ))}
      </datalist>
    </>
  )
}

export function StatusBadge({ status }) {
  const s = (status || '').toLowerCase()
  let cls = 'bg-slate-100 text-slate-600'
  let dot = false
  if (s.includes('complet') || s === 'done' || s === 'delivered' || s === 'received' || s === 'fulfilled') { cls = 'bg-green-100 text-green-700'; dot = true }
  else if (s === 'over-fulfilled' || s === 'over_fulfilled' || s === 'overlift') { cls = 'bg-red-100 text-red-700'; dot = true }
  else if (s.includes('in progress') || s.includes('partial') || s.includes('production')) { cls = 'bg-blue-100 text-blue-700'; dot = true }
  else if (s.includes('transfer')) { cls = 'bg-violet-100 text-violet-700'; dot = true }
  else if (s.includes('purchase') || s === 'ordered') { cls = 'bg-cyan-100 text-cyan-700'; dot = true }
  else if (s === 'pending' || s === 'planned' || s === 'new' || s === 'confirmed' || s === 'shortage') { cls = 'bg-amber-100 text-amber-700'; dot = true }
  else if (s.includes('cancel')) { cls = 'bg-red-100 text-red-600' }
  else if (s === 'ready' || s.includes('ready for dispatch')) { cls = 'bg-teal-100 text-teal-700'; dot = true }
  return (
    <Badge className={cls} dot={dot}>{status || '—'}</Badge>
  )
}

export function SectionHeader({ title, subtitle, right }) {
  return (
    <div className="flex items-end justify-between mb-1">
      <div className="flex items-center gap-2">
        <div className="h-4 w-1 rounded-full brand-gradient" />
        <h3 className="font-semibold text-slate-800 text-[0.9375rem]">{title}</h3>
      </div>
      {right && <div>{right}</div>}
    </div>
  )
}

export function PageTabs({ tabs, active, onChange }) {
  return (
    <div className="tabs mb-5">
      {tabs.map((t) => (
        <button key={t.key} onClick={() => onChange(t.key)} className={`tab ${active === t.key ? 'active' : ''}`}>
          {t.icon}
          {t.label}
          {t.count != null && (
            <span className={`ml-1 text-[0.65rem] font-bold rounded-full px-1.5 ${active === t.key ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'}`}>
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}