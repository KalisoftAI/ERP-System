import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, Plus, ClipboardList, CheckCircle2, AlertTriangle } from 'lucide-react'
import api from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { PageHeader, Card, Loading, Empty, Badge, StatCard } from '../components/ui'
import Table from '../components/Table'
import PrnEditorModal, { newPrnDraft } from '../components/PrnEditorModal'
import { PrnDetailModal } from './PrnDetail'

export default function PRN() {
  const { user } = useAuth()

  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [meta, setMeta] = useState({ priorities: [], requirement_types: [], statuses: [] })
  const [departments, setDepartments] = useState([])
  const [materials, setMaterials] = useState([])
  const [locations, setLocations] = useState([])

  const [filters, setFilters] = useState({ search: '', department: '', priority: '' })

  const [editor, setEditor] = useState(null) // { mode, prn } or null
  const [detailId, setDetailId] = useState(null)

  const load = () => {
    setLoading(true)
    api.get('/prn', { params: { ...filters, page_size: 500 } })
      .then((res) => { setRows(res.data.items || []); setTotal(res.data.total) })
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    api.get('/prn/constants').then((r) => setMeta(r.data)).catch(() => {})
    api.get('/prn/departments').then((r) => setDepartments(r.data || [])).catch(() => {})
    api.get('/prn/materials', { params: { limit: 200 } }).then((r) => setMaterials(r.data || [])).catch(() => {})
    api.get('/prn/locations').then((r) => setLocations(r.data || [])).catch(() => {})
  }, [])

  useEffect(() => { load() }, [filters.department, filters.priority])

  const counts = useMemo(() => ({
    critical: rows.filter((r) => r.priority === 'Critical').length,
    urgent: rows.filter((r) => r.priority === 'Urgent').length,
    normal: rows.filter((r) => r.priority === 'Normal').length,
  }), [rows])

  const openNew = () => setEditor({ mode: 'new', prn: newPrnDraft(user) })

  // The whole row opens the PRN details modal. No row-level action buttons.
  const openRow = (r) => setDetailId(r.id)

  const cols = [
    { key: 'prn_number', label: 'PRN No.', render: (r) => <span className="font-mono text-xs font-semibold">{r.prn_number}</span> },
    { key: 'prn_date', label: 'PRN Date' },
    { key: 'department', label: 'Department', render: (r) => r.department || '—' },
    { key: 'requested_by_name', label: 'Requested By', render: (r) => r.requested_by_name || '—' },
    { key: 'required_by_date', label: 'Required By', render: (r) => r.required_by_date || '—' },
    { key: 'priority', label: 'Priority', render: (r) => (
      <Badge className={r.priority === 'Critical' ? 'bg-red-100 text-red-700' : r.priority === 'Urgent' ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-600'}>{r.priority}</Badge>
    )},
    { key: 'item_count', label: 'Items', render: (r) => r.item_count },
    { key: 'created_at', label: 'Created', render: (r) => (r.created_at || '').slice(0, 10) },
  ]

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Purchase Requisition Note" subtitle="Material purchase requirements"
        actions={<>
          <button onClick={load} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
          <button onClick={openNew} className="btn btn-primary"><Plus size={15} /> New PRN</button>
        </>} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Total PRNs" value={total} icon={ClipboardList} iconClass="bg-slate-100 text-slate-600" />
        <StatCard label="Critical" value={counts.critical} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
        <StatCard label="Urgent" value={counts.urgent} icon={AlertTriangle} iconClass="bg-amber-50 text-amber-600" valueClass="text-amber-600" />
        <StatCard label="Normal" value={counts.normal} icon={CheckCircle2} iconClass="bg-green-50 text-green-600" />
      </div>

      <Card>
        <div className="flex items-center gap-2 flex-wrap mb-4">
          <input value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="Search PRN no. / material description…" className="input text-sm py-1.5 px-3 w-72" />
          <select value={filters.department} onChange={(e) => setFilters((f) => ({ ...f, department: e.target.value }))} className="input text-sm py-1.5 px-2 w-44">
            <option value="">All Departments</option>
            {departments.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <select value={filters.priority} onChange={(e) => setFilters((f) => ({ ...f, priority: e.target.value }))} className="input text-sm py-1.5 px-2 w-32">
            <option value="">All Priority</option>
            {meta.priorities.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={load} className="btn btn-secondary"><RefreshCw size={14} /> Search</button>
        </div>
        <div className="text-sm text-slate-500 mb-2">{total} PRN(s) · click a row to open it</div>
        {loading ? <Loading /> : rows.length === 0 ? <Empty text="No PRNs yet" /> : <Table columns={cols} data={rows} keyField="id" onRowClick={openRow} dense />}
      </Card>

      {editor && (
        <PrnEditorModal editor={editor} setEditor={setEditor} meta={meta} departments={departments}
          materials={materials} locations={locations} currentUser={user} onSaved={() => { setEditor(null); load() }} />
      )}

      {detailId && (
        <PrnDetailModal prnId={detailId} currentUser={user}
          lookups={{ meta, departments, materials, locations }}
          onClose={() => setDetailId(null)}
          onChanged={load}
          onDeleted={load} />
      )}
    </div>
  )
}
