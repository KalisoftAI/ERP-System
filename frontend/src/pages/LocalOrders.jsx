import { useEffect, useState } from 'react'
import { Plus, Eye, Pencil, X, Store, ClipboardList, CheckCircle2, Trash2, Truck, Calendar, PackageSearch, ArrowLeftRight, Upload, Share2, Printer, Download } from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, StatCard, StatusBadge, SearchSelect } from '../components/ui'
import Table from '../components/Table'
import StockTransferModal, { findDispatchPlant } from '../components/StockTransferModal'
import { fmtNum } from '../lib/format'

const today = () => new Date().toISOString().slice(0, 10)

const emptyLine = { product_id: null, item_code: '', description: '', quantity: 1, uom: '', unit_price: null, less: null, id: null }

const errText = (err) => {
  const d = err?.response?.data?.detail
  if (Array.isArray(d)) return d.map((x) => x.msg || x).join('. ')
  if (typeof d === 'string') return d
  return 'Request failed. Please try again.'
}

export default function LocalOrders() {
  const [rows, setRows] = useState([])
  const [completedTotal, setCompletedTotal] = useState(0)
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [customers, setCustomers] = useState([])
  const [products, setProducts] = useState([])
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [showOrderForm, setShowOrderForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState({})
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  // bulk import state
  const [showImport, setShowImport] = useState(false)
  const [importFile, setImportFile] = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [importBusy, setImportBusy] = useState(false)

  // dispatch entry state
  const [showEntry, setShowEntry] = useState(false)
  const [entry, setEntry] = useState(null)
  const [entryErr, setEntryErr] = useState(null)
  const [entrySaving, setEntrySaving] = useState(false)

  // stock transfer (reposition) state
  const [locations, setLocations] = useState([])
  const [dispatchPlantId, setDispatchPlantId] = useState(null)
  const [showTransferModal, setShowTransferModal] = useState(false)
  const [transferInit, setTransferInit] = useState(null)

  const [success, setSuccess] = useState('')

  const flash = (text) => { setSuccess(text); setTimeout(() => setSuccess(''), 6000) }

  const load = () => {
    setLoading(true)
    api.get('/local-orders', { params: { page_size: 500, active_only: true } })
      .then((res) => {
        setRows(res.data.items || [])
        setCompletedTotal(res.data.completed_total || 0)
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  const loadMeta = () => {
    api.get('/customers', { params: { page_size: 500 } }).then((r) => setCustomers(r.data.items || []))
    api.get('/products', { params: { page_size: 500 } }).then((r) => setProducts(r.data.items || []))
  }

  useEffect(() => {
    load()
    loadMeta()
    api.get('/local-orders/plans')
      .then((res) => setPlans(res.data.items || []))
      .catch(() => setPlans([]))
    api.get('/inventory/locations').then((r) => {
      const locs = r.data.items || []
      setLocations(locs)
      setDispatchPlantId(findDispatchPlant(locs))
    }).catch(() => {})
    const focus = new URLSearchParams(window.location.search).get('order')
    if (focus && Number(focus)) {
      setDetailLoading(true)
      api.get(`/local-orders/${Number(focus)}`)
        .then((res) => setDetail(res.data))
        .catch(() => {})
        .finally(() => setDetailLoading(false))
    }
  }, [])

  const lineAmt = (l) => (Number(l.quantity) || 0) * (Number(l.unit_price) || 0)
  const orderTotal = (form.lines || []).reduce((s, l) => s + lineAmt(l), 0)

  const openDetail = (r) => {
    setDetail({ id: r.id, order_no: r.order_no, loading: true })
    setDetailLoading(true)
    api.get(`/local-orders/${r.id}`)
      .then((res) => setDetail(res.data))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  const openCreate = () => {
    setForm({ customer_id: null, customer_name: '', customer_mobile: '', customer_email: '', local_order_type: 'TRADING', order_date: today(), delivery_date: '', remarks: '', so_no: '', customer_po_no: '', lines: [{ ...emptyLine }] })
    setErrors({})
    setEditing(null)
    setShowOrderForm(true)
  }

  const openEdit = (r) => {
    setForm({
      customer_id: r.customer_id, customer_name: r.customer_name || r.customer || '',
      customer_mobile: r.customer_mobile || '', customer_email: r.customer_email || '',
      local_order_type: r.order_type || 'TRADING',
      order_date: r.order_date || today(), delivery_date: r.delivery_date || '',
      so_no: r.so_no || '',
      customer_po_no: r.customer_po_no || '',
      status: r.order_status || 'New',
      remarks: r.commitment || r.remarks || '',
      lines: (r.lines || []).map((ln) => ({
        id: ln.id, product_id: ln.product_id, item_code: ln.item_code || '',
        description: ln.description || ln.model || '', quantity: ln.quantity,
        uom: ln.uom || '', unit_price: ln.rate != null ? ln.rate : null, less: ln.less != null ? ln.less : null,
      })),
    })
    setErrors({})
    setEditing(r)
    setShowOrderForm(true)
  }

  const addLine = () => setForm({ ...form, lines: [...(form.lines || []), { ...emptyLine }] })
  const updateLine = (i, key, value) => {
    const lines = [...(form.lines || [])]
    lines[i] = { ...lines[i], [key]: value }
    setForm({ ...form, lines })
  }
  const setLineProduct = (i, id, manual) => {
    const p = id ? products.find((pp) => pp.id === id) : null
    const lines = [...(form.lines || [])]
    lines[i] = {
      ...lines[i],
      product_id: id,
      description: id ? lines[i].description : (manual || ''),
      item_code: p ? (lines[i].item_code || p.item_code || '') : (lines[i].item_code || ''),
      uom: p ? (lines[i].uom || p.uom || '') : (lines[i].uom || ''),
    }
    setForm({ ...form, lines })
  }
  const removeLine = (i) => setForm({ ...form, lines: (form.lines || []).filter((_, idx) => idx !== i) })

  const validate = () => {
    const errs = {}
    if (!form.customer_id && !(form.customer_name || '').trim()) errs.customer_id = 'Enter or select a customer'
    const lines = form.lines || []
    if (lines.length === 0) errs.lines = 'Add at least one order line'
    lines.forEach((l, i) => {
      if (!l.product_id && !(l.description || '').trim()) errs[`line_${i}_product`] = 'Select a product or enter a size/description'
      if (!(Number(l.quantity) > 0)) errs[`line_${i}_qty`] = 'Qty > 0 required'
      if (l.less != null && Number(l.less) < 0) errs[`line_${i}_less`] = 'Less cannot be negative'
    })
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const payload = () => ({
    customer_id: form.customer_id ? Number(form.customer_id) : null,
    customer_name: form.customer_name || '',
    customer_mobile: (form.customer_mobile || '').trim(),
    customer_email: (form.customer_email || '').trim(),
    local_order_type: form.local_order_type || 'TRADING',
    order_date: form.order_date || today(),
    required_delivery_date: form.delivery_date || null,
    so_no: (form.so_no || '').trim(),
    customer_po_no: (form.customer_po_no || '').trim(),
    remarks: form.remarks || '',
    status: editing ? (form.status || undefined) : 'New',
    lines: (form.lines || []).map((l) => ({
      id: editing ? (l.id || null) : undefined,
      product_id: l.product_id ? Number(l.product_id) : null,
      item_code: l.item_code || '',
      description: l.description || '',
      quantity: Number(l.quantity),
      uom: (l.uom || '').trim(),
      unit_price: l.unit_price != null && l.unit_price !== '' ? Number(l.unit_price) : null,
      less: l.less != null && l.less !== '' ? Number(l.less) : null,
      amount: lineAmt(l),
    })),
  })

  const submit = () => {
    if (!validate()) return
    setSaving(true)
    const req = editing ? api.patch(`/local-orders/${editing.id}`, payload()) : api.post('/local-orders', payload())
    req
      .then((res) => {
        setShowOrderForm(false)
        setEditing(null)
        flash(`${editing ? 'Updated' : 'Created'} local order ${res.data.order_no} — status: ${res.data.status}`)
        load()
        if (detail) openDetail({ id: detail.id, order_no: detail.order_no })
      })
      .catch((err) => setErrors({ api: errText(err) }))
      .finally(() => setSaving(false))
  }

  // ---- bulk CSV/Excel import ----
  const runImport = async () => {
    if (!importFile) { window.alert('Choose a CSV or Excel file first'); return }
    const fd = new FormData()
    fd.append('file', importFile)
    setImportBusy(true)
    try {
      const { data } = await api.post('/local-orders/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
      setImportResult(data)
      flash(`Import done — ${data.summary.created} order(s) created, ${data.summary.lines} line(s), ${data.summary.errors} row error(s)`)
      load()
      loadMeta()
    } catch (e) {
      window.alert(e.response?.data?.detail || 'Import failed')
    } finally {
      setImportBusy(false)
    }
  }

  // ---- share (Web Share API with clipboard fallback) ----
  const shareOrder = async () => {
    const d = detail
    if (!d || d.loading) return
    const items = (d.lines || []).map((l) =>
      `- ${l.description || l.model || l.item_code || 'Item'}: ${fmtNum(l.quantity)}${l.uom ? ' ' + l.uom : ''}` +
      (l.rate != null ? ` @ ${fmtNum(l.rate)} = ${fmtNum(l.amount)}` : ''),
    ).join('\n')
    const text = `LOCAL ORDER ${d.order_no}\nCustomer: ${d.customer || '—'}\nSO No: ${d.so_no || '—'} · PO No: ${d.customer_po_no || '—'}\nOrder Date: ${d.order_date || '—'} · Delivery: ${d.delivery_date || '—'}\nStatus: ${d.status} · Dispatched: ${fmtNum(d.dispatched_qty)} · Pending: ${fmtNum(d.pending_qty)}\nTotal Amount: ${fmtNum(d.total_value)}\n\n${items}`
    const url = `${window.location.origin}/local-orders?order=${d.id}`
    const copy = async () => {
      try { await navigator.clipboard.writeText(`${text}\n\n${url}`); flash('Order details copied to clipboard') }
      catch { window.alert('Could not copy. Please share manually.') }
    }
    if (navigator.share) {
      try { await navigator.share({ title: `Local Order ${d.order_no}`, text, url }) }
      catch (e) { if (e?.name !== 'AbortError') await copy() }
    } else {
      await copy()
    }
  }

  // ---- PDF (browser print to PDF) ----
  const downloadPdf = () => {
    const d = detail
    if (!d || d.loading) return
    const escHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
    const lineRows = (d.lines || []).map((l) => (
      `<tr><td>${escHtml(l.description || l.model || '—')}</td>` +
      `<td class="r">${fmtNum(l.quantity)} ${escHtml(l.uom || '')}</td>` +
      `<td class="r">${l.rate != null ? fmtNum(l.rate) : '—'}</td>` +
      `<td class="r">${l.less != null ? fmtNum(l.less) : '—'}</td>` +
      `<td class="r">${fmtNum(l.amount)}</td>` +
      `<td class="r">${fmtNum(l.dispatched_qty)}</td>` +
      `<td class="r">${fmtNum(l.balance_qty)}</td></tr>`
    )).join('')
    const hisRows = flattenedHistory.map((h) => (
      `<tr><td>${escHtml(h.dispatch_no || '—')}</td>` +
      `<td>${escHtml(h.description || h.item_code || '—')}</td>` +
      `<td class="r">${fmtNum(h.quantity)}</td>` +
      `<td>${escHtml(h.dispatch_date || '—')}</td></tr>`
    )).join('')
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Local Order ${escHtml(d.order_no)}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: #111; margin: 28px; }
  h1 { font-size: 20px; margin: 0 0 2px; }
  .sub { color: #666; font-size: 11px; margin-bottom: 16px; }
  .meta { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px 18px; border: 1px solid #ddd; border-radius: 6px; padding: 12px 14px; margin-bottom: 18px; }
  .meta .lbl { display: block; color: #888; font-size: 9px; text-transform: uppercase; letter-spacing: .4px; margin-bottom: 2px; }
  .meta .val { font-weight: 600; }
  h2 { font-size: 13px; margin: 16px 0 8px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; font-size: 11px; }
  th { background: #f4f4f4; text-transform: uppercase; font-size: 9px; letter-spacing: .4px; color: #555; }
  .r { text-align: right; }
  .total td { font-weight: 700; background: #fafafa; }
  .foot { margin-top: 26px; font-size: 10px; color: #888; }
  @media print { body { margin: 12mm; } }
</style></head><body>
<h1>Local Order — ${escHtml(d.order_no)}</h1>
<div class="sub">Generated ${escHtml(new Date().toLocaleString())}</div>
<div class="meta">
  <div><span class="lbl">Customer</span><span class="val">${escHtml(d.customer || '—')}</span></div>
  <div><span class="lbl">Mobile</span><span class="val">${escHtml(d.customer_mobile || '—')}</span></div>
  <div><span class="lbl">Email</span><span class="val">${escHtml(d.customer_email || '—')}</span></div>
  <div><span class="lbl">Order Type</span><span class="val">${escHtml(d.order_type || '—')}</span></div>
  <div><span class="lbl">SO Number</span><span class="val">${escHtml(d.so_no || '—')}</span></div>
  <div><span class="lbl">PO Number</span><span class="val">${escHtml(d.customer_po_no || '—')}</span></div>
  <div><span class="lbl">Order Date</span><span class="val">${escHtml(d.order_date || '—')}</span></div>
  <div><span class="lbl">Delivery Date</span><span class="val">${escHtml(d.delivery_date || '—')}</span></div>
  <div><span class="lbl">Status</span><span class="val">${escHtml(d.status || '—')}</span></div>
  <div><span class="lbl">Total Amount</span><span class="val">${fmtNum(d.total_value)}</span></div>
  <div><span class="lbl">Dispatched</span><span class="val">${fmtNum(d.dispatched_qty)}</span></div>
  <div><span class="lbl">Pending</span><span class="val">${fmtNum(d.pending_qty)}</span></div>
</div>
<h2>Order Lines</h2>
<table><thead><tr><th>Item</th><th class="r">Qty</th><th class="r">Rate</th><th class="r">Less</th><th class="r">Amount</th><th class="r">Dispatched</th><th class="r">Pending</th></tr></thead>
<tbody>${lineRows || '<tr><td colspan="7">No lines</td></tr>'}</tbody>
<tfoot><tr class="total"><td colspan="4">Order Total</td><td class="r">${fmtNum(d.total_value)}</td><td class="r">${fmtNum(d.dispatched_qty)}</td><td class="r">${fmtNum(d.pending_qty)}</td></tr></tfoot></table>
<h2>Dispatch History</h2>
<table><thead><tr><th>Dispatch</th><th>Item</th><th class="r">Qty</th><th>Date</th></tr></thead>
<tbody>${hisRows || '<tr><td colspan="4">No dispatches yet</td></tr>'}</tbody></table>
<div class="foot">Generated by Kalika ERP — Local Orders</div>
</body></html>`
    const win = window.open('', '_blank', 'width=900,height=760')
    if (!win) { window.alert('Popup blocked — please allow popups to generate the PDF.'); return }
    win.document.write(html)
    win.document.close()
    win.focus()
    setTimeout(() => win.print(), 350)
  }

  // ---- dispatch entries (actual dispatch, reuses the sales-order Dispatch module) ----
  const openNewEntry = (order, line) => {
    // Available stock for this line = current balance at the Dispatch location.
    const sl = (order?.stock?.lines || []).find((s) => s.line_id === line?.id)
    setEntry({
      id: null, dispatch_no: '', order: order, order_line_id: line?.id ?? null,
      product_id: line?.product_id ?? null, item_code: line?.item_code || '',
      description: line?.description || line?.model || '', quantity: line ? (line.balance_qty > 0 ? line.balance_qty : '') : '',
      dispatch_date: today(), rate: line?.rate ?? '', weight: '',
      available: sl?.tracked ? (Number(sl.available_dispatch) || 0) : null, oldQty: 0,
    })
    setEntryErr(null)
    setShowEntry(true)
  }

  const openEditEntry = (ln) => {
    const sl = (detail?.stock?.lines || []).find((s) => s.line_id === ln.sales_order_line_id)
    setEntry({
      id: null, entry_line_id: ln.entry_line_id, dispatch_no: ln.dispatch_no, order: detail,
      order_line_id: ln.sales_order_line_id ?? null,
      product_id: ln.product_id ?? null, item_code: ln.item_code || '',
      description: ln.description || '', quantity: ln.quantity ?? '',
      dispatch_date: ln.dispatch_date || today(), rate: ln.rate ?? '', weight: ln.weight ?? '',
      available: sl?.tracked ? (Number(sl.available_dispatch) || 0) : null, oldQty: Number(ln.quantity) || 0,
    })
    setEntryErr(null)
    setShowEntry(true)
  }

  const saveEntry = () => {
    if (!entry.quantity || Number(entry.quantity) <= 0) { setEntryErr('Enter a dispatch quantity'); return }
    if (!entry.product_id && !(entry.item_code || '').trim() && !(entry.description || '').trim()) {
      setEntryErr('Select or enter the product / item'); return
    }
    // Local Order dispatch is capped at BOTH the current stock at the Dispatch
    // location AND the order line's remaining (Balance) quantity.
    const maxQty = entryMax
    if (maxQty != null && Number(entry.quantity) > maxQty) {
      const why = []
      if (entryRemaining != null && Number(entry.quantity) > Number(entryRemaining) + Number(entry.oldQty || 0)) {
        why.push(`only ${fmtNum(entryRemaining)} remaining to dispatch on the order line`)
      }
      if (entryStockCap != null && Number(entry.quantity) > entryStockCap) {
        why.push(`available stock is ${fmtNum(entry.available)}`)
      }
      setEntryErr(`Dispatch quantity cannot exceed ${why.length ? why.join(' and ') : `the maximum of ${fmtNum(maxQty)}`}.`)
      return
    }
    if (entryMax != null && entryMax <= 0) { setEntryErr('Nothing left to dispatch — this order line is already fully dispatched.'); return }
    const line = {
      product_id: entry.product_id ? Number(entry.product_id) : null,
      item_code: entry.item_code || '',
      description: entry.description || '',
      quantity: Number(entry.quantity),
      dispatch_date: entry.dispatch_date,
      rate: entry.rate !== '' && entry.rate != null ? Number(entry.rate) : null,
      weight: entry.weight !== '' && entry.weight != null ? Number(entry.weight) : null,
      sales_order_line_id: entry.order_line_id ? Number(entry.order_line_id) : null,
    }
    setEntrySaving(true)
    const req = entry.entry_line_id
      ? api.patch(`/dispatch/lines/${entry.entry_line_id}`, line)
      : api.post('/dispatch', {
          customer_id: entry.order?.customer_id ?? null,
          customer_name: entry.order?.customer_name || entry.order?.customer || '',
          sales_order_id: entry.order?.id,
          schedule_qty: entry.order?.quantity ?? 0,
          dispatch_date: entry.dispatch_date,
          remarks: entry.order?.order_no || '',
          lines: [line],
        })
    req
      .then(() => {
        setShowEntry(false); setEntry(null); setEntryErr(null)
        flash(entry.entry_line_id ? 'Dispatch entry updated' : 'Dispatch entry recorded')
        if (detail) openDetail({ id: detail.id, order_no: detail.order_no })
        load()
      })
      .catch((e) => setEntryErr(e.response?.data?.detail || 'Dispatch failed'))
      .finally(() => setEntrySaving(false))
  }

  const transferForOrder = (o) => {
    const lines = (o.lines || []).map((ln, i) => {
      const s = (o.stock?.lines || [])[i] || {}
      const need = Math.max((Number(ln.balance_qty) || 0) - (Number(s.available_dispatch) || 0), 0)
      return { product_id: ln.product_id, item_code: ln.item_code || '', description: ln.description || ln.model || '', quantity: need }
    }).filter((l) => l.product_id && l.quantity > 0)
    setTransferInit({
      id: null, transfer_no: null,
      from_plant_id: '', to_plant_id: dispatchPlantId ?? '',
      customer_id: o.customer_id ?? null,
      customer_name: o.customer_name || o.customer || '',
      transfer_date: today(), notes: `Reposition stock for ${o.order_no}`, lines,
    })
    setShowTransferModal(true)
  }

  const afterTransfer = () => {
    load()
    if (detail) openDetail({ id: detail.id, order_no: detail.order_no })
    flash('Stock transferred to Dispatch — order status updated')
  }

  const delEntry = async (ln) => {
    if (!ln?.entry_line_id) return
    if (!window.confirm(`Delete dispatch entry of ${fmtNum(ln.quantity)} on ${ln.dispatch_date}? Stock will be restored.`)) return
    try {
      await api.delete(`/dispatch/lines/${ln.entry_line_id}`)
      flash('Dispatch entry deleted — order status/pending recalculated')
      if (detail) openDetail({ id: detail.id, order_no: detail.order_no })
      load()
    } catch (e) { window.alert('Delete failed: ' + (e.response?.data?.detail || e.message)) }
  }

  const removeOrder = (r) => {
    if (!window.confirm(`Delete local order ${r.order_no || r.id}? This cannot be undone.`)) return
    api.delete(`/local-orders/${r.id}`)
      .then(() => {
        setDetail(null)
        flash(`Local order ${r.order_no || r.id} deleted`)
        load()
      })
      .catch((err) => window.alert(typeof err?.response?.data?.detail === 'string' ? err.response.data.detail : 'Failed to delete local order.'))
  }

  const readyCount = rows.filter((r) => r.status === 'Ready for Dispatch').length
  const partialCount = rows.filter((r) => r.status === 'Partially Dispatched').length
  const totalValue = rows.reduce((s, r) => s + (Number(r.total_value) || 0), 0)

  const orderCols = [
    { key: 'order_no', label: 'Order', render: (r) => <span className="font-mono text-xs font-medium">{r.order_no || '—'}</span> },
    { key: 'so_no', label: 'SO Number', render: (r) => <span className="font-mono text-xs">{r.so_no || '—'}</span> },
    { key: 'customer_po_no', label: 'PO Number', render: (r) => <span className="font-mono text-xs">{r.customer_po_no || '—'}</span> },
    { key: 'customer', label: 'Customer', render: (r) => <span className="font-medium">{r.customer || '—'}</span> },
    { key: 'order_type', label: 'Type', render: (r) => <Badge className={r.order_type === 'MANUFACTURING' ? 'bg-violet-100 text-violet-700' : 'bg-cyan-100 text-cyan-700'}>{r.order_type || 'TRADING'}</Badge> },
    { key: 'order_date', label: 'Order Date', render: (r) => r.order_date || '—' },
    { key: 'delivery_date', label: 'Delivery', render: (r) => r.delivery_date || '—' },
    { key: 'item', label: 'Size / Description', render: (r) => {
      const first = (r.lines || [])[0]
      return <span className="text-xs block max-w-40 truncate">{first?.description || first?.model || '—'}{(r.lines?.length || 0) > 1 ? ` +${r.lines.length - 1}` : ''}</span>
    } },
    { key: 'quantity', label: 'Qty', render: (r) => fmtNum(r.quantity) },
    { key: 'unit', label: 'Unit', render: (r) => {
      const first = (r.lines || [])[0]
      return first?.uom ? <span className="text-xs">{first.uom}</span> : '—'
    } },
    { key: 'rate', label: 'Rate', render: (r) => {
      const first = (r.lines || [])[0]
      return first?.rate != null ? fmtNum(first.rate) : '—'
    } },
    { key: 'less', label: 'Less', render: (r) => {
      const first = (r.lines || [])[0]
      return first?.less != null ? fmtNum(first.less) : '—'
    } },
    { key: 'total_value', label: 'Amount', render: (r) => <span className="font-mono text-xs font-medium">{fmtNum(r.total_value)}</span> },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => fmtNum(r.dispatched_qty) },
    { key: 'pending_qty', label: 'Pending', render: (r) => <span className="font-medium">{fmtNum(r.pending_qty)}</span> },
    { key: 'dispatch_stock', label: 'Disp Stock', render: (r) => <span className="font-mono text-xs">{fmtNum(r.stock_summary?.dispatch_stock)}</span> },
    { key: 'main_stock', label: 'Main Store', render: (r) => <span className="font-mono text-xs">{fmtNum(r.stock_summary?.main_store_stock)}</span> },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-0.5">
        <button onClick={() => openDetail(r)} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="View"><Eye size={14} /></button>
        {r.stock_summary?.transfer_required ? (
          <button onClick={() => transferForOrder(r)} className="text-violet-600 hover:text-violet-800 p-1 hover:bg-violet-50 rounded" title="Stock exists — transfer Main Store → Dispatch"><ArrowLeftRight size={14} /></button>
        ) : (
          <button onClick={() => openNewEntry(r, (r.lines || [])[0])} className="text-blue-500 hover:text-blue-700 p-1 hover:bg-blue-50 rounded" title="Dispatch now"><Truck size={14} /></button>
        )}
        <button onClick={() => openEdit(r)} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit"><Pencil size={14} /></button>
        <button onClick={(e) => { e.stopPropagation(); removeOrder(r) }} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete"><Trash2 size={14} /></button>
      </div>
    )},
  ]

  const detailLineCols = [
    { key: 'description', label: 'Size / Description', render: (r) => <span className="font-medium">{r.description || r.model || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'quantity', label: 'Order Qty', render: (r) => fmtNum(r.quantity) },
    { key: 'unit', label: 'Unit', render: (r) => <span className="text-xs">{r.uom || '—'}</span> },
    { key: 'rate', label: 'Rate', render: (r) => r.rate != null ? fmtNum(r.rate) : '—' },
    { key: 'less', label: 'Less', render: (r) => r.less != null ? fmtNum(r.less) : '—' },
    { key: 'amount', label: 'Amount', render: (r) => <span className="font-mono text-xs font-medium">{fmtNum(r.amount)}</span> },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.dispatched_qty)}</span> },
    { key: 'balance_qty', label: 'Pending', render: (r) => <span className={r.balance_qty < 0 ? 'text-red-600 font-semibold' : 'font-medium'}>{fmtNum(r.balance_qty)}</span> },
    { key: 'stock', label: 'Stock', render: (r) => {
      const st = (detail?.stock?.lines || []).find((s) => s.line_id === r.id)
      if (!st || st.ready == null) return '—'
      return st.ready ? <Badge className="bg-green-100 text-green-700" dot>Ready</Badge> : <Badge className="bg-red-100 text-red-700">Short</Badge>
    } },
    { key: 'action', label: '', render: (r) => (
      <button onClick={() => openNewEntry(detail, r)} className="btn btn-primary btn-sm py-1"><Truck size={13} className="mr-1" /> Dispatch</button>
    )},
  ]

  const histCols = [
    { key: 'dispatch_no', label: 'Dispatch', render: (r) => <span className="font-mono text-xs">{r.dispatch_no}</span> },
    { key: 'product', label: 'Product', render: (r) => <span className="font-medium">{r.description || r.item_code || '—'}</span> },
    { key: 'quantity', label: 'Qty', render: (r) => <span className="font-semibold">{fmtNum(r.quantity)}</span> },
    { key: 'dispatch_date', label: 'Date', render: (r) => r.dispatch_date || '—' },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-0.5">
        <button onClick={() => openEditEntry(r)} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit entry"><Pencil size={13} /></button>
        <button onClick={() => delEntry(r)} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete entry"><Trash2 size={13} /></button>
      </div>
    )},
  ]

  const planCols = [
    { key: 'plan_type', label: 'Plan Type', render: (r) => <Badge className="bg-violet-100 text-violet-700">{r.plan_type || '—'}</Badge> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.model || '—'}</span> },
    { key: 'customer', label: 'Customer', render: (r) => r.customer || '—' },
    { key: 'quantity', label: 'Quantity', render: (r) => fmtNum(r.quantity) },
    { key: 'owner', label: 'Owner', render: (r) => r.owner || '—' },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'plan_date', label: 'Date', render: (r) => r.plan_date || '—' },
    { key: 'remarks', label: 'Remarks', render: (r) => r.remarks || '—' },
  ]

  const flattenedHistory = (detail?.dispatches || []).flatMap((d) =>
    (d.lines || []).map((ln) => ({
      ...ln,
      dispatch_no: d.dispatch_no,
      dispatch_date: ln.dispatch_date || d.dispatch_date,
      entry_line_id: ln.id,
      dispatch_id: d.id,
      status: d.status,
      rate: ln.rate ?? undefined,
    }))
  )

  // Remaining balance (Schedule minus Dispatched) for the current dispatch entry.
  const entryLine = (entry?.order?.lines || []).find((l) => l.id === entry?.order_line_id)
  const entryRemaining = entryLine != null ? Number(entryLine.balance_qty) : null
  const entryStockCap = entry?.available != null ? Number(entry.available) + Number(entry.oldQty || 0) : null
  const entryMax = entryRemaining != null || entryStockCap != null
    ? Math.min(
        entryRemaining != null ? Number(entryRemaining) + Number(entry.oldQty || 0) : Infinity,
        entryStockCap != null ? entryStockCap : Infinity,
      )
    : null
  const entryTooBig = entryMax != null && Number(entry.quantity || 0) > entryMax

  if (loading) return <Loading />
  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Local Orders" subtitle="Complete live workflow — order • stock check • dispatch • history"
        actions={<div className="flex items-center gap-2">
          <button onClick={() => setShowImport(true)} className="btn btn-secondary"><Upload size={15} /> Import</button>
          <button onClick={openCreate} className="btn btn-primary"><Plus size={15} /> New Local Order</button>
        </div>} />

      {success && (
        <div className="mb-4 rounded-lg bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 flex items-center gap-2">
          <CheckCircle2 size={16} /> {success}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-5">
        <StatCard label="Active Local Orders" value={rows.length} icon={Store} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Ready for Dispatch" value={readyCount} icon={PackageSearch} iconClass="bg-teal-50 text-teal-600" />
        <StatCard label="Partially Dispatched" value={partialCount} icon={Truck} iconClass="bg-blue-50 text-blue-600" />
        <StatCard label="Total Amount" value={fmtNum(totalValue)} icon={Store} iconClass="bg-blue-50 text-blue-600" />
      </div>

      <Card title="Local Orders" subtitle="Active/incomplete orders only — completed orders move to history below" className="mb-6">
        {rows.length === 0 ? <Empty text="No active local orders" /> : <Table columns={orderCols} data={rows} keyField="id" onRowClick={openDetail} stickyColumns={['order_no']} dense />}
      </Card>

      <Card title="Completed Local Orders" subtitle="Historical completed-order report for records / invoicing" className="mb-6"
        actions={<button onClick={() => downloadFile('/local-orders/report/orders', 'local_orders_completed.csv')} className="btn btn-secondary btn-sm"><Download size={13} /> Download CSV</button>}>
        <div className="text-sm text-slate-500">
          {completedTotal} completed local order(s). The active list above shows {rows.length} in-progress order(s). Download the full completed-order history (CSV).
        </div>
      </Card>

      <Card title="Production / Dispatch Plans (Local)" subtitle="Production & dispatch plans with linked order, production and dispatch progress"
        actions={<button onClick={() => downloadFile('/local-orders/report/plans', 'local_plans.csv')} className="btn btn-secondary btn-sm"><Download size={13} /> Download CSV</button>}>
        {plans.length === 0 ? <Empty text="No plans" /> : <Table columns={planCols} data={plans} keyField="id" stickyColumns={['model']} dense />}
      </Card>

      {/* Detail modal */}
      <Modal open={!!detail} title={detail && !detail.loading ? `Local Order ${detail.order_no}` : 'Loading…'} onClose={() => setDetail(null)} wide
        footer={<>
          {detail && !detail.loading && (detail.stock_summary?.transfer_required
            ? <button onClick={() => transferForOrder(detail)} className="btn btn-secondary mr-auto"><ArrowLeftRight size={14} className="mr-1" /> Transfer to Dispatch</button>
            : <button onClick={() => openNewEntry(detail, (detail.lines || [])[0])} className="btn btn-primary mr-auto"><Truck size={14} className="mr-1" /> Dispatch</button>)}
          {detail && !detail.loading && (
            <>
              <button onClick={shareOrder} className="btn btn-secondary"><Share2 size={14} className="mr-1" /> Share</button>
              <button onClick={downloadPdf} className="btn btn-secondary"><Printer size={14} className="mr-1" /> PDF</button>
            </>
          )}
          <button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>
        </>}>
        {detailLoading || detail?.loading ? <Loading /> : detail && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-sm">
              <div><span className="text-slate-500 block text-xs">Customer</span><span className="font-medium">{detail.customer || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Mobile</span><span className="font-mono text-xs font-medium">{detail.customer_mobile || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Email</span><span className="text-xs font-medium">{detail.customer_email || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">SO Number</span><span className="font-mono text-xs font-medium">{detail.so_no || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">PO Number</span><span className="font-mono text-xs font-medium">{detail.customer_po_no || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Order Type</span><Badge className={detail.order_type === 'MANUFACTURING' ? 'bg-violet-100 text-violet-700' : 'bg-cyan-100 text-cyan-700'}>{detail.order_type || 'TRADING'}</Badge></div>
              <div><span className="text-slate-500 block text-xs">Order Date</span><span className="font-medium">{detail.order_date}</span></div>
              <div><span className="text-slate-500 block text-xs">Delivery Date</span><span className="font-medium">{detail.delivery_date || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Status</span><StatusBadge status={detail.status} /></div>
              <div><span className="text-slate-500 block text-xs">Dispatched</span><span className="font-semibold">{fmtNum(detail.dispatched_qty)}</span></div>
              <div><span className="text-slate-500 block text-xs">Pending</span><span className={detail.pending_qty > 0 ? 'font-semibold' : 'text-green-600 font-semibold'}>{fmtNum(detail.pending_qty)}</span></div>
              <div><span className="text-slate-500 block text-xs">Total Amount</span><span className="font-mono font-medium">{fmtNum(detail.total_value)}</span></div>
            </div>

            {detail.status !== 'Completed' && (
              <div className={`mb-4 rounded-lg px-3 py-2 text-xs flex items-start gap-2 border ${
                detail.status === 'Ready for Dispatch' ? 'bg-teal-50 border-teal-200 text-teal-800'
                : detail.status === 'Stock Transfer Required' ? 'bg-violet-50 border-violet-200 text-violet-800'
                : detail.status === 'Partially Dispatched' ? 'bg-blue-50 border-blue-200 text-blue-800'
                : 'bg-amber-50 border-amber-200 text-amber-800'
              }`}>
                <Calendar size={14} className="mt-0.5 shrink-0" />
                {detail.status === 'Stock Transfer Required' && <div className="flex items-center justify-between gap-4">
                  <span className="text-violet-800">Company stock exists at the Main Store — move it to the Dispatch location with a transfer (this is NOT a Purchase Requirement).</span>
                  <button onClick={() => transferForOrder(detail)} className="btn btn-secondary btn-sm shrink-0"><ArrowLeftRight size={13} className="mr-1" /> Transfer to Dispatch</button>
                </div>}
                <div>
                  {detail.status === 'Ready for Dispatch' && <>Stock at the Dispatch location is sufficient — this order is ready to dispatch.</>}
                  {detail.status === 'Partially Dispatched' && <>Order partially dispatched. Remaining {fmtNum(detail.pending_qty)} unit(s) can be dispatched as separate date-wise entries.</>}
                  {detail.status === 'Purchase / Stock Required' && <>Stock insufficient for a {detail.order_type || 'TRADING'} order — arrange purchase / stock (existing Purchases + Purchase Requirements modules).</>}
                  {detail.status === 'Production Required' && <>Stock insufficient for a manufacturing order — schedule production (existing Production Department).</>}
                </div>
              </div>
            )}

            {detail.commitment && <div className="mb-3 text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">Commitment: {detail.commitment}</div>}

            <div className="flex items-center gap-2 mb-2">
              <PackageSearch size={15} className="text-amber-500" />
              <h4 className="font-semibold text-slate-800 text-sm">Order Lines — Stock Position</h4>
            </div>
            <div className="overflow-x-auto mb-4">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wide text-slate-400 border-b border-gray-100">
                    <th className="py-1.5 pr-3">Item</th><th className="py-1.5 pr-3 text-right">Required</th>
                    <th className="py-1.5 pr-3 text-right">At Dispatch</th><th className="py-1.5 pr-3 text-right">Main Store</th>
                    <th className="py-1.5">Readiness</th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.stock?.lines || []).map((s) => (
                    <tr key={s.line_id} className="border-b border-gray-50">
                      <td className="py-1.5 pr-3 font-medium text-slate-700">
                        {(detail.lines || []).find((l) => l.id === s.line_id)?.description || `Line #${s.line_id}`}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{fmtNum(s.required)}</td>
                      <td className="py-1.5 pr-3 text-right">{s.tracked ? fmtNum(s.available_dispatch) : <span className="text-slate-400 italic">untracked</span>}</td>
                      <td className="py-1.5 pr-3 text-right">{s.tracked ? fmtNum(s.available_main) : '—'}</td>
                      <td className="py-1.5">{s.ready == null ? '—' : s.ready ? <Badge className="bg-green-100 text-green-700" dot>Ready</Badge> : <Badge className="bg-red-100 text-red-700">Short</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Table columns={detailLineCols} data={detail.lines || []} keyField="id" stickyColumns={['description']} dense />

            <div className="flex items-center gap-2 mt-5 mb-2">
              <Truck size={15} className="text-amber-500" />
              <h4 className="font-semibold text-slate-800 text-sm">Date-wise Dispatch History</h4>
              <Badge className="bg-slate-100 text-slate-600 ml-2">{flattenedHistory.length} entry(ies)</Badge>
            </div>
            {flattenedHistory.length === 0 ? <Empty text="No dispatches yet — record the first actual dispatch entry" /> : (
              <Table columns={histCols} data={flattenedHistory} keyField="entry_line_id" dense />
            )}
          </>
        )}
      </Modal>

      {/* Create / Edit order modal */}
      <Modal open={showOrderForm} title={editing ? `Edit Local Order ${editing.order_no}` : 'New Local Order'} onClose={() => setShowOrderForm(false)} wide
        footer={<>
          <button onClick={() => setShowOrderForm(false)} className="btn btn-secondary" disabled={saving}>Cancel</button>
          <button onClick={submit} disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : editing ? 'Save Changes' : 'Create Order'}</button>
        </>}>
        {errors.api && <div className="mb-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{errors.api}</div>}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-sm">
          <div className="sm:col-span-2">
            <label className="block text-slate-500 text-xs mb-1">Customer <span className="text-red-500">*</span> <span className="text-slate-400">(new name auto-creates in master)</span></label>
            <SearchSelect
              options={customers.map((c) => ({ id: c.id, label: c.name }))}
              value={form.customer_id || null}
              initialLabel={!form.customer_id ? (form.customer_name || '') : ''}
              placeholder="Type to search or enter a new customer"
              onChange={(id, manual) => setForm((f) => {
                const c = id ? customers.find((cc) => cc.id === id) : null
                return {
                  ...f, customer_id: id, customer_name: manual,
                  customer_mobile: c ? (f.customer_mobile || c.phone || '') : f.customer_mobile,
                  customer_email: c ? (f.customer_email || c.email || '') : f.customer_email,
                }
              })}
            />
            {errors.customer_id && <p className="text-xs text-red-600 mt-1">{errors.customer_id}</p>}
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">Customer Mobile</label>
            <input value={form.customer_mobile || ''} onChange={(e) => setForm({ ...form, customer_mobile: e.target.value })} type="tel" placeholder="e.g. 98XXXXXXXX" className="input" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">Customer Email</label>
            <input value={form.customer_email || ''} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} type="email" placeholder="e.g. name@company.com" className="input" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">SO Number <span className="text-slate-400">(manual)</span></label>
            <input value={form.so_no || ''} onChange={(e) => setForm({ ...form, so_no: e.target.value })} placeholder="e.g. ABC/2026/00125" className="input" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">PO Number <span className="text-slate-400">(manual)</span></label>
            <input value={form.customer_po_no || ''} onChange={(e) => setForm({ ...form, customer_po_no: e.target.value })} placeholder="e.g. PO/2026/00088" className="input" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">Order Type</label>
            <select value={form.local_order_type || 'TRADING'} onChange={(e) => setForm({ ...form, local_order_type: e.target.value })} className="input">
              <option value="TRADING">Trading</option>
              <option value="MANUFACTURING">Manufacturing</option>
            </select>
          </div>
          {editing && (
            <div>
              <label className="block text-slate-500 text-xs mb-1">Status <span className="text-slate-400">(manual)</span></label>
              <select value={form.status || 'New'} onChange={(e) => setForm({ ...form, status: e.target.value })} className="input">
                <option value="New">New</option>
                <option value="In Production">Production Required</option>
                <option value="Production Completed">Production Completed</option>
                <option value="Ready">Ready for Dispatch</option>
                <option value="Confirmed">Purchase / Stock Required</option>
                <option value="Dispatched">Partially Dispatched</option>
                <option value="Completed">Completed</option>
                <option value="Cancelled">Cancelled</option>
              </select>
              <p className="text-[0.6875rem] text-slate-400 mt-1">User-controlled — Production never changes it automatically.</p>
            </div>
          )}
          <div>
            <label className="block text-slate-500 text-xs mb-1">Order Date</label>
            <input type="date" value={form.order_date || ''} onChange={(e) => setForm({ ...form, order_date: e.target.value })} className="input" />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-slate-500 text-xs mb-1">Delivery Date</label>
            <input type="date" value={form.delivery_date || ''} onChange={(e) => setForm({ ...form, delivery_date: e.target.value })} className="input" />
          </div>
          <div className="sm:col-span-2">
            <label className="block text-slate-500 text-xs mb-1">Commitment / Remarks</label>
            <input value={form.remarks || ''} onChange={(e) => setForm({ ...form, remarks: e.target.value })} className="input" />
          </div>

          <div className="sm:col-span-4 mt-2 border-t border-gray-100 pt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-slate-700 text-sm">Order Items — Size / Description</span>
              <button onClick={addLine} className="btn btn-secondary text-xs py-1.5"><Plus size={13} /> Add Item</button>
            </div>

            {(form.lines || []).map((l, i) => (
              <div key={i} className="relative grid grid-cols-2 sm:grid-cols-12 gap-2 mb-3 p-3 rounded-lg bg-slate-50/70 border border-gray-100">
                <button onClick={() => removeLine(i)} className="absolute top-2 right-2 text-red-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Remove item"><X size={14} /></button>
                <div className="col-span-2 sm:col-span-4">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Product</label>
                  <SearchSelect
                    options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''}` }))}
                    value={l.product_id || null}
                    initialLabel={!l.product_id ? (l.description || '') : ''}
                    placeholder="Product or manual item…"
                    className="input py-1.5"
                    onChange={(id, manual) => setLineProduct(i, id || null, manual)}
                  />
                  {errors[`line_${i}_product`] && <p className="text-xs text-red-600 mt-1">{errors[`line_${i}_product`]}</p>}
                </div>
                <div className="col-span-2 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Size / Description</label>
                  <input value={l.description || ''} onChange={(e) => updateLine(i, 'description', e.target.value)} className="input py-1.5" />
                </div>
                <div className="col-span-2 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Item Code</label>
                  <input value={l.item_code || ''} onChange={(e) => updateLine(i, 'item_code', e.target.value)} placeholder="e.g. LAP-001" className="input py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-2">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Qty <span className="text-red-500">*</span></label>
                  <input type="number" min="1" step="any" value={l.quantity ?? ''} onChange={(e) => updateLine(i, 'quantity', e.target.value)} className="input py-1.5" />
                  {errors[`line_${i}_qty`] && <p className="text-xs text-red-600 mt-1">{errors[`line_${i}_qty`]}</p>}
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Unit</label>
                  <input value={l.uom || ''} list="local-uom-options" onChange={(e) => updateLine(i, 'uom', e.target.value)} placeholder="KG / NOS / NO. OF BOX" className="input py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Rate</label>
                  <input type="number" min="0" step="any" value={l.unit_price ?? ''} onChange={(e) => updateLine(i, 'unit_price', e.target.value)} placeholder="0" className="input py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Less</label>
                  <input type="number" min="0" step="any" value={l.less ?? ''} onChange={(e) => updateLine(i, 'less', e.target.value)} placeholder="0" className="input py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Amount</label>
                  <div className="input input-num py-1.5 bg-white text-right font-mono text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis">{fmtNum(lineAmt(l))}</div>
                </div>
              </div>
            ))}

            <datalist id="local-uom-options">
              <option value="KG" /><option value="NOS" /><option value="NO. OF BOX" />
            </datalist>
            {errors.lines && <p className="text-xs text-red-600 mt-1">{errors.lines}</p>}

            <div className="flex items-center justify-between border-t border-gray-100 pt-3 mt-1">
              <span className="text-xs text-slate-500">Total Amount = Qty × Rate (Less is recorded but not subtracted)</span>
              <div className="flex items-center gap-3">
                <span className="text-sm text-slate-600 font-medium">Order Total</span>
                <span className="text-base font-bold text-slate-900 font-mono">{fmtNum(orderTotal)}</span>
              </div>
            </div>
          </div>
        </div>
      </Modal>

      {/* Dispatch entry modal */}
      {showEntry && entry && (
        <Modal open title={entry.entry_line_id ? `Edit Dispatch Entry — ${entry.dispatch_no}` : `Dispatch Local Order ${entry.order?.order_no || ''}`} onClose={() => setShowEntry(false)}
          footer={<>
            <button onClick={() => setShowEntry(false)} className="btn btn-secondary">Cancel</button>
            <button onClick={saveEntry} disabled={entrySaving || entryTooBig || (entryMax != null && entryMax <= 0)} className="btn btn-primary">{entrySaving ? 'Saving…' : entry.entry_line_id ? 'Save Entry' : 'Record Dispatch'}</button>
          </>}>
          {entryErr && <div className="mb-3 text-sm state-box bg-red-50 text-red-700 border border-red-200">{entryErr}</div>}
          {entryRemaining != null && (
            <div className={`mb-3 rounded-lg px-3 py-2 text-xs flex items-center gap-2 border ${
              entryRemaining > 0 ? 'bg-blue-50 border-blue-200 text-blue-800' : 'bg-green-50 border-green-200 text-green-700'
            }`}>
              <Truck size={14} className="shrink-0" />
              {entryRemaining > 0
                ? <span>Schedule <b>{fmtNum(Number(entryLine.quantity) || 0)}</b> · Dispatched <b>{fmtNum(Number(entryLine.dispatched_qty) || 0)}</b> · <b>Remaining to Dispatch: {fmtNum(entryRemaining)}</b></span>
                : <span>Order line fully dispatched — Balance 0. This order will be marked <b>Completed</b>.</span>}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3 text-sm mb-3">
            <div className="col-span-2"><label className="block text-slate-500 text-xs mb-1">Product</label>
              <SearchSelect
                options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''}` }))}
                value={entry.product_id || null}
                initialLabel={!entry.product_id ? (entry.description || '') : ''}
                placeholder="Product or manual item…"
                onChange={(id, manual) => {
                  const p = id ? products.find((pp) => pp.id === id) : null
                  setEntry((f) => ({ ...f, product_id: id, description: id ? f.description : (manual || ''), item_code: p ? (f.item_code || p.item_code || '') : (f.item_code || '') }))
                }}
              /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Size / Description</label>
              <input value={entry.description || ''} onChange={(e) => setEntry({ ...entry, description: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Item Code</label>
              <input value={entry.item_code || ''} onChange={(e) => setEntry({ ...entry, item_code: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Dispatch Qty <span className="text-red-500">*</span></label>
              <input value={entry.quantity ?? ''} type="number" min="0" step="any"
                max={entryMax != null ? entryMax : undefined}
                onChange={(e) => { const v = e.target.value; setEntry({ ...entry, quantity: v }); const tooBig = entryMax != null && Number(v) > entryMax; if (tooBig) { const why = []; if (entryRemaining != null && Number(v) > Number(entryRemaining) + Number(entry.oldQty || 0)) why.push(`only ${fmtNum(entryRemaining)} remaining to dispatch`); if (entryStockCap != null && Number(v) > entryStockCap) why.push(`available stock is ${fmtNum(entry.available)}`); setEntryErr(`Dispatch quantity cannot exceed ${why.join(' and ')}.`); } else setEntryErr(null) }} className="input" />
              <p className="text-xs mt-1">
                {entryTooBig && <span className="text-red-600 font-medium">Max allowed: {fmtNum(entryMax)}</span>}
                {entryRemaining != null && !entryTooBig && <span className="text-slate-500">Remaining to Dispatch: <b>{fmtNum(entryRemaining)}</b>{entry.oldQty ? <span className="text-slate-400"> (incl. current entry {fmtNum(entry.oldQty)})</span> : null}</span>}
                {entryRemaining == null && entry.available != null && !entryTooBig
                  ? <span className={entryTooBig ? 'text-red-600 font-medium' : 'text-slate-500'}>Available Stock: {fmtNum(entry.available)}{entry.oldQty ? <span className="text-slate-400"> (incl. current entry {fmtNum(entry.oldQty)})</span> : null}</span>
                  : entry.available != null && !entryTooBig ? <span className="text-slate-400"> · Available Stock: {fmtNum(entry.available)}</span> : null}
                {entryRemaining == null && entry.available == null && <span className="text-slate-400 italic">Tracked stock / balance unknown for this item</span>}
              </p></div>
            <div><label className="block text-slate-500 text-xs mb-1">Dispatch Date</label>
              <input type="date" value={entry.dispatch_date} onChange={(e) => setEntry({ ...entry, dispatch_date: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Rate</label>
              <input value={entry.rate ?? ''} type="number" onChange={(e) => setEntry({ ...entry, rate: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Weight</label>
              <input value={entry.weight ?? ''} type="number" onChange={(e) => setEntry({ ...entry, weight: e.target.value })} className="input" /></div>
          </div>
          <p className="text-xs text-slate-400">Each dispatch creates a separate date-wise historical transaction; stock is deducted from the Dispatch location. Editing an order afterwards never rewrites this history.</p>
        </Modal>
      )}

      <Modal open={showImport} title="Import Local Orders"
        onClose={() => { setShowImport(false); setImportResult(null); setImportFile(null) }}
        footer={<>
          <button onClick={() => { setShowImport(false); setImportResult(null); setImportFile(null) }} className="btn btn-secondary" disabled={importBusy}>Close</button>
          <button onClick={runImport} className="btn btn-primary" disabled={importBusy}>
            {importBusy ? 'Importing…' : 'Import'}
          </button>
        </>}>
        <p className="text-sm text-gray-500 mb-4">
          CSV or Excel. Required: Customer, Size/Description or Item Code, Quantity.
          Optional: SO Number, PO Number, Order Date, Delivery Date, Order Type,
          Mobile, Email, Unit, Rate, Less, Remarks. Rows are grouped into one order
          per SO Number (or per PO Number when no SO number, otherwise per row). SO
          Numbers are kept exactly as entered.
        </p>
        <input type="file" accept=".csv,.xlsx,.xls" className="input mb-4"
          onChange={(e) => setImportFile(e.target.files?.[0])} />
        {importResult && (
          <div className="bg-gray-50 rounded-lg p-4 text-sm">
            <p className="font-bold mb-1">Results</p>
            <p>Created: {importResult.summary?.created ?? 0}, Errors: {importResult.summary?.errors ?? 0}, Lines: {importResult.summary?.lines ?? 0}</p>
            {(importResult.created || []).length > 0 && (
              <ul className="mt-2 text-green-700 text-xs max-h-32 overflow-auto">
                {importResult.created.map((c) => <li key={c.order_id}>Row {c.rows?.join(', ') || '—'}: {c.order_no}{c.so_no ? ` (SO ${c.so_no})` : ''} — {c.lines} line(s)</li>)}
              </ul>
            )}
            {(importResult.errors || []).length > 0 && (
              <ul className="mt-2 text-red-600 text-xs max-h-40 overflow-auto">
                {importResult.errors.map((e, i) => <li key={i}>Row {e.row}: {e.message}</li>)}
              </ul>
            )}
          </div>
        )}
      </Modal>

      {showTransferModal && (
        <StockTransferModal
          open={showTransferModal}
          onClose={() => { setShowTransferModal(false); setTransferInit(null) }}
          locations={locations}
          products={products}
          customers={customers}
          initial={transferInit}
          onSaved={afterTransfer}
        />
      )}
    </div>
  )
}