import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Copy, Download, Edit3, Eye, FileText, Filter, History, Mail, Plus,
  Printer, RefreshCw, Search, Send, Share2, Trash2, X,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { Badge, Card, Empty, ErrorState, Loading, Modal, PageHeader, SearchSelect, SectionHeader, StatCard } from '../components/ui'
import Table from '../components/Table'

const MANUFACTURING_PRODUCTS = [
  'Stretch Film',
  'Poly Bag',
  'Poly Box',
  'VCI Poly Bag',
  'VCI Poly Box',
  'Shrink Film',
  'HDPE Bag',
  'HDPE Cover',
  'Tarpaulin',
  'BOPP Tape',
  'Masking Tape',
  'PVC Floor Marking Tape',
  'Bubble Wrap',
  'Cross Lamination / Cross-Laminated Timber',
]

const STATUS_OPTIONS = [
  { value: 'Draft', label: 'Draft', className: 'bg-slate-100 text-slate-600' },
  { value: 'Sent', label: 'Sent', className: 'bg-blue-100 text-blue-700' },
  { value: 'Accepted', label: 'Accepted', className: 'bg-green-100 text-green-700' },
  { value: 'Rejected', label: 'Rejected', className: 'bg-red-100 text-red-700' },
  { value: 'Expired', label: 'Expired', className: 'bg-amber-100 text-amber-700' },
]

// Company identities a quotation can be issued under. Mirrors the backend
// allow-list (QUOTATION_COMPANY_NAMES) so the dropdown cannot drift from it.
const COMPANY_OPTIONS = ['KALIKA ENTERPRISES', 'KALIKA INFOTECH']

function normalizeCompanyName(value) {
  const v = String(value || '').trim().toUpperCase()
  return v.includes('INFOTECH') ? 'KALIKA INFOTECH' : 'KALIKA ENTERPRISES'
}

const EMPTY_LINE = {
  product_id: null,
  item_code: '',
  description: '',
  hsn_code: '',
  quantity: '',
  uom: '',
  price: '',
  lead_time: '',
  tax_percent: '',
  amount: 0,
}

const DEFAULT_PAYMENT_DAYS = 30

const defaultTerms = (days = DEFAULT_PAYMENT_DAYS) => `1. Customer will be billed after Confirm PO only
2. Payment will be ${days} days to delivery of service and goods
3. Gst tax will be Extra
4. Delivery will be free of cost`

const PAYMENT_LINE_RE = /^.*Payment will be.*$/im

// Number inputs change their value on mouse-wheel (Chrome/Firefox). Blur the
// field on wheel so scrolling only scrolls the form. Keyboard editing is unaffected.
const blurNumberOnWheel = (e) => {
  if (e.target.type === 'number') e.target.blur()
}

function parsePaymentDays(terms) {
  const m = String(terms || '').match(/Payment will be\s+(\d+)\s+days/i)
  return m ? Number(m[1]) : null
}

function applyPaymentDays(terms, days) {
  const line = `2. Payment will be ${days} days to delivery of service and goods`
  const text = String(terms || '')
  return PAYMENT_LINE_RE.test(text) ? text.replace(PAYMENT_LINE_RE, line) : `${text}\n${line}`
}

const EMPTY_FORM = {
  id: null,
  quotation_no: '',
  quotation_type: 'Manufacturing',
  status: 'Draft',
  customer_id: null,
  customer_name: '',
  customer_contact: '',
  customer_email: '',
  customer_address: '',
  customer_gstin: '',
  company_name: 'KALIKA ENTERPRISES',
  company_address: 'Plot No. M-59, MIDC, AHMEDNAGAR',
  company_website: 'www.kalikaindia.com',
  company_phone: '+91 9405536016',
  contact_email: 'info@kalikaindia.com',
  quote_date: new Date().toISOString().split('T')[0],
  valid_until: '',
  approved_by: '',
  terms: defaultTerms(DEFAULT_PAYMENT_DAYS),
  payment_days: DEFAULT_PAYMENT_DAYS,
  lines: [{ ...EMPTY_LINE }],
}

function fmtNum(v) {
  if (v === null || v === undefined || v === '') return '0.00'
  const n = Number(v)
  if (Number.isNaN(n)) return '0.00'
  return n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function statusBadge(status) {
  const s = STATUS_OPTIONS.find((o) => o.value === status)
  return <Badge className={s ? s.className : 'bg-slate-100 text-slate-600'}>{status || '—'}</Badge>
}

function calcLine(line) {
  const qty = Number(line.quantity) || 0
  const price = Number(line.price) || 0
  const amount = Math.round(qty * price * 100) / 100
  return { amount }
}

function computeTotals(lines) {
  return lines.reduce((acc, ln) => {
    acc.subtotal += calcLine(ln).amount
    return acc
  }, { subtotal: 0 }).subtotal
}

function buildQuotationHtml(q) {
  const total = computeTotals(q.lines || [])
  const companyName = normalizeCompanyName(q.company_name)
  const companyAddress = q.company_address || 'Plot No. M-59, MIDC, AHMEDNAGAR'
  const companyPhone = q.company_phone || '+91 9405536016'
  const companyWebsite = q.company_website || 'www.kalikaindia.com'
  const contactEmail = q.contact_email || 'info@kalikaindia.com'

  const fmtTax = (v) => {
    if (v === '' || v == null) return ''
    const n = Number(v)
    return Number.isNaN(n) ? '' : `${n.toFixed(2)}%`
  }

  const lineRows = (q.lines || []).map((ln, i) => {
    return `<tr>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:center">${i + 1}</td>
      <td style="padding:8px;border:1px solid #e2e8f0">${ln.description || '—'}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:center">${ln.hsn_code || '—'}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:right">${fmtNum(ln.quantity)}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:center">${ln.uom || '—'}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:right">${fmtNum(ln.price)}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:center">${ln.lead_time || '—'}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:right">${fmtNum(ln.amount)}</td>
      <td style="padding:8px;border:1px solid #e2e8f0;text-align:center">${fmtTax(ln.tax_percent)}</td>
    </tr>`
  }).join('')

  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Quotation ${q.quotation_no}</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    body { font-family: 'Inter', sans-serif; color: #334155; margin: 0; padding: 32px 40px; background: #fff; }
    .header { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #f59e0b; padding-bottom: 14px; margin-bottom: 22px; }
    .logo { max-height: 64px; }
    .company { text-align: right; }
    .company h1 { margin: 0; color: #1e3a8a; font-size: 20px; font-weight: 700; letter-spacing: 0.5px; }
    .company p { margin: 4px 0 0; font-size: 12px; color: #475569; line-height: 1.5; }
    .title { text-align: center; color: #1e3a8a; font-size: 26px; font-weight: 700; margin: 18px 0 16px; letter-spacing: 1px; }
    .meta-table { width: 100%; border-collapse: collapse; margin-bottom: 18px; }
    .meta-table td { padding: 7px 12px; border: 1px solid #e2e8f0; font-size: 12px; }
    .meta-table td:first-child { background: #f8fafc; font-weight: 600; width: 22%; }
    .customer-box { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 14px; margin-bottom: 18px; }
    .customer-box h3 { margin: 0 0 8px; font-size: 11px; color: #1e3a8a; text-transform: uppercase; letter-spacing: 0.6px; }
    .customer-box p { margin: 3px 0; font-size: 12px; }
    .lines { width: 100%; border-collapse: collapse; margin-bottom: 18px; }
    .lines th { background: #1e3a8a; color: #fff; padding: 9px 6px; font-size: 11px; font-weight: 600; text-align: left; }
    .lines td { padding: 7px 6px; border: 1px solid #e2e8f0; font-size: 12px; }
    .lines tr:nth-child(even) { background: #f8fafc; }
    .totals { width: 280px; margin-left: auto; border-collapse: collapse; }
    .totals td { padding: 7px 12px; border: 1px solid #e2e8f0; font-size: 12px; }
    .totals td:first-child { background: #f8fafc; font-weight: 600; }
    .totals .grand { background: #1e3a8a; color: #fff; font-weight: 700; }
    .terms { margin-top: 20px; padding: 12px 14px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; }
    .terms h3 { margin: 0 0 6px; color: #1e3a8a; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .terms pre { margin: 0; font-family: inherit; font-size: 11px; line-height: 1.6; white-space: pre-wrap; color: #475569; }
    .signatory-block { margin-top: 28px; display: flex; justify-content: flex-end; }
    .signatory-inner { text-align: center; width: 140px; }
    .signatory-inner .stamp { max-height: 100px; display: block; margin: 0 auto 4px; }
    .signatory-text { font-size: 12px; color: #334155; font-weight: 600; }
    .signatory-sub { font-size: 11px; color: #475569; margin-top: 2px; }
    .contact { margin-top: 12px; font-size: 11px; color: #475569; }
    .footer { margin-top: 24px; text-align: center; font-size: 10px; color: #64748b; border-top: 1px solid #e2e8f0; padding-top: 10px; }
    @media print { body { padding: 0; } }
  </style>
</head>
<body>
  <div class="header">
    <img src="/Kalika_logo.png" class="logo" alt="Kalika Enterprises">
    <div class="company">
      <h1>${companyName}</h1>
      <p>${companyAddress}</p>
      <p>Phone: ${companyPhone} | Email: ${contactEmail} | Web: ${companyWebsite}</p>
    </div>
  </div>

  <div class="title">QUOTATION</div>

  <table class="meta-table">
    <tr><td>Quote Number</td><td>${q.quotation_no} Rev. ${q.revision}</td><td>Quote Date</td><td>${q.quote_date}</td></tr>
    <tr><td>Valid Until</td><td>${q.valid_until || '—'}</td><td>Customer ID</td><td>167428</td></tr>
    <tr><td>Approved By</td><td>${q.approved_by || '—'}</td><td>Contact Email</td><td>${contactEmail}</td></tr>
  </table>

  <div class="customer-box">
    <h3>Billed To</h3>
    <p><strong>${q.customer_name || '—'}</strong></p>
    <p>${q.customer_address || ''}</p>
    <p>Contact: ${q.customer_contact || '—'}</p>
    <p>Email: ${q.customer_email || '—'}</p>
    ${q.customer_gstin ? `<p>GSTIN: ${q.customer_gstin}</p>` : ''}
  </div>

  <table class="lines">
    <thead>
      <tr>
        <th>#</th><th>Description</th><th>HSN</th><th>Qty</th><th>UOM</th><th>Price (INR)</th><th>Lead Time</th><th>Amount</th><th>Tax</th>
      </tr>
    </thead>
    <tbody>${lineRows || '<tr><td colspan="9" style="text-align:center">No line items</td></tr>'}</tbody>
  </table>

  <table class="totals">
    <tr><td>Subtotal</td><td style="text-align:right">${fmtNum(total)}</td></tr>
    <tr class="grand"><td>Total Amount (INR)</td><td style="text-align:right">${fmtNum(total)}</td></tr>
  </table>

  ${q.terms ? `<div class="terms"><h3>Terms & Conditions</h3><pre>${q.terms}</pre></div>` : ''}

  <div class="signatory-block">
    <div class="signatory-inner">
      <img src="/assets/stamp.png" class="stamp" alt="Approved Stamp">
      <div class="signatory-text">Authorized Signatory</div>
      <div class="signatory-sub">For ${companyName}</div>
    </div>
  </div>

  <div class="contact">If you have any questions about this price quote, please contact ${contactEmail}</div>
  <div class="footer">Quotation ${q.quotation_no} Rev. ${q.revision} | ${companyName}</div>
</body>
</html>`
}

export default function Quotations() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [customers, setCustomers] = useState([])
  const [products, setProducts] = useState([])
  const [templates, setTemplates] = useState([])

  const [search, setSearch] = useState('')
  const [filterStatus, setFilterStatus] = useState('')
  const [filterCustomer, setFilterCustomer] = useState('')
  const [filterQuoteNo, setFilterQuoteNo] = useState('')
  const [filterDateFrom, setFilterDateFrom] = useState('')
  const [filterDateTo, setFilterDateTo] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [formBusy, setFormBusy] = useState(false)
  const [formError, setFormError] = useState(null)

  const [emailOpen, setEmailOpen] = useState(false)
  const [emailForm, setEmailForm] = useState({ to: '', cc: '', subject: '', message: '', attach_pdf: true })
  const [emailBusy, setEmailBusy] = useState(false)

  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyData, setHistoryData] = useState({ revisions: [], audit: [] })

  const customerMap = useMemo(() => {
    const m = {}
    customers.forEach((c) => { m[c.id] = c })
    return m
  }, [customers])

  const productMap = useMemo(() => {
    const m = {}
    products.forEach((p) => { m[p.model?.toLowerCase()] = p })
    return m
  }, [products])

  const manufacturingOptions = useMemo(() => MANUFACTURING_PRODUCTS.map((p) => ({ id: p, label: p })), [])

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {}
      if (search.trim()) params.search = search.trim()
      if (filterCustomer) params.customer = filterCustomer
      if (filterQuoteNo) params.quote_no = filterQuoteNo
      if (filterStatus) params.status = filterStatus
      if (filterDateFrom) params.date_from = filterDateFrom
      if (filterDateTo) params.date_to = filterDateTo
      const { data } = await api.get('/quotations', { params })
      setItems(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load quotations')
    } finally {
      setLoading(false)
    }
  }

  const loadCustomers = async () => {
    try {
      const { data } = await api.get('/customers')
      setCustomers(data.items || [])
    } catch {}
  }

  const loadProducts = async () => {
    try {
      const { data } = await api.get('/products')
      setProducts(data.items || [])
    } catch {}
  }

  const loadTemplates = async () => {
    try {
      const { data } = await api.get('/quotations/terms-templates')
      setTemplates(data || [])
    } catch {}
  }

  useEffect(() => { loadCustomers(); loadProducts(); loadTemplates(); load() }, [])

  // Debounced backend search when the global search term changes.
  useEffect(() => {
    const t = setTimeout(() => { load() }, 400)
    return () => clearTimeout(t)
  }, [search])

  const filteredItems = items

  const stats = useMemo(() => {
    return {
      total: items.length,
      draft: items.filter((i) => i.status === 'Draft').length,
      sent: items.filter((i) => i.status === 'Sent').length,
      accepted: items.filter((i) => i.status === 'Accepted').length,
    }
  }, [items])

  const openDetail = async (row) => {
    setDetailLoading(true)
    setDetail(null)
    try {
      const { data } = await api.get(`/quotations/${row.id}`)
      setDetail(data)
    } catch (e) {
      alert(e.response?.data?.detail || 'Failed to load quotation')
    } finally {
      setDetailLoading(false)
    }
  }

  const openNew = () => {
    setForm({ ...EMPTY_FORM })
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (q) => {
    setForm({
      ...EMPTY_FORM,
      ...q,
      company_name: normalizeCompanyName(q.company_name),
      quote_date: q.quote_date || EMPTY_FORM.quote_date,
      valid_until: q.valid_until || '',
      payment_days: q.payment_days ?? parsePaymentDays(q.terms) ?? DEFAULT_PAYMENT_DAYS,
      lines: (q.lines || []).map((l) => ({
        ...EMPTY_LINE,
        ...l,
        quantity: l.quantity || '',
        price: l.price || '',
        tax_percent: l.tax_percent || '',
      })),
    })
    setFormError(null)
    setFormOpen(true)
    setDetail(null)
  }

  const setCustomer = (id, manual) => {
    setForm((f) => {
      const c = id ? customerMap[id] : null
      // When an existing customer is deselected, clear the derived contact
      // fields so stale data from the previous selection is not kept.
      const clearDerived = f.customer_id && !id ? {
        customer_contact: '',
        customer_email: '',
        customer_address: '',
        customer_gstin: '',
      } : {}
      return {
        ...f,
        customer_id: id || null,
        customer_name: c?.name || manual || '',
        ...(c ? {
          customer_contact: c.phone || '',
          customer_email: c.email || '',
          customer_address: c.address || '',
          customer_gstin: c.gstin || '',
        } : clearDerived),
      }
    })
  }

  const setLine = (idx, field, value) => {
    setForm((f) => {
      const lines = f.lines.map((ln, i) => (i === idx ? { ...ln, [field]: value } : ln))
      return { ...f, lines }
    })
  }

  const setLineProduct = (idx, id, manual) => {
    setForm((f) => {
      const lines = f.lines.map((ln, i) => {
        if (i !== idx) return ln
        if (id) {
          const p = productMap[id.toLowerCase()]
          return {
            ...ln,
            description: id,
            product_id: p?.id || null,
            item_code: p?.item_code || '',
            uom: p?.uom || ln.uom || '',
          }
        }
        return { ...ln, description: manual || '', product_id: null }
      })
      return { ...f, lines }
    })
  }

  const addLine = () => setForm((f) => ({ ...f, lines: [...f.lines, { ...EMPTY_LINE }] }))
  const removeLine = (idx) => setForm((f) => ({ ...f, lines: f.lines.length > 1 ? f.lines.filter((_, i) => i !== idx) : f.lines }))

  const loadDefaultTerms = () => {
    const defT = templates.find((t) => t.is_default)
    if (defT) setForm((f) => ({ ...f, terms: defT.content }))
  }

  const validateForm = () => {
    if (!COMPANY_OPTIONS.includes(form.company_name)) return 'Company name is required.'
    if (!form.customer_name.trim()) return 'Customer name is required.'
    if (!form.lines.length) return 'At least one line item is required.'
    for (const ln of form.lines) {
      if (!ln.description.trim()) return 'Description is required for every line item.'
      if (!(Number(ln.quantity) > 0)) return 'Quantity must be greater than 0 for every line item.'
      if (Number(ln.price) < 0) return 'Price cannot be negative.'
    }
    return null
  }

  const save = async (forceStatus) => {
    const err = validateForm()
    if (err) { setFormError(err); return }
    setFormBusy(true)
    setFormError(null)
    try {
      // Send only the fields defined by the quotation API schema. Avoid leaking
      // response-only data such as id, nested customer object, revision totals,
      // subtotal/total or timestamps back to the create/update endpoints.
      const payload = {
        quotation_type: form.quotation_type,
        customer_id: form.customer_id,
        customer_name: form.customer_name,
        customer_contact: form.customer_contact,
        customer_email: form.customer_email,
        customer_address: form.customer_address,
        customer_gstin: form.customer_gstin,
        company_name: form.company_name,
        company_address: form.company_address,
        company_website: form.company_website,
        company_phone: form.company_phone,
        contact_email: form.contact_email,
        quotation_no: form.quotation_no || null,
        quote_date: form.quote_date,
        valid_until: form.valid_until || null,
        approved_by: form.approved_by,
        terms: form.terms,
        payment_days: form.payment_days === '' || form.payment_days == null ? null : Number(form.payment_days),
        status: forceStatus || form.status,
        lines: form.lines.map((ln) => ({
          product_id: ln.product_id || null,
          item_code: ln.item_code || '',
          description: ln.description,
          hsn_code: ln.hsn_code || '',
          quantity: Number(ln.quantity),
          uom: ln.uom || '',
          price: Number(ln.price),
          lead_time: ln.lead_time || '',
          tax_percent: ln.tax_percent === '' ? null : Number(ln.tax_percent),
          amount: calcLine(ln).amount,
        })),
      }
      if (form.id) {
        await api.put(`/quotations/${form.id}`, payload)
      } else {
        await api.post('/quotations', payload)
      }
      setFormOpen(false)
      setSearch('')
      setFilterStatus('')
      setFilterCustomer('')
      setFilterQuoteNo('')
      setFilterDateFrom('')
      setFilterDateTo('')
      await load()
    } catch (e) {
      const detail = e.response?.data?.detail
      setFormError(typeof detail === 'string' ? detail : (detail ? JSON.stringify(detail) : 'Save failed'))
    } finally {
      setFormBusy(false)
    }
  }

  const duplicate = async (q) => {
    if (!window.confirm('Duplicate this quotation?')) return
    try {
      await api.post(`/quotations/${q.id}/duplicate`)
      load()
      setDetail(null)
    } catch (e) { alert(e.response?.data?.detail || 'Duplicate failed') }
  }

  const revise = async (q) => {
    if (!window.confirm('Create a new revision of this quotation?')) return
    try {
      const { data } = await api.post(`/quotations/${q.id}/revise`)
      load()
      setDetail(null)
      openDetail(data)
    } catch (e) { alert(e.response?.data?.detail || 'Revise failed') }
  }

  const changeStatus = async (q, newStatus) => {
    try {
      await api.post(`/quotations/${q.id}/status`, { status: newStatus })
      const { data } = await api.get(`/quotations/${q.id}`)
      setDetail(data)
      load()
    } catch (e) { alert(e.response?.data?.detail || 'Status change failed') }
  }

  const del = async (q) => {
    if (!window.confirm(`Delete quotation ${q.quotation_no} Rev. ${q.revision}?`)) return
    try {
      await api.delete(`/quotations/${q.id}`)
      load()
      setDetail(null)
    } catch (e) { alert(e.response?.data?.detail || 'Delete failed') }
  }

  const openPreview = (q) => {
    const html = buildQuotationHtml(q)
    const w = window.open('', '_blank')
    if (w) {
      w.document.open()
      w.document.write(html)
      w.document.close()
    } else {
      alert('Please allow popups to open the preview.')
    }
  }

  const downloadPdf = (q) => downloadFile(`/reports/quotations/${q.id}/pdf`)

  const buildShareText = (q) => {
    const lines = (q.lines || []).map((l, i) => `${i + 1}. ${l.description} | Qty: ${fmtNum(l.quantity)} ${l.uom || ''} | Price: ₹${fmtNum(l.price)} | Amount: ₹${fmtNum(l.amount)}${l.tax_percent != null ? ' | Tax: ' + fmtNum(l.tax_percent) + '%' : ''}`).join('\n')
    return `Quotation ${q.quotation_no} Rev. ${q.revision}\nCustomer: ${q.customer_name || '—'}\nQuote Date: ${q.quote_date}\nValid Until: ${q.valid_until || '—'}\nTotal Amount: ₹${fmtNum(q.total_amount)}\n\nLine Items:\n${lines || 'No line items'}\n\n${window.location.origin}/quotations`
  }

  const shareQuotation = async (q) => {
    const text = buildShareText(q)
    if (navigator.share) {
      try {
        await navigator.share({ title: `Quotation ${q.quotation_no}`, text })
      } catch {
        // user cancelled share
      }
    } else {
      try {
        await navigator.clipboard.writeText(text)
        alert('Quotation details copied to clipboard')
      } catch {
        alert('Unable to share or copy')
      }
    }
  }

  const openEmail = async (q) => {
    setDetail(null)
    try {
      const { data } = await api.get(`/quotations/${q.id}/email-preview`)
      setEmailForm({ ...data, attach_pdf: true })
      setEmailOpen(true)
    } catch (e) {
      setEmailForm({ to: q.customer_email || '', cc: '', subject: `Quotation ${q.quotation_no} Rev. ${q.revision} - ${normalizeCompanyName(q.company_name)}`, message: '', attach_pdf: true })
      setEmailOpen(true)
    }
    // keep detail for sending
    setDetail(q)
  }

  const sendEmail = async () => {
    if (!detail) return
    setEmailBusy(true)
    try {
      await api.post(`/quotations/${detail.id}/send-email`, emailForm)
      setEmailOpen(false)
      load()
      alert('Email sent successfully')
    } catch (e) {
      alert(e.response?.data?.detail || 'Email send failed')
    } finally {
      setEmailBusy(false)
    }
  }

  const openHistory = async (q) => {
    try {
      const { data } = await api.get(`/quotations/${q.id}/history`)
      setHistoryData(data)
      setHistoryOpen(true)
    } catch (e) { alert(e.response?.data?.detail || 'Failed to load history') }
  }

  const totals = useMemo(() => computeTotals(form.lines), [form.lines])

  const columns = [
    { key: 'quotation_no', label: 'Quote Number', render: (q) => <span className="font-semibold">{q.quotation_no} <span className="text-slate-400 font-normal">Rev. {q.revision}</span></span> },
    { key: 'customer_name', label: 'Customer', render: (q) => q.customer_name || '—' },
    { key: 'quote_date', label: 'Quote Date' },
    { key: 'valid_until', label: 'Valid Until', render: (q) => q.valid_until || '—' },
    { key: 'status', label: 'Status', render: (q) => statusBadge(q.status) },
    { key: 'total_amount', label: 'Total Amount', render: (q) => <span className="font-medium">₹ {fmtNum(q.total_amount)}</span> },
  ]

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Quotations" subtitle="Sales → Quotations • Draft → Sent → Accepted / Rejected / Expired"
        actions={
          <>
            <button onClick={load} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
            <button onClick={openNew} className="btn btn-primary"><Plus size={15} /> New Quotation</button>
          </>
        } />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
        <StatCard label="Quotations" value={stats.total} icon={FileText} iconClass="bg-blue-50 text-blue-600" />
        <StatCard label="Draft" value={stats.draft} icon={Edit3} iconClass="bg-slate-50 text-slate-600" />
        <StatCard label="Sent" value={stats.sent} icon={Send} iconClass="bg-blue-50 text-blue-600" />
        <StatCard label="Accepted" value={stats.accepted} icon={FileText} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
      </div>

      <Card actions={
        <div className="flex flex-col sm:flex-row gap-3 w-full">
          <div className="relative flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search customer or quote number…" className="input input-icon w-full" />
          </div>
          <button onClick={() => setShowFilters((s) => !s)} className={`btn ${showFilters ? 'btn-primary' : 'btn-secondary'}`}><Filter size={15} /> Filters</button>
        </div>
      }>
        {showFilters && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-4">
            <input value={filterCustomer} onChange={(e) => setFilterCustomer(e.target.value)} placeholder="Customer" className="input" />
            <input value={filterQuoteNo} onChange={(e) => setFilterQuoteNo(e.target.value)} placeholder="Quote Number" className="input" />
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="input">
              <option value="">All Statuses</option>
              {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <input type="date" value={filterDateFrom} onChange={(e) => setFilterDateFrom(e.target.value)} placeholder="From date" className="input" />
            <div className="flex gap-2">
              <input type="date" value={filterDateTo} onChange={(e) => setFilterDateTo(e.target.value)} placeholder="To date" className="input flex-1" />
              <button onClick={load} className="btn btn-primary px-3"><Search size={15} /></button>
            </div>
          </div>
        )}

        {loading ? <Loading /> : error ? <ErrorState message={error} /> : (
          <Table columns={columns} data={filteredItems} onRowClick={openDetail} />
        )}
      </Card>

      {/* Detail Modal */}
      {detail && (
        <Modal open title={`${detail.quotation_no} Rev. ${detail.revision}`} onClose={() => setDetail(null)} xwide
          footer={
            <div className="flex flex-wrap items-center gap-2 w-full">
              <div className="flex items-center gap-2 mr-auto flex-wrap">
                {detail.status === 'Draft' && <button onClick={() => openEdit(detail)} className="btn btn-secondary"><Edit3 size={14} /> Edit</button>}
                <button onClick={() => duplicate(detail)} className="btn btn-secondary"><Copy size={14} /> Duplicate</button>
                {(detail.status === 'Sent' || detail.status === 'Accepted') && <button onClick={() => revise(detail)} className="btn btn-secondary"><FileText size={14} /> Revise</button>}
                <select value="" onChange={(e) => e.target.value && changeStatus(detail, e.target.value)} className="input py-1.5 text-sm w-36">
                  <option value="">Change Status</option>
                  {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
                <button onClick={() => del(detail)} className="btn btn-danger"><Trash2 size={14} /> Delete</button>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => openPreview(detail)} className="btn btn-secondary"><Eye size={14} /> Preview</button>
                <button onClick={() => downloadPdf(detail)} className="btn btn-secondary"><Printer size={14} /> PDF</button>
                <button onClick={() => openEmail(detail)} className="btn btn-secondary"><Mail size={14} /> Email</button>
                <button onClick={() => shareQuotation(detail)} className="btn btn-secondary"><Share2 size={14} /> Share</button>
                <button onClick={() => openHistory(detail)} className="btn btn-secondary"><History size={14} /> History</button>
                <button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>
              </div>
            </div>
          }>
          <div className="max-h-[70vh] overflow-y-auto pr-1">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4 text-sm">
              <div><span className="text-slate-500 block text-xs">Customer</span><span className="font-medium">{detail.customer_name || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Quote Date</span><span className="font-medium">{detail.quote_date}</span></div>
              <div><span className="text-slate-500 block text-xs">Valid Until</span><span className="font-medium">{detail.valid_until || '—'}</span></div>
              <div><span className="text-slate-500 block text-xs">Type</span><span className="font-medium">{detail.quotation_type}</span></div>
              <div><span className="text-slate-500 block text-xs">Status</span><span>{statusBadge(detail.status)}</span></div>
              <div><span className="text-slate-500 block text-xs">Total</span><span className="font-bold text-slate-800">₹ {fmtNum(detail.total_amount)}</span></div>
            </div>
            <Table
              columns={[
                { key: 'description', label: 'Description', render: (l) => <span className="font-medium">{l.description}</span> },
                { key: 'hsn_code', label: 'HSN' },
                { key: 'quantity', label: 'Qty', render: (l) => fmtNum(l.quantity) },
                { key: 'uom', label: 'UOM' },
                { key: 'price', label: 'Price', render: (l) => fmtNum(l.price) },
                { key: 'lead_time', label: 'Lead Time' },
                { key: 'tax_percent', label: 'Tax %', render: (l) => l.tax_percent != null ? `${fmtNum(l.tax_percent)}%` : '—' },
                { key: 'amount', label: 'Amount', render: (l) => fmtNum(l.amount) },
              ]}
              data={detail.lines || []}
              dense
            />
            <div className="mt-4 flex flex-col sm:flex-row justify-end gap-4">
              <div className="text-sm text-right">
                <div className="text-slate-500">Subtotal: <span className="font-medium text-slate-800">₹ {fmtNum(detail.subtotal)}</span></div>
                <div className="text-lg font-bold text-slate-800 mt-1">Total Amount: ₹ {fmtNum(detail.total_amount)}</div>
              </div>
            </div>
            {detail.terms && (
              <div className="mt-5 p-4 bg-slate-50 rounded-lg border border-slate-200">
                <h4 className="text-sm font-semibold text-slate-700 mb-2">Terms & Conditions</h4>
                <pre className="text-xs text-slate-600 whitespace-pre-wrap font-sans">{detail.terms}</pre>
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Form Modal */}
      {formOpen && (
        <Modal open title={form.id ? `Edit Quotation ${form.quotation_no}` : 'New Quotation'} onClose={() => setFormOpen(false)} xwide
          footer={
            <div className="flex flex-wrap items-center gap-2 w-full">
              <div className="mr-auto">
                {formError && <span className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-3 py-1.5">{formError}</span>}
              </div>
              <button onClick={() => setFormOpen(false)} className="btn btn-secondary">Cancel</button>
              <button onClick={() => save('Draft')} className="btn btn-secondary" disabled={formBusy}>{formBusy ? 'Saving…' : 'Save as Draft'}</button>
              <button onClick={() => save(form.status)} className="btn btn-primary" disabled={formBusy}>{formBusy ? 'Saving…' : (form.id ? 'Save Changes' : 'Save Quotation')}</button>
            </div>
          }>
          <div className="max-h-[70vh] overflow-y-auto pr-1 space-y-6" onWheel={blurNumberOnWheel}>
            {/* Section A: Customer */}
            <div>
              <SectionHeader title="A. Customer / Client" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Customer *</label>
                  <SearchSelect
                    options={customers.map((c) => ({ id: c.id, label: c.name }))}
                    value={form.customer_id || null}
                    initialLabel={form.customer_name}
                    placeholder="Search or enter a customer"
                    onChange={setCustomer}
                  />
                </div>
                <div><label className="block text-xs text-slate-500 mb-1">Contact</label><input value={form.customer_contact} onChange={(e) => setForm({ ...form, customer_contact: e.target.value })} className="input w-full" /></div>
                <div><label className="block text-xs text-slate-500 mb-1">Email</label><input value={form.customer_email} onChange={(e) => setForm({ ...form, customer_email: e.target.value })} className="input w-full" /></div>
                <div><label className="block text-xs text-slate-500 mb-1">GSTIN</label><input value={form.customer_gstin} onChange={(e) => setForm({ ...form, customer_gstin: e.target.value })} className="input w-full" /></div>
                <div className="md:col-span-2"><label className="block text-xs text-slate-500 mb-1">Address</label><textarea value={form.customer_address} onChange={(e) => setForm({ ...form, customer_address: e.target.value })} className="input w-full h-20" /></div>
              </div>
            </div>

            {/* Section B: Quotation Details */}
            <div>
              <SectionHeader title="B. Quotation Details" />
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Company Name *</label>
                  <select value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} className="input w-full">
                    {COMPANY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-slate-500 mb-1">Quotation Type *</label>
                  <select value={form.quotation_type} onChange={(e) => setForm({ ...form, quotation_type: e.target.value })} className="input w-full">
                    <option value="Manufacturing">Manufacturing</option>
                    <option value="Trading">Trading</option>
                  </select>
                </div>
                <div><label className="block text-xs text-slate-500 mb-1">Quote Date</label><input type="date" value={form.quote_date} onChange={(e) => setForm({ ...form, quote_date: e.target.value })} className="input w-full" /></div>
                <div><label className="block text-xs text-slate-500 mb-1">Valid Until</label><input type="date" value={form.valid_until} onChange={(e) => setForm({ ...form, valid_until: e.target.value })} className="input w-full" /></div>
                <div><label className="block text-xs text-slate-500 mb-1">Status</label>
                  <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="input w-full">
                    {STATUS_OPTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div><label className="block text-xs text-slate-500 mb-1">Approved By</label><input value={form.approved_by} onChange={(e) => setForm({ ...form, approved_by: e.target.value })} className="input w-full" /></div>
                <div><label className="block text-xs text-slate-500 mb-1">Quotation No. {form.id ? '(read-only)' : '(auto if blank)'}</label><input value={form.quotation_no} onChange={(e) => setForm({ ...form, quotation_no: e.target.value })} disabled={!!form.id} className="input w-full disabled:bg-slate-100" placeholder="QTN-YYYYMMDD-###" /></div>
              </div>
            </div>

            {/* Section C: Products / Items */}
            <div>
              <SectionHeader title="C. Products / Items" right={<button onClick={addLine} className="btn btn-ghost text-xs"><Plus size={12} /> Add Line</button>} />
              <div className="space-y-3">
                {form.lines.map((ln, idx) => {
                  const computed = calcLine(ln)
                  return (
                    <div key={idx} className="border border-slate-200 rounded-xl p-4 bg-slate-50/60">
                      <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
                        {form.quotation_type === 'Manufacturing' ? (
                          <div className="md:col-span-3">
                            <label className="block text-xs text-slate-500 mb-1">Product *</label>
                            <SearchSelect
                              options={manufacturingOptions}
                              value={MANUFACTURING_PRODUCTS.includes(ln.description) ? ln.description : null}
                              initialLabel={ln.description}
                              placeholder="Search product…"
                              onChange={(id, manual) => setLineProduct(idx, id, manual)}
                            />
                          </div>
                        ) : (
                          <div className="md:col-span-3">
                            <label className="block text-xs text-slate-500 mb-1">Description *</label>
                            <input value={ln.description} onChange={(e) => setLine(idx, 'description', e.target.value)} className="input w-full" placeholder="Item description" />
                          </div>
                        )}
                        <div className="md:col-span-2"><label className="block text-xs text-slate-500 mb-1">Item Code</label><input value={ln.item_code} onChange={(e) => setLine(idx, 'item_code', e.target.value)} className="input w-full" /></div>
                        <div className="md:col-span-2"><label className="block text-xs text-slate-500 mb-1">HSN</label><input value={ln.hsn_code} onChange={(e) => setLine(idx, 'hsn_code', e.target.value)} className="input w-full" /></div>
                        <div className="md:col-span-1"><label className="block text-xs text-slate-500 mb-1">Qty *</label><input type="number" value={ln.quantity} onChange={(e) => setLine(idx, 'quantity', e.target.value)} className="input w-full" /></div>
                        <div className="md:col-span-1"><label className="block text-xs text-slate-500 mb-1">UOM</label><input value={ln.uom} onChange={(e) => setLine(idx, 'uom', e.target.value)} className="input w-full" placeholder="PCS" /></div>
                        <div className="md:col-span-1"><label className="block text-xs text-slate-500 mb-1">Price *</label><input type="number" value={ln.price} onChange={(e) => setLine(idx, 'price', e.target.value)} className="input w-full" /></div>
                        <div className="md:col-span-1"><label className="block text-xs text-slate-500 mb-1">Lead Time</label><input value={ln.lead_time} onChange={(e) => setLine(idx, 'lead_time', e.target.value)} className="input w-full" placeholder="7 Days" /></div>
                        <div className="md:col-span-1"><label className="block text-xs text-slate-500 mb-1">Tax %</label><input type="number" value={ln.tax_percent} onChange={(e) => setLine(idx, 'tax_percent', e.target.value)} className="input w-full" placeholder="18" /></div>
                      </div>
                      <div className="flex items-center justify-between mt-3">
                        <div className="text-xs text-slate-500">
                          Amount: <span className="font-bold text-slate-800">₹ {fmtNum(computed.amount)}</span>
                        </div>
                        <button onClick={() => removeLine(idx)} className="text-red-400 hover:text-red-600"><Trash2 size={16} /></button>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Section D: Pricing */}
            <div>
              <SectionHeader title="D. Pricing" />
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 bg-white border border-slate-200 rounded-lg"><div className="text-xs text-slate-400 uppercase">Subtotal</div><div className="text-lg font-bold text-slate-800">₹ {fmtNum(totals)}</div></div>
                <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg"><div className="text-xs text-slate-400 uppercase">Total Amount</div><div className="text-lg font-bold text-blue-800">₹ {fmtNum(totals)}</div></div>
              </div>
            </div>

            {/* Section E: Terms & Conditions */}
            <div>
              <SectionHeader title="E. Terms & Conditions" right={
                <select value="" onChange={(e) => {
                  const t = templates.find((x) => x.id === Number(e.target.value))
                  if (t) setForm((f) => ({ ...f, terms: t.content, payment_days: parsePaymentDays(t.content) ?? f.payment_days }))
                }} className="input text-xs py-1">
                  <option value="">Load template…</option>
                  {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              } />
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="text-xs text-slate-500">Payment Period (days)</span>
                <input
                  type="number" min="1" step="1"
                  value={form.payment_days ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value
                    const days = raw === '' ? '' : Math.max(1, Math.floor(Number(raw)))
                    setForm((f) => ({ ...f, payment_days: days, terms: days ? applyPaymentDays(f.terms, days) : f.terms }))
                  }}
                  placeholder="e.g. 30"
                  className="input text-xs py-1 w-24"
                />
                <span className="text-xs text-slate-400">updates condition 2 automatically</span>
              </div>
              <textarea value={form.terms} onChange={(e) => setForm({ ...form, terms: e.target.value })} className="input w-full h-32" placeholder="Enter terms & conditions…" />
            </div>
          </div>
        </Modal>
      )}

      {/* Email Modal */}
      {emailOpen && (
        <Modal open title="Send Quotation by Email" onClose={() => setEmailOpen(false)} wide
          footer={
            <>
              <button onClick={() => setEmailOpen(false)} className="btn btn-secondary">Cancel</button>
              <button onClick={sendEmail} className="btn btn-primary" disabled={emailBusy}>{emailBusy ? 'Sending…' : <><Send size={14} className="mr-1" /> Send Email</>}</button>
            </>
          }>
          <div className="grid grid-cols-1 gap-3 text-sm">
            <div><label className="block text-xs text-slate-500 mb-1">To *</label><input value={emailForm.to} onChange={(e) => setEmailForm({ ...emailForm, to: e.target.value })} className="input w-full" /></div>
            <div><label className="block text-xs text-slate-500 mb-1">CC</label><input value={emailForm.cc} onChange={(e) => setEmailForm({ ...emailForm, cc: e.target.value })} className="input w-full" placeholder="Comma separated emails" /></div>
            <div><label className="block text-xs text-slate-500 mb-1">Subject</label><input value={emailForm.subject} onChange={(e) => setEmailForm({ ...emailForm, subject: e.target.value })} className="input w-full" /></div>
            <div><label className="block text-xs text-slate-500 mb-1">Message</label><textarea value={emailForm.message} onChange={(e) => setEmailForm({ ...emailForm, message: e.target.value })} className="input w-full h-32" /></div>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={emailForm.attach_pdf} onChange={(e) => setEmailForm({ ...emailForm, attach_pdf: e.target.checked })} />
              <span>Attach quotation PDF</span>
            </label>
          </div>
        </Modal>
      )}

      {/* History Modal */}
      {historyOpen && (
        <Modal open title="Quotation History" onClose={() => setHistoryOpen(false)} wide
          footer={<button onClick={() => setHistoryOpen(false)} className="btn btn-secondary">Close</button>}>
          <div className="max-h-[60vh] overflow-y-auto">
            <h4 className="text-sm font-semibold text-slate-700 mb-2">Revisions</h4>
            <Table
              columns={[
                { key: 'quotation_no', label: 'Quote Number', render: (r) => `${r.quotation_no} Rev. ${r.revision}` },
                { key: 'status', label: 'Status', render: (r) => statusBadge(r.status) },
                { key: 'quote_date', label: 'Quote Date' },
                { key: 'total_amount', label: 'Total', render: (r) => fmtNum(r.total_amount) },
                { key: 'created_by', label: 'By', render: (r) => r.created_by?.full_name || '—' },
              ]}
              data={historyData.revisions}
              dense
            />
            <h4 className="text-sm font-semibold text-slate-700 mt-5 mb-2">Audit Trail</h4>
            <Table
              columns={[
                { key: 'created_at', label: 'Date', render: (a) => new Date(a.created_at).toLocaleString() },
                { key: 'action', label: 'Action' },
                { key: 'details', label: 'Details' },
              ]}
              data={historyData.audit}
              dense
            />
          </div>
        </Modal>
      )}
    </div>
  )
}
