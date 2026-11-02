import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Download, Printer, FileText, History, Trash2,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { Loading, Modal, Badge, StatusBadge } from '../components/ui'
import Table from '../components/Table'
import PrnEditorModal, { lineFromApi } from '../components/PrnEditorModal'
import { fmtNum } from '../lib/format'

const PRIORITY_CLS = {
  Critical: 'bg-red-100 text-red-700',
  Urgent: 'bg-amber-100 text-amber-700',
  Normal: 'bg-gray-100 text-gray-600',
}

const PURCHASING_CLS = {
  'Awaiting PO': 'bg-amber-100 text-amber-700',
  'PO Created': 'bg-cyan-100 text-cyan-700',
  'Partially Received': 'bg-blue-100 text-blue-700',
  Completed: 'bg-green-100 text-green-700',
  Cancelled: 'bg-red-100 text-red-600',
}

const EMPTY_LOOKUPS = {
  meta: { priorities: [], requirement_types: [], statuses: [] },
  departments: [],
  materials: [],
  locations: [],
}

export default function PrnDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [lookups, setLookups] = useState(EMPTY_LOOKUPS)

  useEffect(() => {
    let alive = true
    Promise.all([
      api.get('/prn/constants').then((r) => r.data).catch(() => EMPTY_LOOKUPS.meta),
      api.get('/prn/departments').then((r) => r.data || []).catch(() => []),
      api.get('/prn/materials', { params: { limit: 200 } }).then((r) => r.data || []).catch(() => []),
      api.get('/prn/locations').then((r) => r.data || []).catch(() => []),
    ]).then(([meta, departments, materials, locations]) => {
      if (alive) setLookups({ meta, departments, materials, locations })
    })
    return () => { alive = false }
  }, [])

  return (
    <PrnDetailModal
      prnId={id}
      lookups={lookups}
      onClose={() => navigate('/prn')}
    />
  )
}

/**
 * PRN details in the same centered-modal layout as the PO details modal.
 * The register passes its already-loaded lookups so opening a PRN only costs
 * the single detail request.
 */
export function PrnDetailModal({ prnId, onClose, onDeleted, onChanged, lookups = EMPTY_LOOKUPS, currentUser }) {
  const { user: authUser } = useAuth()
  const user = currentUser || authUser
  const isAdmin = user?.role === 'admin'
  const { meta, departments, materials, locations } = lookups

  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editor, setEditor] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(() => {
    if (!prnId) return
    setLoading(true)
    api.get(`/prn/${prnId}`)
      .then((r) => setDetail(r.data))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
  }, [prnId])

  useEffect(() => {
    setDetail(null)
    setEditor(null)
    setConfirmDelete(false)
    setError('')
    reload()
  }, [reload])

  // Keep the page locked while a nested modal (editor / delete confirm) closes.
  useEffect(() => {
    document.body.style.overflow = 'hidden'
  }, [confirmDelete, editor])

  const openEdit = () => {
    if (!detail) return
    setEditor({ mode: 'edit', prn: { ...detail, lines: (detail.lines || []).map(lineFromApi) } })
  }

  // Escape/X on the detail modal must not also close an open editor or
  // delete-confirmation modal stacked above it.
  const handleClose = () => {
    if (confirmDelete || editor) return
    onClose?.()
  }

  const remove = async () => {
    setError('')
    setBusy(true)
    try {
      await api.delete(`/prn/${prnId}`)
      setConfirmDelete(false)
      onDeleted?.()
      onClose?.()
    } catch (err) {
      setError('Delete failed: ' + (err.response?.data?.detail || err.message))
      setBusy(false)
    }
  }

  const print = async () => {
    try {
      const res = await api.get(`/prn/${prnId}/pdf`, { responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
      const w = window.open(url, '_blank')
      if (!w) { URL.revokeObjectURL(url); downloadFile(`/prn/${prnId}/pdf`, `${detail?.prn_number || 'PRN'}.pdf`); return }
      setTimeout(() => URL.revokeObjectURL(url), 60000)
    } catch (err) {
      if (err.response?.status !== 401) setError('Could not generate PDF: ' + (err.response?.data?.detail || err.message))
    }
  }

  const pdf = () => downloadFile(`/prn/${prnId}/pdf`, `${detail?.prn_number || 'PRN'}.pdf`)

  const requester = detail?.requested_by_id === user?.id
  const canEdit = requester || isAdmin
  const canDelete = (requester || isAdmin) && !(detail?.linked_pos && detail.linked_pos.length)

  const lineRows = (detail?.lines || []).map((l, i) => ({ ...l, _sr: i + 1 }))
  const lineColumns = [
    { key: '_sr', label: 'Sr.', render: (l) => <span className="text-xs text-slate-500">{l._sr}</span> },
    { key: 'material_code', label: 'Item Code', render: (l) => <span className="font-mono text-xs">{l.material_code || '—'}</span> },
    {
      key: 'description',
      label: 'Material Description',
      render: (l) => (
        <div className="font-medium min-w-[170px]">
          {l.description}
          {l.is_new_material && <span className="block text-[10px] text-amber-600">Manual Entry – Item Master Review Required</span>}
        </div>
      ),
    },
    { key: 'specification', label: 'Specification', render: (l) => <span className="text-xs">{l.specification || '—'}</span> },
    { key: 'uom', label: 'UOM', render: (l) => l.uom || '—' },
    { key: 'quantity', label: 'Required Qty', render: (l) => <span className="font-medium">{fmtNum(l.quantity)}</span> },
    {
      key: 'available_stock',
      label: 'Inventory Stock',
      render: (l) => (
        <>
          <span title="Actual inventory at request time (read-only)">
            {l.available_stock == null ? 'Unknown' : fmtNum(l.available_stock)}
          </span>
          {l.material_id && l.location && <span className="block text-[10px] text-slate-400">{l.location}</span>}
        </>
      ),
    },
    {
      key: 'stock_override',
      label: 'PRN Stock Override',
      render: (l) => (
        <>
          {l.stock_override == null
            ? '—'
            : <span className="font-semibold text-amber-700">{fmtNum(l.stock_override)}</span>}
          {l.stock_overridden_by_name && <span className="block text-[10px] text-slate-400">by {l.stock_overridden_by_name}</span>}
        </>
      ),
    },
    { key: 'remarks', label: 'Purpose / Remarks', render: (l) => <span className="text-xs">{l.remarks || '—'}</span> },
    {
      key: 'file',
      label: 'File',
      render: (l) => (l.has_attachment
        ? <button onClick={() => downloadFile(`/prn/${detail.id}/lines/${l.id}/attachment`, l.attachment_name)} className="text-sky-600 hover:underline text-xs">Download</button>
        : '—'),
    },
  ]

  return (
    <>
      <Modal
        open
        xwide
        title={loading ? 'Loading…' : detail ? `PRN ${detail.prn_number}` : 'PRN'}
        subtitle={detail ? [detail.department, detail.priority].filter(Boolean).join(' · ') : undefined}
        onClose={handleClose}
        footer={!detail || loading ? (
          <button onClick={handleClose} className="btn btn-secondary">Close</button>
        ) : (
          <>
            <div className="flex items-center gap-2 mr-auto">
              {canDelete && (
                <button disabled={busy} onClick={() => { setError(''); setConfirmDelete(true) }} className="btn btn-danger">
                  <Trash2 size={14} className="mr-1" /> Delete
                </button>
              )}
            </div>
            <div className="flex items-center gap-2">
              {canEdit && <button onClick={openEdit} className="btn btn-secondary"><FileText size={14} className="mr-1" /> Edit</button>}
              <button onClick={pdf} className="btn btn-secondary"><Download size={14} className="mr-1" /> PDF</button>
              <button onClick={print} className="btn btn-secondary"><Printer size={14} className="mr-1" /> Print</button>
              <button onClick={handleClose} className="btn btn-secondary">Close</button>
            </div>
          </>
        )}
      >
        {loading ? <Loading text="Loading PRN…" /> : !detail ? (
          <div className="text-sm text-slate-500 py-6 text-center">PRN not found.</div>
        ) : (
          <div className="max-h-[70vh] overflow-y-auto pr-1">
            {error && <div className="mb-3 text-sm bg-red-50 text-red-700 border border-red-200 rounded px-3 py-2">{error}</div>}

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-sm">
              <div><span className="text-slate-500 block text-xs">PRN Date</span><span className="font-medium">{detail.prn_date || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Department</span><span className="font-medium">{detail.department || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Requested By</span><span className="font-medium">{detail.requested_by_name || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Required By</span><span className="font-medium">{detail.required_by_date || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Priority</span><Badge className={PRIORITY_CLS[detail.priority] || PRIORITY_CLS.Normal}>{detail.priority}</Badge></div>
              <div><span className="text-slate-500 block text-xs">Requirement Type</span><span className="font-medium">{detail.requirement_type || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Status</span><StatusBadge status={detail.status} /></div>
              <div><span className="text-slate-500 block text-xs">Purchasing</span><Badge className={PURCHASING_CLS[detail.purchasing_status] || 'bg-gray-100 text-gray-600'}>{detail.purchasing_status || '—'}</Badge></div>
              <div><span className="text-slate-500 block text-xs">Department Head</span><span className="font-medium">{detail.department_head || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Checked By (Store)</span><span className="font-medium">{detail.checked_by_name || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Purchase Ref</span><span className="font-medium">{detail.purchase_reference || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Company</span><span className="font-medium">{detail.company_name || '—'}</span></div>
              {detail.fulfillment_status && <div><span className="text-slate-500 block text-xs">Fulfilment</span><StatusBadge status={detail.fulfillment_status} /></div>}
              {detail.production_reference && <div><span className="text-slate-500 block text-xs">Production Ref</span><span className="font-medium">{detail.production_reference}</span></div>}
              {detail.approved_by_name && <div><span className="text-slate-500 block text-xs">Approved By</span><span className="font-medium">{detail.approved_by_name}</span></div>}
              {detail.purpose && <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Purpose of Requisition</span><span className="font-medium">{detail.purpose}</span></div>}
              {detail.purchase_remarks && <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Purchase Department Remarks</span><span className="font-medium">{detail.purchase_remarks}</span></div>}
              {detail.rejection_reason && <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Rejection Reason</span><span className="font-medium text-red-600">{detail.rejection_reason}</span></div>}
            </div>

            <Table columns={lineColumns} data={lineRows} dense />

            {(detail.linked_pos || []).length > 0 && (
              <div className="mt-6">
                <div className="text-sm font-semibold text-slate-700 mb-2">Linked Purchase Orders</div>
                <Table
                  dense
                  columns={[
                    { key: 'po_number', label: 'PO No.', render: (po) => <span className="font-mono text-xs">{po.po_number}</span> },
                    { key: 'order_date', label: 'Order Date', render: (po) => po.order_date || '—' },
                    { key: 'status', label: 'Status', render: (po) => <StatusBadge status={po.status} /> },
                    { key: 'ordered_qty', label: 'Ordered Qty', render: (po) => fmtNum(po.ordered_qty) },
                    { key: 'received_qty', label: 'Received Qty', render: (po) => <span className="text-green-700">{fmtNum(po.received_qty)}</span> },
                    { key: 'total_amount', label: 'Value', render: (po) => fmtNum(po.total_amount) },
                  ]}
                  data={detail.linked_pos}
                />
              </div>
            )}

            <div className="mt-6 pt-4 border-t border-slate-200">
              <div className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2"><History size={15} /> Activity History</div>
              <div className="text-xs text-slate-600 space-y-1">
                {(detail.history || []).length === 0 ? <div className="text-slate-400">No history yet.</div> :
                  detail.history.map((h, i) => (
                    <div key={i} className="flex gap-2">
                      <span className="text-slate-400 w-36 shrink-0">{(h.created_at || '').replace('T', ' ').slice(0, 16)}</span>
                      <span className="font-medium w-28 shrink-0">{h.action}</span>
                      <span>{h.details}</span>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {confirmDelete && (
        <Modal open title="Delete PRN?" subtitle={detail?.prn_number}
          onClose={() => setConfirmDelete(false)}
          footer={(
            <div className="flex items-center justify-end gap-2 w-full">
              <button onClick={() => setConfirmDelete(false)} className="btn btn-secondary">Cancel</button>
              <button onClick={remove} disabled={busy} className="btn btn-danger">{busy ? 'Deleting…' : 'Delete'}</button>
            </div>
          )}>
          <p className="text-sm text-slate-600">This permanently removes the PRN and cannot be undone.</p>
          {error && <div className="mt-3 text-sm bg-red-50 text-red-700 border border-red-200 rounded px-3 py-2">{error}</div>}
        </Modal>
      )}

      {editor && (
        <PrnEditorModal editor={editor} setEditor={setEditor} meta={meta} departments={departments}
          materials={materials} locations={locations} currentUser={user}
          onSaved={() => { setEditor(null); reload(); onChanged?.() }} />
      )}
    </>
  )
}
