import { useEffect, useState } from 'react'
import { Download, RefreshCw, Users, Truck, ClipboardCheck, AlertTriangle, Package, ChevronDown, ChevronRight, Calendar, Factory, Plus, Pencil, Trash2, Eye, Search, ArrowLeftRight } from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Loading, Empty, Badge, StatCard, StatusBadge, Modal, PageTabs, SearchSelect } from '../components/ui'
import Table from '../components/Table'
import StockTransferModal, { findDispatchPlant } from '../components/StockTransferModal'
import { fmtNum, CompletionBar } from '../lib/format'

const TABS = [
  { key: 'dispatches', label: 'Dispatches', icon: <Truck size={15} /> },
  { key: 'customer', label: 'Customer Dispatch', icon: <Users size={15} /> },
  { key: 'dispatch-stock', label: 'Dispatch Stock', icon: <Package size={15} /> },
  { key: 'production', label: 'Completed Production', icon: <Factory size={15} /> },
  { key: 'local', label: 'Local Orders', icon: <Package size={15} /> },
]

const today = () => new Date().toISOString().slice(0, 10)

const blankLine = () => ({ product_id: '', item_code: '', description: '', quantity: '', dispatch_date: today(), rate: '', weight: '', sales_order_line_id: null, schedule_qty: '' })

const orderLinesToLines = (order, orderLineDetails = []) => {
  const map = Object.fromEntries((orderLineDetails || []).map((x) => [x.sales_order_line_id, x]))
  return (order?.lines || []).map((ln) => {
    const d = map[ln.id]
    const sched = d?.schedule_qty ?? ln.schedule_qty ?? ln.balance_qty ?? ln.quantity ?? ''
    return {
      product_id: ln.product_id ?? d?.product_id ?? '',
      item_code: ln.item_code || ln.product?.item_code || d?.item_code || '',
      description: ln.description || ln.product?.model || d?.description || '',
      quantity: ln.quantity ?? '',
      dispatch_date: today(),
      rate: ln.rate ?? d?.rate ?? '',
      weight: '',
      sales_order_line_id: ln.id ?? null,
      schedule_qty: sched,
    }
  })
}

export default function Dispatch() {
  const [tab, setTab] = useState('dispatches')

  // --- shared state ---
  const [customers, setCustomers] = useState([])
  const [orders, setOrders] = useState([])
  const [products, setProducts] = useState([])
  const [salespersons, setSalespersons] = useState([])
  const [loading, setLoading] = useState(true)

  // --- Dispatches (manage) state ---
  const [disps, setDisps] = useState([])
  const [dispLoading, setDispLoading] = useState(true)
  const [dispSearch, setDispSearch] = useState('')
  const [showDispForm, setShowDispForm] = useState(false)
  const [dispForm, setDispForm] = useState(null)
  const [dispError, setDispError] = useState(null)
  const [showEntryForm, setShowEntryForm] = useState(false)
  const [entryForm, setEntryForm] = useState(null)
  const [entryError, setEntryError] = useState(null)
  const [viewDisp, setViewDisp] = useState(null)

  // --- Customer dispatch state ---
  const [summary, setSummary] = useState([])
  const [selected, setSelected] = useState('')
  const [customerItems, setCustomerItems] = useState([])
  const [expandedItem, setExpandedItem] = useState(null)
  const [search, setSearch] = useState('')
  const [filterPO, setFilterPO] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [itemTotal, setItemTotal] = useState(0)

  // --- Completed production state ---
  const [production, setProduction] = useState([])
  const [prodLoading, setProdLoading] = useState(true)
  const [prodFrom, setProdFrom] = useState('')
  const [prodTo, setProdTo] = useState('')
  const [prodTotal, setProdTotal] = useState(0)

  // --- Local orders state ---
  const [localOrders, setLocalOrders] = useState([])
  const [localLoading, setLocalLoading] = useState(true)
  const [localFrom, setLocalFrom] = useState('')
  const [localTo, setLocalTo] = useState('')
  const [localTotal, setLocalTotal] = useState(0)
  const [localExpanded, setLocalExpanded] = useState(null)
  const [localFilter, setLocalFilter] = useState('')
  const [localReadyOnly, setLocalReadyOnly] = useState(false)

  // --- Dispatch stock state ---
  const [dispatchStock, setDispatchStock] = useState([])
  const [dispatchStockLoading, setDispatchStockLoading] = useState(true)
  const [dispatchStockTotal, setDispatchStockTotal] = useState(0)

  // --- Stock transfer (reposition for local orders) state ---
  const [locations, setLocations] = useState([])
  const [dispatchPlantId, setDispatchPlantId] = useState(null)
  const [showTransferModal, setShowTransferModal] = useState(false)
  const [transferInit, setTransferInit] = useState(null)

  // --- shared ---
  const [msg, setMsg] = useState('')
  const [msgType, setMsgType] = useState('success')

  const flash = (text, type = 'success') => {
    setMsg(text); setMsgType(type)
    setTimeout(() => setMsg(''), 4000)
  }

  useEffect(() => {
    api.get('/customers', { params: { page_size: 500 } })
      .then((r) => setCustomers(r.data.items || []))
      .catch(() => {})
    api.get('/orders', { params: { page_size: 500, exclude_order_type: '' } })
      .then((r) => setOrders(r.data.items || []))
      .catch(() => {})
    api.get('/products', { params: { page_size: 500 } })
      .then((r) => setProducts(r.data.items || []))
      .catch(() => {})
    api.get('/salespersons').then((r) => setSalespersons(r.data.items || [])).catch(() => {})
    api.get('/inventory/locations').then((r) => {
      const locs = r.data.items || []
      setLocations(locs)
      setDispatchPlantId(findDispatchPlant(locs))
    }).catch(() => {})
    loadSummary()
  }, [])

  // --- DISPATCHES (manage) ---
  const loadDisps = () => {
    setDispLoading(true)
    api.get('/dispatch', { params: { search: dispSearch || undefined, page_size: 200 } })
      .then((r) => setDisps(r.data.items || []))
      .catch(() => setDisps([]))
      .finally(() => setDispLoading(false))
  }
  useEffect(() => { if (tab === 'dispatches') loadDisps() }, [tab, dispSearch])

  const orderOf = (id) => orders.find((o) => o.id === id)

  const openNewDispatch = (prefill) => {
    setDispForm(dispatch => ({
      id: null, dispatch_no: '',
      customer_id: prefill?.customer_id ?? null,
      customer_name: prefill?.customer_name || '',
      sales_order_id: prefill?.sales_order_id ?? null,
      schedule_qty: prefill?.schedule_qty ?? '',
      dispatch_date: prefill?.dispatch_date || today(),
      sales_person: '', remarks: '',
      lines: prefill?.lines ? prefill.lines.map((l) => ({ product_id: l.product_id ?? '', item_code: l.item_code || '', description: l.description || '', quantity: l.quantity ?? '', dispatch_date: l.dispatch_date || today(), rate: l.rate ?? '', weight: l.weight ?? '', sales_order_line_id: l.sales_order_line_id ?? null })) : [],
    }))
    setDispError(null)
    setShowDispForm(true)
  }

  const openEditDispatch = async (d) => {
    try {
      const r = await api.get(`/dispatch/${d.id}`)
      const x = r.data
      setDispForm({
        id: x.id, dispatch_no: x.dispatch_no,
        customer_id: x.customer_id ?? null, customer_name: x.customer?.name || '',
        sales_order_id: x.sales_order_id ?? null,
        schedule_qty: x.schedule_qty ?? 0, dispatch_date: x.dispatch_date || today(),
        sales_person: x.sales_person || '', remarks: x.remarks || '', lines: [],
      })
      setDispError(null); setShowDispForm(true)
    } catch (e) { alert('Failed to load dispatch: ' + (e.response?.data?.detail || e.message)) }
  }

  const saveDispForm = async () => {
    if (!dispForm.customer_id && !(dispForm.customer_name || '').trim()) {
      setDispError('Select or enter a customer'); return
    }
    const header = {
      customer_id: dispForm.customer_id ? Number(dispForm.customer_id) : null,
      customer_name: dispForm.customer_name || '',
      sales_order_id: dispForm.sales_order_id ? Number(dispForm.sales_order_id) : null,
      schedule_qty: Number(dispForm.schedule_qty || 0),
      dispatch_date: dispForm.dispatch_date,
      sales_person: dispForm.sales_person || '',
      remarks: dispForm.remarks || '',
    }
    try {
      if (dispForm.id) {
        await api.patch(`/dispatch/${dispForm.id}`, header)
      } else {
        const lines = dispForm.lines
          .filter((l) => l.product_id || (l.item_code || '').trim() || (l.description || '').trim())
          .map((l) => ({
            product_id: l.product_id ? Number(l.product_id) : null,
            item_code: l.item_code || '', description: l.description || '',
            quantity: Number(l.quantity || 0),
            dispatch_date: l.dispatch_date || dispForm.dispatch_date,
            rate: l.rate !== '' && l.rate != null ? Number(l.rate) : null,
            weight: l.weight !== '' && l.weight != null ? Number(l.weight) : null,
            sales_order_line_id: l.sales_order_line_id ? Number(l.sales_order_line_id) : null,
          }))
        await api.post('/dispatch', { ...header, dispatch_no: dispForm.dispatch_no || null, lines })
      }
      setShowDispForm(false); setDispForm(null); setDispError(null)
      flash(dispForm.id ? 'Dispatch updated' : 'Dispatch created')
      loadDisps(); loadSummary()
      if (tab === 'local') loadLocal()
      if (viewDisp) openView(viewDisp)
      if (tab === 'customer' && selected) selectCustomer(selected)
    } catch (e) { setDispError(e.response?.data?.detail || 'Save failed') }
  }

  const delDispatch = async (d) => {
    if (!confirm(`Delete dispatch ${d.dispatch_no}? All entries and stock movements will be reversed.`)) return
    try {
      await api.delete(`/dispatch/${d.id}`)
      flash(`Dispatch ${d.dispatch_no} deleted`)
      loadDisps(); loadSummary()
      if (viewDisp?.id === d.id) setViewDisp(null)
      if (tab === 'customer' && selected) selectCustomer(selected)
    } catch (e) { alert('Delete failed: ' + (e.response?.data?.detail || e.message)) }
  }

  const openView = async (d) => {
    setViewDisp({ id: d.id, dispatch_no: d.dispatch_no, loading: true })
    try {
      const r = await api.get(`/dispatch/${d.id}`)
      setViewDisp(r.data)
    } catch (e) { setViewDisp(null); alert('Failed to load: ' + (e.response?.data?.detail || e.message)) }
  }

  // --- date-wise dispatch entries ---
  const openAddEntry = (d) => {
    setEntryForm({ dispatch_id: d.id, dispatch_no: d.dispatch_no, line_id: null,
      product_id: '', item_code: '', description: '', quantity: '', dispatch_date: today(), rate: '', weight: '' })
    setEntryError(null); setShowEntryForm(true)
  }

  const openEditEntry = (d, ln) => {
    setEntryForm({
      dispatch_id: d.id, dispatch_no: d.dispatch_no, line_id: ln.id,
      product_id: ln.product_id ?? '', item_code: ln.product?.item_code || '',
      description: ln.description || '', quantity: ln.quantity,
      dispatch_date: ln.dispatch_date, rate: ln.rate ?? '', weight: ln.weight ?? '',
    })
    setEntryError(null); setShowEntryForm(true)
  }

  const saveEntry = async () => {
    if (!(entryForm.quantity > 0)) { setEntryError('Enter a dispatch quantity'); return }
    if (!entryForm.product_id && !(entryForm.item_code || '').trim() && !(entryForm.description || '').trim()) {
      setEntryError('Select a product or enter an item code / description'); return
    }
    const payload = {
      product_id: entryForm.product_id ? Number(entryForm.product_id) : null,
      item_code: entryForm.item_code || '',
      description: entryForm.description || '',
      quantity: Number(entryForm.quantity),
      dispatch_date: entryForm.dispatch_date,
      rate: entryForm.rate !== '' && entryForm.rate != null ? Number(entryForm.rate) : null,
      weight: entryForm.weight !== '' && entryForm.weight != null ? Number(entryForm.weight) : null,
    }
    try {
      if (entryForm.line_id) {
        await api.patch(`/dispatch/lines/${entryForm.line_id}`, payload)
      } else {
        await api.post(`/dispatch/${entryForm.dispatch_id}/lines`, payload)
      }
      setShowEntryForm(false); setEntryForm(null); setEntryError(null)
      flash(entryForm.line_id ? 'Dispatch entry updated' : 'Dispatch entry added')
      loadDisps(); loadSummary()
      if (tab === 'local') loadLocal()
      if (viewDisp && viewDisp.id === entryForm.dispatch_id) openView(viewDisp)
      else if (viewDisp) openView(viewDisp)
    } catch (e) { setEntryError(e.response?.data?.detail || 'Save failed') }
  }

  const delEntry = async (d, ln) => {
    if (!confirm(`Delete dispatch entry of ${ln.quantity} on ${ln.dispatch_date}? Stock will be restored.`)) return
    try {
      await api.delete(`/dispatch/lines/${ln.id}`)
      flash('Dispatch entry deleted')
      loadDisps(); loadSummary()
      if (viewDisp && viewDisp.id === d.id) openView(d)
    } catch (e) { alert('Delete failed: ' + (e.response?.data?.detail || e.message)) }
  }

  // --- Customer dispatch ---
  const loadSummary = () => {
    setLoading(true)
    api.get('/dispatch/summary')
      .then((r) => setSummary(r.data.items || []))
      .catch(() => setSummary([]))
      .finally(() => setLoading(false))
  }

  const selectCustomer = (id) => {
    setSelected(id)
    setExpandedItem(null)
    setCustomerItems([])
    if (!id) return
    setLoading(true)
    api.get(`/dispatch/customer-items/${id}`)
      .then((r) => setCustomerItems(r.data.items || []))
      .catch(() => setCustomerItems([]))
      .finally(() => setLoading(false))
  }

  const filteredItems = customerItems.filter((item) => {
    if (search && !`${item.model} ${item.item_code} ${item.description}`.toLowerCase().includes(search.toLowerCase())) return false
    if (filterPO && item.po_no !== filterPO) return false
    if (filterStatus === 'over' && !item.is_over_dispatched) return false
    if (filterStatus === 'complete' && item.dispatch_pct < 1) return false
    if (filterStatus === 'partial' && (item.dispatch_pct <= 0 || item.dispatch_pct >= 1)) return false
    if (filterStatus === 'pending' && item.dispatched_qty > 0) return false
    return true
  })

  const poNumbers = [...new Set(customerItems.map((i) => i.po_no).filter(Boolean))]

  const itemCols = [
    { key: 'po_no', label: 'PO Number', render: (r) => <span className="font-mono text-xs">{r.po_no || '—'}</span> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.model || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => fmtNum(r.schedule_qty) },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.dispatched_qty)}</span> },
    { key: 'balance_qty', label: 'Balance', render: (r) => r.balance_qty == null ? '—' : (
      r.is_over_dispatched
        ? <Badge className="bg-red-100 text-red-700" dot>OVER · {fmtNum(r.balance_qty)}</Badge>
        : <span className={r.balance_qty <= 0 ? 'text-green-600 font-medium' : 'font-medium'}>{fmtNum(r.balance_qty)}</span>
    )},
    { key: 'dispatch_pct', label: 'Dispatch %', render: (r) => {
      const pct = (r.dispatch_pct * 100).toFixed(1)
      const cls = r.dispatch_pct >= 1 ? 'text-green-700 bg-green-100' : r.dispatch_pct > 0 ? 'text-amber-700 bg-amber-100' : 'text-slate-500 bg-slate-100'
      return <Badge className={cls}>{pct}%</Badge>
    }},
    { key: 'dispatch_count', label: 'Dispatches', render: (r) => <Badge className="bg-blue-100 text-blue-700">{r.dispatch_count}</Badge> },
    { key: 'expand', label: '', render: (r) => (
      <button onClick={() => setExpandedItem(expandedItem === r.product_id ? null : r.product_id)}
        className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="View dispatch history">
        {expandedItem === r.product_id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
      </button>
    )},
  ]

  const historyCols = [
    { key: 'dispatch_no', label: 'Dispatch Ref', render: (r) => <span className="font-mono text-xs">{r.dispatch_no}</span> },
    { key: 'quantity', label: 'Qty Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.quantity)}</span> },
    { key: 'dispatch_date', label: 'Date', render: (r) => r.dispatch_date || '—' },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
  ]

  const selectedItem = customerItems.find((i) => i.product_id === expandedItem)
  const selectedInfo = summary.find((s) => s.customer_id === Number(selected))

  // --- Completed production ---
  const loadProduction = () => {
    setProdLoading(true)
    const params = { page_size: 100 }
    if (prodFrom) params.date_from = prodFrom
    if (prodTo) params.date_to = prodTo
    api.get('/dispatch/completed-production', { params })
      .then((r) => { setProduction(r.data.items || []); setProdTotal(r.data.total || 0) })
      .catch(() => setProduction([]))
      .finally(() => setProdLoading(false))
  }
  useEffect(() => { if (tab === 'production') loadProduction() }, [tab, prodFrom, prodTo])

  const prodCols = [
    { key: 'order_no', label: 'Production Ref', render: (r) => <span className="font-mono text-xs font-medium">{r.order_no}</span> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.model || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'customer', label: 'Customer', render: (r) => r.customer?.name || <span className="text-slate-400 italic">—</span> },
    { key: 'po_no', label: 'PO Number', render: (r) => <span className="font-mono text-xs">{r.po_no || '—'}</span> },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => fmtNum(r.schedule_qty) },
    { key: 'produced_qty', label: 'Produced', render: (r) => <span className="font-semibold text-green-700">{fmtNum(r.produced_qty)}</span> },
    { key: 'available_qty', label: 'Available', render: (r) => <span className="font-semibold">{fmtNum(r.available_qty)}</span> },
    { key: 'completion_date', label: 'Completed', render: (r) => r.completion_date || '—' },
    { key: 'status', label: 'Status', render: (r) => <Badge className="bg-green-100 text-green-700">{r.status}</Badge> },
    { key: 'dispatch_now', label: '', render: (r) => (
      <button onClick={() => openDispatchNow(r)} className="btn btn-primary btn-sm py-1"><Truck size={13} className="mr-1" /> Dispatch Now</button>
    )},
  ]

  const openDispatchNow = (pr) => {
    let qty = pr.available_qty ?? ''
    if (pr.sales_order_id && pr.sales_order_line_id) {
      const o = orderOf(pr.sales_order_id)
      const line = (o?.lines || []).find((l) => l.id === pr.sales_order_line_id)
      if (line?.balance_qty != null && line.balance_qty < qty) qty = line.balance_qty
    }
    openNewDispatch({
      customer_id: pr.customer_id ?? null,
      customer_name: pr.customer?.name || '',
      sales_order_id: pr.sales_order_id ?? null,
      schedule_qty: pr.schedule_qty || pr.available_qty || '',
      lines: [{
        product_id: pr.product_id ?? '', item_code: pr.item_code || '',
        description: pr.model || '', quantity: qty,
        dispatch_date: today(),
        sales_order_line_id: pr.sales_order_line_id ?? null,
      }],
    })
    flash(`Dispatch Now — ${pr.model || pr.item_code || ''} (available: ${fmtNum(pr.available_qty)})`)
  }

  // --- Local orders ---
  const loadLocal = () => {
    setLocalLoading(true)
    const params = { page_size: 100 }
    if (localFrom) params.date_from = localFrom
    if (localTo) params.date_to = localTo
    if (localReadyOnly) params.ready_only = 1
    api.get('/dispatch/local-order-dispatch', { params })
      .then((r) => { setLocalOrders(r.data.items || []); setLocalTotal(r.data.total || 0) })
      .catch(() => setLocalOrders([]))
      .finally(() => setLocalLoading(false))
  }
  useEffect(() => { if (tab === 'local') loadLocal() }, [tab, localFrom, localTo, localReadyOnly])

  // --- Dispatch stock ---
  const loadDispatchStock = () => {
    if (!dispatchPlantId) return
    setDispatchStockLoading(true)
    api.get('/inventory', { params: { plant_id: dispatchPlantId, page_size: 500 } })
      .then((r) => { setDispatchStock(r.data.items || []); setDispatchStockTotal(r.data.total || 0) })
      .catch(() => setDispatchStock([]))
      .finally(() => setDispatchStockLoading(false))
  }
  useEffect(() => { if (tab === 'dispatch-stock' && dispatchPlantId) loadDispatchStock() }, [tab, dispatchPlantId])

  const dispatchLocal = (o, ln) => {
    openNewDispatch({
      customer_id: o.customer_id ?? null,
      customer_name: o.customer_name || o.customer || '',
      sales_order_id: o.id,
      schedule_qty: ln ? (ln.balance_qty || ln.quantity || '') : (o.quantity || ''),
      dispatch_date: today(),
      lines: [{
        product_id: ln?.product_id ?? '', item_code: ln?.item_code || '',
        description: ln?.description || '', quantity: ln ? (ln.balance_qty || '') : '',
        dispatch_date: today(), rate: ln?.rate ?? '', weight: '',
        sales_order_line_id: ln?.id ?? null,
      }],
    })
    flash(`Dispatch Local Order ${o.order_no} — ${ln?.description || ''}`)
  }

  const transferForLocal = (o) => {
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

  const afterLocalTransfer = () => {
    loadLocal(); loadDisps()
    flash('Stock transferred to Dispatch — order is now Ready for Dispatch')
  }

  const localCols = [
    { key: 'order_no', label: 'Order No', render: (r) => <span className="font-mono text-xs font-medium">{r.order_no}</span> },
    { key: 'customer', label: 'Customer', render: (r) => r.customer || '—' },
    { key: 'order_type', label: 'Type', render: (r) => <Badge className={r.order_type === 'MANUFACTURING' ? 'bg-violet-100 text-violet-700' : 'bg-cyan-100 text-cyan-700'}>{r.order_type || 'TRADING'}</Badge> },
    { key: 'order_date', label: 'Order Date', render: (r) => r.order_date || '—' },
    { key: 'delivery_date', label: 'Delivery', render: (r) => r.delivery_date || '—' },
    { key: 'description', label: 'Size / Description', render: (r) => {
      const first = (r.lines || [])[0]
      return <span className="text-xs block max-w-40 truncate">{first?.description || first?.model || '—'}</span>
    } },
    { key: 'quantity', label: 'Order Qty', render: (r) => fmtNum(r.quantity) },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => fmtNum(r.dispatched_qty) },
    { key: 'pending_qty', label: 'Pending', render: (r) => <span className="font-medium">{fmtNum(r.pending_qty)}</span> },
    { key: 'dispatch_stock', label: 'Dispatch Stock', render: (r) => <span className="font-mono text-xs">{fmtNum(r.stock_summary?.dispatch_stock)}</span> },
    { key: 'main_stock', label: 'Main Store', render: (r) => <span className="font-mono text-xs">{fmtNum(r.stock_summary?.main_store_stock)}</span> },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-1.5">
        {r.stock_summary?.transfer_required ? (
          <button onClick={() => transferForLocal(r)} className="btn btn-secondary btn-sm py-1"><ArrowLeftRight size={13} className="mr-1" /> Transfer to Dispatch</button>
        ) : (
          <button onClick={() => dispatchLocal(r, (r.lines || [])[0])} className="btn btn-primary btn-sm py-1"><Truck size={13} className="mr-1" /> Dispatch Now</button>
        )}
        <button onClick={() => setLocalExpanded(localExpanded === r.id ? null : r.id)}
          className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="View items">
          {localExpanded === r.id ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>
      </div>
    )},
  ]

  const localLineCols = [
    { key: 'description', label: 'Size / Description', render: (r) => <span className="font-medium">{r.description || r.model || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'quantity', label: 'Order Qty', render: (r) => fmtNum(r.quantity) },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => fmtNum(r.dispatched_qty) },
    { key: 'balance_qty', label: 'Pending', render: (r) => <span className={r.balance_qty < 0 ? 'text-red-600 font-semibold' : 'font-medium'}>{fmtNum(r.balance_qty)}</span> },
    { key: 'dispatch', label: '', render: (r) => (
      <button onClick={() => dispatchLocal(localExpandedOrder, r)} className="btn btn-primary btn-sm py-1"><Truck size={12} className="mr-1" /> Dispatch</button>
    )},
  ]

  const localExpandedOrder = localOrders.find((o) => o.id === localExpanded)

  // --- Dispatch stock columns ---
  const dispatchStockCols = [
    { key: 'product.model', label: 'Product', render: (r) => <span className="font-medium">{r.product?.model || '—'}</span> },
    { key: 'product.item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.product?.item_code || '—'}</span> },
    { key: 'product.category', label: 'Category', render: (r) => r.product?.category || '—' },
    { key: 'current_stock', label: 'Quantity', render: (r) => <span className="font-semibold">{fmtNum(r.current_stock)}</span> },
    { key: 'product.uom', label: 'Unit', render: (r) => r.product?.uom || '—' },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
  ]

  // --- Dispatches tab derived ---
  const dTotSched = disps.reduce((s, x) => s + (Number(x.schedule_qty) || 0), 0)
  const dTotDisp = disps.reduce((s, x) => s + (Number(x.dispatched_qty) || 0), 0)

  const dispColumns = [
    { key: 'dispatch_no', label: 'Dispatch No', render: (r) => <span className="font-mono text-xs font-medium">{r.dispatch_no}</span> },
    { key: 'customer', label: 'Customer', render: (r) => r.customer?.name || '—' },
    { key: 'order', label: 'Order', render: (r) => {
      const o = orderOf(r.sales_order_id)
      return r.sales_order_id ? <span className="font-mono text-xs">{o?.order_no || `#${r.sales_order_id}`}</span> : <span className="text-slate-400">—</span>
    }},
    { key: 'schedule_qty', label: 'Schedule', render: (r) => <span className="font-medium">{fmtNum(r.schedule_qty)}</span> },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.dispatched_qty)}</span> },
    { key: 'balance_qty', label: 'Balance', render: (r) => (
      r.balance_qty < 0
        ? <Badge className="bg-red-100 text-red-700" dot>OVER · {fmtNum(r.balance_qty)}</Badge>
        : <span className={r.balance_qty <= 0 ? 'text-green-600 font-medium' : 'font-medium'}>{fmtNum(r.balance_qty)}</span>
    )},
    { key: 'pct', label: 'Dispatch %', render: (r) => {
      const pct = ((r.completion_pct ?? 0) * 100).toFixed(1)
      const cls = r.completion_pct >= 1 ? 'text-green-700 bg-green-100' : r.completion_pct > 0 ? 'text-amber-700 bg-amber-100' : 'text-slate-500 bg-slate-100'
      return <Badge className={cls}>{pct}%</Badge>
    }},
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'dispatch_date', label: 'Date', render: (r) => r.dispatch_date || r.report_date || '—' },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-1.5">
        <button onClick={() => openView(r)} className="btn btn-ghost p-1.5" title="View"><Eye size={15} /></button>
        <button onClick={() => openAddEntry(r)} className="btn btn-ghost p-1.5 text-blue-600" title="Add date-wise dispatch entry"><Plus size={15} /></button>
        <button onClick={() => openEditDispatch(r)} className="btn btn-ghost p-1.5" title="Edit (schedule)"><Pencil size={15} /></button>
        <button onClick={() => delDispatch(r)} className="btn btn-ghost p-1.5 text-red-400" title="Delete"><Trash2 size={15} /></button>
      </div>
    )},
  ]

  const viewLineCols = [
    { key: 'dispatch_date', label: 'Date', render: (r) => <span className="font-medium">{r.dispatch_date}</span> },
    { key: 'product', label: 'Product', render: (r) => <span className="font-medium">{r.product?.model || r.description || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.product?.item_code || '—'}</span> },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => r.schedule_qty != null ? fmtNum(r.schedule_qty) : '—' },
    { key: 'quantity', label: 'Qty Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.quantity)}</span> },
    { key: 'dispatched_total', label: 'Cumulative', render: (r) => r.dispatched_total != null ? fmtNum(r.dispatched_total) : '—' },
    { key: 'balance_qty', label: 'Balance', render: (r) => r.balance_qty == null ? '—' : (
      r.balance_qty < 0 ? <Badge className="bg-red-100 text-red-700" dot>OVER · {fmtNum(r.balance_qty)}</Badge>
        : <span className={r.balance_qty <= 0 ? 'text-green-600 font-medium' : 'font-medium'}>{fmtNum(r.balance_qty)}</span>
    )},
    { key: 'completion_pct', label: 'Line %', render: (r) => {
      if (r.completion_pct == null) return '—'
      const pct = (r.completion_pct * 100).toFixed(1)
      const cls = r.completion_pct >= 1 ? 'text-green-700 bg-green-100' : r.completion_pct > 0 ? 'text-amber-700 bg-amber-100' : 'text-slate-500 bg-slate-100'
      return <Badge className={cls}>{pct}%</Badge>
    }},
    { key: 'line_status', label: 'Line Status', render: (r) => r.line_status ? <StatusBadge status={r.line_status} /> : (r.status ? <StatusBadge status={r.status} /> : '—') },
    { key: 'rate', label: 'Rate', render: (r) => r.rate != null ? fmtNum(r.rate) : '—' },
    { key: 'weight', label: 'Weight', render: (r) => r.weight != null ? fmtNum(r.weight) : '—' },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-1.5">
        <button onClick={() => openEditEntry(viewDisp, r)} className="btn btn-ghost p-1.5" title="Edit entry"><Pencil size={14} /></button>
        <button onClick={() => delEntry(viewDisp, r)} className="btn btn-ghost p-1.5 text-red-400" title="Delete entry"><Trash2 size={14} /></button>
      </div>
    )},
  ]

  const refreshAll = () => {
    if (tab === 'dispatches') loadDisps()
    if (tab === 'customer') { loadSummary(); if (selected) selectCustomer(selected) }
    if (tab === 'dispatch-stock') loadDispatchStock()
    if (tab === 'production') loadProduction()
    if (tab === 'local') loadLocal()
  }

  const setDLine = (i, k, v) => {
    const lines = [...dispForm.lines]
    lines[i] = { ...lines[i], [k]: v }
    setDispForm({ ...dispForm, lines })
  }

  const setDLineProduct = (i, id, manual) => {
    const lines = [...dispForm.lines]
    const p = id ? products.find((pp) => pp.id === id) : null
    lines[i] = {
      ...lines[i],
      product_id: id,
      description: id ? lines[i].description : (manual || ''),
      item_code: p ? (lines[i].item_code || p.item_code || '') : (lines[i].item_code || ''),
    }
    setDispForm({ ...dispForm, lines })
  }

  return (
    <div className="animate-fade-in-up">
      <PageHeader
        title="Dispatch Department"
        subtitle="Live order-driven dispatch • completed production • dynamic dispatch history"
        actions={
          <>
            <button onClick={refreshAll} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
            <button onClick={() => openNewDispatch()} className="btn btn-primary"><Plus size={15} /> New Dispatch</button>
          </>
        }
      />

      {msg && (
        <div className={`mb-4 rounded-lg text-sm px-4 py-3 flex items-center gap-2 ${msgType === 'success' ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {msg}
        </div>
      )}

      {/* Stat cards (dispatches tab) */}
      {tab === 'dispatches' && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <StatCard label="Dispatch Records" value={disps.length} icon={Truck} iconClass="bg-amber-50 text-amber-600" />
          <StatCard label="Total Schedule" value={fmtNum(dTotSched)} icon={ClipboardCheck} iconClass="bg-blue-50 text-blue-600" />
          <StatCard label="Total Dispatched" value={fmtNum(dTotDisp)} icon={Package} iconClass="bg-cyan-50 text-cyan-600" />
          <StatCard label="Over-fulfilled" value={disps.filter((s) => (s.balance_qty || 0) < 0).length} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
        </div>
      )}

      {/* Stat cards (customer tab only) */}
      {tab === 'customer' && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <StatCard label="Customers" value={summary.length} icon={Users} iconClass="bg-amber-50 text-amber-600" />
          <StatCard label="Total Dispatch Lines" value={summary.reduce((s, x) => s + (x.count || 0), 0)} icon={ClipboardCheck} iconClass="bg-blue-50 text-blue-600" />
          <StatCard label="Over-fulfilled" value={summary.filter((s) => s.over_dispatched).length} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
          <StatCard label="Dispatch Done" value={fmtNum(summary.reduce((s, x) => s + (x.total_dispatched || 0), 0))} icon={Truck} iconClass="bg-cyan-50 text-cyan-600" />
        </div>
      )}

      {/* Stat cards (dispatch stock tab) */}
      {tab === 'dispatch-stock' && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <StatCard label="Stock Lines" value={dispatchStockTotal} icon={Package} iconClass="bg-amber-50 text-amber-600" />
          <StatCard label="Total Quantity" value={fmtNum(dispatchStock.reduce((s, x) => s + (Number(x.current_stock) || 0), 0))} icon={ClipboardCheck} iconClass="bg-blue-50 text-blue-600" />
          <StatCard label="Low Stock" value={dispatchStock.filter((x) => x.status === 'LOW').length} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
          <StatCard label="Out of Stock" value={dispatchStock.filter((x) => x.status === 'OUT_OF_STOCK').length} icon={AlertTriangle} iconClass="bg-red-50 text-red-600" valueClass="text-red-600" />
        </div>
      )}

      <PageTabs tabs={TABS} active={tab} onChange={setTab} />

      {/* ==================== MANAGE DISPATCHES TAB ==================== */}
      {tab === 'dispatches' && (
        <Card title="Dispatcher: Dispatch Records" subtitle={`${disps.length} dispatch record(s) — schedule vs date-wise dispatch history, DB-driven`}
          actions={
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                <input value={dispSearch} onChange={(e) => setDispSearch(e.target.value)} placeholder="Search dispatch…" className="input input-icon sm:w-56" />
              </div>
              <button onClick={loadDisps} className="btn btn-secondary"><RefreshCw size={14} /> Refresh</button>
            </div>
          }>
          {dispLoading ? <Loading /> : disps.length === 0
            ? <Empty text="No dispatch records yet — create one with New Dispatch" />
            : <Table columns={dispColumns} data={disps} keyField="id" stickyColumns={['dispatch_no']} />}
        </Card>
      )}

      {/* ==================== CUSTOMER DISPATCH TAB ==================== */}
      {tab === 'customer' && (
        <>
          {/* Customer selector */}
          <div className="card p-4 mb-5 flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-600 shrink-0">
              <Users size={16} className="text-amber-500" /> Customer:
            </div>
            <select value={selected} onChange={(e) => selectCustomer(e.target.value)} className="input sm:max-w-md">
              <option value="">Select a customer…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {selectedInfo && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 ml-0 sm:ml-auto">
                <span><span className="font-semibold text-slate-700">{selectedInfo.total_dispatched}</span> dispatched</span>
                <span><span className="font-semibold text-slate-700">{(selectedInfo.completion_pct * 100).toFixed(1)}%</span> complete</span>
              </div>
            )}
          </div>

          {/* Summary table */}
          <Card title="Customer Dispatch Summary" subtitle="Click a customer to see item-wise dispatch detail">
            {loading && !selected ? <Loading /> : summary.length === 0 ? <Empty text="No dispatch summary" /> : (
              <Table
                columns={[
                  { key: 'customer', label: 'Customer', render: (r) => <button onClick={() => selectCustomer(r.customer_id)} className="font-medium text-slate-700 hover:text-amber-700 hover:underline text-left">{r.customer || '—'}</button> },
                  { key: 'count', label: 'Dispatches', render: (r) => <Badge className="bg-slate-100 text-slate-600">{r.count}</Badge> },
                  { key: 'total_schedule', label: 'Schedule', render: (r) => fmtNum(r.total_schedule) },
                  { key: 'total_dispatched', label: 'Dispatched', render: (r) => <span className="font-semibold">{fmtNum(r.total_dispatched)}</span> },
                  { key: 'completion_pct', label: 'Completion', render: (r) => <div className="min-w-32"><CompletionBar value={r.completion_pct} /></div> },
                  { key: 'total_balance', label: 'Balance', render: (r) => r.over_dispatched
                    ? <Badge className="bg-red-100 text-red-700" dot>OVER · {fmtNum(r.total_balance)}</Badge>
                    : <span className={r.total_balance < 0 ? 'text-red-600 font-semibold' : 'font-medium'}>{fmtNum(r.total_balance)}</span>
                  },
                ]}
                data={summary} keyField="customer_id" stickyColumns={['customer']}
              />
            )}
          </Card>

          {/* Item-wise detail for selected customer */}
          {selected && (
            <Card className="mt-6" title={`${selectedInfo?.customer || 'Customer'} — Item-wise Dispatch`} subtitle={`${customerItems.length} item(s) across all dispatches`}>
              {/* Filters */}
              <div className="flex flex-wrap gap-2 mb-4 items-center">
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search model / item code…" className="input sm:w-52" />
                <select value={filterPO} onChange={(e) => setFilterPO(e.target.value)} className="input sm:w-48">
                  <option value="">All PO numbers</option>
                  {poNumbers.map((po) => <option key={po} value={po}>{po}</option>)}
                </select>
                <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="input sm:w-auto">
                  <option value="">All statuses</option>
                  <option value="pending">Pending (no dispatch)</option>
                  <option value="partial">Partially Dispatched</option>
                  <option value="complete">Completed (100%)</option>
                  <option value="over">Over-Dispatched</option>
                </select>
                <button onClick={() => downloadFile('/reports/dispatch/csv', 'dispatch.csv')} className="btn btn-secondary"><Download size={14} /> CSV</button>
              </div>

              {/* Totals */}
              <div className="flex flex-wrap gap-4 mb-3 text-xs text-slate-500">
                <span>Scheduled: <span className="font-semibold text-slate-700">{fmtNum(filteredItems.reduce((s, i) => s + (i.schedule_qty || 0), 0))}</span></span>
                <span>Dispatched: <span className="font-semibold text-slate-700">{fmtNum(filteredItems.reduce((s, i) => s + (i.dispatched_qty || 0), 0))}</span></span>
                <span>Items: <span className="font-semibold text-slate-700">{filteredItems.length}</span></span>
              </div>

              {loading ? <Loading /> : customerItems.length === 0 ? <Empty text="No dispatch items for this customer" /> : (
                <>
                  <Table columns={itemCols} data={filteredItems} keyField="product_id" stickyColumns={['model']} dense />

                  {/* Dispatch history expanded panel */}
                  {selectedItem && (
                    <div className="mt-4 border-t border-gray-100 pt-4 animate-fade-in">
                      <div className="flex items-center gap-2 mb-3">
                        <Truck size={16} className="text-amber-500" />
                        <h4 className="font-semibold text-slate-800 text-sm">
                          Dispatch History — {selectedItem.model} ({selectedItem.item_code || 'no code'})
                        </h4>
                        <Badge className="bg-slate-100 text-slate-600 ml-2">{selectedItem.dispatch_count} dispatch(es)</Badge>
                      </div>
                      {selectedItem.dispatch_history.length === 0 ? (
                        <p className="text-sm text-slate-400">No dispatch history</p>
                      ) : (
                        <Table columns={historyCols} data={selectedItem.dispatch_history} keyField="dispatch_id" dense />
                      )}
                    </div>
                  )}
                </>
              )}
            </Card>
          )}
        </>
      )}

      {/* ==================== COMPLETED PRODUCTION TAB ==================== */}
      {tab === 'production' && (
        <Card title="Completed Production Available for Dispatch" subtitle={`${prodTotal} completed production record(s) — only COMPLETED production counts as dispatchable`}>
          <div className="flex flex-wrap gap-2 mb-4 items-center">
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Calendar size={14} /> Completed between:
            </div>
            <input type="date" value={prodFrom} onChange={(e) => setProdFrom(e.target.value)} className="input w-40" />
            <span className="text-slate-400">—</span>
            <input type="date" value={prodTo} onChange={(e) => setProdTo(e.target.value)} className="input w-40" />
            {(prodFrom || prodTo) && (
              <button onClick={() => { setProdFrom(''); setProdTo('') }} className="text-xs text-amber-600 hover:underline">Clear dates</button>
            )}
          </div>
          {prodLoading ? <Loading /> : production.length === 0 ? <Empty text="No completed production records found — production moves to COMPLETED appear here automatically" /> : (
            <Table columns={prodCols} data={production} keyField="id" stickyColumns={['order_no']} />
          )}
        </Card>
      )}

      {/* ==================== LOCAL ORDERS TAB ==================== */}
      {tab === 'local' && (
        <Card title="Local Order Dispatch Plan" subtitle={`${localTotal} local order(s)`}>
          <div className="flex flex-wrap gap-2 mb-4 items-center">
            <div className="flex items-center gap-2 text-sm text-slate-600">
              <Calendar size={14} /> Order date:
            </div>
            <input type="date" value={localFrom} onChange={(e) => { setLocalFrom(e.target.value); setLocalExpanded(null) }} className="input w-40" />
            <span className="text-slate-400">—</span>
            <input type="date" value={localTo} onChange={(e) => { setLocalTo(e.target.value); setLocalExpanded(null) }} className="input w-40" />
            {(localFrom || localTo) && (
              <button onClick={() => { setLocalFrom(''); setLocalTo('') }} className="text-xs text-amber-600 hover:underline">Clear dates</button>
            )}
            <label className="flex items-center gap-1.5 text-xs font-medium text-slate-600 ml-2">
              <input type="checkbox" checked={localReadyOnly} onChange={(e) => { setLocalReadyOnly(e.target.checked); setLocalExpanded(null) }} className="w-4 h-4 rounded border-slate-300" />
              Ready / Partial only
            </label>
            <button onClick={() => dispatchLocal(localOrders.find((o) => o.status === 'Ready for Dispatch' || o.status === 'Partially Dispatched'))} className="btn btn-primary ml-auto"><Truck size={14} className="mr-1" /> Dispatch Local Order</button>
          </div>
          {localLoading ? <Loading /> : localOrders.length === 0 ? <Empty text="No local orders found" /> : (
            <>
              <Table columns={localCols} data={localOrders} keyField="id" stickyColumns={['order_no']} dense />

              {localExpandedOrder && (
                <div className="mt-4 border-t border-gray-100 pt-4 animate-fade-in">
                  <div className="flex items-center gap-2 mb-3">
                    <Package size={16} className="text-amber-500" />
                    <h4 className="font-semibold text-slate-800 text-sm">
                      Items — {localExpandedOrder.order_no}
                    </h4>
                    <span className="text-xs text-slate-400">{localExpandedOrder.customer}</span>
                    <StatusBadge status={localExpandedOrder.status} />
                  </div>
                  <Table columns={localLineCols} data={localExpandedOrder.lines} keyField="id" dense />
                </div>
              )}
            </>
          )}
        </Card>
      )}

      {/* ==================== DISPATCH STOCK TAB ==================== */}
      {tab === 'dispatch-stock' && (
        <Card title="Dispatch Department Stock" subtitle={`${dispatchStockTotal} stock line(s) at Dispatch location`}>
          <div className="flex flex-wrap gap-2 mb-4 items-center">
            {!dispatchPlantId && <p className="text-sm text-red-500">Dispatch location not found — ensure internal locations are seeded</p>}
            <a href={`/inventory?plant_id=${dispatchPlantId || ''}`} className="btn btn-outline ml-auto text-xs">
              View in Inventory
            </a>
          </div>
          {dispatchStockLoading ? <Loading /> : dispatchStock.length === 0 ? <Empty text="No stock found at Dispatch location — transfer stock from Main Store first" /> : (
            <Table columns={dispatchStockCols} data={dispatchStock} keyField="id" dense />
          )}
        </Card>
      )}

      {/* ==================== DISPATCH DETAIL MODAL ==================== */}
      {viewDisp && (
        <Modal open title={`Dispatch ${viewDisp.dispatch_no || ''}`} onClose={() => setViewDisp(null)} wide
          footer={<>
            <button onClick={() => setViewDisp(null)} className="btn btn-secondary">Close</button>
            <button onClick={() => openAddEntry(viewDisp)} className="btn btn-primary"><Plus size={14} className="mr-1" /> Add Date-wise Entry</button>
          </>}>
          {viewDisp.loading ? <Loading /> : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4 text-sm">
                <div><span className="text-slate-500 block text-xs">Schedule Qty</span><span className="font-semibold">{fmtNum(viewDisp.schedule_qty)}</span></div>
                <div><span className="text-slate-500 block text-xs">Total Dispatched</span><span className="font-semibold">{fmtNum(viewDisp.dispatched_qty)}</span></div>
                <div><span className="text-slate-500 block text-xs">Balance</span><span className={viewDisp.balance_qty < 0 ? 'font-semibold text-red-600' : 'font-semibold'}>{fmtNum(viewDisp.balance_qty)}</span></div>
                <div><span className="text-slate-500 block text-xs">Dispatch %</span><span className="font-semibold">{((viewDisp.completion_pct ?? 0) * 100).toFixed(1)}%</span></div>
              </div>
              <div className="grid grid-cols-2 gap-3 mb-4 text-sm">
                <div><span className="text-slate-500 block text-xs">Customer</span><span className="font-medium">{viewDisp.customer?.name || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">Order</span><span className="font-medium">
                  {viewDisp.sales_order_id ? (orderOf(viewDisp.sales_order_id)?.order_no || `#${viewDisp.sales_order_id}`) : '—'}
                </span></div>
                <div><span className="text-slate-500 block text-xs">Dispatch Date</span><span className="font-medium">{viewDisp.dispatch_date || viewDisp.report_date || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">Status</span><StatusBadge status={viewDisp.status} /></div>
                <div><span className="text-slate-500 block text-xs">Sales Person</span><span className="font-medium">{viewDisp.sales_person || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">Remarks</span><span className="font-medium">{viewDisp.remarks || '—'}</span></div>
              </div>
              <div className="flex items-center gap-2 mb-2">
                <Truck size={15} className="text-amber-500" />
                <h4 className="font-semibold text-slate-800 text-sm">Date-wise Dispatch History</h4>
                <Badge className="bg-slate-100 text-slate-600 ml-2">{viewDisp.lines?.length || 0} entry(ies)</Badge>
              </div>
              {!viewDisp.lines?.length ? <Empty text="No dispatch entries yet — add a date-wise entry" /> : (
                <Table columns={viewLineCols} data={viewDisp.lines} keyField="id" dense />
              )}
            </>
          )}
        </Modal>
      )}

      {/* ==================== NEW / EDIT DISPATCH MODAL ==================== */}
      {showDispForm && dispForm && (
        <Modal open title={dispForm.id ? `Edit Dispatch ${dispForm.dispatch_no}` : 'New Dispatch'} onClose={() => setShowDispForm(false)} xwide
          footer={<>
            <button onClick={() => setShowDispForm(false)} className="btn btn-secondary">Cancel</button>
            <button onClick={saveDispForm} className="btn btn-primary">{dispForm.id ? 'Save Changes' : 'Create Dispatch'}</button>
          </>}>
          {dispError && <div className="mb-3 text-sm state-box bg-red-50 text-red-700 border border-red-200">{dispError}</div>}
          <div className="grid grid-cols-2 gap-3 text-sm mb-3">
            <div><label className="block text-slate-500 text-xs mb-1">Customer * <span className="text-slate-400">(new name auto-creates in master)</span></label>
              <SearchSelect
                options={customers.map((c) => ({ id: c.id, label: c.name }))}
                value={dispForm.customer_id || null}
                initialLabel={!dispForm.customer_id ? (dispForm.customer_name || '') : ''}
                placeholder="Type to search or enter a new customer"
                onChange={(id, manual) => setDispForm((f) => ({ ...f, customer_id: id, customer_name: manual }))}
              /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Order Reference <span className="text-slate-400">(optional)</span></label>
              <select value={dispForm.sales_order_id ?? ''} onChange={(e) => {
                const id = e.target.value ? Number(e.target.value) : null
                const o = id ? orderOf(id) : null
                setDispForm((f) => ({
                  ...f, sales_order_id: id,
                  customer_id: f.customer_id || o?.customer_id || null,
                  customer_name: (!f.customer_id && o?.customer?.name) || f.customer_name || '',
                }))
                if (id && o && !dispForm?.id) {
                  api.get(`/dispatch/order-lines/${id}`)
                    .then((r) => {
                      const details = r.data.items || []
                      const sched = details.reduce((s, l) => s + (Number(l.schedule_qty) || 0), 0)
                      setDispForm((f) => (f?.sales_order_id === id ? {
                        ...f,
                        schedule_qty: f.schedule_qty || sched || 0,
                        lines: orderLinesToLines(o, details),
                      } : f))
                    })
                    .catch(() => {
                      setDispForm((f) => (f?.sales_order_id === id ? {
                        ...f,
                        schedule_qty: f.schedule_qty || o?.lines?.reduce((s, l) => s + (Number(l.schedule_qty) || Number(l.quantity) || 0), 0) || 0,
                        lines: orderLinesToLines(o),
                      } : f))
                    })
                } else if (id && o && dispForm?.id) {
                  setDispForm((f) => ({
                    ...f,
                    schedule_qty: f.schedule_qty || o?.lines?.reduce((s, l) => s + (Number(l.quantity) || 0), 0) || 0,
                  }))
                }
      if (id && o && !dispForm?.id) {
        // Fetch product-wise schedules from the order (order-line derived)
        api.get(`/dispatch/order-lines/${id}`)
          .then((r) => {
            const details = r.data.items || []
            const sched = details.reduce((s, l) => s + (Number(l.schedule_qty) || 0), 0)
            setDispForm((f) => (f?.sales_order_id === id ? {
              ...f,
              schedule_qty: f.schedule_qty || sched || 0,
              lines: orderLinesToLines(o, details),
            } : f))
          })
          .catch(() => {
            setDispForm((f) => (f?.sales_order_id === id ? {
              ...f,
              schedule_qty: f.schedule_qty || o?.lines?.reduce((s, l) => s + (Number(l.schedule_qty) || Number(l.quantity) || 0), 0) || 0,
              lines: orderLinesToLines(o),
            } : f))
          })
      } else if (id && o && dispForm?.id) {
        setDispForm((f) => ({
          ...f,
          schedule_qty: f.schedule_qty || o?.lines?.reduce((s, l) => s + (Number(l.quantity) || 0), 0) || 0,
        }))
      }
              }} className="input">
                <option value="">No order (manual dispatch)</option>
                {orders.map((o) => <option key={o.id} value={o.id}>{o.order_no} — {o.customer?.name || o.customer_name}</option>)}
              </select></div>
            <div><label className="block text-slate-500 text-xs mb-1">Schedule Quantity</label>
              <input value={dispForm.schedule_qty ?? ''} type="number" onChange={(e) => setDispForm({ ...dispForm, schedule_qty: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Dispatch Date</label>
              <input type="date" value={dispForm.dispatch_date} onChange={(e) => setDispForm({ ...dispForm, dispatch_date: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Sales Person <span className="text-slate-400">(select or type new)</span></label>
              <SearchSelect
                options={salespersons.map((s) => ({ id: s.id, label: s.name }))}
                value={dispForm.sales_person == null || dispForm.sales_person === '' ? null : (salespersons.find((s) => s.name === dispForm.sales_person)?.id || null)}
                initialLabel={(salespersons.find((s) => s.name === dispForm.sales_person)?.name) || dispForm.sales_person || ''}
                placeholder="Select or type a sales person"
                onChange={(id, manual) => {
                  const sp = id ? salespersons.find((s) => s.id === id) : null
                  setDispForm((f) => ({ ...f, sales_person: sp ? sp.name : (manual || '') }))
                }}
              /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Remarks</label>
              <input value={dispForm.remarks || ''} onChange={(e) => setDispForm({ ...dispForm, remarks: e.target.value })} className="input" /></div>
          </div>

          {!dispForm.id && (
            <>
              <div className="mb-1 text-xs font-medium text-slate-500 uppercase">Initial Dispatch Entries <span className="text-slate-400">(optional, date-wise)</span></div>
              {dispForm.lines.length > 0 && (
                <div className="hidden sm:grid grid-cols-12 gap-2 items-center text-[10px] uppercase tracking-wide text-slate-400 mb-1 px-1">
                  <div className="col-span-2">Product / Manual Item</div>
                  <div className="col-span-1">Item Code</div>
                  <div className="col-span-3">Description / Model</div>
                  <div className="col-span-1">Schedule</div>
                  <div className="col-span-1">Dispatch Qty</div>
                  <div className="col-span-1">Date</div>
                  <div className="col-span-1">Rate</div>
                  <div className="col-span-1">Wt</div>
                  <div className="col-span-1" />
                </div>
              )}
              <div className="space-y-2">
                {dispForm.lines.map((ln, i) => (
                  <div key={i} className="grid grid-cols-12 gap-2 items-center text-xs">
                    <SearchSelect
                      options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''}` }))}
                      value={ln.product_id || null}
                      initialLabel={!ln.product_id ? (ln.description || '') : ''}
                      placeholder="Product or manual item…"
                      className="input col-span-2 py-1.5"
                      onChange={(id, manual) => setDLineProduct(i, id || '', manual)}
                    />
                    <input value={ln.item_code ?? ''} onChange={(e) => setDLine(i, 'item_code', e.target.value)} placeholder="e.g. LAP-001" className="input col-span-1 py-1.5" />
                    <input value={ln.description ?? ''} onChange={(e) => setDLine(i, 'description', e.target.value)} placeholder="Model / description" className="input col-span-3 py-1.5" />
                    <span className="col-span-1 text-center font-medium text-slate-600 truncate">{ln.schedule_qty != null && ln.schedule_qty !== '' ? fmtNum(ln.schedule_qty) : '—'}</span>
                    <input value={ln.quantity ?? ''} type="number" onChange={(e) => setDLine(i, 'quantity', e.target.value)} placeholder="Qty" className="input col-span-1 py-1.5 px-1.5" />
                    <input type="date" value={ln.dispatch_date} onChange={(e) => setDLine(i, 'dispatch_date', e.target.value)} className="input col-span-1 py-1.5 px-1.5" />
                    <input value={ln.rate ?? ''} type="number" onChange={(e) => setDLine(i, 'rate', e.target.value)} placeholder="Rate" className="input col-span-1 py-1.5 px-1.5" />
                    <input value={ln.weight ?? ''} type="number" onChange={(e) => setDLine(i, 'weight', e.target.value)} placeholder="Wt" className="input col-span-1 py-1.5 px-1.5" />
                    <button onClick={() => { if (dispForm.lines.length > 1) setDispForm({ ...dispForm, lines: dispForm.lines.filter((_, j) => j !== i) }) }} className="text-red-400 hover:text-red-600 col-span-1 justify-self-end"><Trash2 size={14} /></button>
                  </div>
                ))}
              </div>
              <button onClick={() => setDispForm({ ...dispForm, lines: [...dispForm.lines, blankLine()] })} className="btn btn-ghost mt-2 text-xs"><Plus size={12} className="inline mr-1" />Add entry</button>
              <p className="text-xs text-slate-400 mt-2">Schedule Quantity and dispatch entries stay separate: edit entries later via the dispatch detail view without touching the schedule.</p>
            </>
          )}
        </Modal>
      )}

      {/* ==================== ADD / EDIT DATE-WISE ENTRY MODAL ==================== */}
      {showEntryForm && entryForm && (
        <Modal open title={entryForm.line_id ? `Edit Entry — ${entryForm.dispatch_no}` : `Add Date-wise Entry — ${entryForm.dispatch_no}`} onClose={() => setShowEntryForm(false)}
          footer={<>
            <button onClick={() => setShowEntryForm(false)} className="btn btn-secondary">Cancel</button>
            <button onClick={saveEntry} className="btn btn-primary">{entryForm.line_id ? 'Save Entry' : 'Add Entry'}</button>
          </>}>
          {entryError && <div className="mb-3 text-sm state-box bg-red-50 text-red-700 border border-red-200">{entryError}</div>}
          <div className="grid grid-cols-2 gap-3 text-sm mb-3">
            <div className="col-span-2"><label className="block text-slate-500 text-xs mb-1">Product / Manual Item</label>
              <SearchSelect
                options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''}` }))}
                value={entryForm.product_id || null}
                initialLabel={!entryForm.product_id ? (entryForm.description || '') : ''}
                placeholder="Product or manual item…"
                onChange={(id, manual) => {
                  const p = id ? products.find((pp) => pp.id === id) : null
                  setEntryForm((f) => ({ ...f, product_id: id,
                    description: id ? f.description : (manual || ''),
                    item_code: p ? (f.item_code || p.item_code || '') : (f.item_code || '') }))
                }}
              /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Item Code</label>
              <input value={entryForm.item_code || ''} onChange={(e) => setEntryForm({ ...entryForm, item_code: e.target.value })} placeholder="e.g. LAP-001" className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Dispatch Quantity *</label>
              <input value={entryForm.quantity ?? ''} type="number" onChange={(e) => setEntryForm({ ...entryForm, quantity: e.target.value })} placeholder="Qty" className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Dispatch Date</label>
              <input type="date" value={entryForm.dispatch_date} onChange={(e) => setEntryForm({ ...entryForm, dispatch_date: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Description</label>
              <input value={entryForm.description || ''} onChange={(e) => setEntryForm({ ...entryForm, description: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Rate</label>
              <input value={entryForm.rate ?? ''} type="number" onChange={(e) => setEntryForm({ ...entryForm, rate: e.target.value })} className="input" /></div>
            <div><label className="block text-slate-500 text-xs mb-1">Weight</label>
              <input value={entryForm.weight ?? ''} type="number" onChange={(e) => setEntryForm({ ...entryForm, weight: e.target.value })} className="input" /></div>
          </div>
        </Modal>
      )}

      {showTransferModal && (
        <StockTransferModal
          open={showTransferModal}
          onClose={() => { setShowTransferModal(false); setTransferInit(null) }}
          locations={locations}
          products={products}
          customers={customers}
          initial={transferInit}
          onSaved={afterLocalTransfer}
        />
      )}
    </div>
  )
}