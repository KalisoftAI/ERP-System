import { useCallback, useEffect, useState } from 'react'
import {
  Activity, PlusCircle, PencilLine, Trash2, Download, RefreshCw,
  History, CalendarDays, Eye, FileSpreadsheet, AlertTriangle,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, StatCard, PageTabs } from '../components/ui'

const today = () => new Date().toISOString().slice(0, 10)

const ACTION_CLASS = {
  CREATE: 'bg-green-100 text-green-700',
  UPDATE: 'bg-blue-100 text-blue-700',
  DELETE: 'bg-red-100 text-red-700',
  APPROVE: 'bg-emerald-100 text-emerald-700',
  REJECT: 'bg-red-100 text-red-700',
  SUBMIT: 'bg-amber-100 text-amber-700',
  CANCEL: 'bg-slate-100 text-slate-600',
  STATUS: 'bg-violet-100 text-violet-700',
  RECEIVE: 'bg-cyan-100 text-cyan-700',
  IMPORT: 'bg-indigo-100 text-indigo-700',
}

const moduleLabel = (name = '') => name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const fmtWhen = (value) => (value ? value.replace('T', ' ').slice(0, 19) : '-')

const fmtCount = (value) => Number(value || 0).toLocaleString()

const recordText = (row) => {
  const counts = row.counts || {}
  const parts = []
  if (counts.added) parts.push(`+${counts.added} added`)
  if (counts.updated) parts.push(`${counts.updated} updated`)
  if (counts.deleted) parts.push(`${counts.deleted} deleted`)
  if (counts.failed) parts.push(`${counts.failed} failed`)
  return parts.length ? parts.join(' · ') : `${Object.keys(row.changes || {}).length} fields`
}

const valueText = (value) => {
  if (value === null || value === undefined || value === '') return '(empty)'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const TABS = [
  { key: 'summary', label: 'Daily Summary', icon: <CalendarDays size={15} /> },
  { key: 'history', label: 'Detailed History', icon: <History size={15} /> },
]

export default function ActivityLog() {
  const [tab, setTab] = useState('summary')
  const [dateFrom, setDateFrom] = useState(today)
  const [dateTo, setDateTo] = useState(today)
  const [module, setModule] = useState('')
  const [userId, setUserId] = useState('')
  const [action, setAction] = useState('')
  const [kind, setKind] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [refreshKey, setRefreshKey] = useState(0)
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState([])
  const [options, setOptions] = useState({ modules: [], actions: [], users: [] })
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState(null)

  const filters = useCallback(() => {
    const params = {}
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    if (module) params.module = module
    if (userId) params.user_id = Number(userId)
    if (action) params.action = action
    if (kind) params.kind = kind
    if (search.trim()) params.search = search.trim()
    return params
  }, [dateFrom, dateTo, module, userId, action, kind, search])

  useEffect(() => {
    api.get('/activity-log/options').then((r) => setOptions(r.data || {})).catch(() => {})
  }, [])

  useEffect(() => {
    setPage(1)
  }, [dateFrom, dateTo, module, userId, action, kind, search])

  useEffect(() => {
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        if (tab === 'summary') {
          const res = await api.get('/activity-log/summary', { params: filters() })
          setSummary(res.data.items || [])
        } else {
          const res = await api.get('/activity-log', { params: { ...filters(), page, page_size: 50 } })
          setItems(res.data.items || [])
          setTotal(res.data.total || 0)
        }
      } catch {
        if (tab === 'summary') setSummary([])
        else { setItems([]); setTotal(0) }
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => clearTimeout(timer)
  }, [tab, page, refreshKey, filters])

  const totals = summary.reduce((acc, row) => ({
    total: acc.total + row.total,
    added: acc.added + row.added,
    updated: acc.updated + row.updated,
    deleted: acc.deleted + row.deleted,
    failed: acc.failed + row.failed,
    imports: acc.imports + row.imports,
  }), { total: 0, added: 0, updated: 0, deleted: 0, failed: 0, imports: 0 })

  const totalPages = Math.max(1, Math.ceil(total / 50))

  const drill = (filters, nextKind) => {
    setDateFrom(filters.day || dateFrom)
    setDateTo(filters.day || dateTo)
    setModule(filters.module ?? module)
    setUserId(filters.user_id != null ? String(filters.user_id) : '')
    setAction('')
    setSearch('')
    setKind(nextKind)
    setTab('history')
    setPage(1)
  }

  const drillStat = (nextKind) => {
    setAction('')
    setKind(nextKind)
    setTab('history')
    setPage(1)
  }

  const exportLog = (format) => {
    const params = new URLSearchParams(filters())
    params.set('format', format)
    const ext = format === 'excel' ? 'xlsx' : 'csv'
    downloadFile(`/activity-log/export?${params.toString()}`, `activity_log.${ext}`)
  }

  return (
    <div className="animate-fade-in-up">
      <PageHeader
        title="Activity Log"
        subtitle="Who changed what, when - field-level history and daily summary"
        actions={
          <>
            <button onClick={() => exportLog('csv')} className="btn btn-secondary"><Download size={15} /> CSV</button>
            <button onClick={() => exportLog('excel')} className="btn btn-secondary"><FileSpreadsheet size={15} /> Excel</button>
            <button onClick={() => setRefreshKey((k) => k + 1)} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
          </>
        }
      />

      <PageTabs tabs={TABS} active={tab} onChange={(next) => {
        setTab(next)
        if (next === 'summary') setKind('')
      }} />

      <Card title="Filters" bodyClass="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs text-slate-500 mb-1">From</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">To</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="input" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Module</label>
            <select value={module} onChange={(e) => setModule(e.target.value)} className="input min-w-44">
              <option value="">All modules</option>
              {(options.modules || []).map((m) => <option key={m} value={m}>{moduleLabel(m)}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">User</label>
            <select value={userId} onChange={(e) => setUserId(e.target.value)} className="input min-w-44">
              <option value="">All users</option>
              {(options.users || []).map((u) => (
                <option key={u.id} value={u.id}>{u.full_name || u.username}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Action</label>
            <select value={action} onChange={(e) => { setAction(e.target.value); setKind('') }} className="input min-w-36">
              <option value="">All actions</option>
              {(options.actions || []).map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <div className="flex-1 min-w-48">
            <label className="block text-xs text-slate-500 mb-1">Search</label>
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="User, module, action, details..." className="input w-full" />
          </div>
        </div>
      </Card>

      {kind && (
        <div className="mt-4 flex items-center gap-2 text-sm text-slate-600">
          Showing <span className="font-semibold capitalize">{kind === 'records' ? 'total' : kind}</span> records from the daily summary
          <button onClick={() => setKind('')} className="btn btn-secondary btn-sm">Clear</button>
        </div>
      )}

      {tab === 'summary' ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 my-5">
            <button onClick={() => drillStat('records')} className="text-left">
              <StatCard label="Total Records" value={fmtCount(totals.total)} icon={Activity} iconClass="bg-blue-50 text-blue-600" />
            </button>
            <button onClick={() => drillStat('added')} className="text-left">
              <StatCard label="Added" value={fmtCount(totals.added)} icon={PlusCircle} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
            </button>
            <button onClick={() => drillStat('updated')} className="text-left">
              <StatCard label="Updated" value={fmtCount(totals.updated)} icon={PencilLine} iconClass="bg-amber-50 text-amber-600" valueClass="text-amber-600" />
            </button>
            <button onClick={() => drillStat('deleted')} className="text-left">
              <StatCard label="Deleted" value={fmtCount(totals.deleted)} icon={Trash2} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
            </button>
            <button onClick={() => drillStat('failed')} className="text-left">
              <StatCard label="Import Failed" value={fmtCount(totals.failed)} icon={AlertTriangle} iconClass="bg-rose-50 text-rose-600" valueClass="text-rose-600" />
            </button>
          </div>

          <Card title="Day / Module / User Summary" subtitle="Counts for the selected period">
            {loading ? <Loading /> : summary.length === 0 ? <Empty text="No activity matches the selected filters" /> : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr>
                    <th className="whitespace-nowrap">Day</th><th className="whitespace-nowrap">Module</th>
                    <th className="whitespace-nowrap">User</th>
                    <th className="text-right whitespace-nowrap">Total</th><th className="text-right whitespace-nowrap">Added</th>
                    <th className="text-right whitespace-nowrap">Updated</th><th className="text-right whitespace-nowrap">Deleted</th>
                    <th className="text-right whitespace-nowrap">Imports</th><th className="text-right whitespace-nowrap">Failed</th>
                  </tr></thead>
                  <tbody>
                    {summary.map((row, i) => {
                      const user = { day: row.day, module: row.module, user_id: row.user.id }
                      return (
                        <tr key={`${row.day}-${row.module}-${row.user.id ?? 'system'}-${i}`}>
                          <td className="font-medium whitespace-nowrap">{row.day}</td>
                          <td className="whitespace-nowrap">{moduleLabel(row.module)}</td>
                          <td className="whitespace-nowrap">{row.user.full_name || row.user.username}</td>
                          <td className="text-right whitespace-nowrap tabular-nums font-bold text-slate-700"><button className="hover:underline" onClick={() => drill(user, 'records')}>{fmtCount(row.total)}</button></td>
                          <td className="text-right whitespace-nowrap tabular-nums text-green-600"><button className="hover:underline font-semibold" onClick={() => drill(user, 'added')}>{fmtCount(row.added)}</button></td>
                          <td className="text-right whitespace-nowrap tabular-nums text-amber-600"><button className="hover:underline font-semibold" onClick={() => drill(user, 'updated')}>{fmtCount(row.updated)}</button></td>
                          <td className="text-right whitespace-nowrap tabular-nums text-red-600"><button className="hover:underline font-semibold" onClick={() => drill(user, 'deleted')}>{fmtCount(row.deleted)}</button></td>
                          <td className="text-right whitespace-nowrap tabular-nums text-indigo-600"><button className="hover:underline font-semibold" onClick={() => drill(user, 'imports')}>{fmtCount(row.imports)}</button></td>
                          <td className="text-right whitespace-nowrap tabular-nums text-rose-600"><button className="hover:underline font-semibold" onClick={() => drill(user, 'failed')}>{fmtCount(row.failed)}</button></td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      ) : (
        <Card title="Change History" subtitle={`${total} matching entries`} className="mt-5">
          {loading ? <Loading /> : items.length === 0 ? <Empty text="No activity for these filters" /> : (
            <>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr>
                    <th>Date</th><th>User</th><th>Module</th><th>Record</th>
                    <th>Action</th><th>Details</th><th>Records</th><th></th>
                  </tr></thead>
                  <tbody>
                    {items.map((row) => (
                      <tr key={row.id}>
                        <td className="text-xs whitespace-nowrap">{fmtWhen(row.created_at)}</td>
                        <td>
                          <div className="font-medium">{row.user.full_name || row.user.username}</div>
                          <div className="text-[0.6875rem] text-slate-400">{row.user.role || '-'}</div>
                        </td>
                        <td>{moduleLabel(row.module)}</td>
                        <td className="text-slate-500">{row.record_id ? `#${row.record_id}` : '-'}</td>
                        <td><Badge className={ACTION_CLASS[row.action] || 'bg-slate-100 text-slate-600'}>{row.action}</Badge></td>
                        <td className="max-w-72 truncate text-xs" title={row.details}>{row.details || '-'}</td>
                        <td className="text-xs text-slate-500">{recordText(row)}</td>
                        <td>
                          <button onClick={() => setDetail(row)} className="btn btn-secondary btn-sm" title="View details">
                            <Eye size={14} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {total > 50 && (
                <div className="flex items-center justify-between mt-4 text-sm">
                  <span className="text-slate-500">Page {page} of {totalPages}</span>
                  <div className="flex gap-2">
                    <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="btn btn-secondary">Previous</button>
                    <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="btn btn-secondary">Next</button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      )}

      <Modal open={!!detail} title="Activity Detail" subtitle={detail ? fmtWhen(detail.created_at) : ''}
        onClose={() => setDetail(null)} wide
        footer={<button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>}>
        {detail && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-3">
              <div><span className="text-slate-500 text-xs">User</span>
                <div className="font-medium">{detail.user.full_name || detail.user.username} ({detail.user.role || '-'})</div></div>
              <div><span className="text-slate-500 text-xs">Action</span>
                <div><Badge className={ACTION_CLASS[detail.action] || 'bg-slate-100 text-slate-600'}>{detail.action}</Badge></div></div>
              <div><span className="text-slate-500 text-xs">Module</span>
                <div>{moduleLabel(detail.module)}{detail.record_id ? ` #${detail.record_id}` : ''}</div></div>
              <div><span className="text-slate-500 text-xs">IP</span>
                <div>{detail.ip || '-'}</div></div>
            </div>
            <div className="grid grid-cols-4 gap-2">
              <div className="rounded-lg bg-green-50 px-3 py-2"><div className="text-xs text-green-700">Added</div><div className="font-semibold text-green-700">{detail.counts.added}</div></div>
              <div className="rounded-lg bg-amber-50 px-3 py-2"><div className="text-xs text-amber-700">Updated</div><div className="font-semibold text-amber-700">{detail.counts.updated}</div></div>
              <div className="rounded-lg bg-red-50 px-3 py-2"><div className="text-xs text-red-700">Deleted</div><div className="font-semibold text-red-700">{detail.counts.deleted}</div></div>
              <div className="rounded-lg bg-rose-50 px-3 py-2"><div className="text-xs text-rose-700">Failed</div><div className="font-semibold text-rose-700">{detail.counts.failed}</div></div>
            </div>
            <div>
              <span className="text-slate-500 text-xs">Details</span>
              <div className="mt-1 bg-slate-50 rounded-lg p-3">{detail.details || '-'}</div>
            </div>
            <div>
              <span className="text-slate-500 text-xs">Field Changes</span>
              {Object.keys(detail.changes || {}).length === 0 ? (
                <div className="mt-1 text-slate-400">No field-level values recorded for this entry.</div>
              ) : (
                <div className="table-wrap mt-1">
                  <table className="data-table">
                    <thead><tr><th>Field</th><th>Previous</th><th>New</th></tr></thead>
                    <tbody>
                      {Object.entries(detail.changes).map(([field, change]) => (
                        <tr key={field}>
                          <td className="font-medium">{field}</td>
                          <td className="text-red-600 break-all">{valueText(change?.old)}</td>
                          <td className="text-green-700 break-all">{valueText(change?.new)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

