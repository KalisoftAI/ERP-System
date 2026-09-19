import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Plus, Pencil, RefreshCw, CalendarClock, CalendarDays, Factory, BarChart3, Trash2, Download,
} from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, Badge, PageTabs, StatCard, SearchSelect } from '../components/ui'
import Table from '../components/Table'
import { fmtNum, CompletionBar } from '../lib/format'

const TABS = [
  { key: 'production', label: 'Production', icon: <Factory size={15} /> },
  { key: 'schedule', label: 'Monthly Schedule', icon: <CalendarClock size={15} /> },
  { key: 'actual', label: 'Actual Production', icon: <CalendarDays size={15} /> },
  { key: 'report', label: 'Production Report', icon: <BarChart3 size={15} /> },
]

const today = () => new Date().toISOString().slice(0, 10)
const thisMonth = () => new Date().toISOString().slice(0, 7)
const monthBounds = (m) => {
  const [y, mo] = m.split('-').map(Number)
  const last = new Date(y, mo, 0).getDate()
  return [`${m}-01`, `${m}-${String(last).padStart(2, '0')}`]
}

export default function Production() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState('production')

  const [productionOrders, setProductionOrders] = useState([])
  const [plans, setPlans] = useState([])
  const [actual, setActual] = useState([])
  const [report, setReport] = useState(null)
  const [products, setProducts] = useState([])
  const [customers, setCustomers] = useState([])
  const [loading, setLoading] = useState(true)
  const [reportLoading, setReportLoading] = useState(false)

  const [scheduleMonth, setScheduleMonth] = useState(thisMonth)
  const [reportMonth, setReportMonth] = useState(thisMonth)
  const [actualFrom, setActualFrom] = useState('')
  const [actualTo, setActualTo] = useState('')
  const [actualProduct, setActualProduct] = useState('')

  const [showProdForm, setShowProdForm] = useState(false)
  const [prodForm, setProdForm] = useState({})
  const [showScheduleForm, setShowScheduleForm] = useState(false)
  const [schedForm, setSchedForm] = useState({})
  const [showActualForm, setShowActualForm] = useState(false)
  const [outputForm, setOutputForm] = useState({})
  const [showEditActual, setShowEditActual] = useState(false)
  const [editForm, setEditForm] = useState({})

  const loadProducts = () => api.get('/products', { params: { page_size: 500 } })
    .then((r) => setProducts(r.data.items || [])).catch(() => {})
  const loadCustomers = () => api.get('/customers', { params: { page_size: 500 } })
    .then((r) => setCustomers(r.data.items || [])).catch(() => {})

  const loadProductionOrders = () => api.get('/production', { params: { page_size: 500 } })
    .then((r) => setProductionOrders(r.data.items || [])).catch(() => setProductionOrders([]))

  const loadSchedules = (month = scheduleMonth) => {
    const [from, to] = monthBounds(month)
    return api.get('/plans', { params: { plan_type: 'PRODUCTION_PLAN', date_from: from, date_to: to, page_size: 500 } })
      .then((r) => setPlans(r.data.items || [])).catch(() => setPlans([]))
  }

  const loadActual = () => api.get('/production/actual', {
    params: {
      page_size: 1000,
      product_id: actualProduct || undefined,
      date_from: actualFrom || undefined,
      date_to: actualTo || undefined,
    },
  }).then((r) => setActual(r.data.items || [])).catch(() => setActual([]))

  const loadReport = (month = reportMonth) => {
    setReportLoading(true)
    return api.get('/reports/production/monthly', { params: { month } })
      .then((r) => setReport(r.data)).catch(() => setReport(null)).finally(() => setReportLoading(false))
  }

  const load = () => {
    setLoading(true)
    return Promise.all([loadProductionOrders(), loadSchedules(), loadActual()]).finally(() => setLoading(false))
  }

  useEffect(() => { load(); loadProducts(); loadCustomers() }, [])
  useEffect(() => { if (tab === 'schedule') loadSchedules() }, [tab, scheduleMonth])
  useEffect(() => { if (tab === 'actual') loadActual() }, [tab, actualFrom, actualTo, actualProduct])
  useEffect(() => { if (tab === 'report') loadReport() }, [tab, reportMonth])

  // "Go to Production" from a Local Order: open the monthly schedule modal,
  // pre-filled from the order (product + qty + customer), already linked back to
  // the order so completing the schedule flows the finished goods to that order
  // automatically (existing Local Order status automation — unchanged).
  useEffect(() => {
    const orderId = searchParams.get('order')
    if (!orderId) return
    api.get(`/local-orders/${orderId}`)
      .then((r) => {
        const o = r.data
        const line = (o.lines || [0])[0] || {}
        setSchedForm({
          product_id: line.product_id || null,
          model: line.model || line.description || '',
          customer_id: o.customer_id || null,
          customer_name: o.customer_name || o.customer || '',
          quantity: line.quantity,
          plan_month: today().slice(0, 7),
          status: 'PENDING',
          sales_order_id: o.id,
          remarks: `Local order ${o.order_no}`,
        })
        setTab('schedule')
        setShowScheduleForm(true)
        setSearchParams({}, { replace: true })
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const refreshAll = () => Promise.all([loadProductionOrders(), loadSchedules(), loadActual(), loadReport()])

  // ---- production order (schedule + date-wise actual) -----------------------
  const saveProduction = async () => {
    try {
      const askTill = prodForm.ask_till_date === '' || prodForm.ask_till_date == null
        ? null : Number(prodForm.ask_till_date)
      if (prodForm.id) {
        await api.patch(`/production/${prodForm.id}`, {
          schedule_qty: Number(prodForm.schedule_qty || 0),
          ask_till_date: askTill,
          customer_id: prodForm.customer_id || null,
          customer_name: prodForm.customer_name || '',
          section: prodForm.section || '',
          report_date: prodForm.report_date || undefined,
          remarks: prodForm.remarks || '',
          status: prodForm.status || 'Planned',
        })
      } else {
        const r = await api.post('/production', {
          product_id: prodForm.product_id || null,
          item_code: prodForm.item_code || '',
          model: prodForm.model || '',
          section: prodForm.section || '',
          schedule_qty: Number(prodForm.schedule_qty || 0),
          ask_till_date: askTill,
          customer_id: prodForm.customer_id || null,
          customer_name: prodForm.customer_name || '',
          report_date: prodForm.report_date || undefined,
          remarks: prodForm.remarks || '',
          status: 'Planned',
        })
        const qty = Number(prodForm.produced_qty || 0)
        if (qty > 0) {
          await api.post(`/production/${r.data.id}/movements`, null, {
            params: { quantity: qty, production_date: prodForm.production_date || today() },
          })
        }
      }
      setShowProdForm(false); setProdForm({})
      refreshAll()
    } catch (e) {
      alert('Save failed: ' + (e.response?.data?.detail || e.message))
    }
  }

  const removeProduction = (r) => {
    if (!window.confirm(`Delete production order ${r.order_no || r.id} for "${r.product?.model || ''}" and reverse its stock effect?`)) return
    api.delete(`/production/${r.id}`)
      .then(() => refreshAll())
      .catch((e) => alert('Delete failed: ' + (e.response?.data?.detail || e.message)))
  }

  // ---- monthly schedule (reuses the existing production Plan records) -------
  const saveSchedule = () => {
    const month = schedForm.plan_month || scheduleMonth
    const payload = {
      plan_type: 'PRODUCTION_PLAN', model: schedForm.model || '',
      product_id: schedForm.product_id || null, customer_id: schedForm.customer_id || null,
      customer_name: schedForm.customer_name || '',
      sales_order_id: schedForm.sales_order_id || null,
      quantity: schedForm.quantity != null && schedForm.quantity !== '' ? Number(schedForm.quantity) : null,
      owner: schedForm.owner || '', status: schedForm.status || 'PENDING',
      plan_date: `${month}-01`,
      remarks: schedForm.remarks || '',
    }
    if (schedForm.id) {
      api.patch(`/plans/${schedForm.id}`, payload)
        .then(() => { setShowScheduleForm(false); setSchedForm({}); loadSchedules() })
        .catch((e) => alert('Save failed: ' + (e.response?.data?.detail || e.message)))
      return
    }
    // Update the existing schedule for this product/month instead of creating a
    // duplicate planning record.
    const dup = plans.find((p) => {
      const same = schedForm.product_id
        ? p.product_id === schedForm.product_id
        : (p.model || '').toLowerCase() === (schedForm.model || '').toLowerCase()
      return same && (p.status || '').toUpperCase() !== 'COMPLETED'
    })
    if (dup && !window.confirm(`A schedule for "${dup.model || schedForm.model}" already exists in ${month}. Update it instead of creating a duplicate?`)) {
      return
    }
    const req = dup ? api.patch(`/plans/${dup.id}`, payload) : api.post('/plans', payload)
    req.then(() => { setShowScheduleForm(false); setSchedForm({}); loadSchedules() })
      .catch((e) => alert('Save failed: ' + (e.response?.data?.detail || e.message)))
  }

  const removePlan = (r) => {
    if (!window.confirm(`Delete schedule for "${r.model || (r.product?.model || '')}" (${r.plan_date})? This cannot be undone.`)) return
    api.delete(`/plans/${r.id}`)
      .then(() => loadSchedules())
      .catch((e) => alert('Delete failed: ' + (e.response?.data?.detail || e.message)))
  }

  const saveOutput = async () => {
    const q = Number(outputForm.quantity)
    if (!q || q <= 0) { alert('Quantity must be greater than 0'); return }
    try {
      await api.post(`/production/${outputForm.order_id}/movements`, null, {
        params: { quantity: q, production_date: outputForm.production_date },
      })
      setShowActualForm(false); setOutputForm({})
      refreshAll()
    } catch (e) {
      alert('Failed to record output: ' + (e.response?.data?.detail || e.message))
    }
  }

  const saveEditActual = async () => {
    const q = Number(editForm.quantity)
    if (!q || q <= 0) { alert('Quantity must be greater than 0'); return }
    try {
      await api.patch(`/production/movements/${editForm.id}`, null, {
        params: { quantity: q, production_date: editForm.production_date },
      })
      setShowEditActual(false); setEditForm({})
      refreshAll()
    } catch (e) {
      alert('Failed to edit output: ' + (e.response?.data?.detail || e.message))
    }
  }

  const productionCols = [
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.product?.item_code || '—'}</span> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.product?.model || '—'}</span> },
    { key: 'schedule_qty', label: 'Schedule', render: (r) => <span className="font-semibold tabular-nums">{fmtNum(r.schedule_qty)}</span> },
    { key: 'ask_till_date', label: 'Ask Till Date', render: (r) => <span className="tabular-nums">{r.ask_till_date != null ? fmtNum(r.ask_till_date) : '—'}</span> },
    { key: 'produced_qty', label: 'Production Qty', render: (r) => <span className="font-semibold text-green-700 tabular-nums">{fmtNum(r.produced_qty)}</span> },
    { key: 'completion_pct', label: '% Comp', render: (r) => <div className="min-w-32"><CompletionBar value={r.completion_pct} /></div> },
    { key: 'balance_qty', label: 'Balance Qty', render: (r) => <span className={`tabular-nums ${r.balance_qty < 0 ? 'text-red-600 font-semibold' : ''}`}>{fmtNum(r.balance_qty)}</span> },
    { key: 'status', label: 'Status', render: (r) => <Badge className={sc[r.status]} dot>{r.status}</Badge> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-0.5">
        <button onClick={() => {
          setProdForm({
            id: r.id, product_id: r.product_id, item_code: r.product?.item_code || '',
            model: r.product?.model || '', schedule_qty: r.schedule_qty,
            ask_till_date: r.ask_till_date, customer_id: r.customer_id,
            customer_name: r.customer?.name || '', section: r.section,
            report_date: r.report_date, remarks: r.remarks, status: r.status,
          })
          setShowProdForm(true)
        }} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit"><Pencil size={15} /></button>
        <button onClick={(e) => { e.stopPropagation(); removeProduction(r) }} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete"><Trash2 size={14} /></button>
      </div>
    )},
  ]

  const scheduleCols = [
    { key: 'plan_date', label: 'Date', render: (r) => r.plan_date || '—' },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.product?.item_code || '—'}</span> },
    { key: 'model', label: 'Model', render: (r) => r.model || r.product?.model || '—' },
    { key: 'quantity', label: 'Schedule', render: (r) => <span className="font-semibold tabular-nums">{fmtNum(r.quantity)}</span> },
    { key: 'status', label: 'Status', render: (r) => <Badge className={sc[r.status]} dot>{r.status}</Badge> },
    { key: 'remarks', label: 'Remarks', render: (r) => <span className="text-slate-500 text-xs">{r.remarks || '—'}</span> },
    { key: 'actions', label: '', render: (r) => (
      <div className="flex items-center gap-0.5">
        <button onClick={() => {
          setSchedForm({
            id: r.id, model: r.model, product_id: r.product_id, customer_id: r.customer_id,
            customer_name: r.customer?.name || '', sales_order_id: r.sales_order_id,
            quantity: r.quantity, owner: r.owner, status: r.status,
            plan_month: (r.plan_date || '').slice(0, 7) || scheduleMonth, remarks: r.remarks,
          })
          setShowScheduleForm(true)
        }} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit"><Pencil size={15} /></button>
        <button onClick={(e) => { e.stopPropagation(); removePlan(r) }} className="text-slate-400 hover:text-red-600 p-1 hover:bg-red-50 rounded" title="Delete"><Trash2 size={14} /></button>
      </div>
    )},
  ]

  const actualCols = [
    { key: 'production_date', label: 'Production Date', render: (r) => r.production_date || '—' },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.model || '—'}</span> },
    { key: 'quantity', label: 'Production Qty', render: (r) => <span className="font-semibold tabular-nums">{fmtNum(r.quantity)}</span> },
    { key: 'customer', label: 'Customer', render: (r) => r.customer || '—' },
    { key: 'ref', label: 'Reference', render: (r) => <span className="font-mono text-xs">{r.ref || '—'}</span> },
    { key: 'edit', label: '', render: (r) => (
      <button onClick={() => { setEditForm({ id: r.id, quantity: r.quantity, production_date: r.production_date }); setShowEditActual(true) }} className="text-slate-400 hover:text-slate-700 p-1 hover:bg-gray-100 rounded" title="Edit output"><Pencil size={14} /></button>
    )},
  ]

  const reportDailyCols = [
    { key: 'production_date', label: 'Date' },
    { key: 'quantity', label: 'Production Qty', render: (r) => <span className="font-semibold tabular-nums">{fmtNum(r.quantity)}</span> },
    { key: 'movements', label: 'Records', render: (r) => <span className="tabular-nums">{r.movements}</span> },
  ]

  const reportProductCols = [
    { key: 'model', label: 'Model', render: (r) => <span className="font-medium">{r.model || '—'}</span> },
    { key: 'item_code', label: 'Item Code', render: (r) => <span className="font-mono text-xs">{r.item_code || '—'}</span> },
    { key: 'quantity', label: 'Total Qty', render: (r) => <span className="font-semibold tabular-nums">{fmtNum(r.quantity)}</span> },
    { key: 'days', label: 'Days', render: (r) => <span className="tabular-nums">{r.days}</span> },
    { key: 'movements', label: 'Records', render: (r) => <span className="tabular-nums">{r.movements}</span> },
  ]

  const totalSchedule = productionOrders.reduce((s, p) => s + (Number(p.schedule_qty) || 0), 0)
  const totalProduced = productionOrders.reduce((s, p) => s + (Number(p.produced_qty) || 0), 0)
  const totalBalance = productionOrders.reduce((s, p) => s + (Number(p.balance_qty) || 0), 0)
  const completedOrders = productionOrders.filter((p) => (p.completion_pct || 0) >= 1).length
  const totalScheduledPlans = plans.reduce((s, p) => s + (Number(p.quantity) || 0), 0)
  const totalActual = actual.reduce((s, p) => s + (Number(p.quantity) || 0), 0)

  const renderTab = () => {
    if (tab === 'production') {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <StatCard label="Total Schedule" value={fmtNum(totalSchedule)} icon={CalendarClock} iconClass="bg-amber-50 text-amber-600" />
            <StatCard label="Total Production" value={fmtNum(totalProduced)} icon={Factory} iconClass="bg-green-50 text-green-600" valueClass="text-green-600" />
            <StatCard label="Balance" value={fmtNum(totalBalance)} icon={BarChart3} iconClass="bg-blue-50 text-blue-600" />
            <StatCard label="Completed" value={completedOrders} icon={Factory} iconClass="bg-violet-50 text-violet-600" />
          </div>
          <Card title="Production" subtitle="Schedule, production quantity, completion and balance by item"
            actions={<button onClick={() => { setProdForm({}); setShowProdForm(true) }} className="btn btn-primary"><Plus size={15} /> New Plan</button>}>
            {loading ? <Loading /> : productionOrders.length === 0
              ? <Empty text="No production plans found" />
              : <Table columns={productionCols} data={productionOrders} keyField="id" stickyColumns={['model']} />}
          </Card>
        </div>
      )
    }
    if (tab === 'schedule') {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <StatCard label="Scheduled Records" value={plans.length} icon={CalendarClock} iconClass="bg-amber-50 text-amber-600" />
            <StatCard label="Total Schedule Qty" value={fmtNum(totalScheduledPlans)} icon={Factory} iconClass="bg-violet-50 text-violet-600" />
            <StatCard label="Models" value={new Set(plans.map((p) => p.model || p.product?.model || '').filter(Boolean)).size} icon={Factory} iconClass="bg-blue-50 text-blue-600" />
          </div>
          <Card title="Monthly Production Schedule" subtitle="Product / model schedule for the selected month"
            actions={
              <div className="flex items-center gap-2 flex-wrap">
                <input type="month" value={scheduleMonth} onChange={(e) => setScheduleMonth(e.target.value)} className="input w-40" />
                <button onClick={() => { setSchedForm({ plan_month: scheduleMonth, status: 'PENDING' }); setShowScheduleForm(true) }} className="btn btn-primary"><Plus size={15} /> Add Schedule</button>
              </div>
            }>
            {loading ? <Loading /> : plans.length === 0
              ? <Empty text="No production schedule for this month" />
              : <Table columns={scheduleCols} data={plans} keyField="id" stickyColumns={['model']} />}
          </Card>
        </div>
      )
    }
    if (tab === 'actual') {
      return (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <StatCard label="Daily Records" value={actual.length} icon={CalendarDays} iconClass="bg-violet-50 text-violet-600" />
            <StatCard label="Total Actual Qty" value={fmtNum(totalActual)} icon={Factory} iconClass="bg-green-50 text-green-600" />
            <StatCard label="Days Tracked" value={new Set(actual.map((p) => p.production_date)).size} icon={CalendarClock} iconClass="bg-cyan-50 text-cyan-600" />
          </div>
          <Card title="Actual Production (date-wise)" subtitle="Daily production output per item — the actual production entry ledger"
            actions={
              <div className="flex items-center gap-2 flex-wrap">
                <select value={actualProduct} onChange={(e) => setActualProduct(e.target.value ? Number(e.target.value) : '')} className="input w-48">
                  <option value="">All products</option>
                  {products.map((p) => <option key={p.id} value={p.id}>{p.model}</option>)}
                </select>
                <input type="date" value={actualFrom} onChange={(e) => setActualFrom(e.target.value)} className="input w-40" />
                <input type="date" value={actualTo} onChange={(e) => setActualTo(e.target.value)} className="input w-40" />
                <button onClick={() => setShowActualForm(true)} className="btn btn-primary"><Plus size={15} /> Record Output</button>
              </div>
            }>
            {loading ? <Loading /> : actual.length === 0
              ? <Empty text="No actual output recorded" />
              : <Table columns={actualCols} data={actual} keyField="id" stickyColumns={['model']} />}
          </Card>
        </div>
      )
    }
    return (
      <div className="space-y-4">
        <Card title="Production Report" subtitle="Daily and monthly actual production output (DB-driven, from production movements)"
          actions={
            <div className="flex items-center gap-2 flex-wrap">
              <input type="month" value={reportMonth} onChange={(e) => setReportMonth(e.target.value)} className="input w-40" />
              <button onClick={() => downloadFile(reportMonth ? `/reports/production/monthly/csv?month=${reportMonth}` : '/reports/production/monthly/csv', 'monthly_production.csv')} className="btn btn-secondary"><Download size={15} /> CSV</button>
            </div>
          }>
          {reportLoading || !report ? <Loading /> : (
            <>
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                <StatCard label="Monthly Total" value={fmtNum(report.totals.quantity)} icon={Factory} iconClass="bg-violet-50 text-violet-600" />
                <StatCard label="Production Days" value={report.totals.days} icon={CalendarDays} iconClass="bg-green-50 text-green-600" />
                <StatCard label="Products" value={report.totals.products} icon={Factory} iconClass="bg-blue-50 text-blue-600" />
                <StatCard label="Output Records" value={report.totals.movements} icon={BarChart3} iconClass="bg-amber-50 text-amber-600" />
              </div>
              {report.items.length === 0 ? <Empty text="No actual production recorded for this month" /> : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div>
                    <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Daily Total</div>
                    <Table columns={reportDailyCols} data={report.by_date} keyField="production_date" dense />
                  </div>
                  <div>
                    <div className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Item / Model Total</div>
                    <Table columns={reportProductCols} data={report.by_product} keyField="product_id" dense />
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    )
  }

  return (
    <div className="animate-fade-in-up">
      <PageHeader title="Production" subtitle="Production schedule, date-wise actual output and monthly production report"
        actions={
          <button onClick={refreshAll} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>
        } />

      <PageTabs tabs={TABS} active={tab} onChange={setTab} />

      {renderTab()}

      {/* Production plan create/edit modal (schedule + date-wise quantity) */}
      <Modal open={showProdForm} title={prodForm.id ? 'Edit Production Plan' : 'New Production Plan'}
        subtitle="Schedule quantity and date-wise production quantity for an item"
        onClose={() => setShowProdForm(false)} wide
        footer={<>
          <button onClick={() => setShowProdForm(false)} className="btn btn-secondary">Cancel</button>
          <button onClick={saveProduction} className="btn btn-primary">Save Plan</button>
        </>}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <div><label className="block text-slate-500 text-xs mb-1">Item Code</label>
            <input value={prodForm.item_code || ''} disabled={!!prodForm.id} onChange={(e) => setProdForm({ ...prodForm, item_code: e.target.value })} className="input disabled:bg-slate-50 disabled:text-slate-500" placeholder="e.g. SF-100" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Model</label>
            {prodForm.id ? (
              <input value={prodForm.model || ''} disabled className="input disabled:bg-slate-50 disabled:text-slate-500" />
            ) : (
              <SearchSelect
                options={products.map((p) => ({ id: p.id, label: p.model }))}
                value={prodForm.product_id}
                initialLabel={!prodForm.product_id ? (prodForm.model || '') : ''}
                placeholder="Type to search or enter a model"
                onChange={(id, manual) => {
                  if (id) { const mm = products.find((p) => p.id === id); setProdForm((f) => ({ ...f, product_id: id, model: mm?.model || '', item_code: f.item_code || mm?.item_code || '' })) }
                  else setProdForm((f) => ({ ...f, product_id: null, model: manual }))
                }}
              />
            )}</div>
          <div><label className="block text-slate-500 text-xs mb-1">Schedule Quantity</label>
            <input type="number" min="0" value={prodForm.schedule_qty ?? ''} onChange={(e) => setProdForm({ ...prodForm, schedule_qty: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Ask Till Date</label>
            <input type="number" min="0" value={prodForm.ask_till_date ?? ''} onChange={(e) => setProdForm({ ...prodForm, ask_till_date: e.target.value })} className="input" /></div>
          {!prodForm.id && (
            <>
              <div><label className="block text-slate-500 text-xs mb-1">Production Quantity</label>
                <input type="number" min="0" value={prodForm.produced_qty ?? ''} onChange={(e) => setProdForm({ ...prodForm, produced_qty: e.target.value })} className="input" /></div>
              <div><label className="block text-slate-500 text-xs mb-1">Production Date</label>
                <input type="date" value={prodForm.production_date || today()} onChange={(e) => setProdForm({ ...prodForm, production_date: e.target.value })} className="input" /></div>
            </>
          )}
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Customer</label>
            <SearchSelect
              options={customers.map((c) => ({ id: c.id, label: c.name }))}
              value={prodForm.customer_id}
              initialLabel={!prodForm.customer_id ? (prodForm.customer_name || '') : ''}
              placeholder="Type to search or enter a customer name — new customers are auto-created"
              onChange={(id, manual) => setProdForm((f) => ({ ...f, customer_id: id, customer_name: manual }))}
            /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Section</label>
            <input value={prodForm.section || ''} onChange={(e) => setProdForm({ ...prodForm, section: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Report Date</label>
            <input type="date" value={prodForm.report_date || ''} onChange={(e) => setProdForm({ ...prodForm, report_date: e.target.value })} className="input" /></div>
          {prodForm.id && (
            <div><label className="block text-slate-500 text-xs mb-1">Status</label>
              <select value={prodForm.status || 'Planned'} onChange={(e) => setProdForm({ ...prodForm, status: e.target.value })} className="input">
                <option>Planned</option><option>In Production</option><option>Completed</option><option>Cancelled</option>
              </select></div>
          )}
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Remarks</label>
            <textarea value={prodForm.remarks || ''} onChange={(e) => setProdForm({ ...prodForm, remarks: e.target.value })} className="input" rows={2} /></div>
          <div className="sm:col-span-2 text-xs text-slate-400">Production Quantity is recorded as date-wise actual output (production movement); completion % and balance update automatically.</div>
        </div>
      </Modal>

      {/* Monthly schedule modal (Plan) */}
      <Modal open={showScheduleForm} title={schedForm.id ? 'Edit Monthly Schedule' : 'Add Monthly Schedule'}
        subtitle="Product / model monthly schedule — reuses the production plan records"
        onClose={() => setShowScheduleForm(false)} wide
        footer={<>
          <button onClick={() => setShowScheduleForm(false)} className="btn btn-secondary">Cancel</button>
          <button onClick={saveSchedule} className="btn btn-primary">Save Schedule</button>
        </>}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Model</label>
            <SearchSelect
              options={products.map((p) => ({ id: p.id, label: p.model }))}
              value={schedForm.product_id}
              initialLabel={!schedForm.product_id ? (schedForm.model || '') : ''}
              placeholder="Type to search or enter a product — existing products match automatically"
              onChange={(id, manual) => {
                if (id) { const mm = products.find((p) => p.id === id); setSchedForm((f) => ({ ...f, product_id: id, model: mm?.model || '' })) }
                else setSchedForm((f) => ({ ...f, product_id: null, model: manual }))
              }}
            /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Schedule Month</label>
            <input type="month" value={schedForm.plan_month || scheduleMonth} onChange={(e) => setSchedForm({ ...schedForm, plan_month: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Schedule Quantity</label>
            <input type="number" min="0" value={schedForm.quantity ?? ''} onChange={(e) => setSchedForm({ ...schedForm, quantity: e.target.value })} className="input" /></div>
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Customer</label>
            <SearchSelect
              options={customers.map((c) => ({ id: c.id, label: c.name }))}
              value={schedForm.customer_id}
              initialLabel={!schedForm.customer_id ? (schedForm.customer_name || '') : ''}
              placeholder="Type to search or enter a customer name — new customers are auto-created"
              onChange={(id, manual) => setSchedForm((f) => ({ ...f, customer_id: id, customer_name: manual }))}
            /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Owner / Salesperson</label>
            <input value={schedForm.owner || ''} onChange={(e) => setSchedForm({ ...schedForm, owner: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Status</label>
            <select value={schedForm.status || 'PENDING'} onChange={(e) => setSchedForm({ ...schedForm, status: e.target.value })} className="input">
              <option>PENDING</option><option>IN_PROCESS</option><option>COMPLETED</option>
            </select></div>
          <div className="sm:col-span-2"><label className="block text-slate-500 text-xs mb-1">Remarks</label>
            <textarea value={schedForm.remarks || ''} onChange={(e) => setSchedForm({ ...schedForm, remarks: e.target.value })} className="input" rows={2} /></div>
        </div>
      </Modal>

      {/* Actual record modal */}
      <Modal open={showActualForm} title="Record Daily Production Output" onClose={() => setShowActualForm(false)}
        footer={<>
          <button onClick={() => setShowActualForm(false)} className="btn btn-secondary">Cancel</button>
          <button onClick={saveOutput} className="btn btn-primary">Save Output</button>
        </>}>
        <div className="grid grid-cols-1 gap-3 text-sm">
          <div><label className="block text-slate-500 text-xs mb-1">Production Order (ref)</label>
            <select value={outputForm.order_id ?? ''} onChange={(e) => setOutputForm({ ...outputForm, order_id: e.target.value ? Number(e.target.value) : null })} className="input">
              <option value="">Select production order…</option>
              {productionOrders.map((p) => <option key={p.id} value={p.id}>{p.product?.item_code ? `${p.product.item_code} — ` : ''}{p.product?.model || p.order_no} (schedule {fmtNum(p.schedule_qty)})</option>)}
            </select></div>
          <div><label className="block text-slate-500 text-xs mb-1">Production Quantity</label>
            <input type="number" min="0" value={outputForm.quantity ?? ''} onChange={(e) => setOutputForm({ ...outputForm, quantity: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Production Date</label>
            <input type="date" value={outputForm.production_date || today()} onChange={(e) => setOutputForm({ ...outputForm, production_date: e.target.value })} className="input" /></div>
        </div>
      </Modal>

      {/* Actual edit modal */}
      <Modal open={showEditActual} title="Edit Daily Production Output" onClose={() => setShowEditActual(false)}
        footer={<>
          <button onClick={() => setShowEditActual(false)} className="btn btn-secondary">Cancel</button>
          <button onClick={saveEditActual} className="btn btn-primary">Save Edit</button>
        </>}>
        <div className="grid grid-cols-1 gap-3 text-sm">
          <div><label className="block text-slate-500 text-xs mb-1">Quantity</label>
            <input type="number" min="0" value={editForm.quantity ?? ''} onChange={(e) => setEditForm({ ...editForm, quantity: e.target.value })} className="input" /></div>
          <div><label className="block text-slate-500 text-xs mb-1">Production Date</label>
            <input type="date" value={editForm.production_date || ''} onChange={(e) => setEditForm({ ...editForm, production_date: e.target.value })} className="input" /></div>
        </div>
      </Modal>
    </div>
  )
}

const sc = {
  PENDING: 'bg-amber-100 text-amber-700',
  IN_PROCESS: 'bg-blue-100 text-blue-700',
  'In Process': 'bg-blue-100 text-blue-700',
  COMPLETED: 'bg-green-100 text-green-700',
  Completed: 'bg-green-100 text-green-700',
  Planned: 'bg-slate-100 text-slate-600',
  'In Production': 'bg-blue-100 text-blue-700',
  Cancelled: 'bg-red-100 text-red-600',
}
