import { useEffect, useMemo, useRef, useState } from 'react'
import { Plus, Pencil, X, Trash2, Copy, Share2, Printer, Search, Image, Package } from 'lucide-react'
import html2canvas from 'html2canvas'
import api from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, SearchSelect } from '../components/ui'
import Table from '../components/Table'
const today = () => new Date().toISOString().slice(0, 10)
// Weights are stored as entered; only the on-screen rendering is padded to 3 decimals.
const fmtWt = (v) => {
  const n = Number(v)
  if (v === '' || v == null || Number.isNaN(n)) return '—'
  return n.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 })
}

// Net WT = Gross WT - Less, kept at full float precision (no early rounding).
const round6 = (n) => Number(Number(n || 0).toFixed(6))
const calcNet = (gross, less) => round6((Number(gross) || 0) - (Number(less) || 0))

const emptyLine = () => ({ sr_no: 1, gross_wt: '', less: '', net_wt: 0, lessTouched: false })

// A starter row that has never been filled in — replaced when adding boxes in bulk.
const isUntouchedBlank = (l) => (l.gross_wt === '' || l.gross_wt == null) && !l.lessTouched

// Upper bound for a single "Add Boxes" action so a mistyped count cannot hang the UI.
const MAX_BOXES_AT_ONCE = 500

const emptyForm = () => ({
  list_date: today(),
  customer_id: null,
  customer_name: '',
  product_id: null,
  item_description: '',
  less_default: '',
  lines: [emptyLine()],
})

// Unsaved form draft survives an accidental window/tab close and is only
// cleared once the packaging list is saved successfully.
const DRAFT_KEY = 'kalika_packaging_draft_v1'

const readDraft = () => {
  try {
    const raw = localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const d = JSON.parse(raw)
    if (!d || !d.form || !Array.isArray(d.form.lines)) return null
    return d
  } catch {
    return null
  }
}

const clearDraft = () => {
  try { localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
}

// A pristine (untouched) form is not worth persisting as a draft.
const isFormEmpty = (f) => {
  if (!f) return true
  const lines = f.lines || []
  const hasLineData = lines.some(
    (l) => (l.gross_wt !== '' && l.gross_wt != null) || (l.less !== '' && l.less != null)
  )
  return (
    !f.customer_id &&
    !(f.customer_name || '').trim() &&
    !(f.item_description || '').trim() &&
    (f.less_default === '' || f.less_default == null) &&
    !hasLineData
  )
}

const errText = (err) => {
  const d = err?.response?.data
  if (d?.message) return d.message
  const detail = d?.detail
  if (Array.isArray(detail)) return detail.map((x) => x.msg || x).join('. ')
  if (typeof detail === 'string') return detail
  return 'Request failed. Please try again.'
}

export default function PackagingList() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [customers, setCustomers] = useState([])
  const [products, setProducts] = useState([])
  const [search, setSearch] = useState('')

  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  // Inline "add weight" row inside the detail table
  const [addRow, setAddRow] = useState({ gross_wt: '', less: '' })
  const [lineBusy, setLineBusy] = useState(false)

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(emptyForm())
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [boxCount, setBoxCount] = useState('')
  const [boxCountError, setBoxCountError] = useState('')

  const [warning, setWarning] = useState(null)
  const [showDelete, setShowDelete] = useState(null)
  const [success, setSuccess] = useState('')

  // Draft restore/persistence (see DRAFT_KEY above)
  const [draftSavedAt, setDraftSavedAt] = useState(null)

  // Refs so Enter can move the cursor down the box-weight rows without clicking.
  const grossRefs = useRef([])
  const lessRefs = useRef([])
  const addRowGrossRef = useRef(null)
  // Row index that should receive focus after the next render (new row added).
  const pendingFocusRef = useRef(null)

  const flash = (text) => { setSuccess(text); setTimeout(() => setSuccess(''), 6000) }

  const customerOptions = useMemo(
    () => customers.map((c) => ({ id: c.id, label: c.name })).sort((a, b) => a.label.localeCompare(b.label)),
    [customers]
  )

  const productOptions = useMemo(
    () => products.map((p) => ({ id: p.id, label: `${p.item_code ? p.item_code + ' — ' : ''}${p.description || p.name || ''}` })).sort((a, b) => a.label.localeCompare(b.label)),
    [products]
  )

  const load = () => {
    setLoading(true)
    api.get('/packaging-lists', {
      params: { search, page_size: 500 },
    })
      .then((res) => setRows(res.data.items || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    api.get('/customers', { params: { page_size: 500 } }).then((r) => setCustomers(r.data.items || [])).catch(() => {})
    api.get('/products', { params: { page_size: 500 } }).then((r) => setProducts(r.data.items || [])).catch(() => {})
    const focus = new URLSearchParams(window.location.search).get('list')
    if (focus && Number(focus)) {
      openDetail({ id: Number(focus) })
    } else {
      // Restore unsaved work from a previous visit (window/tab was closed).
      const draft = readDraft()
      if (draft) {
        setForm(draft.form)
        setEditing(draft.editing || null)
        setDraftSavedAt(draft.savedAt || Date.now())
        setShowForm(true)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Persist the in-progress form so an accidental close never loses data.
  useEffect(() => {
    if (!showForm) return
    if (isFormEmpty(form)) {
      clearDraft()
      setDraftSavedAt(null)
      return
    }
    const snapshot = {
      form,
      editing: editing ? { id: editing.id, list_no: editing.list_no } : null,
      savedAt: Date.now(),
    }
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(snapshot))
      setDraftSavedAt(snapshot.savedAt)
    } catch { /* storage unavailable (private mode) — ignore */ }
  }, [form, showForm, editing])

  useEffect(() => {
    const t = setTimeout(load, 250)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const totals = useMemo(() => {
    const gross = (form.lines || []).reduce((s, l) => s + (Number(l.gross_wt) || 0), 0)
    const less = (form.lines || []).reduce((s, l) => s + (Number(l.less) || 0), 0)
    return { gross: round6(gross), less: round6(less), net: round6(gross - less) }
  }, [form.lines])

  const openDetail = (row) => {
    setDetail({ id: row.id, loading: true })
    setDetailLoading(true)
    setAddRow({ gross_wt: '', less: '' })
    api.get(`/packaging-lists/${row.id}`)
      .then((res) => {
        setDetail(res.data)
        // Pre-fill the inline add row's less with the list default.
        const def = res.data.less_default != null ? String(res.data.less_default) : ''
        setAddRow({ gross_wt: '', less: def })
      })
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false))
  }

  const openCreate = () => {
    setForm(emptyForm())
    setEditing(null)
    setErrors({})
    setBoxCount('')
    setBoxCountError('')
    setShowForm(true)
  }

  // Explicitly throw away the saved draft and start clean.
  const discardDraft = () => {
    clearDraft()
    setDraftSavedAt(null)
    setForm(emptyForm())
    setEditing(null)
    setErrors({})
    setBoxCount('')
    setBoxCountError('')
    setShowForm(false)
  }

  // Enter on a Gross/Less cell drops the cursor onto the next row's Gross cell,
  // adding a fresh row when the last one is filled. Avoids clicking each row.
  const focusGross = (i) => {
    const el = grossRefs.current[i]
    if (el) {
      el.focus()
      if (typeof el.select === 'function') el.select()
    }
  }

  const handleLineEnter = (i) => {
    const lines = form.lines || []
    const isLast = i === lines.length - 1
    if (isLast) {
      const last = lines[i] || {}
      if ((last.gross_wt === '' || last.gross_wt == null) && (last.less === '' || last.less == null)) return
      pendingFocusRef.current = i + 1
      addLine()
    } else {
      focusGross(i + 1)
    }
  }

  // Move focus to the freshly-added row once it is rendered.
  useEffect(() => {
    if (pendingFocusRef.current == null) return
    const target = pendingFocusRef.current
    pendingFocusRef.current = null
    const el = grossRefs.current[target]
    if (el) {
      el.focus()
      if (typeof el.select === 'function') el.select()
    }
  }, [form.lines])

  const openEdit = (row) => {
    // Modals are portalled to <body> in JSX order, so the detail window would
    // paint over the edit form. Close it before opening the form.
    setDetail(null)
    setDetailLoading(false)
    setForm({
      list_date: row.list_date || today(),
      customer_id: row.customer_id || null,
      customer_name: row.customer_name || '',
      item_description: row.item_description || '',
      less_default: row.less_default != null ? String(row.less_default) : '',
      product_id: null,
      lines: (row.lines || []).length
        ? row.lines.map((l) => ({
            id: l.id,
            sr_no: l.sr_no,
            gross_wt: l.gross_wt != null ? String(l.gross_wt) : '',
            less: l.less != null ? String(l.less) : '',
            net_wt: l.net_wt,
            // Stored rows follow the default until the user edits their Less.
            lessTouched: false,
          }))
        : [emptyLine()],
    })
    setEditing(row)
    setErrors({})
    setBoxCount('')
    setBoxCountError('')
    setShowForm(true)
  }

  const addLine = () => {
    setForm((f) => ({
      ...f,
      lines: [...(f.lines || []), {
        ...emptyLine(),
        sr_no: (f.lines || []).length + 1,
        less: f.less_default === '' || f.less_default == null ? '' : String(f.less_default),
      }],
    }))
  }

  const addBoxes = () => {
    const raw = String(boxCount).trim()
    if (!/^\d+$/.test(raw)) {
      setBoxCountError('Enter a whole number of boxes (1 or more).')
      return
    }
    const count = Number(raw)
    if (count < 1) {
      setBoxCountError('Enter at least 1 box.')
      return
    }
    if (count > MAX_BOXES_AT_ONCE) {
      setBoxCountError(`Enter ${MAX_BOXES_AT_ONCE} boxes or fewer at a time.`)
      return
    }
    setBoxCountError('')
    setBoxCount('')
    const defLess = form.less_default === '' || form.less_default == null ? '' : String(form.less_default)
    const existing = (form.lines || []).filter((l) => !isUntouchedBlank(l))
    pendingFocusRef.current = existing.length
    setForm((f) => {
      const kept = (f.lines || []).filter((l) => !isUntouchedBlank(l))
      const added = Array.from({ length: count }, (_, k) => ({
        ...emptyLine(),
        sr_no: kept.length + k + 1,
        less: defLess,
      }))
      return { ...f, lines: [...kept, ...added].map((l, idx) => ({ ...l, sr_no: idx + 1 })) }
    })
  }

  const updateLine = (i, key, value) => {
    setForm((f) => {
      const lines = [...(f.lines || [])]
      const line = { ...lines[i], [key]: value }
      // Editing Less on a single box overrides the list default for that box only.
      if (key === 'less') line.lessTouched = true
      // Any gross entry keeps the row in sync with the current default less.
      if (key === 'gross_wt' && !line.lessTouched) {
        line.less = f.less_default === '' || f.less_default == null ? '' : String(f.less_default)
      }
      if (key === 'gross_wt' || key === 'less') {
        line.net_wt = calcNet(line.gross_wt, line.less)
      }
      lines[i] = line
      return { ...f, lines }
    })
  }

  const removeLine = (i) => {
    setForm((f) => {
      const lines = (f.lines || []).filter((_, idx) => idx !== i).map((l, idx) => ({ ...l, sr_no: idx + 1 }))
      return { ...f, lines }
    })
  }

  const setCustomer = (id, manual) => {
    const name = id ? customers.find((c) => c.id === id)?.name || '' : manual
    setForm((f) => ({ ...f, customer_id: id, customer_name: name }))
  }

  const setProduct = (id, manual) => {
    const desc = id ? products.find((p) => p.id === id)?.description || products.find((p) => p.id === id)?.name || '' : manual
    setForm((f) => ({ ...f, product_id: id, item_description: desc }))
  }

  // Changing the list default re-syncs every box that still follows the default.
// Boxes whose Less was edited by hand are left untouched.
const setDefaultLess = (value) => {
    setForm((f) => {
      const def = value === '' || value == null ? '' : String(value)
      const lines = (f.lines || []).map((l) => {
        if (l.lessTouched) return l
        return { ...l, less: def, net_wt: calcNet(l.gross_wt, def) }
      })
      return { ...f, less_default: value, lines }
    })
  }

  const validate = () => {
    const errs = {}
    if (!form.customer_id && !(form.customer_name || '').trim()) errs.customer = 'Select or enter a customer'
    if (!(form.item_description || '').trim()) errs.item_description = 'Enter item description'
    if (!form.lines || form.lines.length === 0) errs.lines = 'Add at least one box line'
    form.lines.forEach((l, i) => {
      if ((l.gross_wt === '' || l.gross_wt == null) && (l.less === '' || l.less == null)) {
        errs[`line_${i}_gross`] = 'Enter gross or less'
      }
      if (Number(l.gross_wt) < 0) errs[`line_${i}_gross`] = 'Gross cannot be negative'
      if (Number(l.less) < 0) errs[`line_${i}_less`] = 'Less cannot be negative'
      if (Number(l.net_wt) < 0) errs[`line_${i}_net`] = 'Net cannot be negative'
    })
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const payload = () => ({
    list_date: form.list_date,
    customer_id: form.customer_id ? Number(form.customer_id) : null,
    customer_name: form.customer_name || '',
    item_description: form.item_description || '',
    less_default: form.less_default === '' || form.less_default == null ? 0 : Number(form.less_default),
    lines: (form.lines || []).map((l, i) => ({
      id: editing ? l.id || null : undefined,
      sr_no: i + 1,
      gross_wt: l.gross_wt === '' || l.gross_wt == null ? 0 : Number(l.gross_wt),
      // Send null when blank so the backend falls back to the list default.
      less: l.less === '' || l.less == null ? null : Number(l.less),
      net_wt: l.net_wt,
    })),
  })

  const doSave = (force = false) => {
    if (!validate()) return
    setSaving(true)
    const url = editing ? `/packaging-lists/${editing.id}` : '/packaging-lists'
    const method = editing ? 'put' : 'post'
    api[method](url, payload(), { params: force ? { force: true } : {} })
      .then((res) => {
        if (res.data?.warning) {
          setWarning({ data: res.data, forceAction: force ? 'retry' : 'confirm' })
          setSaving(false)
          return
        }
        setShowForm(false)
        setEditing(null)
        setWarning(null)
        clearDraft()
        setDraftSavedAt(null)
        flash(`${editing ? 'Updated' : 'Created'} packaging list ${res.data.list_no}`)
        load()
        if (detail?.id) openDetail({ id: detail.id })
      })
      .catch((err) => setErrors({ api: errText(err) }))
      .finally(() => setSaving(false))
  }

  const confirmWarning = () => doSave(true)
  const cancelWarning = () => setWarning(null)

  // ---- inline add / delete weight rows directly from the detail table ----
  const linesPayload = (lines) => lines.map((l, i) => ({
    id: l.id || null,
    sr_no: i + 1,
    gross_wt: l.gross_wt === '' || l.gross_wt == null ? 0 : Number(l.gross_wt),
    less: l.less === '' || l.less == null ? null : Number(l.less),
  }))

  const addWeightInline = () => {
    const d = detail
    if (!d || d.loading) return
    const gross = addRow.gross_wt === '' ? null : Number(addRow.gross_wt)
    if (gross === null || Number.isNaN(gross)) { window.alert('Enter the box gross weight'); return }
    if (gross <= 0) { window.alert('Gross weight must be greater than 0'); return }
    const less = addRow.less === '' ? null : Number(addRow.less)
    if (less !== null && Number.isNaN(less)) { window.alert('Less weight is not valid'); return }
    const effLess = less === null ? Number(d.less_default || 0) : less
    if (gross - effLess < 0) { window.alert('Net weight cannot be negative. Reduce gross or less.'); return }

    setLineBusy(true)
    const nextLines = [...(d.lines || []).map((l) => ({ id: l.id, gross_wt: l.gross_wt, less: l.less })),
      { gross_wt: gross, less: effLess }]
    api.put(`/packaging-lists/${d.id}`, { lines: linesPayload(nextLines) }, { params: { force: true } })
      .then((res) => {
        setDetail(res.data)
        setAddRow({ gross_wt: '', less: res.data.less_default != null ? String(res.data.less_default) : '' })
        load()
        // Keep the cursor in the add box for fast consecutive entry.
        requestAnimationFrame(() => addRowGrossRef.current?.focus())
      })
      .catch((err) => window.alert(errText(err)))
      .finally(() => setLineBusy(false))
  }

  const deleteWeightInline = (line) => {
    const d = detail
    if (!d || d.loading) return
    if (!window.confirm(`Remove box ${line.sr_no} (Gross ${fmtWt(line.gross_wt)}, Less ${fmtWt(line.less)}) from this packing list?`)) return
    setLineBusy(true)
    const nextLines = (d.lines || []).filter((l) => l.id !== line.id)
    api.put(`/packaging-lists/${d.id}`, { lines: linesPayload(nextLines) }, { params: { force: true } })
      .then((res) => {
        setDetail(res.data)
        load()
        flash(`Removed box ${line.sr_no}`)
      })
      .catch((err) => window.alert(errText(err)))
      .finally(() => setLineBusy(false))
  }

  const addRowNet = () => {
    const gross = Number(addRow.gross_wt) || 0
    const less = addRow.less === '' || addRow.less == null ? Number(detail?.less_default || 0) : Number(addRow.less)
    return calcNet(gross, less)
  }

  const duplicateRow = (row) => {
    api.post(`/packaging-lists/${row.id}/duplicate`)
      .then((res) => {
        flash(`Duplicated as ${res.data.list_no}`)
        load()
      })
      .catch((err) => window.alert(errText(err)))
  }

  const deleteRow = (row) => {
    api.delete(`/packaging-lists/${row.id}`)
      .then(() => {
        setShowDelete(null)
        setDetail(null)
        flash(`Deleted packaging list ${row.list_no}`)
        load()
      })
      .catch((err) => window.alert(errText(err)))
  }

  // ---- share text ----
  const shareList = async () => {
    const d = detail
    if (!d || d.loading) return
    const linesText = (d.lines || []).map((l) =>
      `#${l.sr_no}: Gross ${fmtWt(l.gross_wt)} - Less ${fmtWt(l.less)} = Net ${fmtWt(l.net_wt)}`
    ).join('\n')
    const text = `PACKING LIST ${d.list_no}\nDate: ${d.list_date}\nCustomer: ${d.customer_name || '—'}\nItem: ${d.item_description || '—'}\n\n${linesText}\n\nTotal Gross: ${fmtWt(d.total_gross_wt)}\nTotal Less: ${fmtWt(d.total_less)}\nTotal Net: ${fmtWt(d.total_net_wt)}`
    const url = `${window.location.origin}/packaging-lists?list=${d.id}`
    const copy = async () => {
      try {
        await navigator.clipboard.writeText(`${text}\n\n${url}`)
        flash('Packing list copied to clipboard')
      } catch {
        window.alert('Could not copy. Please share manually.')
      }
    }
    if (navigator.share) {
      try { await navigator.share({ title: `Packing List ${d.list_no}`, text, url }) }
      catch (e) { if (e?.name !== 'AbortError') await copy() }
    } else {
      await copy()
    }
  }

  // ---- document HTML builder ----
  const buildHtml = (d) => {
    const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
    const lineRows = (d.lines || []).map((l) =>
      `<tr>
        <td class="c">${l.sr_no}</td>
        <td class="r">${fmtWt(l.gross_wt)}</td>
        <td class="r">${fmtWt(l.less)}</td>
        <td class="r"><strong>${fmtWt(l.net_wt)}</strong></td>
      </tr>`
    ).join('')
    const logoUrl = `${window.location.origin}/Kalika_logo.png`
    return `<!doctype html><html><head><meta charset="utf-8"><title>Packing List ${esc(d.list_no)}</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 11px; color: #111; margin: 10mm; background: #fff; }
  .header { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
  .header img { height: 42px; max-width: 160px; object-fit: contain; }
  .header .title { font-size: 19px; font-weight: 800; color: #111; line-height: 1.15; letter-spacing: -0.3px; }
  .header .sub-title { font-size: 11px; color: #666; margin-top: 1px; }
  .doc-title { text-align: center; font-size: 14px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin: 8px 0 6px; border-bottom: 1.5px solid #111; padding-bottom: 4px; }
  .meta { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 20px; margin-bottom: 8px; }
  .meta .row { display: flex; justify-content: space-between; border-bottom: 1px dashed #ddd; padding: 2px 0; }
  .meta .lbl { color: #666; font-size: 9px; text-transform: uppercase; letter-spacing: .4px; }
  .meta .val { font-weight: 700; }
  table { width: 100%; border-collapse: collapse; margin-top: 4px; }
  thead { display: table-header-group; }
  th, td { border: 1px solid #bbb; padding: 2px 6px; line-height: 1.2; font-size: 10px; }
  th { background: #f0f0f0; text-transform: uppercase; font-size: 9px; letter-spacing: .4px; color: #444; padding: 3px 6px; }
  .c { text-align: center; }
  .r { text-align: right; }
  .total td { font-weight: 800; background: #f7f7f7; border-top: 2px solid #111; font-size: 11px; }
  .foot { margin-top: 12px; font-size: 9px; color: #888; text-align: center; }
  @page { size: A4; margin: 10mm; }
  @media print { body { margin: 0; } }
</style></head><body>
<div class="header">
  <img src="${logoUrl}" alt="Kalika" />
  <div>
    <div class="title">KALIKA ENTERPRISES</div>
    <div class="sub-title">Packing List — ${esc(d.list_no)}</div>
  </div>
</div>
<div class="doc-title">Packing List</div>
<div class="meta">
  <div class="row"><span class="lbl">Date</span><span class="val">${esc(d.list_date)}</span></div>
  <div class="row"><span class="lbl">List No</span><span class="val">${esc(d.list_no)}</span></div>
  <div class="row"><span class="lbl">Default Less</span><span class="val">${fmtWt(d.less_default)}</span></div>
  <div class="row"><span class="lbl">Total Boxes</span><span class="val">${(d.lines || []).length}</span></div>
  <div class="row" style="grid-column: span 2;"><span class="lbl">Customer</span><span class="val">${esc(d.customer_name || '—')}</span></div>
  <div class="row" style="grid-column: span 2;"><span class="lbl">Item</span><span class="val">${esc(d.item_description || '—')}</span></div>
</div>
<table><thead><tr><th>Sr. No</th><th class="r">Gross WT</th><th class="r">Less</th><th class="r">Net WT</th></tr></thead>
<tbody>${lineRows || '<tr><td class="c">-</td><td class="r">-</td><td class="r">-</td><td class="r">-</td></tr>'}</tbody>
<tfoot><tr class="total"><td class="c">TOTAL WT</td><td class="r">${fmtWt(d.total_gross_wt)}</td><td class="r">${fmtWt(d.total_less)}</td><td class="r">${fmtWt(d.total_net_wt)}</td></tr></tfoot></table>
<div class="foot">Generated by Kalika ERP — Packaging List</div>
</body></html>`
  }

  const downloadPdf = () => {
    const d = detail
    if (!d || d.loading) return
    const html = buildHtml(d)
    const win = window.open('', '_blank', 'width=900,height=760')
    if (!win) { window.alert('Popup blocked — please allow popups to generate the PDF.'); return }
    win.document.write(html)
    win.document.close()
    win.focus()
    setTimeout(() => win.print(), 350)
  }

  const downloadJpg = async () => {
    const d = detail
    if (!d || d.loading) return
    const html = buildHtml(d)
    const iframe = document.createElement('iframe')
    iframe.style.position = 'fixed'
    iframe.style.left = '-9999px'
    iframe.style.top = '0'
    iframe.style.width = '900px'
    // Tall viewport so long lists (40+ rows) are not clipped in the JPG.
    iframe.style.height = '4000px'
    document.body.appendChild(iframe)

    const doc = iframe.contentDocument
    doc.open()
    doc.write(html)
    doc.close()

    await new Promise((resolve) => {
      const img = doc.querySelector('.header img')
      if (!img || img.complete) return resolve()
      img.onload = resolve
      img.onerror = resolve
      setTimeout(resolve, 1000)
    })

    try {
      const canvas = await html2canvas(doc.body, { scale: 2, backgroundColor: '#ffffff', useCORS: true, logging: false })
      const link = document.createElement('a')
      link.href = canvas.toDataURL('image/jpeg', 0.95)
      link.download = `packing_list_${d.list_no}.jpg`
      link.click()
    } catch (err) {
      window.alert('Failed to generate JPG: ' + (err?.message || 'Unknown error'))
    } finally {
      document.body.removeChild(iframe)
    }
  }

  const columns = [
    { key: 'list_no', label: 'List No', render: (r) => <span className="whitespace-nowrap font-medium">{r.list_no}</span> },
    { key: 'list_date', label: 'Date', render: (r) => <span className="whitespace-nowrap">{r.list_date}</span> },
    { key: 'customer_name', label: 'Customer', render: (r) => <span className="block max-w-[160px] truncate" title={r.customer_name}>{r.customer_name || '—'}</span> },
    { key: 'item_description', label: 'Item', render: (r) => <span className="block max-w-[180px] truncate" title={r.item_description}>{r.item_description || '—'}</span> },
    { key: 'total_gross_wt', label: 'Gross WT', render: (r) => <span className="whitespace-nowrap">{fmtWt(r.total_gross_wt)}</span> },
    { key: 'total_net_wt', label: 'Net WT', render: (r) => <span className="whitespace-nowrap font-semibold">{fmtWt(r.total_net_wt)}</span> },
  ]

  return (
    <div>
      <PageHeader
        title="Packaging List"
        subtitle="Box-wise packing weights for dispatches"
        actions={(
          <button onClick={openCreate} className="btn btn-primary"><Plus size={17} /> New Packing List</button>
        )}
      />

      {success && <div className="mb-4 p-3 rounded-lg bg-green-50 text-green-700 text-sm border border-green-200">{success}</div>}

      {draftSavedAt && !showForm && (
        <div className="mb-4 p-3 rounded-lg bg-amber-50 border border-amber-200 flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
          <div className="flex-1 text-sm text-amber-800">
            <span className="font-semibold">Unsaved draft found.</span>{' '}
            Last edited {new Date(draftSavedAt).toLocaleString()}. It was kept safe when the window was closed.
          </div>
          <div className="flex gap-2">
            <button onClick={() => setShowForm(true)} className="btn btn-sm btn-primary">Resume editing</button>
            <button onClick={discardDraft} className="btn btn-sm btn-secondary">Discard</button>
          </div>
        </div>
      )}

      <Card>
        <div className="mb-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by customer, item or list no…"
              className="input pl-9 pr-9 w-full"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                title="Clear search"
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-700"
              >
                <X size={16} />
              </button>
            )}
          </div>
          {!loading && (
            <p className="mt-2 text-xs text-slate-500">
              {search ? `${rows.length} result${rows.length === 1 ? '' : 's'}` : `${rows.length} packing list${rows.length === 1 ? '' : 's'}`}
              {' · '}Tap any row to open its weights.
            </p>
          )}
        </div>

        {loading ? <Loading /> : (
          <Table
            columns={columns}
            data={rows}
            onRowClick={(r) => openDetail(r)}
            empty={<Empty text={search ? 'No packing lists match your search' : 'No packing lists yet'} icon={Package} />}
          />
        )}
      </Card>

      {/* Create / Edit modal */}
      <Modal
        open={showForm}
        onClose={() => { setShowForm(false); setWarning(null) }}
        title={editing ? `Edit ${editing.list_no}` : 'New Packaging List'}
        subtitle="Record box-wise gross, less and net weights"
        wide
        footer={(
          <div className="flex flex-wrap items-center justify-between gap-2 w-full">
            <span className="text-xs text-slate-400">
              {draftSavedAt ? `Draft auto-saved ${new Date(draftSavedAt).toLocaleTimeString()}` : 'Changes are saved as a draft automatically'}
            </span>
            <div className="flex items-center gap-2 ml-auto">
              <button onClick={() => setShowForm(false)} className="btn btn-secondary">Cancel</button>
              <button onClick={() => doSave(false)} disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : (editing ? 'Update' : 'Save')}</button>
            </div>
          </div>
        )}
      >
        {errors.api && <div className="mb-3 p-2 rounded bg-red-50 text-red-600 text-sm">{errors.api}</div>}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
          <div>
            <label className="label">Date <span className="text-red-500">*</span></label>
            <input type="date" value={form.list_date} onChange={(e) => setForm({ ...form, list_date: e.target.value })} className="input w-full" />
          </div>
          <div>
            <label className="label">Default Less</label>
            <input
              type="number"
              step="0.001"
              min="0"
              value={form.less_default}
              onChange={(e) => setDefaultLess(e.target.value)}
              placeholder="e.g. 3.200"
              className="input w-full"
            />
          </div>
          <div>
            <label className="label">Customer <span className="text-red-500">*</span></label>
            <SearchSelect
              options={customerOptions}
              value={form.customer_id}
              initialLabel={form.customer_name}
              onChange={setCustomer}
              placeholder="Search or type customer…"
              className={`input w-full ${errors.customer ? 'border-red-300' : ''}`}
            />
            {errors.customer && <p className="text-red-500 text-xs mt-1">{errors.customer}</p>}
          </div>
          <div>
            <label className="label">Item / Product</label>
            <SearchSelect
              options={productOptions}
              value={form.product_id}
              initialLabel={form.item_description}
              onChange={setProduct}
              placeholder="Search product or type description…"
              className={`input w-full ${errors.item_description ? 'border-red-300' : ''}`}
              allowCustom
            />
            {errors.item_description && <p className="text-red-500 text-xs mt-1">{errors.item_description}</p>}
          </div>
        </div>

        <div className="flex items-center justify-between mb-2 gap-2 flex-wrap">
          <div>
            <h4 className="font-semibold text-slate-800 text-sm">Box Weights</h4>
            <p className="text-xs text-slate-500">Less follows Default Less automatically — Net WT = Gross WT − Less.</p>
          </div>
          <div className="flex items-end gap-2 flex-wrap">
            <div>
              <label htmlFor="box-count" className="label">Number of Boxes</label>
              <input
                id="box-count"
                type="number"
                step="1"
                min="1"
                inputMode="numeric"
                value={boxCount}
                onChange={(e) => { setBoxCount(e.target.value); setBoxCountError('') }}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addBoxes() } }}
                placeholder="e.g. 10"
                className={`input w-28 py-1.5 text-right ${boxCountError ? 'border-red-300' : ''}`}
              />
            </div>
            <button onClick={addBoxes} disabled={!boxCount} className="btn btn-sm btn-primary"><Plus size={14} /> Add Boxes</button>
            <button onClick={() => { pendingFocusRef.current = (form.lines || []).length; addLine() }} className="btn btn-sm btn-secondary"><Plus size={14} /> Add Box</button>
          </div>
        </div>
        {boxCountError && <p className="text-red-500 text-xs mb-2">{boxCountError}</p>}
        {errors.lines && <p className="text-red-500 text-xs mb-2">{errors.lines}</p>}

        <div className="overflow-x-auto border rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-slate-600 w-14">Sr.</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600">Gross WT</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600">Less</th>
                <th className="text-right px-3 py-2 font-medium text-slate-600">Net WT</th>
                <th className="px-3 py-2 w-10"></th>
              </tr>
            </thead>
            <tbody>
              {(form.lines || []).map((l, i) => (
                <tr key={i} className="border-t">
                  <td className="px-3 py-2 text-center text-slate-500">{i + 1}</td>
                  <td className="px-3 py-2">
                    <input
                      ref={(el) => { grossRefs.current[i] = el }}
                      type="number"
                      step="0.001"
                      min="0"
                      value={l.gross_wt}
                      onChange={(e) => updateLine(i, 'gross_wt', e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleLineEnter(i) } }}
                      placeholder="Gross"
                      className={`input w-full text-right font-medium ${errors[`line_${i}_gross`] ? 'border-red-300' : ''}`}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <input
                      ref={(el) => { lessRefs.current[i] = el }}
                      type="number"
                      step="0.001"
                      min="0"
                      value={l.less}
                      onChange={(e) => updateLine(i, 'less', e.target.value)}
                      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleLineEnter(i) } }}
                      title={l.lessTouched ? 'Custom less — will not change with Default Less' : 'Follows Default Less'}
                      className={`input w-full text-right ${l.lessTouched ? 'text-amber-700 bg-amber-50/40' : 'text-slate-600'} ${errors[`line_${i}_less`] ? 'border-red-300' : ''}`}
                    />
                  </td>
                  <td className="px-3 py-2 text-right font-semibold">{fmtWt(l.net_wt)}</td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => removeLine(i)} title="Remove box" className="text-slate-400 hover:text-red-500">
                      <X size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-gray-50 font-semibold">
              <tr className="border-t-2">
                <td className="px-3 py-2 text-left">TOTAL</td>
                <td className="px-3 py-2 text-right">{fmtWt(totals.gross)}</td>
                <td className="px-3 py-2 text-right">{fmtWt(totals.less)}</td>
                <td className="px-3 py-2 text-right">{fmtWt(totals.net)}</td>
                <td></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Modal>

      {/* Duplicate warning modal */}
      <Modal
        open={!!warning}
        onClose={cancelWarning}
        title="Possible duplicate"
        subtitle="A packaging list with the same date, customer and item already exists."
        footer={(
          <div className="flex items-center justify-end gap-2 w-full">
            <button onClick={cancelWarning} className="btn btn-secondary">Cancel</button>
            <button onClick={confirmWarning} className="btn btn-primary">Save anyway</button>
          </div>
        )}
      >
        {warning?.data?.existing?.map((ex) => (
          <div key={ex.id} className="p-3 border rounded-lg mb-2 text-sm">
            <div className="font-semibold">{ex.list_no}</div>
            <div className="text-slate-500">{ex.list_date} · {ex.customer_name} · {ex.item_description}</div>
          </div>
        ))}
      </Modal>

      {/* Detail modal */}
      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail?.list_no || 'Packaging List'}
        subtitle={detailLoading ? 'Loading…' : `${detail?.customer_name || '—'} · ${detail?.item_description || '—'}`}
        wide
        footer={detail?.loading ? null : (
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full sm:justify-end">
            <button onClick={shareList} className="btn btn-secondary justify-center flex-1 sm:flex-none"><Share2 size={16} /> Share</button>
            <button onClick={downloadJpg} className="btn btn-secondary justify-center flex-1 sm:flex-none"><Image size={16} /> JPG</button>
            <button onClick={downloadPdf} className="btn btn-primary justify-center flex-1 sm:flex-none"><Printer size={16} /> PDF</button>
          </div>
        )}
      >
        {detailLoading ? <Loading /> : detail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="px-2.5 py-1 rounded-full bg-gray-100 text-slate-600">Date <span className="font-semibold text-slate-800">{detail.list_date}</span></span>
                <span className="px-2.5 py-1 rounded-full bg-gray-100 text-slate-600">Default Less <span className="font-semibold text-slate-800">{fmtWt(detail.less_default)}</span></span>
                <span className="px-2.5 py-1 rounded-full bg-gray-100 text-slate-600">Boxes <span className="font-semibold text-slate-800">{(detail.lines || []).length}</span></span>
              </div>
              <div className="flex items-center gap-1.5">
                <button onClick={() => openEdit(detail)} className="btn btn-sm btn-secondary" title="Edit all weights"><Pencil size={14} /> Edit</button>
                <button onClick={() => duplicateRow(detail)} className="btn btn-sm btn-secondary" title="Duplicate this list"><Copy size={14} /> Duplicate</button>
                <button onClick={() => setShowDelete(detail)} className="btn btn-sm btn-secondary text-red-600" title="Delete this list"><Trash2 size={14} /></button>
              </div>
            </div>

            <div className="overflow-x-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium text-slate-600 w-14">Sr.</th>
                    <th className="text-right px-3 py-2 font-medium text-slate-600">Gross WT</th>
                    <th className="text-right px-3 py-2 font-medium text-slate-600">Less</th>
                    <th className="text-right px-3 py-2 font-medium text-slate-600">Net WT</th>
                    <th className="px-3 py-2 w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {(detail.lines || []).map((l) => (
                    <tr key={l.id} className="border-t hover:bg-gray-50">
                      <td className="px-3 py-2 text-center text-slate-500">{l.sr_no}</td>
                      <td className="px-3 py-2 text-right font-medium">{fmtWt(l.gross_wt)}</td>
                      <td className="px-3 py-2 text-right text-slate-600">{fmtWt(l.less)}</td>
<td className="px-3 py-2 text-right font-semibold">{l.gross_wt === '' || l.gross_wt == null ? '—' : fmtWt(l.net_wt)}</td>
                      <td className="px-3 py-2 text-right">
                        <button
                          onClick={() => deleteWeightInline(l)}
                          disabled={lineBusy}
                          title={`Remove box ${l.sr_no}`}
                          className="p-1 text-slate-400 hover:text-red-500 disabled:opacity-40"
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {(detail.lines || []).length === 0 && (
                    <tr className="border-t"><td colSpan={5} className="px-3 py-6 text-center text-slate-400 text-xs">No weights yet — add the first box below.</td></tr>
                  )}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 bg-gray-50 font-semibold">
                    <td className="px-3 py-2 text-center text-slate-500">Σ</td>
                    <td className="px-3 py-2 text-right">{fmtWt(detail.total_gross_wt)}</td>
                    <td className="px-3 py-2 text-right">{fmtWt(detail.total_less)}</td>
                    <td className="px-3 py-2 text-right">{fmtWt(detail.total_net_wt)}</td>
                    <td></td>
                  </tr>
                  <tr className="border-t border-dashed bg-slate-50/60">
                    <td className="px-3 py-2 text-slate-400 text-xs font-medium whitespace-nowrap">+ Add</td>
                    <td className="px-3 py-2">
                      <input
                        ref={addRowGrossRef}
                        type="number"
                        step="0.001"
                        min="0"
                        value={addRow.gross_wt}
                        onChange={(e) => setAddRow({ ...addRow, gross_wt: e.target.value })}
                        onKeyDown={(e) => { if (e.key === 'Enter') addWeightInline() }}
                        placeholder="Gross"
                        className="input w-full text-right py-1.5"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <input
                        type="number"
                        step="0.001"
                        min="0"
                        value={addRow.less}
                        onChange={(e) => setAddRow({ ...addRow, less: e.target.value })}
                        onKeyDown={(e) => { if (e.key === 'Enter') addWeightInline() }}
                        placeholder="Less"
                        className="input w-full text-right py-1.5"
                      />
                    </td>
                    <td className="px-3 py-2 text-right font-semibold text-slate-400">{addRow.gross_wt === '' || addRow.gross_wt == null ? '—' : fmtWt(addRowNet())}</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        onClick={addWeightInline}
                        disabled={lineBusy}
                        title="Add weight"
                        className="btn btn-sm btn-primary inline-flex items-center gap-1"
                      >
                        <Plus size={14} /> Add
                      </button>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <p className="text-xs text-slate-500">
              Add a box by typing its Gross WT — Less is pre-filled from Default Less and Net WT is calculated automatically.
            </p>
          </div>
        ) : <Empty text="Packaging list not found" />}
      </Modal>

      {/* Delete confirmation */}
      <Modal
        open={!!showDelete}
        onClose={() => setShowDelete(null)}
        title="Delete packaging list?"
        subtitle={`This will permanently delete ${showDelete?.list_no}.`}
        footer={(
          <div className="flex items-center justify-end gap-2 w-full">
            <button onClick={() => setShowDelete(null)} className="btn btn-secondary">Cancel</button>
            <button onClick={() => showDelete && deleteRow(showDelete)} className="btn btn-danger">Delete</button>
          </div>
        )}
      >
        <p className="text-sm text-slate-600">Deleted records cannot be recovered. No inventory or dispatch records will be affected.</p>
      </Modal>
    </div>
  )
}
