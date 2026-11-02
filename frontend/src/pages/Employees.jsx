import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Plus, Pencil, Trash2, Search, Users, User, UserCheck, UserX, ShieldCheck,
  Upload, Download, FileText, ChevronLeft, ChevronRight, Settings2, CheckCircle2,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import {
  PageHeader, Card, Modal, Loading, Empty, Badge, StatCard, SectionHeader,
} from '../components/ui'
import Table from '../components/Table'
import { useAuth } from '../context/AuthContext'

const empty = {
  employee_code: '', name: '', mobile: '', email: '',
  department: '', designation: '', joining_date: '', status: 'Active',
  aadhaar_number: '', pan_number: '', bank_account_number: '',
  ifsc_code: '', bank_name: '', branch_name: '',
}

const SENSITIVE_FIELDS = [
  'aadhaar_number', 'pan_number', 'bank_account_number', 'ifsc_code', 'bank_name', 'branch_name',
]

// All exportable columns, in display order.
const EXPORT_COLUMNS = [
  { field: 'employee_code', label: 'Employee ID' },
  { field: 'name', label: 'Name' },
  { field: 'mobile', label: 'Mobile' },
  { field: 'email', label: 'Email' },
  { field: 'department', label: 'Department' },
  { field: 'designation', label: 'Designation' },
  { field: 'joining_date', label: 'Joining Date' },
  { field: 'status', label: 'Status' },
  { field: 'aadhaar_number', label: 'Aadhaar Number' },
  { field: 'pan_number', label: 'PAN Number' },
  { field: 'bank_account_number', label: 'Bank Account Number' },
  { field: 'ifsc_code', label: 'IFSC Code' },
  { field: 'bank_name', label: 'Bank Name' },
  { field: 'branch_name', label: 'Branch Name' },
]
const DEFAULT_COLUMNS = EXPORT_COLUMNS.filter((c) => !SENSITIVE_FIELDS.includes(c.field)).map((c) => c.field)

// Indian format rules (identifiers are optional).
const AADHAAR_RE = /^[2-9]\d{11}$/
const PAN_RE = /^[A-Z]{5}[0-9]{4}[A-Z]$/
const IFSC_RE = /^[A-Z]{4}0[A-Z0-9]{6}$/

// Advanced Edit (statutory / payroll) fields, option sets and rules.
const ADVANCED_EMPTY = {
  pf_applicable: '', uan: '', pf_member_id: '', pf_joining_date: '', pf_exit_date: '',
  previous_pf_membership: '', esic_applicable: '', esic_ip_number: '', esic_joining_date: '',
  esic_exit_date: '', esic_registration_status: '', verification_status: '', verified_by: '',
  verification_date: '', remarks: '', supporting_document_ref: '', job_leave_date: '',
}
const ADVANCED_DATE_FIELDS = [
  'pf_joining_date', 'pf_exit_date', 'esic_joining_date', 'esic_exit_date',
  'verification_date', 'job_leave_date',
]
const APPLICABILITY = ['', 'Yes', 'No', 'Pending Verification']
const PREVIOUS_PF = ['', 'Yes', 'No', 'Unknown']
const ESIC_REG_STATUS = ['', 'Not Registered', 'Pending', 'Registered', 'Inactive']
const VERIFICATION_OPTIONS = ['', 'Pending', 'Verified', 'Rejected']
const UAN_RE = /^\d{12}$/
const ESIC_IP_RE = /^\d{10,17}$/
const PF_MEMBER_RE = /^[A-Z0-9/-]{3,30}$/

const maskValue = (v) => {
  const s = v || ''
  if (!s) return ''
  if (s.length <= 4) return 'X'.repeat(s.length)
  return 'X'.repeat(s.length - 4) + s.slice(-4)
}

const csvEscape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`

const downloadCsv = (rows, filename) => {
  const csv = rows.map((r) => r.map(csvEscape).join(',')).join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}

const PAGE_SIZES = [25, 50, 100]

// Render a value, falling back to an em dash for blank/missing data.
const dv = (v) => (v === null || v === undefined || v === '' ? '—' : v)

// Read-only labelled field used in the employee details window.
function DetailField({ label, value, mono = false }) {
  return (
    <div className="min-w-0">
      <div className="text-[0.6875rem] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-0.5 text-sm text-slate-800 break-words ${mono ? 'font-mono' : ''}`}>
        {dv(value)}
      </div>
    </div>
  )
}

export default function Employees() {
  const { user } = useAuth()
  const isHr = user?.role === 'admin'

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [dept, setDept] = useState('')
  const [desig, setDesig] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [options, setOptions] = useState({ departments: [], designations: [] })
  const [selected, setSelected] = useState(() => new Set())
  const [total, setTotal] = useState(0)
  const [statusCounts, setStatusCounts] = useState({})
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)

  // read-only details window
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const editFromDetailRef = useRef(null)

  // advanced edit (statutory / payroll details) window
  const [advBase, setAdvBase] = useState(null)
  const [advForm, setAdvForm] = useState(ADVANCED_EMPTY)
  const [advErrors, setAdvErrors] = useState({})
  const [advSaving, setAdvSaving] = useState(false)
  const [flash, setFlash] = useState('')

  // employee form
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(empty)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  // export
  const [exportOpen, setExportOpen] = useState(false)
  const [exportFormat, setExportFormat] = useState('csv')
  const [exportScope, setExportScope] = useState('filtered')
  const [exportColumns, setExportColumns] = useState(DEFAULT_COLUMNS)
  const [unmask, setUnmask] = useState(false)

  // import
  const [importOpen, setImportOpen] = useState(false)
  const [importFile, setImportFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [importBusy, setImportBusy] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [dupAction, setDupAction] = useState('skip')

  const load = () => {
    setLoading(true)
    api
      .get('/employees', {
        params: {
          search, department: dept, designation: desig, status: statusFilter,
          page, page_size: pageSize,
        },
      })
      .then((res) => {
        setItems(res.data.items)
        setTotal(res.data.total ?? res.data.items.length)
        setStatusCounts(res.data.status_counts || {})
      })
      .catch(() => { setItems([]); setTotal(0); setStatusCounts({}) })
      .finally(() => setLoading(false))
  }

  const loadOptions = () => {
    api.get('/employees/filters').then((res) => setOptions(res.data)).catch(() => {})
  }

  useEffect(loadOptions, [])
  useEffect(() => {
    setSelected(new Set())
    setPage(1)
  }, [search, dept, desig, statusFilter, pageSize])
  useEffect(() => {
    const t = setTimeout(load, 300)
    return () => clearTimeout(t)
  }, [search, dept, desig, statusFilter, page, pageSize])

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  useEffect(() => {
    // Keep the page in range after deletes / filter changes shrink the result.
    if (page > totalPages) setPage(totalPages)
  }, [totalPages, page])

  // ---- selection ----
  const allSelected = items.length > 0 && items.every((i) => selected.has(i.id))
  const toggleSelect = (id) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map((i) => i.id)))

  // ---- employee form ----
  const openCreate = () => { editFromDetailRef.current = null; setForm(empty); setErrors({}); setModal('create') }
  const openEdit = async (row) => {
    setErrors({})
    try {
      const res = await api.get(`/employees/${row.id}`)
      setForm({ ...empty, ...res.data, joining_date: res.data.joining_date || '' })
    } catch {
      setForm({ ...empty, ...row, joining_date: row.joining_date || '' })
    }
    setModal('edit')
  }
  const closeEdit = () => { editFromDetailRef.current = null; setModal(null) }
  const remove = async (row) => {
    if (!window.confirm(`Delete employee "${row.name}"?`)) return
    try {
      await api.delete(`/employees/${row.id}`)
      setDetail((d) => (d && d.id === row.id ? null : d))
      load(); loadOptions()
    } catch (err) {
      alert(err.response?.data?.detail || 'Delete failed')
    }
  }

  // ---- details window ----
  const openDetail = async (row) => {
    setDetail(row)
    setDetailLoading(true)
    try {
      const res = await api.get(`/employees/${row.id}`)
      setDetail(res.data)
    } catch {
      // fall back to the row data already shown
    } finally {
      setDetailLoading(false)
    }
  }
  const closeDetail = () => { setDetail(null); setDetailLoading(false) }
  const editFromDetail = (row) => {
    editFromDetailRef.current = row.id
    setDetail(null)
    openEdit(row)
  }
  const downloadDetailPdf = (row) => {
    downloadFile(`/employees/${row.id}/pdf`, `employee_${row.employee_code || row.id}.pdf`)
  }

  // ---- advanced edit ----
  const openAdvanced = async (row) => {
    setAdvErrors({})
    let base = row
    try {
      const res = await api.get(`/employees/${row.id}`)
      base = res.data
    } catch {
      // fall back to the row data already loaded
    }
    const filled = { ...ADVANCED_EMPTY }
    Object.keys(ADVANCED_EMPTY).forEach((k) => { filled[k] = base[k] ?? '' })
    setAdvForm(filled)
    setAdvBase(base)
  }
  const closeAdvanced = () => { setAdvBase(null); setAdvErrors({}) }

  const advValidate = () => {
    const e = {}
    const uan = (advForm.uan || '').trim()
    if (uan && !UAN_RE.test(uan)) e.uan = 'Invalid UAN (12 digits)'
    const ip = (advForm.esic_ip_number || '').trim()
    if (ip && !ESIC_IP_RE.test(ip)) e.esic_ip_number = 'Invalid ESIC IP Number (10–17 digits)'
    const member = (advForm.pf_member_id || '').trim().toUpperCase()
    if (member && !PF_MEMBER_RE.test(member)) e.pf_member_id = 'Invalid PF Member ID'
    if (advForm.pf_joining_date && advForm.pf_exit_date
      && advForm.pf_exit_date < advForm.pf_joining_date) {
      e.pf_exit_date = 'PF Exit Date cannot be before PF Joining Date'
    }
    if (advForm.esic_joining_date && advForm.esic_exit_date
      && advForm.esic_exit_date < advForm.esic_joining_date) {
      e.esic_exit_date = 'ESIC Exit Date cannot be before ESIC Joining Date'
    }
    const jd = advBase?.joining_date || ''
    if (jd && advForm.job_leave_date && advForm.job_leave_date < jd) {
      e.job_leave_date = 'Job Leave Date cannot be before Joining Date'
    }
    setAdvErrors(e)
    return Object.keys(e).length === 0
  }

  const saveAdvanced = async (e) => {
    e.preventDefault()
    if (!advValidate()) return
    setAdvSaving(true)
    try {
      const payload = { ...advForm }
      ADVANCED_DATE_FIELDS.forEach((k) => { payload[k] = payload[k] || null })
      const res = await api.patch(`/employees/${advBase.id}`, payload)
      setDetail((d) => (d && d.id === advBase.id ? res.data : d))
      setAdvBase(null)
      load(); loadOptions()
      setFlash(`Advanced details saved for ${res.data.name}`)
      setTimeout(() => setFlash(''), 5000)
    } catch (err) {
      // Keep the modal (and typed values) open so nothing is lost on failure.
      alert(err.response?.data?.detail || 'Save failed')
    } finally {
      setAdvSaving(false)
    }
  }

  const validateSensitive = () => {
    const e = {}
    const aadhaar = (form.aadhaar_number || '').replace(/[\s-]/g, '')
    if (aadhaar && !AADHAAR_RE.test(aadhaar)) e.aadhaar_number = 'Invalid Aadhaar (12 digits, cannot start with 0 or 1)'
    const pan = (form.pan_number || '').trim().toUpperCase()
    if (pan && !PAN_RE.test(pan)) e.pan_number = 'Invalid PAN (format ABCDE1234F)'
    const ifsc = (form.ifsc_code || '').trim().toUpperCase()
    if (ifsc && !IFSC_RE.test(ifsc)) e.ifsc_code = 'Invalid IFSC (format ABCD0123456)'
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const save = async (e) => {
    e.preventDefault()
    if (isHr && !validateSensitive()) return
    setSaving(true)
    try {
      const payload = { ...form, joining_date: form.joining_date || null }
      if (payload.aadhaar_number) payload.aadhaar_number = payload.aadhaar_number.replace(/[\s-]/g, '')
      if (payload.bank_account_number) payload.bank_account_number = payload.bank_account_number.replace(/\s/g, '')
      if (payload.pan_number) payload.pan_number = payload.pan_number.trim().toUpperCase()
      if (payload.ifsc_code) payload.ifsc_code = payload.ifsc_code.trim().toUpperCase()
      if (!isHr) SENSITIVE_FIELDS.forEach((k) => delete payload[k])
      if (modal === 'create') await api.post('/employees', payload)
      else await api.patch(`/employees/${form.id}`, payload)
      const reopenId = editFromDetailRef.current
      editFromDetailRef.current = null
      setModal(null)
      load(); loadOptions()
      if (reopenId != null) {
        try {
          const res = await api.get(`/employees/${reopenId}`)
          setDetail(res.data)
        } catch {
          // details window stays closed if the refresh fails
        }
      }
    } catch (err) {
      alert(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  // ---- export ----
  const openExport = (scope = 'filtered') => {
    setExportFormat('csv'); setExportScope(scope); setExportColumns(DEFAULT_COLUMNS)
    setUnmask(false); setExportOpen(true)
  }
  const anySensitive = exportColumns.some((f) => SENSITIVE_FIELDS.includes(f))
  const runExport = () => {
    if (exportScope === 'selected' && selected.size === 0) {
      window.alert('Select at least one employee to export.')
      return
    }
    if (exportColumns.length === 0) {
      window.alert('Choose at least one column to export.')
      return
    }
    const p = new URLSearchParams()
    p.set('format', exportFormat)
    p.set('columns', exportColumns.join(','))
    if (exportScope === 'selected') {
      p.set('ids', [...selected].join(','))
    } else {
      if (search) p.set('search', search)
      if (dept) p.set('department', dept)
      if (desig) p.set('designation', desig)
      if (statusFilter) p.set('status', statusFilter)
    }
    if (anySensitive && isHr) {
      p.set('include_sensitive', 'true')
      if (unmask) p.set('unmask_sensitive', 'true')
    }
    const ext = exportFormat === 'xlsx' ? 'xlsx' : exportFormat
    downloadFile(`/employees/export?${p.toString()}`, `employees.${ext}`)
    setExportOpen(false)
  }

  const downloadSelectedPdf = () => {
    if (selected.size === 0) {
      window.alert('Select at least one employee to download.')
      return
    }
    const p = new URLSearchParams()
    p.set('format', 'pdf')
    p.set('ids', [...selected].join(','))
    p.set('columns', DEFAULT_COLUMNS.join(','))
    downloadFile(`/employees/export?${p.toString()}`, 'employees.pdf')
  }

  const toggleColumn = (field) => setExportColumns((prev) => (
    prev.includes(field) ? prev.filter((f) => f !== field) : [...prev, field]
  ))

  // ---- import ----
  const openImport = () => {
    setImportFile(null); setPreview(null); setImportResult(null); setDupAction('skip')
    setImportOpen(true)
  }
  const runPreview = async (file) => {
    if (!file) return
    setImportBusy(true); setPreview(null); setImportResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/employees/import/preview', fd)
      setPreview(res.data)
    } catch (err) {
      alert(err.response?.data?.detail || 'Preview failed. Please check the file.')
    } finally {
      setImportBusy(false)
    }
  }
  const confirmImport = async () => {
    if (!importFile) return
    setImportBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', importFile)
      const res = await api.post(`/employees/import?duplicate_action=${dupAction}`, fd)
      setImportResult(res.data)
      load(); loadOptions()
    } catch (err) {
      alert(err.response?.data?.detail || 'Import failed')
    } finally {
      setImportBusy(false)
    }
  }
  const downloadErrorDetails = (payload) => {
    const rows = [['Row', 'Employee ID', 'Error']]
    ;(payload.errors || []).forEach((e) => rows.push([e.row, e.employee_code || '', e.message]))
    downloadCsv(rows, 'employee_import_errors.csv')
  }

  const columns = [
    {
      key: 'select',
      label: <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Select all" />,
      render: (r) => (
        <input
          type="checkbox"
          checked={selected.has(r.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => toggleSelect(r.id)}
          aria-label={`Select ${r.name}`}
        />
      ),
    },
    { key: 'employee_code', label: 'Employee ID', render: (r) => <span className="font-mono text-xs font-medium">{r.employee_code}</span> },
    { key: 'name', label: 'Name', render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'mobile', label: 'Mobile', render: (r) => <span className="font-mono text-xs">{r.mobile || '—'}</span> },
    { key: 'email', label: 'Email', render: (r) => r.email || '—' },
    { key: 'department', label: 'Department', render: (r) => r.department || '—' },
    { key: 'designation', label: 'Designation', render: (r) => r.designation || '—' },
    { key: 'joining_date', label: 'Joining Date', render: (r) => r.joining_date || '—' },
    { key: 'aadhaar_number', label: 'Aadhaar', render: (r) => <span className="font-mono text-xs text-slate-500">{r.aadhaar_number ? maskValue(r.aadhaar_number) : '—'}</span> },
    { key: 'pan_number', label: 'PAN', render: (r) => <span className="font-mono text-xs text-slate-500">{r.pan_number ? maskValue(r.pan_number) : '—'}</span> },
    { key: 'bank_account_number', label: 'Bank A/c', render: (r) => <span className="font-mono text-xs text-slate-500">{r.bank_account_number ? maskValue(r.bank_account_number) : '—'}</span> },
    { key: 'status', label: 'Status', render: (r) => <Badge className={r.status === 'Active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}>{r.status}</Badge> },
  ]

  const field = (label, key, props = {}, error = '') => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{label}</label>
      <input
        value={form[key] ?? ''}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="input"
        {...props}
      />
      {error && <div className="text-[0.6875rem] text-red-500 mt-1">{error}</div>}
    </div>
  )

  const advInput = (label, key, props = {}, error = '') => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{label}</label>
      <input
        value={advForm[key] ?? ''}
        onChange={(e) => setAdvForm({ ...advForm, [key]: e.target.value })}
        className="input"
        {...props}
      />
      {error && <div className="text-[0.6875rem] text-red-500 mt-1">{error}</div>}
    </div>
  )

  const advSelect = (label, key, choices, error = '') => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{label}</label>
      <select
        value={advForm[key] ?? ''}
        onChange={(e) => setAdvForm({ ...advForm, [key]: e.target.value })}
        className="input"
      >
        {choices.map((c) => <option key={c || 'blank'} value={c}>{c || '—'}</option>)}
      </select>
      {error && <div className="text-[0.6875rem] text-red-500 mt-1">{error}</div>}
    </div>
  )

  const active = statusCounts.Active ?? 0
  const inactive = statusCounts.Inactive ?? 0
  const previewColumns = useMemo(() => {
    if (!preview) return []
    return [
      { key: '__row', label: 'Row', render: (r) => r.row },
      ...preview.columns.map((c) => ({
        key: c.field, label: c.label, render: (r) => r.data[c.field] ?? '',
      })),
      {
        key: '__status', label: 'Status',
        render: (r) => (
          <Badge className={
            r.status === 'error' ? 'bg-red-100 text-red-700'
              : r.status === 'duplicate' ? 'bg-amber-100 text-amber-700'
                : 'bg-green-100 text-green-700'
          }>{r.status}</Badge>
        ),
      },
      { key: '__errors', label: 'Errors', render: (r) => <span className="text-xs text-red-500">{r.errors.join('; ')}</span> },
    ]
  }, [preview])

  return (
    <div className="animate-fade-in-up">
      {flash && (
        <div className="mb-4 rounded-lg bg-green-50 text-green-700 text-sm px-4 py-3 flex items-center gap-2">
          <CheckCircle2 size={16} /> {flash}
        </div>
      )}
      <PageHeader
        title="Employee Management"
        subtitle="HR & Payroll Department"
        actions={
          <>
            <button onClick={openImport} className="btn btn-secondary"><Upload size={15} /> Import</button>
            <button onClick={() => openExport('filtered')} className="btn btn-secondary"><Download size={15} /> Export</button>
            <button onClick={downloadSelectedPdf} className="btn btn-secondary"><FileText size={15} /> Selected PDF</button>
            <button onClick={openCreate} className="btn btn-primary"><Plus size={15} /> Add Employee</button>
          </>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-5">
        <StatCard label="Total Employees" value={total} icon={Users} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Active" value={active} icon={UserCheck} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
        <StatCard label="Inactive" value={inactive} icon={UserX} iconClass="bg-gray-100 text-gray-500" />
        <StatCard label="Selected" value={selected.size} icon={FileText} iconClass="bg-blue-50 text-blue-600" />
      </div>

      <Card
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            <select value={dept} onChange={(e) => setDept(e.target.value)} className="input sm:w-40">
              <option value="">All Departments</option>
              {options.departments.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select value={desig} onChange={(e) => setDesig(e.target.value)} className="input sm:w-40">
              <option value="">All Designations</option>
              {options.designations.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="input sm:w-32">
              <option value="">All Status</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
            <div className="relative">
              <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search ID, name, mobile, email…"
                className="input input-icon sm:w-64"
              />
            </div>
          </div>
        }
      >
        {loading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty />
        ) : (
          <Table
            columns={columns}
            data={items}
            keyField="id"
            onRowClick={openDetail}
            stickyColumns={['employee_code']}
            dense
          />
        )}
      </Card>

      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mt-4">
        <div className="text-xs text-slate-500">
          {total === 0
            ? 'No employees'
            : `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}
        </div>
        <div className="flex items-center gap-2">
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="input py-1.5 text-sm w-28"
            aria-label="Rows per page"
          >
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
          </select>
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="btn btn-secondary p-2 disabled:opacity-40"
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="text-xs text-slate-600 tabular-nums">Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="btn btn-secondary p-2 disabled:opacity-40"
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* ---------------- Employee form ---------------- */}
      {modal && (
        <Modal open title={modal === 'create' ? 'Add Employee' : 'Edit Employee'} onClose={closeEdit} wide
          footer={<>
            <button type="button" onClick={closeEdit} className="btn btn-secondary">Cancel</button>
            <button type="submit" form="employee-form" disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : 'Save'}</button>
          </>}>
          <form onSubmit={save} id="employee-form" className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {field('Employee ID *', 'employee_code', { required: true })}
            {field('Employee Name *', 'name', { required: true })}
            {field('Mobile Number', 'mobile')}
            {field('Email Address', 'email', { type: 'email' })}
            {field('Department', 'department')}
            {field('Designation', 'designation')}
            {field('Joining Date', 'joining_date', { type: 'date' })}
            <div>
              <label className="block text-xs text-slate-500 mb-1">Status</label>
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="input">
                <option value="Active">Active</option>
                <option value="Inactive">Inactive</option>
              </select>
            </div>

            {isHr && (
              <>
                <div className="md:col-span-2 mt-2 border-t border-gray-100 pt-4 flex items-center gap-2">
                  <ShieldCheck size={15} className="text-amber-600" />
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Personal &amp; Bank Details</span>
                  <span className="text-[0.6875rem] text-slate-400">(HR / Admin only)</span>
                </div>
                {field('Aadhaar Number', 'aadhaar_number', { placeholder: '12 digits', inputMode: 'numeric' }, errors.aadhaar_number)}
                {field('PAN Number', 'pan_number', { placeholder: 'ABCDE1234F' }, errors.pan_number)}
                {field('Bank Account Number', 'bank_account_number', { inputMode: 'numeric' })}
                {field('IFSC Code', 'ifsc_code', { placeholder: 'ABCD0123456' }, errors.ifsc_code)}
                {field('Bank Name (optional)', 'bank_name')}
                {field('Branch Name (optional)', 'branch_name')}
              </>
            )}
          </form>
        </Modal>
      )}

      {/* ---------------- Export ---------------- */}
      {exportOpen && (
        <Modal open title="Export Employees" onClose={() => setExportOpen(false)} wide
          footer={<>
            <button onClick={() => setExportOpen(false)} className="btn btn-secondary">Cancel</button>
            <button onClick={runExport} className="btn btn-primary"><Download size={15} /> Download</button>
          </>}>
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Format</label>
              <div className="flex gap-2">
                {['csv', 'xlsx', 'pdf'].map((f) => (
                  <button key={f} onClick={() => setExportFormat(f)}
                    className={`btn ${exportFormat === f ? 'btn-primary' : 'btn-secondary'} uppercase`}>{f}</button>
                ))}
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Records</label>
              <div className="flex gap-2 flex-wrap">
                <button onClick={() => setExportScope('filtered')}
                  className={`btn ${exportScope === 'filtered' ? 'btn-primary' : 'btn-secondary'}`}>
                  Filtered list ({total})
                </button>
                <button onClick={() => setExportScope('selected')} disabled={selected.size === 0}
                  className={`btn ${exportScope === 'selected' ? 'btn-primary' : 'btn-secondary'}`}>
                  Selected ({selected.size})
                </button>
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Columns</label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                {EXPORT_COLUMNS.filter((c) => isHr || !SENSITIVE_FIELDS.includes(c.field)).map((c) => (
                  <label key={c.field} className="flex items-center gap-2 text-sm text-slate-600">
                    <input type="checkbox" checked={exportColumns.includes(c.field)}
                      onChange={() => toggleColumn(c.field)} />
                    {c.label}
                    {SENSITIVE_FIELDS.includes(c.field) && <ShieldCheck size={12} className="text-amber-500" />}
                  </label>
                ))}
              </div>
            </div>
            {isHr && anySensitive && (
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input type="checkbox" checked={unmask} onChange={(e) => setUnmask(e.target.checked)} />
                Include unmasked sensitive values (otherwise masked)
              </label>
            )}
            <p className="text-xs text-slate-400">
              Sensitive fields are excluded by default. PDF/Excel/CSV are generated with the selected columns.
            </p>
          </div>
        </Modal>
      )}

      {/* ---------------- Import ---------------- */}
      {importOpen && (
        <Modal open title="Import Employees" onClose={() => setImportOpen(false)} xwide
          footer={<>
            <button onClick={() => setImportOpen(false)} className="btn btn-secondary">
              {importResult ? 'Close' : 'Cancel'}
            </button>
            <button onClick={() => downloadFile('/employees/import/template', 'employee_import_template.csv')}
              className="btn btn-secondary"><Download size={15} /> Template</button>
            {!importResult && (
              <button onClick={confirmImport} disabled={importBusy || !preview?.summary?.valid}
                className="btn btn-primary">
                {importBusy ? 'Importing…' : `Import ${preview?.summary?.valid || 0} record(s)`}
              </button>
            )}
          </>}>
          <div className="space-y-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">File (CSV or Excel)</label>
              <input type="file" accept=".csv,.xlsx,.xls" className="input"
                onChange={(e) => {
                  const f = e.target.files?.[0] || null
                  setImportFile(f); setImportResult(null)
                  if (f) runPreview(f)
                }} />
            </div>

            {importBusy && <Loading text="Processing…" />}

            {preview && !importResult && (
              <>
                <div className="flex items-center gap-4 text-sm flex-wrap">
                  <span className="text-slate-600">Total: <b>{preview.summary.total}</b></span>
                  <span className="text-green-600">Valid: <b>{preview.summary.valid}</b></span>
                  <span className="text-amber-600">Duplicates: <b>{preview.summary.duplicates}</b></span>
                  <span className="text-red-600">Errors: <b>{preview.summary.errors}</b></span>
                </div>
                {preview.summary.duplicates > 0 && (
                  <div>
                    <label className="block text-xs text-slate-500 mb-1.5">Duplicate Employee IDs</label>
                    <select value={dupAction} onChange={(e) => setDupAction(e.target.value)} className="input sm:w-80">
                      <option value="skip">Skip existing records (keep current data)</option>
                      <option value="update">Update existing records with file values</option>
                    </select>
                  </div>
                )}
                <div className="max-h-80 overflow-auto border border-gray-100 rounded-lg">
                  <Table columns={previewColumns} data={preview.rows} keyField="row" dense />
                </div>
              </>
            )}

            {importResult && (
              <>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                  <StatCard label="Total" value={importResult.summary.total} />
                  <StatCard label="Imported" value={importResult.summary.imported} valueClass="text-green-600" />
                  <StatCard label="Updated" value={importResult.summary.updated} />
                  <StatCard label="Skipped" value={importResult.summary.skipped} valueClass="text-amber-600" />
                  <StatCard label="Errors" value={importResult.summary.errors} valueClass="text-red-600" />
                </div>
                {importResult.errors.length > 0 && (
                  <>
                    <div className="max-h-64 overflow-auto border border-gray-100 rounded-lg">
                      <Table
                        columns={[
                          { key: 'row', label: 'Row' },
                          { key: 'employee_code', label: 'Employee ID' },
                          { key: 'message', label: 'Error' },
                        ]}
                        data={importResult.errors} keyField="row" dense
                      />
                    </div>
                    <button onClick={() => downloadErrorDetails(importResult)} className="btn btn-secondary">
                      <Download size={15} /> Download error details
                    </button>
                  </>
                )}
              </>
            )}
          </div>
        </Modal>
      )}

      {/* ---------------- Details window ---------------- */}
      {detail && (
        <Modal
          open
          wide
          title="Employee Details"
          subtitle={detail.name}
          onClose={closeDetail}
          footer={
            <div className="flex flex-wrap gap-2 w-full justify-end">
              {isHr && (
                <button onClick={() => openAdvanced(detail)} className="btn btn-secondary">
                  <Settings2 size={15} /> Advanced Edit
                </button>
              )}
              <button onClick={() => editFromDetail(detail)} className="btn btn-secondary">
                <Pencil size={15} /> Edit Employee
              </button>
              <button onClick={() => remove(detail)} className="btn btn-secondary text-red-600">
                <Trash2 size={15} /> Delete Employee
              </button>
              <button onClick={() => downloadDetailPdf(detail)} className="btn btn-secondary">
                <Download size={15} /> Download PDF
              </button>
              <button onClick={closeDetail} className="btn btn-primary">Close</button>
            </div>
          }
        >
          {detailLoading ? (
            <Loading />
          ) : (
            <div className="space-y-6">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 rounded-full bg-amber-50 text-amber-600 flex items-center justify-center shrink-0">
                  <User size={22} />
                </div>
                <div className="min-w-0">
                  <div className="font-semibold text-slate-800 truncate">{dv(detail.name)}</div>
                  <div className="text-xs text-slate-500 font-mono">{dv(detail.employee_code)}</div>
                </div>
                <Badge className={`ml-auto ${detail.status === 'Active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                  {detail.status || '—'}
                </Badge>
              </div>

              <section>
                <SectionHeader title="Employment" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 mt-3">
                  <DetailField label="Employee ID" value={detail.employee_code} mono />
                  <DetailField label="Employee Name" value={detail.name} />
                  <DetailField label="Department" value={detail.department} />
                  <DetailField label="Designation" value={detail.designation} />
                  <DetailField label="Joining Date" value={detail.joining_date} />
                  <DetailField label="Employment Status" value={detail.status} />
                </div>
              </section>

              <section>
                <SectionHeader title="Contact" />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 mt-3">
                  <DetailField label="Mobile Number" value={detail.mobile} mono />
                  <DetailField label="Email" value={detail.email} />
                </div>
              </section>

              {isHr && (
                <section>
                  <SectionHeader
                    title="Personal & Bank Details"
                    right={<span className="text-[0.6875rem] text-slate-400">HR / Admin only</span>}
                  />
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-4 mt-3">
                    <DetailField label="Aadhaar Number" value={detail.aadhaar_number} mono />
                    <DetailField label="PAN Number" value={detail.pan_number} mono />
                    <DetailField label="Bank Account Number" value={detail.bank_account_number} mono />
                    <DetailField label="IFSC Code" value={detail.ifsc_code} mono />
                    <DetailField label="Bank Name" value={detail.bank_name} />
                    <DetailField label="Branch Name" value={detail.branch_name} />
                  </div>
                </section>
              )}
            </div>
          )}
        </Modal>
      )}

      {/* ---------------- Advanced Employee Details ---------------- */}
      {advBase && (
        <Modal
          open
          wide
          title="Advanced Employee Details"
          subtitle={advBase.name}
          onClose={closeAdvanced}
          footer={
            <>
              <button type="button" onClick={closeAdvanced} className="btn btn-secondary">Cancel</button>
              <button type="submit" form="employee-advanced-form" disabled={advSaving} className="btn btn-primary">
                {advSaving ? 'Saving…' : 'Save'}
              </button>
            </>
          }
        >
          <form id="employee-advanced-form" onSubmit={saveAdvanced} className="space-y-6">
            <section>
              <SectionHeader title="PF / UAN Details" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                {advSelect('PF Applicable', 'pf_applicable', APPLICABILITY)}
                {advInput('UAN (Universal Account Number)', 'uan', { placeholder: '12 digits', inputMode: 'numeric' }, advErrors.uan)}
                {advInput('PF Member ID', 'pf_member_id', { placeholder: 'e.g. MH/BAN/12345/000/0001234' }, advErrors.pf_member_id)}
                {advSelect('Previous PF Membership', 'previous_pf_membership', PREVIOUS_PF)}
                {advInput('PF Joining Date', 'pf_joining_date', { type: 'date' })}
                {advInput('PF Exit Date', 'pf_exit_date', { type: 'date' }, advErrors.pf_exit_date)}
              </div>
            </section>

            <section>
              <SectionHeader title="ESIC Details" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                {advSelect('ESIC Applicable', 'esic_applicable', APPLICABILITY)}
                {advInput('ESIC Insurance / IP Number', 'esic_ip_number', { inputMode: 'numeric' }, advErrors.esic_ip_number)}
                {advInput('ESIC Joining Date', 'esic_joining_date', { type: 'date' })}
                {advInput('ESIC Exit Date', 'esic_exit_date', { type: 'date' }, advErrors.esic_exit_date)}
                {advSelect('Registration Status', 'esic_registration_status', ESIC_REG_STATUS)}
              </div>
            </section>

            <section>
              <SectionHeader title="Verification & Record Management" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                {advSelect('Verification Status', 'verification_status', VERIFICATION_OPTIONS)}
                {advInput('Verified By', 'verified_by')}
                {advInput('Verification Date', 'verification_date', { type: 'date' })}
                {advInput('Supporting Document Reference', 'supporting_document_ref', { placeholder: 'Reference / file name / URL' })}
                <div className="md:col-span-2">
                  {advInput('Remarks', 'remarks')}
                </div>
              </div>
            </section>

            <section>
              <SectionHeader
                title="Employment Exit"
                right={<span className="text-[0.6875rem] text-slate-400">Leave blank if currently employed</span>}
              />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
                {advInput('Job Leave Date / Last Working Date', 'job_leave_date', { type: 'date' }, advErrors.job_leave_date)}
              </div>
            </section>
          </form>
        </Modal>
      )}
    </div>
  )
}
