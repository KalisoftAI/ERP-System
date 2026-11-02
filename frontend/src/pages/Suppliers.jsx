import { useEffect, useState } from 'react'
import { Plus, Pencil, Trash2, Download, Search, Truck, Package, Eye } from 'lucide-react'
import api, { downloadFile } from '../lib/api'
import { PageHeader, Card, Modal, Loading, Empty, StatCard } from '../components/ui'
import Table from '../components/Table'

const empty = { name: '', code: '', company: '', contact_person: '', phone: '', email: '', address: '', gstin: '', materials: '', notes: '' }

export default function Suppliers() {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(empty)
  const [saving, setSaving] = useState(false)
  const [detail, setDetail] = useState(null)
  const [history, setHistory] = useState({ products: [], history: [] })
  const [historyLoading, setHistoryLoading] = useState(false)

  const load = () => {
    setLoading(true)
    api
      .get('/suppliers', { params: { search } })
      .then((res) => setItems(res.data.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])
  useEffect(() => {
    const t = setTimeout(load, 300)
    return () => clearTimeout(t)
  }, [search])

  const openCreate = () => {
    setForm(empty)
    setModal('create')
  }
  const openEdit = (row) => {
    setForm({ ...empty, ...row })
    setModal('edit')
  }
  const openDetail = (row) => {
    setDetail(row)
    setHistory({ products: [], history: [] })
    setHistoryLoading(true)
    api.get(`/suppliers/${row.id}/purchase-history`)
      .then((r) => setHistory(r.data || { products: [], history: [] }))
      .catch(() => setHistory({ products: [], history: [] }))
      .finally(() => setHistoryLoading(false))
  }
  const remove = async (row) => {
    if (!window.confirm(`Delete supplier "${row.name}"?`)) return
    try {
      await api.delete(`/suppliers/${row.id}`)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Delete failed')
    }
  }
  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      if (modal === 'create') await api.post('/suppliers', form)
      else await api.patch(`/suppliers/${form.id}`, form)
      setModal(null)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const columns = [
    { key: 'name', label: 'Name', render: (r) => <span className="font-medium">{r.name}</span> },
    { key: 'code', label: 'Code', render: (r) => <span className="font-mono text-xs">{r.code || '—'}</span> },
    { key: 'contact_person', label: 'Contact', render: (r) => r.contact_person || '—' },
    { key: 'email', label: 'Email', render: (r) => r.email || '—' },
    { key: 'phone', label: 'Phone', render: (r) => <span className="font-mono text-xs">{r.phone || '—'}</span> },
    {
      key: 'actions', label: '',
      render: (r) => (
        <div className="flex gap-1.5">
          <button onClick={() => openDetail(r)} className="btn btn-ghost p-1.5" title="View"><Eye size={15} /></button>
          <button onClick={() => openEdit(r)} className="btn btn-ghost p-1.5" title="Edit"><Pencil size={15} /></button>
          <button onClick={() => remove(r)} className="btn btn-ghost p-1.5 text-red-400" title="Delete"><Trash2 size={15} /></button>
        </div>
      ),
    },
  ]

  const field = (label, key, props = {}) => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{label}</label>
      <input
        value={form[key] ?? ''}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="input"
        {...props}
      />
    </div>
  )

  return (
    <div className="animate-fade-in-up">
      <PageHeader
        title="Suppliers"
        subtitle={`${items.length} suppliers`}
        actions={
          <>
            <button onClick={() => downloadFile('/reports/suppliers/csv', 'suppliers.csv')} className="btn btn-secondary"><Download size={15} /> CSV</button>
            <button onClick={openCreate} className="btn btn-primary"><Plus size={15} /> Add Supplier</button>
          </>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-5">
        <StatCard label="Suppliers" value={items.length} icon={Truck} iconClass="bg-amber-50 text-amber-600" />
        <StatCard label="With Contact" value={items.filter((r) => r.contact_person).length} icon={Package} iconClass="bg-blue-50 text-blue-600" />
        <StatCard label="With GSTIN" value={items.filter((r) => r.gstin).length} icon={Package} iconClass="bg-violet-50 text-violet-600" />
      </div>

      <Card
        actions={
          <div className="relative">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search supplier…"
              className="input input-icon sm:w-60"
            />
          </div>
        }
      >
        {loading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty text="No suppliers yet — add your first supplier or link purchase orders." />
        ) : (
          <Table columns={columns} data={items} keyField="id" stickyColumns={['name']} dense />
        )}
      </Card>

      {modal && (
        <Modal open title={modal === 'create' ? 'Add Supplier' : 'Edit Supplier'} onClose={() => setModal(null)} wide
          footer={<>
            <button type="button" onClick={() => setModal(null)} className="btn btn-secondary">Cancel</button>
            <button type="submit" form="supplier-form" disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : 'Save'}</button>
          </>}>
          <form onSubmit={save} id="supplier-form" className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {field('Name *', 'name', { required: true })}
            {field('Code', 'code')}
            {field('Company', 'company')}
            {field('Contact Person', 'contact_person')}
            {field('Phone', 'phone')}
            {field('Email', 'email')}
            {field('GSTIN', 'gstin')}
            <div className="md:col-span-2">{field('Materials Supplied', 'materials')}</div>
            <div className="md:col-span-2">{field('Address', 'address')}</div>
          </form>
        </Modal>
      )}

      {detail && (
        <Modal open title={detail.name} onClose={() => setDetail(null)} wide
          footer={<button onClick={() => setDetail(null)} className="btn btn-secondary">Close</button>}>
          {historyLoading ? <Loading /> : (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div><span className="text-slate-500 block text-xs">Name</span><span className="font-medium">{detail.name || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">GST No.</span><span className="font-medium">{detail.gstin || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">Mobile</span><span className="font-medium">{detail.phone || '—'}</span></div>
                <div><span className="text-slate-500 block text-xs">Email</span><span className="font-medium">{detail.email || '—'}</span></div>
                <div className="col-span-2 md:col-span-4"><span className="text-slate-500 block text-xs">Address</span><span className="font-medium">{detail.address || '—'}</span></div>
              </div>
              <div>
                <h4 className="font-medium mb-2">Products Purchased</h4>
                {history.products.length === 0 ? (
                  <Empty text="No purchase history found" />
                ) : (
                  <div className="flex flex-wrap gap-2 mb-3">
                    {history.products.map((p) => (
                      <span key={p.name} className="inline-flex items-center px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 text-xs font-medium border border-blue-100">
                        {p.name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {history.history.length > 0 && (
                <div>
                  <h4 className="font-medium mb-2">Purchase History</h4>
                  <Table
                    columns={[
                      { key: 'po_number', label: 'PO No', render: (r) => <span className="font-mono text-xs">{r.po_number}</span> },
                      { key: 'order_date', label: 'Date' },
                      { key: 'product_name', label: 'Product' },
                      { key: 'quantity', label: 'Qty', render: (r) => `${r.quantity} ${r.uom}` },
                      { key: 'rate', label: 'Rate', render: (r) => r.rate != null ? r.rate : '—' },
                      { key: 'amount', label: 'Total', render: (r) => r.amount != null ? r.amount : '—' },
                    ]}
                    data={history.history}
                    keyField="po_number"
                    dense
                  />
                </div>
              )}
            </div>
          )}
        </Modal>
      )}
    </div>
  )
}
