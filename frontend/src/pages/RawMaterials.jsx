import { useEffect, useState } from 'react'
import {
  Plus, Pencil, Trash2, Eye, Search, Download, RefreshCw, Package,
  AlertTriangle, CheckCircle2, Boxes, ArrowDownToLine, ClipboardList,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, StatCard } from '../components/ui'
import Table from '../components/Table'
import { fmtNum } from '../lib/format'

const stockStatus = (item) => {
  const cur = Number(item.current_stock)
  const min = item.balance?.min_stock
  if (min == null) return cur <= 0 ? { label: 'Low', cls: 'bg-amber-100 text-amber-700' } : { label: 'Normal', cls: 'bg-green-100 text-green-700' }
  if (cur < min) return { label: 'Reorder', cls: 'bg-red-100 text-red-700' }
  return { label: 'Normal', cls: 'bg-green-100 text-green-700' }
}

const emptyForm = { item_code: '', model: '', name: '', uom: 'Each', min_stock_level: '' }

const masterFields = (r) => ({
  id: r.id,
  item_code: r.item_code || '',
  model: r.model || '',
  name: r.name || '',
  uom: r.uom || 'Each',
  min_stock_level: r.min_stock_level ?? '',
})

export default function RawMaterials() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState(null)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState(emptyForm)
  const [balance, setBalance] = useState({})
  const [view, setView] = useState(null)
  const [err, setErr] = useState(null)
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [openingStock, setOpeningStock] = useState('')
  const [showInactive, setShowInactive] = useState(false)
  const [stockModal, setStockModal] = useState(null)
  const [stockValue, setStockValue] = useState('')
  const [stockRemarks, setStockRemarks] = useState('')
  const [stockBusy, setStockBusy] = useState(false)
  const [stockErr, setStockErr] = useState(null)
  const [showImport, setShowImport] = useState(false)
  const [importFile, setImportFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [importBusy, setImportBusy] = useState(false)

  const load = () => {
    setLoading(true)
    api.get('/raw-materials', { params: { search, include_inactive: showInactive } })
      .then((res) => setItems(res.data.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])
  useEffect(() => { const t = setTimeout(load, 300); return () => clearTimeout(t) }, [search, showInactive])

  const notify = (text, isErr = false) => {
    if (isErr) { setMsg(null); setErr(text); return }
    setErr(null); setMsg(text)
    setTimeout(() => setMsg(null), 3000)
  }

  const openNew = () => { setEditing(false); setForm({ ...emptyForm }); setOpeningStock(''); setErr(null); setModal('form') }
  const openEdit = (row) => { setEditing(true); setForm(masterFields(row)); setErr(null); setModal('form') }

  const openView = async (row) => {
    setErr(null)
    setView(row)
    setModal('view')
    try {
      const res = await api.get(`/raw-materials/${row.id}`)
      setView(res.data)
    } catch (e) {
      setView(row)
    }
  }

  const saveMaterial = async (e) => {
    e.preventDefault()
    if (!(form.model || '').trim()) { notify('Material name is required', true); return }
    setSaving(true)
    try {
      const payload = {
        item_code: form.item_code.trim(),
        model: form.model.trim(),
        name: form.name,
        uom: form.uom || 'Each',
        min_stock_level: form.min_stock_level === '' ? null : Number(form.min_stock_level),
      }
      if (editing) {
        await api.patch(`/raw-materials/${form.id}`, payload)
        notify('Raw material updated')
      } else {
        const { data: product } = await api.post('/raw-materials', payload)
        notify('Raw material added')
        if (openingStock && product.id) {
          await api.post(`/raw-materials/${product.id}/stock`, { current_stock: Number(openingStock) })
        }
      }
      setModal(null); setOpeningStock('')
      load()
    } catch (e2) {
      notify(e2.response?.data?.detail || 'Save failed', true)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (row) => {
    if (!window.confirm(`Delete raw material "${row.model}"?\n\nThis will permanently remove the master record.`)) return
    try {
      const res = await api.delete(`/raw-materials/${row.id}`)
      if (res.status === 200 && res.data?.deactivated) {
        notify(`Material deactivated (${res.data.modules?.join(', ')})`)
      } else {
        notify('Raw material deleted')
      }
      load()
    } catch (e2) {
      notify(e2.response?.data?.detail || 'Delete failed', true)
    }
  }

  const openBalance = (row) => {
    setErr(null)
    setBalance(row
      ? {
          product_id: row.id,
          report_date: new Date().toISOString().slice(0, 10),
          schedule_qty: row.balance?.schedule_qty ?? '',
          ask_till_date: row.balance?.ask_till_date ?? '',
          inward_qty: row.balance?.inward_qty ?? '',
          opening_stock: row.balance?.opening_stock ?? '',
          min_stock: row.balance?.min_stock ?? '',
          max_stock: row.balance?.max_stock ?? '',
        }
      : { product_id: '', report_date: new Date().toISOString().slice(0, 10) })
    setModal('balance')
  }

  const saveBalance = async () => {
    if (!balance.product_id) { notify('Select a raw material', true); return }
    try {
      const params = { product_id: Number(balance.product_id), report_date: balance.report_date }
      for (const k of ['schedule_qty', 'ask_till_date', 'inward_qty', 'opening_stock', 'min_stock', 'max_stock']) {
        if (balance[k] !== '' && balance[k] != null) params[k] = Number(balance[k])
      }
      await api.post('/raw-materials/balances', null, { params })
      notify('Balance saved')
      setModal(null)
      load()
    } catch (e3) { notify(e3.response?.data?.detail || 'Save failed', true) }
  }

  const field = (label, key, props = {}, grid = '') => (
    <div className={grid}>
      <label className="block text-slate-500 text-xs mb-1">{label}</label>
      <input value={form[key] ?? ''} onChange={(e) => setForm({ ...form, [key]: e.target.value })} className="input" {...props} />
    </div>
  )

  const detailRow = (label, value, mono = false) => (
    <div className="flex items-center justify-between gap-4 py-2 border-b border-gray-50">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-sm font-medium text-slate-800 text-right ${mono ? 'font-mono' : ''}`}>{value || '—'}</span>
    </div>
  )

  const columns = [
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'model', label: 'Material', render: (r) => (
      <span className="flex items-center gap-1.5">
        <span className={`font-medium ${r.is_active === false ? 'opacity-50' : ''}`}>{r.model}</span>
        {r.is_active === false && <Badge className="bg-gray-100 text-gray-500">Inactive</Badge>}
      </span>
    )},
    { key: 'uom', label: 'UOM', render: (r) => r.uom || 'Each' },
    { key: 'schedule', label: 'Schedule', render: (r) => fmtNum(r.balance?.schedule_qty) },
    { key: 'inward', label: 'Inward Qty', render: (r) => fmtNum(r.balance?.inward_qty) },
    { key: 'balance', label: 'Balance', render: (r) => <span className="font-medium">{fmtNum(r.balance?.balance_qty)}</span> },
    {
      key: 'pct', label: 'Inward %', render: (r) => r.balance?.schedule_qty
        ? <Badge className={r.balance.completion_pct >= 1 ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-600'}>{fmtNum((r.balance.completion_pct || 0) * 100)}%</Badge>
        : '—',
    },
    { key: 'stock', label: 'Current Stock', render: (r) => <span className="font-semibold">{fmtNum(r.current_stock)}</span> },
    { key: 'min', label: 'MIN STOCK', render: (r) => r.balance?.min_stock != null ? <span className="font-mono text-xs">{fmtNum(r.balance.min_stock)}</span> : '—' },
    { key: 'status', label: 'Status', render: (r) => { const s = stockStatus(r); return <Badge className={s.cls} dot>{s.label}</Badge> } },
    {
      key: 'actions', label: '',
      render: (r) => (
        <div className="flex gap-1">
          <button onClick={() => openView(r)} className="btn btn-ghost p-1.5" title="View"><Eye size={15} /></button>
          <button onClick={() => openEdit(r)} className="btn btn-ghost p-1.5" title="Edit"><Pencil size={15} /></button>
          <button onClick={() => openBalance(r)} className="btn btn-ghost p-1.5" title="Update Balance"><ClipboardList size={15} /></button>
          <button onClick={() => { setStockModal(r); setStockValue(String(r.current_stock ?? '')); setStockRemarks('') }} className="btn btn-ghost p-1.5 text-purple-600 hover:text-purple-800" title="Set current stock"><Package size={15} /></button>
          <button onClick={() => remove(r)} className="btn btn-ghost p-1.5 text-red-400" title="Delete"><Trash2 size={15} /></button>
        </div>
      ),
    },
  ]

  const reorderCount = items.filter((r) => stockStatus(r).label === 'Reorder').length
  const lowCount = items.filter((r) => stockStatus(r).label === 'Low').length

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Raw Materials" subtitle="Master data, schedule / inward / balance with MIN-MAX reorder stock tracking"
        actions={
          <>
            <button onClick={() => downloadFile('/reports/raw-materials/csv', 'raw_materials.csv')} className="btn btn-secondary"><Download size={15} /> CSV</button>
            <button onClick={load} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
            <button onClick={() => openBalance(null)} className="btn btn-secondary"><ClipboardList size={15} /> Update Balance</button>
            <button onClick={() => setShowImport(true)} className="btn btn-secondary"><ArrowDownToLine size={15} /> Import</button>
            <button onClick={openNew} className="btn btn-primary"><Plus size={15} /> Add Raw Material</button>
          </>
        } />

      {msg && <div className="mb-4 text-sm state-box bg-green-50 text-green-700 border border-green-200 animate-fade-in">{msg}</div>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Materials Tracked" value={items.length} icon={Boxes} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="In-Stock" value={items.filter((r) => Number(r.current_stock) > 0).length} icon={CheckCircle2} iconClass="bg-green-50 text-green-600" />
        <StatCard label="Reorder Required" value={reorderCount} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
        <StatCard label="Low / Out of Stock" value={lowCount} icon={ArrowDownToLine} iconClass="bg-amber-50 text-amber-600" />
      </div>

      <Card actions={
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search material…" className="input input-icon sm:w-64" />
          </div>
          <label className="flex items-center gap-1.5 text-sm text-gray-500">
            <input type="checkbox" className="rounded" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} />
            Include inactive
          </label>
        </div>
      }>
        {loading ? <Loading /> : items.length === 0 ? <Empty text="No raw materials yet — click &quot;Add Raw Material&quot; to create your first one." /> : <Table columns={columns} data={items} keyField="id" stickyColumns={['model']} dense />}
      </Card>

      {modal === 'form' && (
        <Modal open title={editing ? 'Edit Raw Material' : 'Add Raw Material'} onClose={() => setModal(null)} wide
          footer={<>
            <button type="button" onClick={() => setModal(null)} className="btn btn-secondary">Cancel</button>
            <button type="submit" form="rm-form" disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : 'Save'}</button>
          </>}>
          <form onSubmit={saveMaterial} id="rm-form" className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {field('Material Name *', 'model', { required: true, placeholder: 'e.g. Stainless Steel Coil' })}
            {field('Item Code', 'item_code', { placeholder: 'e.g. RM-1001' })}
            {field('UOM', 'uom', { placeholder: 'e.g. KG' })}
            {field('MIN Stock Level', 'min_stock_level', { type: 'number', min: '0', step: 'any' })}
            <div className="md:col-span-2">{field('Name / Description', 'name', { placeholder: 'Optional description' })}</div>
            <div className="space-y-1">
              <label className="text-xs text-gray-500 font-medium uppercase tracking-wide">Current Stock (optional)</label>
              <input type="number" className="input text-lg font-semibold py-3" value={openingStock} onChange={e => setOpeningStock(e.target.value)} placeholder="0" min="0" step="0.01" />
            </div>
          </form>
        </Modal>
      )}

      {modal === 'balance' && (
        <Modal open title="Update Raw Material Balance" onClose={() => setModal(null)}
          footer={<>
            <button type="button" onClick={() => setModal(null)} className="btn btn-secondary">Cancel</button>
            <button onClick={saveBalance} className="btn btn-primary">Save Balance</button>
          </>}>
          {err && <div className="mb-3 text-sm state-box bg-red-50 text-red-700 border border-red-200">{err}</div>}
          <div className="text-sm space-y-1 mb-3 text-slate-500">
            <div className="text-xs">Balance is auto-calculated as Schedule − Inward. Inward % = Inward ÷ Schedule × 100.</div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="col-span-2">
              <label className="block text-slate-500 text-xs mb-1">Raw Material</label>
              <select value={balance.product_id || ''} onChange={(e) => setBalance({ ...balance, product_id: e.target.value })} className="input">
                <option value="">Select a raw material…</option>
                {items.map((i) => <option key={i.id} value={i.id}>{i.model}{i.item_code ? ` (${i.item_code})` : ''}</option>)}
              </select>
            </div>
            <div><label className="block text-slate-500 text-xs mb-1">Report Date</label>
              <input type="date" value={balance.report_date || ''} onChange={(e) => setBalance({ ...balance, report_date: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Schedule Qty</label>
              <input type="number" min="0" step="any" value={balance.schedule_qty ?? ''} onChange={(e) => setBalance({ ...balance, schedule_qty: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Inward Qty</label>
              <input type="number" min="0" step="any" value={balance.inward_qty ?? ''} onChange={(e) => setBalance({ ...balance, inward_qty: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Opening Stock</label>
              <input type="number" min="0" step="any" value={balance.opening_stock ?? ''} onChange={(e) => setBalance({ ...balance, opening_stock: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">MIN STOCK</label>
              <input type="number" min="0" step="any" value={balance.min_stock ?? ''} onChange={(e) => setBalance({ ...balance, min_stock: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">MAX STOCK</label>
              <input type="number" min="0" step="any" value={balance.max_stock ?? ''} onChange={(e) => setBalance({ ...balance, max_stock: e.target.value })} className="input" /></div>
          </div>
          {balance.schedule_qty !== '' && balance.schedule_qty != null && (
            <div className="text-xs text-slate-500 mt-3">
              Balance preview: <span className="font-semibold text-slate-700">{fmtNum((Number(balance.schedule_qty) || 0) - (Number(balance.inward_qty) || 0))}</span>
              {' · '}Inward %: <span className="font-semibold text-slate-700">{fmtNum((Number(balance.schedule_qty) ? ((Number(balance.inward_qty) || 0) / Number(balance.schedule_qty)) * 100 : 0))}%</span>
            </div>
          )}
        </Modal>
      )}

      {modal === 'view' && view && (
        <Modal open title={view.model || 'Raw Material'} subtitle={view.item_code ? `Item Code: ${view.item_code}` : ''} onClose={() => setModal(null)}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
            <div>
              <div className="text-[0.6875rem] font-semibold uppercase tracking-wide text-slate-400 mb-1">Master</div>
              {detailRow('Material Name', view.model)}
              {detailRow('Item Code', view.item_code, true)}
              {detailRow('Description', view.name)}
              {detailRow('Category', (view.category || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()))}
              {detailRow('UOM', view.uom)}
              {detailRow('MIN Stock Level', view.min_stock_level != null ? fmtNum(view.min_stock_level) : '—', true)}
              {detailRow('Source Type', view.source_type || '—')}
              {detailRow('Family', view.family)}
              {detailRow('Active', view.is_active ? 'Yes' : 'No')}
              {detailRow('Created', view.created_at ? new Date(view.created_at).toLocaleString() : '—')}
            </div>
            <div>
              <div className="text-[0.6875rem] font-semibold uppercase tracking-wide text-slate-400 mb-1 mt-4 sm:mt-0">Position</div>
              {detailRow('Schedule Qty', fmtNum(view.balance?.schedule_qty), true)}
              {detailRow('Inward Qty', fmtNum(view.balance?.inward_qty), true)}
              {detailRow('Balance', fmtNum(view.balance?.balance_qty), true)}
              {detailRow('Inward %', view.balance?.completion_pct != null ? `${fmtNum(view.balance.completion_pct * 100)}%` : '—')}
              {detailRow('Opening Stock', fmtNum(view.balance?.opening_stock), true)}
              {detailRow('Current Stock', fmtNum(view.current_stock), true)}
              {detailRow('MIN STOCK', view.balance?.min_stock != null ? fmtNum(view.balance.min_stock) : '—', true)}
              {detailRow('MAX STOCK', view.balance?.max_stock != null ? fmtNum(view.balance.max_stock) : '—', true)}
              {(() => { const s = stockStatus(view); return detailRow('Status', s.label) })()}
            </div>
          </div>
        </Modal>
      )}

      {stockModal && (
        <div className="modal-overlay" onClick={() => setStockModal(null)}>
          <div className="modal-panel p-5" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-1">{stockModal.model}</h3>
            <p className="text-gray-500 text-sm mb-4">Set current stock (Main Store)</p>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Current Stock</label>
            <input type="number" className="input text-2xl font-bold py-3 w-full mb-4" value={stockValue} onChange={e => setStockValue(e.target.value)} min="0" step="0.01" />
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Remarks (optional)</label>
            <input type="text" className="input mb-4" value={stockRemarks} onChange={e => setStockRemarks(e.target.value)} placeholder="Reason for adjustment..." />
            {stockErr && <div className="text-red-500 text-sm mb-2">{stockErr}</div>}
            <div className="flex gap-2">
              <button onClick={async () => {
                setStockBusy(true); setStockErr(null)
                try {
                  const { data } = await api.post(`/raw-materials/${stockModal.id}/stock`, { current_stock: Number(stockValue), remarks: stockRemarks })
                  notify(`Stock set: ${data.previous_stock} → ${data.current_stock} (delta ${data.delta})`)
                  setStockModal(null); load()
                } catch (e) { setStockErr(e.response?.data?.detail || 'Update failed') }
                finally { setStockBusy(false) }
              }} className="btn btn-primary" disabled={stockBusy}>
                {stockBusy ? 'Saving…' : 'Update Stock'}
              </button>
              <button onClick={() => setStockModal(null)} className="btn btn-secondary">Cancel</button>
            </div>
          </div>
        </div>
      )}

      {showImport && (
        <div className="modal-overlay" onClick={() => setShowImport(null)}>
          <div className="modal-panel p-5 max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-lg font-bold mb-4">Import Raw Materials</h3>
            <p className="text-sm text-gray-500 mb-4">
              CSV or Excel. Required column: Model (or Material/Item Name).
              Optional: Item Code, Schedule Qty, Inward Qty, % COMP, MIN STOCK, MAX STOCK.
            </p>
            <input type="file" accept=".csv,.xlsx,.xls" className="input mb-4" onChange={e => setImportFile(e.target.files?.[0])} />
            {importResult && (
              <div className="bg-gray-50 rounded-lg p-4 mb-4 text-sm">
                <p className="font-bold mb-1">Results</p>
                <p>Created: {importResult.summary.created}, Updated: {importResult.summary.updated}, Errors: {importResult.summary.errors}</p>
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
                  const { data } = await api.post('/raw-materials/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
                  setImportResult(data); load()
                } catch (e) { alert(e.response?.data?.detail || 'Import failed') }
                finally { setImportBusy(false) }
              }} className="btn btn-primary" disabled={importBusy}>
                {importBusy ? 'Importing…' : 'Import'}
              </button>
              <button onClick={() => { setShowImport(null); setImportResult(null); setImportFile(null) }} className="btn btn-secondary">Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
