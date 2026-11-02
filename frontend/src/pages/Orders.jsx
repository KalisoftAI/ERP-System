import { useEffect, useRef, useState } from 'react'
import { Plus, Download, Eye, Pencil, X, ShoppingBag, Layers, CheckCircle2, Clock, Trash2, Share2, FileText, Upload, Mail, Send } from 'lucide-react'
import api from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, PageTabs, StatCard, StatusBadge, SearchSelect } from '../components/ui'
import Table from '../components/Table'
import { FlowBadge } from '../lib/format'
import { fmtNum } from '../lib/format'

const TABS = [
  { key: 'all', label: 'All', icon: <Layers size={15} /> },
  { key: 'oem', label: 'Manufacture', icon: <ShoppingBag size={15} /> },
  { key: 'trading', label: 'Trading', icon: <ShoppingBag size={15} /> },
]

const ORDER_TYPE_OPTIONS = [
  { value: 'OEM', label: 'Manufacture' },
  { value: 'TRADING', label: 'Trading' },
]
const orderTypeLabel = (t) => ORDER_TYPE_OPTIONS.find((o) => o.value === t)?.label || t || '—'

const emptyLine = {
  product_id: null,
  description: '',
  item_code: '',
  quantity: 1,
  schedule_qty: null,
  ask_till_date: null,
  completion_pct: null,
  balance_qty: null,
  opening_stock: null,
  unit_price: null,
}

const errText = (err) => {
  const d = err?.response?.data?.detail
  if (Array.isArray(d)) return d.map((x) => x.msg || x).join('. ')
  if (typeof d === 'string') return d
  return 'Order operation failed. Please try again.'
}

export default function Orders() {
  const [tab, setTab] = useState('all')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [statusF, setStatusF] = useState('')
  const [customerF, setCustomerF] = useState('')
  const [searchF, setSearchF] = useState('')
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [customerDetail, setCustomerDetail] = useState(null)
  const [customerDetailLoading, setCustomerDetailLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [showEdit, setShowEdit] = useState(false)
  const [editLine, setEditLine] = useState(null)
  const [form, setForm] = useState({})
  const [lineForm, setLineForm] = useState({})
  const [customers, setCustomers] = useState([])
  const [products, setProducts] = useState([])
  const [salespersons, setSalespersons] = useState([])
  const [saving, setSaving] = useState(false)
  const [createErrors, setCreateErrors] = useState({})
  const [success, setSuccess] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [importLoading, setImportLoading] = useState(false)
  const [importPreview, setImportPreview] = useState(null)
  const [importError, setImportError] = useState('')
  const [importConfirm, setImportConfirm] = useState(false)
  const fileInputRef = useRef(null)

  const [emailOpen, setEmailOpen] = useState(false)
  const [emailLoading, setEmailLoading] = useState(false)
  const [emailType, setEmailType] = useState('confirmation')
  const [emailForm, setEmailForm] = useState({ to: '', subject: '', message: '' })
  const [emailError, setEmailError] = useState('')
  const [emailHistory, setEmailHistory] = useState([])
  const [emailDispatchId, setEmailDispatchId] = useState(null)
  const [orderDispatches, setOrderDispatches] = useState([])

  const loadMeta = () => {
    api.get('/customers', { params: { page_size: 500 } }).then((r) => setCustomers(r.data.items || []))
    api.get('/products', { params: { page_size: 500 } }).then((r) => setProducts(r.data.items || []))
    api.get('/salespersons').then((r) => setSalespersons(r.data.items || []))
  }

  const load = () => {
    setLoading(true)
    const params = { page_size: 500 }
    if (tab !== 'all') params.order_type = tab.toUpperCase()
    params.exclude_order_type = 'LOCAL'
    if (statusF) params.status = statusF
    if (customerF) params.customer_id = Number(customerF)
    if (searchF) params.search = searchF
    api.get('/orders', { params }).then((res) => { setItems(res.data.items || []); setTotal(res.data.total || 0) })
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadMeta() }, [])
  useEffect(() => { load() }, [tab, statusF, customerF])

  const openDetail = (r) => {
    setDetailLoading(true)
    api.get(`/orders/${r.order_id}`)
      .then((res) => {
        const data = res.data
        setDetail(data)
        loadEmailHistory(data.id)
        if (data.customer_id) {
          api.get(`/dispatch/by-customer/${data.customer_id}`, { params: { page_size: 500 } })
            .then((dres) => {
              const all = dres.data.items || []
              setOrderDispatches(all.filter((d) => d.sales_order_id === data.id))
            })
            .catch(() => setOrderDispatches([]))
        } else {
          setOrderDispatches([])
        }
      })
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  const removeOrder = (r) => {
    if (!window.confirm(`Delete order ${r.order_no}? This cannot be undone.`)) return
    api.delete(`/orders/${r.order_id}`)
      .then(() => {
        setDetail(null)
        setDetailLoading(false)
        setSuccess(`Order ${r.order_no} deleted`)
        setTimeout(() => setSuccess(''), 6000)
        load()
      })
      .catch((err) => {
        const d = err?.response?.data?.detail
        window.alert(typeof d === 'string' ? d : 'Failed to delete order.')
      })
  }

  const openCustomerDetail = (r) => {
    const customer = r.customer
    if (!customer?.id) {
      // No linked customer — fall back to the single order detail.
      openDetail(r)
      return
    }
    setCustomerDetailLoading(true)
    api.get('/orders', { params: { customer_id: customer.id, exclude_order_type: 'LOCAL', page_size: 500 } })
      .then((res) => {
        setCustomerDetail({
          customer: { ...customer, contact: r.customer_contact || customer.phone || '', email: r.customer_email || customer.email || '' },
          orders: res.data.items || [],
        })
      })
      .catch(() => setCustomerDetail(null))
      .finally(() => setCustomerDetailLoading(false))
  }

  const closeCustomerDetail = () => {
    setCustomerDetail(null)
    setCustomerDetailLoading(false)
  }

  const buildShareText = (order) => {
    const c = order.customer
    const lines = (order.lines || []).map((ln) => {
      const model = ln.product?.model || ln.description || ''
      const itemCode = ln.item_code || ln.product?.item_code || ''
      return `• ${itemCode} ${model} | Schedule: ${fmtNum(ln.schedule_qty)} | Dispatch: ${fmtNum(ln.dispatched_qty)} | Balance: ${fmtNum(ln.balance_qty)}`
    }).join('\n')
    return [
      `Kalika Enterprises - Order ${order.order_no}`,
      `Customer: ${c?.name || order.customer_name || ''}`,
      `PO No: ${order.customer_po_no || '—'}`,
      `SO No: ${order.order_no || '—'}`,
      `Order Date: ${order.order_date || ''}`,
      lines ? `Items:\n${lines}` : '',
    ].filter(Boolean).join('\n')
  }

  const shareOrder = (order) => {
    const text = buildShareText(order)
    if (navigator.share) {
      navigator.share({ title: `Order ${order.order_no}`, text }).catch(() => {})
    } else {
      navigator.clipboard.writeText(text).then(() => window.alert('Order summary copied to clipboard.')).catch(() => window.alert('Could not copy summary.'))
    }
  }

  const downloadPDF = (order) => {
    api.get(`/reports/orders/${order.id}/pdf`, { responseType: 'blob' })
      .then((res) => {
        const blob = new Blob([res.data], { type: 'application/pdf' })
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        const safeName = (order.order_no || order.id).toString().replace(/[^a-zA-Z0-9-_]/g, '')
        a.download = `order_${safeName || order.id}.pdf`
        document.body.appendChild(a)
        a.click()
        a.remove()
        window.URL.revokeObjectURL(url)
      })
      .catch(() => window.alert('Failed to download PDF.'))
  }

  const closeEmail = () => {
    setEmailOpen(false)
    setEmailLoading(false)
    setEmailError('')
    setEmailForm({ to: '', subject: '', message: '' })
    setEmailDispatchId(null)
  }

  const loadEmailHistory = (orderId) => {
    api.get(`/orders/${orderId}/email-history`)
      .then((res) => setEmailHistory(res.data.items || []))
      .catch(() => setEmailHistory([]))
  }

  const openEmail = (order, type = 'confirmation', dispatchId = null) => {
    setEmailType(type)
    setEmailDispatchId(dispatchId)
    setEmailLoading(true)
    setEmailError('')
    const url = type === 'dispatch' && dispatchId
      ? `/orders/${order.id}/email-preview/dispatch/${dispatchId}`
      : `/orders/${order.id}/email-preview/confirmation`
    api.get(url)
      .then((res) => {
        setEmailForm({
          to: res.data.to || '',
          subject: res.data.subject || '',
          message: res.data.message || '',
        })
        setEmailOpen(true)
        loadEmailHistory(order.id)
      })
      .catch((err) => {
        const d = err?.response?.data?.detail
        window.alert(typeof d === 'string' ? d : 'Failed to load email preview.')
      })
      .finally(() => setEmailLoading(false))
  }

  const sendEmail = (order) => {
    if (!emailForm.to.trim()) {
      setEmailError('Recipient email is required')
      return
    }
    setEmailLoading(true)
    setEmailError('')
    const url = emailType === 'dispatch' && emailDispatchId
      ? `/orders/${order.id}/send-dispatch-email/${emailDispatchId}`
      : `/orders/${order.id}/send-confirmation`
    api.post(url, {
      to: emailForm.to.trim(),
      subject: emailForm.subject.trim(),
      message: emailForm.message,
    })
      .then(() => {
        closeEmail()
        setSuccess(`Email sent to ${emailForm.to.trim()}`)
        setTimeout(() => setSuccess(''), 6000)
        loadEmailHistory(order.id)
      })
      .catch((err) => {
        const d = err?.response?.data?.detail
        setEmailError(typeof d === 'string' ? d : 'Failed to send email.')
      })
      .finally(() => setEmailLoading(false))
  }

  const openImport = () => {
    setImportOpen(true)
    setImportPreview(null)
    setImportError('')
    setImportConfirm(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const closeImport = () => {
    setImportOpen(false)
    setImportPreview(null)
    setImportError('')
    setImportConfirm(false)
    setImportLoading(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleFileSelect = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportLoading(true)
    setImportError('')
    setImportConfirm(false)
    setImportPreview(null)
    const formData = new FormData()
    formData.append('file', file)
    api.post('/orders/import-preview', formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((res) => { setImportPreview(res.data) })
      .catch((err) => {
        const d = err?.response?.data?.detail
        setImportError(typeof d === 'string' ? d : 'Preview failed. Please check the file format.')
      })
      .finally(() => setImportLoading(false))
  }

  const runImport = (force = false) => {
    const file = fileInputRef.current?.files?.[0]
    if (!file) return
    if (importPreview?.duplicate_rows && !force) {
      setImportConfirm(true)
      return
    }
    setImportLoading(true)
    const formData = new FormData()
    formData.append('file', file)
    api.post(`/orders/import?confirm_duplicates=${force ? 'true' : 'false'}`, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((res) => {
        closeImport()
        setSuccess(`Imported ${res.data.summary.created_orders} order(s) from ${file.name}`)
        setTimeout(() => setSuccess(''), 6000)
        load()
      })
      .catch((err) => {
        const d = err?.response?.data?.detail
        if (typeof d === 'object' && d?.message && d?.duplicates) {
          setImportConfirm(true)
          setImportError(`${d.message} (${d.duplicates.length} duplicate(s))`)
        } else {
          setImportError(typeof d === 'string' ? d : 'Import failed. Please check the file and try again.')
        }
      })
      .finally(() => setImportLoading(false))
  }

  const saveLine = () => {
    if (!lineForm.id) return
    api.patch(`/orders/lines/${lineForm.id}`, {
      product_id: lineForm.product_id,
      description: lineForm.description,
      item_code: (lineForm.item_code || '').trim(),
      quantity: Number(lineForm.quantity),
      schedule_qty: lineForm.schedule_qty != null && lineForm.schedule_qty !== '' ? Number(lineForm.schedule_qty) : null,
      ask_till_date: lineForm.ask_till_date != null && lineForm.ask_till_date !== '' ? Number(lineForm.ask_till_date) : null,
      completion_pct: lineForm.completion_pct != null && lineForm.completion_pct !== '' ? Number(lineForm.completion_pct) : null,
      balance_qty: lineForm.balance_qty != null && lineForm.balance_qty !== '' ? Number(lineForm.balance_qty) : null,
      opening_stock: lineForm.opening_stock != null && lineForm.opening_stock !== '' ? Number(lineForm.opening_stock) : null,
      unit_price: lineForm.unit_price != null ? Number(lineForm.unit_price) : null,
      less: lineForm.less != null && lineForm.less !== '' ? Number(lineForm.less) : null,
      amount: lineForm.amount != null ? Number(lineForm.amount) : null,
      customer_po_no: lineForm.customer_po_no,
    })
      .then((res) => { setDetail(res.data); setEditLine(null); setLineForm({}) })
      .catch((err) => window.alert(errText(err)))
  }

  const openCreate = () => {
    setForm({
      id: null,
      customer_id: null,
      customer_name: '',
      customer_contact: '',
      customer_email: '',
      order_type: tab === 'all' ? 'OEM' : tab.toUpperCase(),
      order_no: '',
      customer_po_no: '',
      salesperson_id: null,
      salesperson_name: '',
      order_date: new Date().toISOString().slice(0, 10),
      remarks: '',
      lines: [{ ...emptyLine }],
    })
    setCreateErrors({})
    setShowCreate(true)
  }

  const openEdit = (order) => {
    setForm({
      id: order.id,
      customer_id: order.customer?.id || null,
      customer_name: order.customer?.name || order.customer_name || '',
      customer_contact: order.customer_contact || order.customer?.phone || '',
      customer_email: order.customer_email || order.customer?.email || '',
      order_type: order.order_type,
      order_no: order.order_no || '',
      customer_po_no: order.customer_po_no || '',
      salesperson_id: order.salesperson?.id || null,
      salesperson_name: order.salesperson?.name || '',
      order_date: order.order_date,
      remarks: order.remarks || '',
    })
    setCreateErrors({})
    setShowEdit(true)
  }

  const closeCreate = () => {
    setShowCreate(false)
    setSaving(false)
    setCreateErrors({})
  }

  const closeEdit = () => {
    setShowEdit(false)
    setSaving(false)
    setCreateErrors({})
  }

  const addLine = () => {
    setForm({ ...form, lines: [...(form.lines || []), { ...emptyLine }] })
  }

  const updateLine = (i, key, value) => {
    const lines = [...(form.lines || [])]
    lines[i] = { ...lines[i], [key]: value }
    if (key === 'quantity' && (lines[i].schedule_qty == null || lines[i].schedule_qty === '')) {
      lines[i].schedule_qty = value
    }
    setForm({ ...form, lines })
  }

  const removeLine = (i) => {
    setForm({ ...form, lines: (form.lines || []).filter((_, idx) => idx !== i) })
  }

  const lineTotal = (l) => (Number(l.quantity) || 0) * (Number(l.unit_price) || 0)

  const orderTotal = (form.lines || []).reduce((s, l) => s + lineTotal(l), 0)

  const validateCreate = () => {
    const errs = {}
    if (!form.customer_id && !(form.customer_name || '').trim()) errs.customer_id = 'Select or type a customer'
    if (!(form.order_no || '').trim()) errs.order_no = 'SO Number is required'
    const lines = form.lines || []
    if (lines.length === 0) errs.lines = 'Add at least one product line'
    lines.forEach((l, i) => {
      if (!l.product_id && !(l.description || '').trim()) errs[`line_${i}_product`] = 'Select a product or type an item description'
      if (!(Number(l.quantity) > 0)) errs[`line_${i}_qty`] = 'Qty > 0 required'
    })
    setCreateErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleProductLine = (i, id, manual) => {
    const lines = [...(form.lines || [])]
    if (id) {
      const product = products.find((p) => String(p.id) === String(id))
      lines[i] = {
        ...lines[i],
        product_id: id,
        description: manual || lines[i].description || product?.model || '',
        item_code: product?.item_code || lines[i].item_code || '',
      }
    } else {
      lines[i] = { ...lines[i], product_id: null, description: manual || '' }
    }
    if ((lines[i].schedule_qty == null || lines[i].schedule_qty === '') && Number(lines[i].quantity) > 0) {
      lines[i].schedule_qty = lines[i].quantity
    }
    setForm({ ...form, lines })
  }

  const customerById = (id) => customers.find((c) => String(c.id) === String(id))

  const handleCustomerChange = (id, manual) => {
    setForm((f) => {
      const selected = id ? customerById(id) : null
      const contact = selected ? (selected.phone || '') : f.customer_contact
      const email = selected ? (selected.email || '') : f.customer_email
      return {
        ...f,
        customer_id: id,
        customer_name: selected ? selected.name : (manual || ''),
        customer_contact: contact || f.customer_contact || '',
        customer_email: email || f.customer_email || '',
      }
    })
  }

  const submitCreate = () => {
    if (!validateCreate()) return
    setSaving(true)
    const payload = {
      customer_id: form.customer_id,
      customer_name: (form.customer_name || '').trim(),
      customer_contact: (form.customer_contact || '').trim(),
      customer_email: (form.customer_email || '').trim(),
      order_type: form.order_type,
      order_no: (form.order_no || '').trim(),
      customer_po_no: form.customer_po_no || '',
      salesperson_id: form.salesperson_id || null,
      salesperson_name: (form.salesperson_name || '').trim(),
      order_date: form.order_date || new Date().toISOString().slice(0, 10),
      remarks: form.remarks || '',
      lines: (form.lines || []).map((l) => ({
        product_id: l.product_id,
        description: l.description || '',
        item_code: (l.item_code || '').trim(),
        quantity: Number(l.quantity),
        schedule_qty: l.schedule_qty != null && l.schedule_qty !== '' ? Number(l.schedule_qty) : null,
        ask_till_date: l.ask_till_date != null && l.ask_till_date !== '' ? Number(l.ask_till_date) : null,
        completion_pct: l.completion_pct != null && l.completion_pct !== '' ? Number(l.completion_pct) : null,
        balance_qty: l.balance_qty != null && l.balance_qty !== '' ? Number(l.balance_qty) : null,
        opening_stock: l.opening_stock != null && l.opening_stock !== '' ? Number(l.opening_stock) : null,
        unit_price: Number(l.unit_price) || null,
        amount: lineTotal(l) || null,
        customer_po_no: '',
      })),
    }
    api.post('/orders', payload)
      .then((res) => {
        closeCreate()
        setSuccess(`Order ${res.data.order_no} created successfully`)
        setTimeout(() => setSuccess(''), 6000)
        load()
      })
      .catch((err) => setCreateErrors({ api: errText(err) }))
      .finally(() => setSaving(false))
  }

  const submitEdit = () => {
    const errs = {}
    if (!(form.order_no || '').trim()) errs.order_no = 'SO Number is required'
    setCreateErrors(errs)
    if (Object.keys(errs).length > 0) return
    setSaving(true)
    const payload = {
      customer_id: form.customer_id || null,
      customer_name: (form.customer_name || '').trim(),
      customer_contact: (form.customer_contact || '').trim(),
      customer_email: (form.customer_email || '').trim(),
      order_type: form.order_type,
      order_no: (form.order_no || '').trim(),
      customer_po_no: form.customer_po_no || '',
      salesperson_id: form.salesperson_id || null,
      salesperson_name: (form.salesperson_name || '').trim(),
      order_date: form.order_date || new Date().toISOString().slice(0, 10),
      remarks: form.remarks || '',
    }
    api.patch(`/orders/${form.id}`, payload)
      .then((res) => {
        closeEdit()
        setSuccess(`Order ${res.data.order_no} updated successfully`)
        setTimeout(() => setSuccess(''), 6000)
        load()
        if (detail && detail.id === res.data.id) setDetail(res.data)
      })
      .catch((err) => setCreateErrors({ api: errText(err) }))
      .finally(() => setSaving(false))
  }

  const lineRows = []
  items.forEach((o) => {
    (o.lines || []).forEach((ln) => {
      lineRows.push({
        order_id: o.id,
        order_no: o.order_no,
        customer_po_no: o.customer_po_no || ln.customer_po_no || '',
        customer: o.customer,
        customer_contact: o.customer_contact,
        customer_email: o.customer_email,
        order_date: o.order_date,
        order_type: o.order_type,
        status: o.status,
        salesperson: o.salesperson,
        total_value: o.total_value,
        ...ln,
      })
    })
  })

  const orderCols = [
    { key: 'order_no', label: 'SO No', render: (r) => <span className="font-mono text-xs font-medium">{r.order_no}</span> },
    { key: 'customer_po_no', label: 'PO No', render: (r) => <span className="font-mono text-xs">{r.customer_po_no || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || r.product?.item_code || '—'}</span> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.product?.model || r.description || '—'}</span> },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => fmtNum(r.schedule_qty) },
    { key: 'customer', label: 'Customer', render: (r) => <span className="font-medium">{r.customer?.name || '—'}</span> },
    { key: 'ask_till_date', label: 'Ask Till Date', render: (r) => fmtNum(r.ask_till_date) },
    { key: 'dispatched_qty', label: 'Dispatch', render: (r) => fmtNum(r.dispatched_qty) },
    { key: 'completion_pct', label: '% Comp', render: (r) => <span className="font-mono text-xs">{r.completion_pct != null ? `${fmtNum(r.completion_pct * 100)}%` : '—'}</span> },
    { key: 'balance_qty', label: 'Balance Qty', render: (r) => <span className={Number(r.balance_qty || 0) < 0 ? 'text-red-600 font-semibold' : ''}>{fmtNum(r.balance_qty)}</span> },
    { key: 'opening_stock', label: 'Opening Stock', render: (r) => fmtNum(r.opening_stock) },
    { key: 'order_type', label: 'Type', render: (r) => <Badge className={r.order_type === 'OEM' ? 'bg-slate-800 text-white' : 'bg-cyan-100 text-cyan-700'}>{orderTypeLabel(r.order_type)}</Badge> },
    { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center justify-end gap-1">
        <button onClick={() => openDetail(r)} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="View order"><Eye size={15} /></button>
        <button onClick={(e) => { e.stopPropagation(); openEdit(items.find((o) => o.id === r.order_id)) }} className="text-slate-400 hover:text-blue-600 p-1 hover:bg-blue-50 rounded" title="Edit order"><Pencil size={14} /></button>
        <button onClick={(e) => { e.stopPropagation(); removeOrder(r) }} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete order"><Trash2 size={14} /></button>
      </div>
    )},
  ]

  const lineDetailCols = [
    { key: 'product', label: 'Product', render: (r) => <span className="font-medium">{r.product?.model || r.description || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || r.product?.item_code || '—'}</span> },
    { key: 'quantity', label: 'Ordered Qty', render: (r) => fmtNum(r.quantity) },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => fmtNum(r.schedule_qty) },
    { key: 'ask_till_date', label: 'Ask Till Date', render: (r) => fmtNum(r.ask_till_date) },
    { key: 'completion_pct', label: '% Comp', render: (r) => <span className="font-mono text-xs">{r.completion_pct != null ? `${fmtNum(r.completion_pct * 100)}%` : '—'}</span> },
    { key: 'balance_qty', label: 'Balance Qty', render: (r) => Number(r.balance_qty || 0) < 0 ? <span className="text-red-600 font-semibold">{fmtNum(r.balance_qty)}</span> : fmtNum(r.balance_qty) },
    { key: 'opening_stock', label: 'Opening Stock', render: (r) => fmtNum(r.opening_stock) },
    { key: 'dispatched_qty', label: 'Dispatched', render: (r) => r.dispatched_qty > 0 ? fmtNum(r.dispatched_qty) : '—' },
    { key: 'available_stock', label: 'In Stock', render: (r) => <span className={Number(r.available_stock || 0) > 0 ? 'text-green-700' : 'text-slate-400'}>{fmtNum(r.available_stock)}</span> },
    { key: 'shortage_qty', label: 'Shortage', render: (r) => Number(r.shortage_qty || 0) > 0 ? <span className="font-semibold text-red-600">{fmtNum(r.shortage_qty)}</span> : '—' },
    { key: 'rate', label: 'Rate', render: (r) => r.unit_price != null ? fmtNum(r.unit_price) : '—' },
    { key: 'less', label: 'Less', render: (r) => r.less != null ? fmtNum(r.less) : '—' },
    { key: 'amount', label: 'Amount', render: (r) => r.amount != null ? fmtNum(r.amount) : '—' },
    { key: 'readiness', label: 'Fulfilment', render: (r) => <FlowBadge status={r.readiness || r.fulfilment} /> },
    { key: 'source_type', label: 'Source Type', render: (r) => <Badge className="bg-gray-100 text-gray-600">{r.product?.source_type || '—'}</Badge> },
    { key: 'edit', label: '', render: (r) => (
      <button onClick={() => { setEditLine(r); setLineForm({ id: r.id, product_id: r.product?.id || null, description: r.description || '', item_code: r.item_code || r.product?.item_code || '', quantity: r.quantity, schedule_qty: r.schedule_qty ?? '', ask_till_date: r.ask_till_date ?? '', completion_pct: r.completion_pct ?? '', balance_qty: r.balance_qty ?? '', opening_stock: r.opening_stock ?? '', unit_price: r.unit_price, less: r.less ?? '', amount: r.amount, customer_po_no: r.customer_po_no || '' }) }} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit line"><Pencil size={14} /></button>
    )},
  ]

  const distinctOrderIds = new Set(items.map((o) => o.id))
  const visibleOrderCount = distinctOrderIds.size
  const completedCount = items.filter((o) => o.status === 'Completed').length
  const orderTotalValue = items.reduce((s, o) => s + (Number(o.total_value) || 0), 0)

  const renderOrderForm = (isEdit) => (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
      <div className="sm:col-span-2">
        <label className="block text-slate-500 text-xs mb-1">Customer <span className="text-red-500">*</span></label>
        <SearchSelect
          options={customers.map((c) => ({ id: c.id, label: c.name }))}
          value={form.customer_id}
          initialLabel={!form.customer_id ? (form.customer_name || '') : ''}
          placeholder="Type to search or enter a customer name — existing customers match automatically"
          onChange={handleCustomerChange}
        />
        {createErrors.customer_id && <p className="text-xs text-red-600 mt-1">{createErrors.customer_id}</p>}
      </div>
      <div className="sm:col-span-1">
        <label className="block text-slate-500 text-xs mb-1">Customer Contact No.</label>
        <input value={form.customer_contact || ''} onChange={(e) => setForm({ ...form, customer_contact: e.target.value })} placeholder="Phone / mobile" className="input input-contact" />
      </div>
      <div className="sm:col-span-1">
        <label className="block text-slate-500 text-xs mb-1">Customer Email</label>
        <input type="email" value={form.customer_email || ''} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} placeholder="email@example.com" className="input input-email" />
      </div>
      <div>
        <label className="block text-slate-500 text-xs mb-1">Order Type</label>
        <select value={form.order_type || 'OEM'} onChange={(e) => setForm({ ...form, order_type: e.target.value })} className="input">
          {ORDER_TYPE_OPTIONS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
      </div>
      <div>
        <label className="block text-slate-500 text-xs mb-1">Order Date</label>
        <input type="date" value={form.order_date || ''} onChange={(e) => setForm({ ...form, order_date: e.target.value })} className="input" />
      </div>
      <div>
        <label className="block text-slate-500 text-xs mb-1">SO Number <span className="text-red-500">*</span> <span className="text-slate-400 font-normal">(manual)</span></label>
        <input value={form.order_no || ''} onChange={(e) => setForm({ ...form, order_no: e.target.value })} placeholder="Enter the actual Sales Order no." className="input" />
        {createErrors.order_no && <p className="text-xs text-red-600 mt-1">{createErrors.order_no}</p>}
      </div>
      <div>
        <label className="block text-slate-500 text-xs mb-1">Customer PO No <span className="text-slate-400 font-normal">(manual)</span></label>
        <input value={form.customer_po_no || ''} onChange={(e) => setForm({ ...form, customer_po_no: e.target.value })} placeholder="PO / reference no" className="input" />
      </div>
      <div className="sm:col-span-2">
        <label className="block text-slate-500 text-xs mb-1">Salesperson</label>
        <SearchSelect
          options={salespersons.map((s) => ({ id: s.id, label: s.name }))}
          value={form.salesperson_id}
          initialLabel={!form.salesperson_id ? (form.salesperson_name || '') : ''}
          placeholder="Type a salesperson name or select…"
          onChange={(id, manual) => setForm((f) => ({ ...f, salesperson_id: id, salesperson_name: manual }))}
        />
      </div>
      {!isEdit && (
        <div className="sm:col-span-2 mt-2 border-t border-gray-100 pt-3">
          <div className="flex items-center justify-between mb-2">
            <span className="font-medium text-slate-700 text-sm">Order Items</span>
            <button onClick={addLine} className="btn btn-secondary text-xs py-1.5"><Plus size={13} /> Add Item</button>
          </div>

          {(form.lines || []).map((l, i) => {
            return (
              <div key={i} className="relative grid grid-cols-2 sm:grid-cols-12 gap-2 mb-3 p-3 rounded-lg bg-slate-50/70 border border-gray-100">
                <button onClick={() => removeLine(i)} className="absolute top-2 right-2 text-red-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Remove item"><X size={14} /></button>
                <div className="col-span-2 sm:col-span-4">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Product <span className="text-red-500">*</span> <span className="text-slate-400 font-normal">(or type manual)</span></label>
                  <SearchSelect
                    options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''} · ${p.uom || 'Each'}` }))}
                    value={l.product_id}
                    initialLabel={!l.product_id ? (l.description || '') : ''}
                    placeholder="Search product / manual item…"
                    onChange={(id, manual) => handleProductLine(i, id, manual)}
                  />
                  {createErrors[`line_${i}_product`] && <p className="text-xs text-red-600 mt-1">{createErrors[`line_${i}_product`]}</p>}
                </div>
                <div className="col-span-2 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Item Code</label>
                  <input type="text" value={l.item_code || ''} onChange={(e) => updateLine(i, 'item_code', e.target.value)} placeholder="Item code" className="input py-1.5" />
                </div>
                <div className="col-span-2 sm:col-span-5">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Items / Description</label>
                  <input value={l.description || ''} onChange={(e) => updateLine(i, 'description', e.target.value)} placeholder="Description" className="input py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Qty <span className="text-red-500">*</span></label>
                  <input type="number" min="1" step="any" value={l.quantity ?? ''} onChange={(e) => updateLine(i, 'quantity', e.target.value)} className="input input-num py-1.5" />
                  {createErrors[`line_${i}_qty`] && <p className="text-xs text-red-600 mt-1">{createErrors[`line_${i}_qty`]}</p>}
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Schedule</label>
                  <input type="number" step="any" value={l.schedule_qty ?? ''} onChange={(e) => updateLine(i, 'schedule_qty', e.target.value)} placeholder="Schedule qty" className="input input-num py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Ask Till Date</label>
                  <input type="number" step="any" value={l.ask_till_date ?? ''} onChange={(e) => updateLine(i, 'ask_till_date', e.target.value)} placeholder="Ask till date" className="input input-num py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-3">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Opening Stock</label>
                  <input type="number" step="any" value={l.opening_stock ?? ''} onChange={(e) => updateLine(i, 'opening_stock', e.target.value)} placeholder="Opening stock" className="input input-num py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-4">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Rate</label>
                  <input type="number" min="0" step="any" value={l.unit_price ?? ''} onChange={(e) => updateLine(i, 'unit_price', e.target.value)} placeholder="0" className="input input-num py-1.5" />
                </div>
                <div className="col-span-1 sm:col-span-4">
                  <label className="block text-slate-500 text-[0.6875rem] mb-1">Amount</label>
                  <div className="input input-num py-1.5 bg-white text-right font-mono text-slate-800 whitespace-nowrap overflow-hidden text-ellipsis">{fmtNum(lineTotal(l))}</div>
                </div>
              </div>
            )
          })}

          {createErrors.lines && <p className="text-xs text-red-600 mt-1">{createErrors.lines}</p>}

          <div className="flex items-center justify-between border-t border-gray-100 pt-3 mt-1">
            <span className="text-xs text-slate-500">Items: {(form.lines || []).length}</span>
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-600 font-medium">Order Total</span>
              <span className="text-base font-bold text-slate-900 font-mono">{fmtNum(orderTotal)}</span>
            </div>
          </div>
        </div>
      )}
      <div className="sm:col-span-2">
        <label className="block text-slate-500 text-xs mb-1">Notes / Remarks</label>
        <textarea value={form.remarks || ''} onChange={(e) => setForm({ ...form, remarks: e.target.value })} rows={2} className="input" />
      </div>
    </div>
  )

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Orders" subtitle="Manufacture / Trading order management"
        actions={<>
          <button onClick={openImport} className="btn btn-secondary"><Upload size={15} /> Import Orders</button>
          <button onClick={openCreate} className="btn btn-primary"><Plus size={15} /> New Order</button>
        </>} />

      {success && (
        <div className="mb-4 rounded-lg bg-green-50 border border-green-200 text-green-700 text-sm px-4 py-3 flex items-center gap-2">
          <CheckCircle2 size={16} /> {success}
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
        <StatCard label="Visible Orders" value={visibleOrderCount} sub={`${lineRows.length} line rows`} icon={ShoppingBag} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="Completed" value={completedCount} sub="of visible" icon={CheckCircle2} iconClass="bg-green-50 text-green-600" />
        <StatCard label="Total Value" value={fmtNum(orderTotalValue)} sub="visible scope" icon={Clock} iconClass="bg-blue-50 text-blue-600" />
      </div>

      <PageTabs tabs={TABS.map((t) => ({ ...t, count: t.key === 'all' ? total : undefined }))} active={tab} onChange={setTab} />

      {/* Filters */}
      <div className="flex gap-2 mb-4 items-center flex-wrap">
        <input value={searchF} onChange={(e) => setSearchF(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} placeholder="Search SO / PO / customer…" className="input sm:w-64" />
        <select value={statusF} onChange={(e) => setStatusF(e.target.value)} className="input sm:w-auto">
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="confirmed">Confirmed</option>
          <option value="in_production">In Production</option>
          <option value="ready">Ready</option>
          <option value="dispatched">Dispatched</option>
          <option value="completed">Completed</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select value={customerF} onChange={(e) => setCustomerF(e.target.value)} className="input sm:w-auto">
          <option value="">All customers</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button onClick={load} className="btn btn-secondary"><Download size={14} /> Search</button>
      </div>

      <Card>
        {loading ? <Loading /> : lineRows.length === 0 ? <Empty text="No orders found" /> : <Table columns={orderCols} data={lineRows} keyField="id" onRowClick={openCustomerDetail} stickyColumns={['order_no']} />}
      </Card>

      {/* Order detail modal */}
      <Modal open={!!detailLoading || !!detail} title={detail ? `${detail.order_no} — ${orderTypeLabel(detail.order_type)}` : 'Loading…'} onClose={() => { setDetail(null); setDetailLoading(false); setOrderDispatches([]) }} xwide
        footer={<>
          <button onClick={() => { setDetail(null); setDetailLoading(false); setOrderDispatches([]) }} className="btn btn-secondary">Close</button>
          <button onClick={() => shareOrder(detail)} className="btn btn-secondary"><Share2 size={14} /> Share</button>
          <button onClick={() => downloadPDF(detail)} className="btn btn-secondary"><FileText size={14} /> PDF</button>
          <button onClick={() => openEmail(detail, 'confirmation')} className="btn btn-secondary"><Mail size={14} /> Confirmation Email</button>
          <button onClick={() => openEdit(detail)} className="btn btn-primary"><Pencil size={14} /> Edit Order</button>
          <button onClick={() => removeOrder(detail)} className="btn btn-danger">Delete Order</button>
        </>}>
        {detailLoading ? <Loading /> : detail && (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4 text-sm">
              <div><span className="text-slate-500">Customer:</span> <span className="font-medium">{detail.customer?.name || '—'}</span></div>
              <div><span className="text-slate-500">Contact:</span> <span className="font-medium">{detail.customer_contact || detail.customer?.phone || '—'}</span></div>
              <div><span className="text-slate-500">Email:</span> <span className="font-medium">{detail.customer_email || detail.customer?.email || '—'}</span></div>
              <div><span className="text-slate-500">Status:</span> <StatusBadge status={detail.status} /></div>
              <div><span className="text-slate-500">Stock:</span> {detail.ready
                ? <FlowBadge status="READY_FOR_DISPATCH" />
                : <FlowBadge status={detail.stock_status || 'MANUAL_DECISION_REQUIRED'} />}</div>
              <div><span className="text-slate-500">Order Date:</span> <span className="font-medium">{detail.order_date}</span></div>
              <div><span className="text-slate-500">SO No:</span> <span className="font-mono text-xs">{detail.order_no || '—'}</span></div>
              <div><span className="text-slate-500">PO No:</span> <span className="font-mono text-xs">{detail.customer_po_no || '—'}</span></div>
              <div><span className="text-slate-500">Salesperson:</span> {detail.salesperson?.name || '—'}</div>
              <div><span className="text-slate-500">Order Type:</span> <Badge className="bg-slate-100 text-slate-600">{orderTypeLabel(detail.order_type)}</Badge></div>
              <div><span className="text-slate-500">Dispatched (order-level):</span> <span className="font-semibold">{fmtNum(detail.dispatch_qty)}</span></div>
              <div><span className="text-slate-500">Value:</span> <span className="font-medium">{fmtNum(detail.total_value)}</span></div>
            </div>
            {detail.lines?.length > 1 && (
              <div className="mb-3 text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2">
                Dispatched qty shown at order level (not per-line) — dispatches in source data are tied to orders, not individual lines.
              </div>
            )}
            <Table columns={lineDetailCols} data={detail.lines || []} keyField="id" stickyColumns={['product']} dense />

            {orderDispatches.length > 0 && (
              <div className="mt-5">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Dispatches</div>
                <div className="space-y-2">
                  {orderDispatches.map((d) => (
                    <div key={d.id} className="flex items-center justify-between bg-slate-50 border border-gray-100 rounded-lg px-3 py-2 text-sm">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs">{d.dispatch_no}</span>
                        <span className="text-slate-500">{d.dispatch_date || d.report_date || '—'}</span>
                        <span className="font-medium">{fmtNum(d.dispatched_qty)} dispatched</span>
                      </div>
                      <button onClick={() => openEmail(detail, 'dispatch', d.id)} className="btn btn-secondary btn-sm"><Mail size={13} /> Dispatch Email</button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {emailHistory.length > 0 && (
              <div className="mt-5">
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Email History</div>
                <div className="space-y-2">
                  {emailHistory.map((h) => (
                    <div key={h.id} className="flex items-center justify-between bg-white border border-gray-100 rounded-lg px-3 py-2 text-sm">
                      <div className="flex items-center gap-3">
                        <Badge className={h.status === 'sent' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}>{h.status}</Badge>
                        <span className="font-medium">{h.email_type}</span>
                        <span className="text-slate-500">{h.recipient}</span>
                        <span className="text-slate-400 text-xs">{h.sent_at?.replace('T', ' ').slice(0, 19)}</span>
                      </div>
                      <span className="text-xs text-slate-500 truncate max-w-xs" title={h.subject}>{h.subject}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </Modal>

      {/* Customer-wise detail modal */}
      <Modal open={!!customerDetailLoading || !!customerDetail} title={customerDetail ? `${customerDetail.customer?.name || 'Customer'} — Orders` : 'Loading…'} onClose={closeCustomerDetail} xwide
        footer={<>
          <button onClick={closeCustomerDetail} className="btn btn-secondary">Close</button>
        </>}>
        {customerDetailLoading ? <Loading /> : customerDetail && (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-5 text-sm bg-slate-50 rounded-lg p-4 border border-gray-100">
              <div><span className="text-slate-500">Customer:</span> <span className="font-semibold text-slate-800">{customerDetail.customer?.name || '—'}</span></div>
              <div><span className="text-slate-500">Contact:</span> <span className="font-medium">{customerDetail.customer?.contact || '—'}</span></div>
              <div><span className="text-slate-500">Email:</span> <span className="font-medium">{customerDetail.customer?.email || '—'}</span></div>
            </div>
            {(() => {
              const cRows = []
              customerDetail.orders.forEach((o) => {
                (o.lines || []).forEach((ln) => {
                  cRows.push({ order_id: o.id, ...o, ...ln, customer_po_no: o.customer_po_no || ln.customer_po_no || '' })
                })
              })
              const customerOrderCols = [
                { key: 'order_no', label: 'SO No', render: (r) => <span className="font-mono text-xs font-medium">{r.order_no}</span> },
                { key: 'customer_po_no', label: 'PO No', render: (r) => <span className="font-mono text-xs">{r.customer_po_no || '—'}</span> },
                { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || r.product?.item_code || '—'}</span> },
                { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.product?.model || r.description || '—'}</span> },
                { key: 'schedule_qty', label: 'Schedule', render: (r) => fmtNum(r.schedule_qty) },
                { key: 'ask_till_date', label: 'Ask Till Date', render: (r) => fmtNum(r.ask_till_date) },
                { key: 'dispatched_qty', label: 'Dispatch', render: (r) => fmtNum(r.dispatched_qty) },
                { key: 'completion_pct', label: '% Comp', render: (r) => <span className="font-mono text-xs">{r.completion_pct != null ? `${fmtNum(r.completion_pct * 100)}%` : '—'}</span> },
                { key: 'balance_qty', label: 'Balance Qty', render: (r) => <span className={Number(r.balance_qty || 0) < 0 ? 'text-red-600 font-semibold' : ''}>{fmtNum(r.balance_qty)}</span> },
                { key: 'opening_stock', label: 'Opening Stock', render: (r) => fmtNum(r.opening_stock) },
                { key: 'order_date', label: 'Order Date' },
                { key: 'status', label: 'Status', render: (r) => <StatusBadge status={r.status} /> },
                { key: 'actions', label: '', render: (r) => (
                  <div className="flex items-center justify-end gap-1">
                    <button onClick={(e) => { e.stopPropagation(); closeCustomerDetail(); openDetail(r) }} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="View order"><Eye size={15} /></button>
                    <button onClick={(e) => { e.stopPropagation(); closeCustomerDetail(); openEdit(customerDetail.orders.find((o) => o.id === r.order_id)) }} className="text-slate-400 hover:text-blue-600 p-1 hover:bg-blue-50 rounded" title="Edit order"><Pencil size={14} /></button>
                    <button onClick={(e) => { e.stopPropagation(); shareOrder(r) }} className="text-slate-400 hover:text-green-600 p-1 hover:bg-green-50 rounded" title="Share order"><Share2 size={14} /></button>
                    <button onClick={(e) => { e.stopPropagation(); downloadPDF(r) }} className="text-slate-400 hover:text-purple-600 p-1 hover:bg-purple-50 rounded" title="Download PDF"><FileText size={14} /></button>
                    <button onClick={(e) => { e.stopPropagation(); removeOrder(r) }} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete order"><Trash2 size={14} /></button>
                  </div>
                )},
              ]
              return cRows.length === 0 ? <Empty text="No orders for this customer" /> : <Table columns={customerOrderCols} data={cRows} keyField="id" stickyColumns={['order_no']} />
            })()}
          </>
        )}
      </Modal>

      {/* Edit line modal */}
      <Modal open={!!editLine} title="Edit Order Line" onClose={() => { setEditLine(null); setLineForm({}) }} wide
        footer={<>
          <button onClick={() => { setEditLine(null); setLineForm({}) }} className="btn btn-secondary">Cancel</button>
          <button onClick={saveLine} className="btn btn-primary">Save</button>
        </>}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Item</label>
            <SearchSelect
              options={products.map((p) => ({ id: p.id, label: `${p.model}${p.item_code ? ` (${p.item_code})` : ''} · ${p.uom || 'Each'}` }))}
              value={lineForm.product_id ?? null}
              initialLabel={!lineForm.product_id ? (lineForm.description || '') : ''}
              placeholder="Type to search products or keep the manual description"
              onChange={(id, manual) => setLineForm((lf) => {
                const p = products.find((x) => String(x.id) === String(id))
                return {
                  ...lf,
                  product_id: id,
                  description: manual || lf.description,
                  item_code: id ? (p?.item_code || lf.item_code || '') : lf.item_code,
                }
              })}
            />
          </div>
          <div><label className="block text-slate-500 text-xs mb-1">Description</label>
            <input value={lineForm.description || ''} onChange={(e) => setLineForm({ ...lineForm, description: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Item Code</label>
            <input value={lineForm.item_code || ''} onChange={(e) => setLineForm({ ...lineForm, item_code: e.target.value })} placeholder="Item code" className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Customer PO No</label>
            <input value={lineForm.customer_po_no || ''} onChange={(e) => setLineForm({ ...lineForm, customer_po_no: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Quantity</label>
            <input type="number" value={lineForm.quantity ?? ''} onChange={(e) => setLineForm({ ...lineForm, quantity: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Schedule</label>
            <input type="number" step="any" value={lineForm.schedule_qty ?? ''} onChange={(e) => setLineForm({ ...lineForm, schedule_qty: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Ask Till Date</label>
            <input type="number" step="any" value={lineForm.ask_till_date ?? ''} onChange={(e) => setLineForm({ ...lineForm, ask_till_date: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">% Completion</label>
            <input type="number" step="any" value={lineForm.completion_pct ?? ''} onChange={(e) => setLineForm({ ...lineForm, completion_pct: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Balance Qty</label>
            <input type="number" step="any" value={lineForm.balance_qty ?? ''} onChange={(e) => setLineForm({ ...lineForm, balance_qty: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Opening Stock</label>
            <input type="number" step="any" value={lineForm.opening_stock ?? ''} onChange={(e) => setLineForm({ ...lineForm, opening_stock: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Unit Price</label>
            <input type="number" value={lineForm.unit_price ?? ''} onChange={(e) => setLineForm({ ...lineForm, unit_price: e.target.value })} className="input input-num" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Less</label>
            <input type="number" value={lineForm.less ?? ''} onChange={(e) => setLineForm({ ...lineForm, less: e.target.value })} className="input input-num" /></div>
        </div>
      </Modal>

      {/* Create order modal */}
      <Modal open={showCreate} title="Create New Order" onClose={closeCreate} xwide
        footer={<>
          <button onClick={closeCreate} className="btn btn-secondary" disabled={saving}>Cancel</button>
          <button onClick={submitCreate} disabled={saving} className="btn btn-primary">{saving ? 'Creating…' : 'Create Order'}</button>
        </>}>
        {createErrors.api && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{createErrors.api}</div>
        )}
        {renderOrderForm(false)}
      </Modal>

      {/* Edit order modal */}
      <Modal open={showEdit} title="Edit Order" onClose={closeEdit} wide
        footer={<>
          <button onClick={closeEdit} className="btn btn-secondary" disabled={saving}>Cancel</button>
          <button onClick={submitEdit} disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : 'Save Order'}</button>
        </>}>
        {createErrors.api && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{createErrors.api}</div>
        )}
        {renderOrderForm(true)}
      </Modal>

      {/* Import orders modal */}
      <input type="file" ref={fileInputRef} onChange={handleFileSelect} accept=".csv,.xlsx,.xls" className="hidden" />
      <Modal open={importOpen} title="Import Orders" onClose={closeImport} xwide
        footer={<>
          <button onClick={closeImport} className="btn btn-secondary" disabled={importLoading}>Cancel</button>
          <button onClick={() => runImport(importConfirm)} disabled={importLoading || !importPreview?.can_import} className="btn btn-primary">
            {importLoading ? 'Importing…' : 'Import Orders'}
          </button>
        </>}>
        <div className="space-y-4 text-sm">
          <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-lg border border-gray-100">
            <button onClick={() => fileInputRef.current?.click()} className="btn btn-secondary" disabled={importLoading}><Upload size={14} /> Choose CSV / Excel</button>
            <div className="text-sm">
              {(() => {
                const f = fileInputRef.current?.files?.[0]
                if (!f) return <span className="text-slate-500">No file selected (.csv, .xlsx, .xls)</span>
                const ext = f.name.split('.').pop().toUpperCase()
                return (
                  <div>
                    <div className="font-medium text-slate-700">{f.name}</div>
                    <div className="text-xs text-slate-500">Type: {f.type || ext}</div>
                  </div>
                )
              })()}
            </div>
          </div>

          {importLoading && <Loading text="Analysing file…" />}

          {importError && (
            <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{importError}</div>
          )}

          {importPreview && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-white border border-gray-100 rounded-lg p-3"><div className="text-xs text-slate-500">Total Rows</div><div className="text-lg font-semibold">{importPreview.total_rows}</div></div>
                <div className="bg-white border border-gray-100 rounded-lg p-3"><div className="text-xs text-slate-500">Valid Rows</div><div className="text-lg font-semibold text-green-700">{importPreview.valid_rows}</div></div>
                <div className="bg-white border border-gray-100 rounded-lg p-3"><div className="text-xs text-slate-500">Errors</div><div className="text-lg font-semibold text-red-600">{importPreview.error_rows}</div></div>
                <div className="bg-white border border-gray-100 rounded-lg p-3"><div className="text-xs text-slate-500">Warnings</div><div className="text-lg font-semibold text-amber-600">{importPreview.warning_rows + (importPreview.duplicate_rows || 0)}</div></div>
              </div>

              {importPreview.duplicate_rows > 0 && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm px-3 py-2">
                  {importPreview.duplicate_rows} row(s) match existing orders. Click <b>Import Orders</b> to create them regardless, or cancel and review the source file.
                </div>
              )}

              {Object.keys(importPreview.mapped_columns || {}).length === 0 && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm px-3 py-2">
                  <p className="font-medium mb-1">No recognized order columns found.</p>
                  <p className="text-xs mb-1">Raw headers detected: <span className="font-mono">{(importPreview.headers || []).join(', ') || '—'}</span></p>
                  <p className="text-xs">Please use the template or check that headers match PO NO, SO No, ITEM CODE, MODEL, SCHEDULE, Customer, ASK TILL DATE, DISPATCH, % COMP, BALANCE QTY, OPNING STOCK.</p>
                </div>
              )}

              <div>
                <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Mapped Columns</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(importPreview.mapped_columns || {}).map(([k, v]) => (
                    <Badge key={k} className="bg-slate-100 text-slate-700">{k} <span className="text-slate-400">→ {v}</span></Badge>
                  ))}
                </div>
              </div>

              {importPreview.sample_rows?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Sample Rows</div>
                  <div className="table-wrap max-h-72">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th className="text-left">Row</th>
                          <th className="text-left">Customer</th>
                          <th className="text-left">SO No</th>
                          <th className="text-left">PO No</th>
                          <th className="text-left">Item</th>
                          <th className="text-left">Model</th>
                          <th className="text-right">Schedule</th>
                          <th className="text-left">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {importPreview.sample_rows.map((r, i) => (
                          <tr key={i} className={r.errors?.length ? 'bg-red-50' : r.warnings?.length || r.duplicate_of ? 'bg-amber-50' : ''}>
                            <td>{r.row}</td>
                            <td>{r.customer_name || '—'}</td>
                            <td className="font-mono text-xs">{r.so_no || '—'}</td>
                            <td className="font-mono text-xs">{r.po_no || '—'}</td>
                            <td className="font-mono text-xs">{r.item_code || '—'}</td>
                            <td>{r.model || '—'}</td>
                            <td className="text-right">{fmtNum(r.schedule_qty)}</td>
                            <td>
                              {r.errors?.length ? <Badge className="bg-red-100 text-red-700">{r.errors.length} error(s)</Badge> :
                                r.warnings?.length || r.duplicate_of ? <Badge className="bg-amber-100 text-amber-700">{r.warnings?.length ? `${r.warnings.length} warn` : ''} {r.duplicate_of ? 'dup' : ''}</Badge> :
                                  <Badge className="bg-green-100 text-green-700">OK</Badge>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {importPreview.errors?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Errors</div>
                  <div className="space-y-1 max-h-40 overflow-y-auto">
                    {importPreview.errors.slice(0, 20).map((e, i) => (
                      <div key={i} className="text-xs bg-red-50 border border-red-100 rounded px-2 py-1.5 text-red-700">
                        Row {e.row}: {e.errors?.join('; ')}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </Modal>

      {/* Email preview/send modal */}
      <Modal open={emailOpen} title={emailType === 'dispatch' ? 'Send Dispatch Email' : 'Send Order Confirmation'} onClose={closeEmail} wide
        footer={<>
          <button onClick={closeEmail} className="btn btn-secondary" disabled={emailLoading}>Cancel</button>
          <button onClick={() => sendEmail(detail)} disabled={emailLoading || !detail} className="btn btn-primary"><Send size={14} /> {emailLoading ? 'Sending…' : 'Send Email'}</button>
        </>}>
        <div className="space-y-3 text-sm">
          {emailLoading && !emailForm.subject && <Loading text="Loading preview…" />}
          {emailError && (
            <div className="rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm px-3 py-2">{emailError}</div>
          )}
          {!emailForm.to && (
            <div className="rounded-lg bg-amber-50 border border-amber-200 text-amber-800 text-sm px-3 py-2">
              Customer has no email on record. Please type the recipient email below.
            </div>
          )}
          <div>
            <label className="block text-slate-500 text-xs mb-1">To <span className="text-red-500">*</span></label>
            <input type="email" value={emailForm.to} onChange={(e) => setEmailForm({ ...emailForm, to: e.target.value })} className="input" placeholder="customer@example.com" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">Subject</label>
            <input value={emailForm.subject} onChange={(e) => setEmailForm({ ...emailForm, subject: e.target.value })} className="input" />
          </div>
          <div>
            <label className="block text-slate-500 text-xs mb-1">Message</label>
            <textarea value={emailForm.message} onChange={(e) => setEmailForm({ ...emailForm, message: e.target.value })} rows={10} className="input" />
          </div>
        </div>
      </Modal>
    </div>
  )
}
