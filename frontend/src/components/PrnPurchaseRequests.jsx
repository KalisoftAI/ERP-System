import { useCallback, useEffect, useState } from 'react'
import { Search, RefreshCw, Eye, FileSearch, Plus, PackageCheck, Clock, CheckCircle2 } from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { Card, Modal, Loading, Empty, Badge, StatCard, PageTabs, StatusBadge } from './ui'
import Table from './Table'
import { fmtNum } from '../lib/format'

const STATUS_CLS = {
  'Awaiting PO': 'bg-amber-100 text-amber-700',
  'PO Created': 'bg-cyan-100 text-cyan-700',
  'Partially Received': 'bg-blue-100 text-blue-700',
  Completed: 'bg-green-100 text-green-700',
  Cancelled: 'bg-red-100 text-red-600',
}

const TABS = [
  { key: 'requests', label: 'Requests' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'partially', label: 'Partially Received' },
  { key: 'completed', label: 'Completed' },
]

const PRIORITY_CLS = {
  Critical: 'bg-red-100 text-red-700',
  Urgent: 'bg-amber-100 text-amber-700',
  Normal: 'bg-gray-100 text-gray-600',
}

/**
 * Purchase Department workspace: the queue of PRNs handed over to purchasing.
 * Read-only here except for "Create Purchase Order", which prefills the
 * existing New PO form in the parent (Purchases) — no PO is created directly.
 */
export default function PrnPurchaseRequests({ onCreatePurchaseOrder }) {
  const [view, setView] = useState('requests')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [counts, setCounts] = useState({ requests: 0, in_progress: 0, partially_received: 0, completed: 0 })
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadCounts = useCallback(() => {
    api.get('/prn/purchase-requests/count')
      .then((r) => setCounts(r.data || {}))
      .catch(() => {})
  }, [])

  const load = useCallback(() => {
    setLoading(true)
    api.get('/prn/purchase-requests', { params: { view, search, page_size: 500 } })
      .then((r) => { setItems(r.data.items || []); setTotal(r.data.total || 0) })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [view, search])

  useEffect(() => { loadCounts() }, [loadCounts])
  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
  }, [load])

  const openDetail = (prn) => {
    setDetail({ id: prn.id, prn_number: prn.prn_number, loading: true })
    setDetailLoading(true)
    api.get(`/prn/${prn.id}`)
      .then((r) => setDetail(r.data))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  const tabs = TABS.map((t) => ({
    ...t,
    count: t.key === 'requests' ? counts.requests
      : t.key === 'in_progress' ? counts.in_progress
        : t.key === 'partially' ? counts.partially_received
          : counts.completed,
  }))

  const columns = [
    { key: 'prn_number', label: 'PRN No.', render: (r) => <span className="font-mono text-xs font-semibold">{r.prn_number}</span> },
    { key: 'prn_date', label: 'PRN Date' },
    { key: 'department', label: 'Department', render: (r) => r.department || '—' },
    { key: 'requested_by_name', label: 'Requested By', render: (r) => r.requested_by_name || '—' },
    { key: 'required_by_date', label: 'Required By', render: (r) => r.required_by_date || '—' },
    { key: 'priority', label: 'Priority', render: (r) => <Badge className={PRIORITY_CLS[r.priority] || PRIORITY_CLS.Normal}>{r.priority}</Badge> },
    { key: 'item_count', label: 'Items', render: (r) => r.item_count },
    { key: 'purchasing_status', label: 'Purchasing', render: (r) => <Badge className={STATUS_CLS[r.purchasing_status] || 'bg-gray-100 text-gray-600'}>{r.purchasing_status}</Badge> },
    { key: 'linked_pos', label: 'POs', render: (r) => <Badge className="bg-slate-100 text-slate-600">{r.linked_pos?.length || 0}</Badge> },
    { key: 'actions', label: 'Actions', render: (r) => (
      <div className="flex items-center gap-1">
        <button onClick={() => openDetail(r)} title="View" className="btn-icon"><Eye size={15} /></button>
        {r.purchasing_status !== 'Completed' && onCreatePurchaseOrder && (
          <button onClick={() => onCreatePurchaseOrder(prefillFrom(r))} title="Create Purchase Order" className="btn-icon text-cyan-600"><Plus size={15} /></button>
        )}
      </div>
    ) },
  ]

  return (
    <div>
      <PageTabs tabs={tabs} active={view} onChange={setView} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Awaiting PO" value={counts.requests || 0} icon={Clock} iconClass="bg-amber-50 text-amber-600" valueClass="text-amber-600" />
        <StatCard label="In Progress" value={counts.in_progress || 0} icon={FileSearch} iconClass="bg-cyan-50 text-cyan-600" valueClass="text-cyan-600" />
        <StatCard label="Partially Received" value={counts.partially_received || 0} icon={PackageCheck} iconClass="bg-blue-50 text-blue-600" valueClass="text-blue-600" />
        <StatCard label="Completed" value={counts.completed || 0} icon={CheckCircle2} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
      </div>

      <Card actions={
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search PRN no. / material…" className="input input-icon sm:w-56" />
          </div>
          <button onClick={() => { load(); loadCounts() }} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
        </div>
      }>
        <div className="text-sm text-slate-500 mb-2">{total} request(s)</div>
        {loading ? <Loading /> : items.length === 0 ? <Empty text="No purchase requests in this view" /> :
          <Table columns={columns} data={items} keyField="id" onRowClick={openDetail} stickyColumns={['prn_number']} />}
      </Card>

      {detail && (
        <Modal open xwide title={detail.loading ? 'Loading…' : detail.prn_number}
          subtitle={detail.loading ? '' : `${detail.department || ''} · ${detail.purchasing_status || detail.status}`}
          onClose={() => setDetail(null)}
          footer={detailLoading || detail.loading ? null : (
            <>
              {detail.purchasing_status !== 'Completed' && onCreatePurchaseOrder && (
                <button onClick={() => onCreatePurchaseOrder(prefillFrom(detail))} className="btn btn-primary mr-auto">
                  <Plus size={14} /> Create Purchase Order
                </button>
              )}
              <button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>
            </>
          )}>
          {detailLoading || detail?.loading ? <Loading /> : <DetailBody detail={detail} />}
        </Modal>
      )}
    </div>
  )
}

function prefillFrom(prn) {
  return {
    prn_id: prn.id,
    prn_number: prn.prn_number,
    lines: (prn.lines || []).map((l) => ({
      prn_line_id: l.id,
      product_id: l.material_id || null,
      description: l.description || '',
      item_code: l.material_code || '',
      quantity: Number(l.remaining_qty != null ? l.remaining_qty : l.quantity) || 0,
      uom: l.uom || '',
    })),
  }
}

function DetailBody({ detail }) {
  return (
    <div className="max-h-[70vh] overflow-y-auto pr-1">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-sm">
        <div><span className="text-slate-500 block text-xs">PRN Date</span><span className="font-medium">{detail.prn_date || '—'}</span></div>
        <div><span className="text-slate-500 block text-xs">Department</span><span className="font-medium">{detail.department || '—'}</span></div>
        <div><span className="text-slate-500 block text-xs">Requested By</span><span className="font-medium">{detail.requested_by_name || '—'}</span></div>
        <div><span className="text-slate-500 block text-xs">Required By</span><span className="font-medium">{detail.required_by_date || '—'}</span></div>
        <div><span className="text-slate-500 block text-xs">Priority</span><Badge className={PRIORITY_CLS[detail.priority] || PRIORITY_CLS.Normal}>{detail.priority}</Badge></div>
        <div><span className="text-slate-500 block text-xs">Requirement Type</span><span className="font-medium">{detail.requirement_type || '—'}</span></div>
        <div><span className="text-slate-500 block text-xs">Purchasing</span><Badge className={STATUS_CLS[detail.purchasing_status] || 'bg-gray-100 text-gray-600'}>{detail.purchasing_status || detail.status}</Badge></div>
        <div><span className="text-slate-500 block text-xs">Fulfilment</span><StatusBadge status={detail.fulfillment_status} /></div>
        {detail.purpose && <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Purpose of Requisition</span><span className="font-medium">{detail.purpose}</span></div>}
        {detail.purchase_remarks && <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Purchase Remarks</span><span className="font-medium">{detail.purchase_remarks}</span></div>}
      </div>

      <div className="table-wrap mb-4">
        <table className="data-table table-dense">
          <thead><tr>
            <th>Sr. No.</th><th>Item Code</th><th>Material Description</th><th>UOM</th>
            <th>Required</th><th>Ordered</th><th>Received</th><th>Remaining</th><th>File</th>
          </tr></thead>
          <tbody>
            {(detail.lines || []).map((l, i) => (
              <tr key={l.id}>
                <td className="text-xs text-slate-500">{i + 1}</td>
                <td className="font-mono text-xs">{l.material_code || '—'}</td>
                <td className="font-medium">
                  {l.description}
                  {l.is_new_material && <span className="block text-[10px] text-amber-600">Manual Entry – Item Master Review Required</span>}
                </td>
                <td>{l.uom || '—'}</td>
                <td>{fmtNum(l.quantity)}</td>
                <td>{fmtNum(l.ordered_qty || 0)}</td>
                <td className="text-green-700">{fmtNum(l.received_qty || 0)}</td>
                <td className="text-amber-700">{fmtNum(l.remaining_qty || 0)}</td>
                <td>{l.has_attachment
                  ? <button onClick={() => downloadFile(`/prn/${detail.id}/lines/${l.id}/attachment`, l.attachment_name)} className="text-sky-600 hover:underline text-xs">Download</button>
                  : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(detail.linked_pos || []).length > 0 && (
        <>
          <div className="text-sm font-semibold text-slate-700 mb-2">Linked Purchase Orders</div>
          <div className="table-wrap mb-4">
            <table className="data-table table-dense">
              <thead><tr><th>PO No.</th><th>Order Date</th><th>Status</th><th>Ordered Qty</th><th>Received Qty</th><th>Value</th></tr></thead>
              <tbody>
                {detail.linked_pos.map((po) => (
                  <tr key={po.id}>
                    <td className="font-mono text-xs">{po.po_number}</td>
                    <td>{po.order_date || '—'}</td>
                    <td><StatusBadge status={po.status} /></td>
                    <td>{fmtNum(po.ordered_qty)}</td>
                    <td className="text-green-700">{fmtNum(po.received_qty)}</td>
                    <td>{fmtNum(po.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
