import { useEffect, useState } from 'react'
import { Plus, Search, Download, Eye, Pencil, Trash2, RefreshCw, PackageOpen, FilePlus2, DollarSign, Layers, CheckCircle2 } from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, StatCard, SearchSelect } from '../components/ui'
import Table from '../components/Table'
import { fmtNum } from '../lib/format'

const statusCls = {
  Draft: 'bg-gray-100 text-gray-600',
  Ordered: 'bg-cyan-100 text-cyan-700',
  'Partially Received': 'bg-amber-100 text-amber-700',
  Received: 'bg-green-100 text-green-700',
  Cancelled: 'bg-red-100 text-red-600',
}
const statuses = ['Draft', 'Ordered', 'Partially Received', 'Received', 'Cancelled']

export default function Purchases() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [detail, setDetail] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [showReceive, setShowReceive] = useState(null)
  const [showImport, setShowImport] = useState(false)
  const [importFile, setImportFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [importBusy, setImportBusy] = useState(false)
  const [suppliers, setSuppliers] = useState([])
  const [products, setProducts] = useState([])
  const [form, setForm] = useState({ lines: [] })
  const [error, setError] = useState(null)

  const load = () => {
    setLoading(true)
    api.get('/purchases', { params: { search } })
      .then((res) => setItems(res.data.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t) }, [search])
  useEffect(() => {
    api.get('/suppliers', { params: { page_size: 500 } }).then((r) => setSuppliers(r.data.items || [])).catch(() => {})
    api.get('/products', { params: { page_size: 500 } }).then((r) => setProducts(r.data.items || [])).catch(() => {})
  }, [])

  const openNew = () => {
    setForm({ po_number: '', order_date: new Date().toISOString().slice(0, 10), status: 'Ordered', notes: '', supplier_id: '', supplier_name: '', lines: [{ product_id: '', description: '', item_code: '', quantity: '', received_qty: 0, rate: '', amount: '', uom: '', tax_percent: null, discount_percent: null }] })
    setError(null); setShowForm(true)
  }

  const openEdit = (po) => {
    setForm({
      id: po.id, po_number: po.po_number, supplier_id: po.supplier_id ?? '',
      supplier_name: po.supplier_name || '',
      order_date: po.order_date, status: po.status, notes: po.notes || '',
      lines: (po.lines || []).map((l) => ({ id: l.id, product_id: l.product_id ?? '', description: l.description || '', item_code: l.item_code || '', quantity: l.quantity, received_qty: l.received_qty || 0, rate: l.rate ?? '', amount: l.amount ?? '', uom: l.uom || '', tax_percent: l.tax_percent ?? null, discount_percent: l.discount_percent ?? null })),
    })
    setError(null); setShowForm(true)
  }

  const setLine = (i, k, v) => {
    const lines = [...form.lines]
    lines[i] = { ...lines[i], [k]: v }
    if ((k === 'product_id' || k === 'quantity' || k === 'rate')) {
      const q = Number(lines[i].quantity || 0)
      const r = Number(lines[i].rate || 0)
      lines[i].amount = q * r
    }
    setForm({ ...form, lines })
  }

  const setLineProduct = (i, id, manual) => {
    const lines = [...form.lines]
    const p = id ? products.find((pp) => pp.id === id) : null
    lines[i] = {
      ...lines[i],
      product_id: id,
      description: id ? lines[i].description : (manual || ''),
      item_code: p ? (lines[i].item_code || p.item_code || '') : (lines[i].item_code || (id ? '' : '')),
      uom: lines[i].uom || p?.uom || '',
    }
    const q = Number(lines[i].quantity || 0)
    const r = Number(lines[i].rate || 0)
    lines[i].amount = q * r
    setForm({ ...form, lines })
  }

  const save = async () => {
    const payload = {
      po_number: form.po_number, supplier_id: form.supplier_id ? Number(form.supplier_id) : null,
      supplier_name: (form.supplier_name || '').trim(),
      order_date: form.order_date, status: form.status || 'Ordered', notes: form.notes || '',
      lines: form.lines.filter((l) => l.product_id || (l.description || '').trim()).map((l) => ({
        product_id: l.product_id ? Number(l.product_id) : null,
        description: l.description || '',
        item_code: l.item_code || '',
        quantity: Number(l.quantity || 0), received_qty: Number(l.received_qty || 0),
        rate: l.rate !== '' && l.rate != null ? Number(l.rate) : null,
        amount: l.amount !== '' && l.amount != null ? Number(l.amount) : null,
        uom: l.uom || '',
        tax_percent: l.tax_percent ?? null,
        discount_percent: l.discount_percent ?? null,
      })),
    }
    if (!payload.po_number) { setError('PO number is required'); return }
    if (!payload.supplier_id && !payload.supplier_name) { setError('Select or type a supplier'); return }
    if (payload.lines.length === 0) { setError('Add at least one line'); return }
    try {
      if (form.id) await api.patch(`/purchases/${form.id}`, payload)
      else { const r = await api.post('/purchases', payload); setDetail(r.data) }
      setShowForm(false); setForm({ lines: [] }); setError(null); load()
    } catch (e) { setError(e.response?.data?.detail || 'Save failed') }
  }

  const del = async (po) => {
    if (!confirm(`Delete PO ${po.po_number}?`)) return
    try { await api.delete(`/purchases/${po.id}`); load() } catch (e) { alert('Delete failed: ' + (e.response?.data?.detail || e.message)) }
  }

  const columns = [
    { key: 'po_number', label: 'PO No', render: (r) => <span className="font-mono text-xs font-medium">{r.po_number}</span> },
    { key: 'supplier', label: 'Supplier', render: (r) => <span className="font-medium">{r.supplier?.name || '—'}</span> },
    { key: 'order_date', label: 'Order Date' },
    { key: 'status', label: 'Status', render: (r) => <Badge className={statusCls[r.status]}>{r.status}</Badge> },
    { key: 'total_amount', label: 'Total Amount', render: (r) => <span className="font-mono text-xs font-medium">{fmtNum(r.total_amount)}</span> },
    { key: 'lines', label: 'Lines', render: (r) => <Badge className="bg-slate-100 text-slate-600">{r.lines?.length || 0}</Badge> },
    {
      key: 'actions', label: '',
      render: (r) => {
        const pending = (r.lines || []).reduce((s, l) => s + Math.max(0, (Number(l.quantity) || 0) - (Number(l.received_qty) || 0)), 0)
        return (
          <div className="flex items-center gap-1.5">
            <button onClick={() => setDetail(r)} className="btn btn-ghost p-1.5" title="View"><Eye size={15} /></button>
            {pending > 0 && (
              <button onClick={() => setShowReceive(r)} className="btn btn-ghost p-1.5 text-green-600" title="Receive"><PackageOpen size={15} /></button>
            )}
            <button onClick={() => openEdit(r)} className="btn btn-ghost p-1.5" title="Edit"><Pencil size={15} /></button>
            <button onClick={() => del(r)} className="btn btn-ghost p-1.5 text-red-400" title="Delete"><Trash2 size={15} /></button>
          </div>
        )
      },
    },
  ]

  const received = items.filter((i) => i.status === 'Received').length
  const partial = items.filter((i) => i.status === 'Partially Received').length
  const partialOpen = items.filter((i) => ['Ordered', 'Partially Received'].includes(i.status))
  const openAmt = partialOpen.reduce((s, i) => s + (Number(i.total_amount) || 0), 0)

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Purchases" subtitle="Supplier purchase orders • Requirement → PO → Ordered → Partially Received → Received → Stock"
        actions={
          <>
            <button onClick={() => downloadFile('/reports/purchases/csv', 'purchases.csv')} className="btn btn-secondary"><Download size={15} /> CSV</button>
            <button onClick={load} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
            <button onClick={() => { setShowImport(true); setImportResult(null); setImportFile(null) }} className="btn btn-secondary text-sm">Import</button>
            <button onClick={openNew} className="btn btn-primary"><Plus size={15} /> New PO</button>
          </>
        } />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Purchase Orders" value={items.length} icon={FilePlus2} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Received" value={received} icon={CheckCircle2} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
        <StatCard label="Partially Received" value={partial} icon={Layers} iconClass="bg-amber-50 text-amber-600" valueClass="text-amber-600" />
        <StatCard label="Open Value" value={fmtNum(openAmt)} icon={DollarSign} iconClass="bg-blue-50 text-blue-600" />
      </div>

      <Card actions={
        <div className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search PO…" className="input input-icon sm:w-56" />
        </div>
      }>
        {loading ? <Loading /> : items.length === 0 ? <Empty /> : <Table columns={columns} data={items} keyField="id" stickyColumns={['po_number']} />}
      </Card>

      {detail && (
        <Modal open title={`PO ${detail.po_number}`} onClose={() => setDetail(null)} wide
          footer={<button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>}>
          <div className="grid grid-cols-2 gap-4 mb-4 text-sm">
            <div><span className="text-slate-500">Supplier:</span> <span className="font-medium">{detail.supplier?.name || '—'}</span></div>
            <div><span className="text-slate-500">Status:</span> <Badge className={statusCls[detail.status]}>{detail.status}</Badge></div>
            <div><span className="text-slate-500">Order Date:</span> {detail.order_date}</div>
            <div><span className="text-slate-500">Total:</span> <span className="font-medium">{fmtNum(detail.total_amount)}</span></div>
            {detail.notes && <div className="col-span-2"><span className="text-slate-500">Notes:</span> {detail.notes}</div>}
            {detail.warnings?.length > 0 && (
              <div className="col-span-2 rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-xs px-3 py-2">
                <strong>Stock not updated:</strong> {detail.warnings.join(' ')}
              </div>
            )}
          </div>
          <Table
            columns={[
              { key: 'product', label: 'Product', render: (l) => <span className="font-medium">{l.product?.model || l.description}</span> },
              { key: 'item_code', label: 'Item Code', render: (l) => <span className="font-mono text-xs">{l.item_code || '—'}</span> },
              { key: 'quantity', label: 'Qty', render: (l) => fmtNum(l.quantity) },
              { key: 'received_qty', label: 'Received', render: (l) => fmtNum(l.received_qty) },
              { key: 'pending', label: 'Pending', render: (l) => <span className={l.quantity - (l.received_qty || 0) > 0 ? 'text-amber-600' : 'text-green-600'}>{fmtNum((l.quantity || 0) - (l.received_qty || 0))}</span> },
              { key: 'rate', label: 'Rate', render: (l) => l.rate != null ? fmtNum(l.rate) : '—' },
              { key: 'amount', label: 'Amount', render: (l) => l.amount != null ? fmtNum(l.amount) : '—' },
              { key: 'uom', label: 'UOM', render: (l) => l.uom || '—' },
              { key: 'tax_percent', label: 'Tax %', render: (l) => l.tax_percent != null ? `${l.tax_percent}%` : '—' },
              { key: 'discount_percent', label: 'Disc %', render: (l) => l.discount_percent != null ? `${l.discount_percent}%` : '—' },
            ]}
            data={detail.lines || []}
          />
        </Modal>
      )}

      {showReceive && (
        <ReceiveModal po={showReceive} onClose={() => setShowReceive(null)} onDone={() => { load() }} />
      )}

      {showImport && (
        <div className="modal-overlay" onClick={() => setShowImport(false)}>
          <div className="modal-panel p-5 max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">Import Purchase Orders</h3>
            <p className="text-sm text-gray-500 mb-4">
              CSV or Excel. Required: PO Number, Item Code or Description, Quantity.
              Optional: Supplier, Rate, UOM, Tax %, Discount %.
            </p>
            <input type="file" accept=".csv,.xlsx,.xls" className="input mb-4" onChange={e => setImportFile(e.target.files?.[0])} />
            {importResult && (
              <div className="bg-gray-50 rounded-lg p-4 mb-4 text-sm">
                <p className="font-bold mb-1">Results</p>
                <p>Created: {importResult.summary.created}, Skipped: {importResult.summary.skipped}, Errors: {importResult.summary.errors}</p>
                {importResult.skipped.length > 0 && (
                  <ul className="mt-2 text-amber-700 text-xs">
                    {importResult.skipped.map((s, i) => <li key={i}>Row {s.rows?.[0]}: {s.po_number} — {s.reason}</li>)}
                  </ul>
                )}
                {importResult.errors.length > 0 && (
                  <ul className="mt-2 text-red-600 text-xs max-h-40 overflow-auto">
                    {importResult.errors.map((e, i) => <li key={i}>Row {e.row}: {e.message}</li>)}
                  </ul>
                )}
              </div>
            )}
            <div className="flex gap-2">
              <button onClick={async () => {
                if (!importFile) return
                const fd = new FormData(); fd.append('file', importFile)
                setImportBusy(true)
                try {
                  const { data } = await api.post('/purchases/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
                  setImportResult(data); load()
                } catch (e) { alert(e.response?.data?.detail || 'Import failed') }
                finally { setImportBusy(false) }
              }} className="btn btn-primary" disabled={importBusy}>
                {importBusy ? 'Importing…' : 'Import'}
              </button>
              <button onClick={() => { setShowImport(false); setImportResult(null); setImportFile(null) }} className="btn btn-secondary">Close</button>
            </div>
          </div>
        </div>
      )}

      {showForm && (
        <Modal open title={form.id ? `Edit PO ${form.po_number}` : 'New Purchase Order'} onClose={() => setShowForm(false)} xwide
          footer={<>
            <button onClick={() => setShowForm(false)} className="btn btn-secondary">Cancel</button>
            <button onClick={save} className="btn btn-primary">{form.id ? 'Save Changes' : 'Create PO'}</button>
          </>}>
          {error && <div className="mb-3 text-sm state-box bg-red-50 text-red-700 border border-red-200">{error}</div>}
          <div className="grid grid-cols-2 gap-3 text-sm mb-3">
            <div><label className="block text-slate-500 text-xs mb-1">PO Number *</label>
              <input value={form.po_number || ''} onChange={(e) => setForm({ ...form, po_number: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Order Date</label>
              <input type="date" value={form.order_date || ''} onChange={(e) => setForm({ ...form, order_date: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Supplier</label>
              <SearchSelect
                options={suppliers.map((s) => ({ id: s.id, label: s.company || s.name }))}
                value={form.supplier_id || null}
                initialLabel={!form.supplier_id ? (form.supplier_name || '') : ''}
                placeholder="Type to search suppliers or enter a manual supplier name"
                onChange={(id, manual) => setForm((f) => ({ ...f, supplier_id: id, supplier_name: manual }))}
              /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Status</label>
              <select value={form.status || 'Ordered'} onChange={(e) => setForm({ ...form, status: e.target.value })} className="input">
                {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
              </select></div>
            <div className="col-span-2"><label className="block text-slate-500 text-xs mb-1">Notes</label>
              <input value={form.notes || ''} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="input" /></div>
          </div>

          <div className="mb-1 text-xs font-medium text-slate-500 uppercase">Purchase Lines</div>
          <div className="hidden sm:grid grid-cols-12 gap-2 items-center text-[10px] uppercase tracking-wide text-slate-400 mb-1 px-1">
            <div className="col-span-3">Product / Manual Item</div>
            <div className="col-span-1">Item Code</div>
            <div className="col-span-1">Qty</div>
            <div className="col-span-1">Rate</div>
            <div className="col-span-1">UOM</div>
            <div className="col-span-2">Tax %</div>
            <div className="col-span-2">Disc %</div>
            <div className="col-span-1" />
          </div>
          <div className="space-y-2">
            {form.lines.map((ln, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-center text-xs">
                <SearchSelect
                  options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''}` }))}
                  value={ln.product_id || null}
                  initialLabel={!ln.product_id ? (ln.description || '') : ''}
                  placeholder="Product or manual item…"
                  className="input col-span-3 py-2"
                  onChange={(id, manual) => setLineProduct(i, id || '', manual)}
                />
                <input value={ln.item_code ?? ''} onChange={(e) => setLine(i, 'item_code', e.target.value)}
                  placeholder="Code" className="input col-span-1 py-2" />
                <input value={ln.quantity ?? ''} type="number" onChange={(e) => setLine(i, 'quantity', e.target.value)} placeholder="Qty" className="input col-span-1 py-2" />
                <input value={ln.rate ?? ''} type="number" onChange={(e) => setLine(i, 'rate', e.target.value)} placeholder="Rate" className="input col-span-1 py-2" />
                <input value={ln.uom || ''} onChange={(e) => setLine(i, 'uom', e.target.value)} placeholder="UOM" className="input col-span-1 py-2" />
                <input value={ln.tax_percent ?? ''} type="number" min="0" step="0.01" onChange={(e) => setLine(i, 'tax_percent', e.target.value === '' ? null : Number(e.target.value))} placeholder="Tax %" className="input col-span-2 py-2 text-sm font-semibold text-right" />
                <input value={ln.discount_percent ?? ''} type="number" min="0" step="0.01" onChange={(e) => setLine(i, 'discount_percent', e.target.value === '' ? null : Number(e.target.value))} placeholder="Disc %" className="input col-span-2 py-2 text-sm font-semibold text-right" />
                <button onClick={() => { if (form.lines.length > 1) setForm({ ...form, lines: form.lines.filter((_, j) => j !== i) }) }} className="col-span-1 text-red-400 hover:text-red-600"><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
          <button onClick={() => setForm({ ...form, lines: [...form.lines, { product_id: '', description: '', item_code: '', quantity: '', received_qty: 0, rate: '', amount: '', uom: '', tax_percent: null, discount_percent: null }] })} className="btn btn-ghost mt-2 text-xs"><Plus size={12} className="inline mr-1" />Add line</button>
        </Modal>
      )}
    </div>
  )
}

function ReceiveModal({ po, onClose, onDone }) {
  const [poData, setPoData] = useState(po)
  const [receiveQty, setReceiveQty] = useState({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [warning, setWarning] = useState(po.warnings || [])
  const [msg, setMsg] = useState(null)

  const notify = (text) => { setMsg(text); setTimeout(() => setMsg(null), 3000) }

  const doReceive = async (line) => {
    const receiveNow = Number(receiveQty[line.id] || 0)
    const already = Number(line.received_qty || 0)
    const remaining = Number(line.quantity || 0) - already
    if (!(receiveNow > 0)) { setErr(`Enter the quantity received for: ${line.description || line.item_code || 'this line'}`); return }
    if (receiveNow > remaining) { setErr(`Cannot receive ${receiveNow} — only ${remaining} remaining on this line`); return }
    setBusy(true); setErr(null); setMsg(null)
    try {
      const { data } = await api.post(`/purchases/${poData.id}/receive`, null, {
        params: { line_id: line.id, received_qty: already + receiveNow }
      })
      setPoData(data)
      setWarning(data.warnings || [])
      setReceiveQty(q => ({ ...q, [line.id]: '' }))
      notify(`Received ${receiveNow} → cumulative ${already + receiveNow}`)
      onDone()
    } catch (e) {
      setErr(e.response?.data?.detail || 'Receive failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-panel p-5 max-w-4xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h3 className="text-lg font-bold mb-1">Receive: {poData.po_number}</h3>
            <p className="text-sm text-gray-500">{poData.supplier?.name || poData.supplier_name || 'Supplier'}</p>
          </div>
          <Badge className={statusCls[poData.status]}>{poData.status}</Badge>
        </div>
        {warning.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded p-3 mb-4 text-sm text-amber-800">
            {warning.map((w, i) => <div key={i}>{w}</div>)}
          </div>
        )}
        {msg && <div className="bg-green-50 border border-green-200 rounded p-3 mb-4 text-sm text-green-800">{msg}</div>}
        <div className="space-y-4">
          {(poData.lines || []).map(line => {
            const already = Number(line.received_qty || 0)
            const ordered = Number(line.quantity || 0)
            const remaining = Math.max(ordered - already, 0)
            const done = ordered > 0 && remaining <= 0
            const partial = already > 0 && !done
            return (
              <div key={line.id} className="border border-slate-200 rounded-xl bg-slate-50/60 p-4">
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-slate-800 truncate">{line.description || line.product?.model || line.item_code || 'Line item'}</div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {line.item_code && <span className="font-mono">{line.item_code}</span>}
                      {line.item_code && line.uom && <span className="mx-1.5 text-slate-300">|</span>}
                      {line.uom && <span>{line.uom}</span>}
                    </div>
                  </div>
                  <Badge className={done ? 'bg-green-100 text-green-700' : partial ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-600'}>
                    {done ? 'Received' : partial ? 'Partial' : 'Pending'}
                  </Badge>
                </div>
                <div className="grid grid-cols-3 gap-3 mb-4">
                  <div className="rounded-lg bg-white border border-slate-200 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-400 font-medium">Ordered</div>
                    <div className="text-lg font-bold text-slate-800">{fmtNum(ordered)}</div>
                  </div>
                  <div className="rounded-lg bg-white border border-slate-200 px-3 py-2">
                    <div className="text-[10px] uppercase tracking-wide text-slate-400 font-medium">Already Received</div>
                    <div className="text-lg font-bold text-green-700">{fmtNum(already)}</div>
                  </div>
                  <div className={`rounded-lg border px-3 py-2 ${remaining > 0 ? 'bg-amber-50 border-amber-200' : 'bg-white border-slate-200'}`}>
                    <div className="text-[10px] uppercase tracking-wide text-slate-400 font-medium">Remaining</div>
                    <div className={`text-lg font-bold ${remaining > 0 ? 'text-amber-700' : 'text-green-700'}`}>{fmtNum(remaining)}</div>
                  </div>
                </div>
                <div className="flex items-end gap-3">
                  <div className="flex-1">
                    <label className="block text-xs font-medium text-slate-500 mb-1">Receive Quantity (this receipt)</label>
                    <input type="number" className="input w-full text-xl font-bold py-3" min="0" max={remaining} step="0.01"
                      value={receiveQty[line.id] || ''} placeholder={`0 — ${remaining} remaining`}
                      onChange={e => setReceiveQty(q => ({ ...q, [line.id]: e.target.value }))} />
                  </div>
                  <button onClick={() => doReceive(line)} className="btn btn-primary px-6 py-2.5 text-sm"
                    disabled={busy || remaining <= 0}>
                    {busy ? 'Saving…' : 'Receive'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
        {err && <div className="text-red-500 text-sm mt-3">{err}</div>}
        <button onClick={onClose} className="btn btn-secondary mt-4">Close</button>
      </div>
    </div>
  )
}