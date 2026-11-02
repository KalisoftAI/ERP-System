import { useRef, useState } from 'react'
import { Plus, Trash2, Paperclip } from 'lucide-react'
import api from '../lib/api'
import { Modal } from './ui'
import { fmtNum } from '../lib/format'

export const UOMS = [
  'Nos', 'Kg', 'Box', 'Ton', 'Roll', 'Meter', 'Litre', 'ML', 'Gram',
  'Packet', 'Set', 'Piece', 'Bag', 'Drum', 'Bundle', 'Pair', 'Dozen', 'Sq.Mtr',
]

export function emptyLine() {
  return {
    _key: Math.random().toString(36).slice(2),
    id: null, entry_mode: 'MANUAL', material_id: null, plant_id: null, location: 'Main Store',
    material_code: '',
    description: '', specification: '', quantity: '', uom: '', remarks: '',
    available_stock: null, reserved_stock: null, incoming_qty: null, suggested_qty: null,
    stock_override: '', attachment_name: '', has_attachment: false,
    _uomTouched: false,
  }
}

export function lineFromApi(l) {
  return {
    _key: 'l' + (l.id ?? Math.random().toString(36).slice(2)),
    id: l.id, entry_mode: l.entry_mode, material_id: l.material_id,
    plant_id: l.plant_id ?? null, location: l.location || 'Main Store',
    material_code: l.material_code || '', description: l.description || '',
    specification: l.specification || '', quantity: l.quantity, uom: l.uom || '',
    remarks: l.remarks || '', available_stock: l.available_stock,
    stock_override: l.stock_override == null ? '' : l.stock_override,
    reserved_stock: l.reserved_stock, incoming_qty: l.incoming_qty,
    suggested_qty: l.suggested_qty, attachment_name: l.attachment_name,
    has_attachment: l.has_attachment,
    stock_overridden_by_name: l.stock_overridden_by_name || '',
    _uomTouched: false,
  }
}

const today = () => new Date().toISOString().slice(0, 10)

export function newPrnDraft(currentUser) {
  return {
    company_name: 'Kalika Enterprises', department: '', department_head: '',
    requested_by_name: currentUser?.full_name || currentUser?.username || '',
    prn_date: today(), required_by_date: '', priority: 'Normal',
    requirement_type: 'Production', purpose: '', production_reference: '',
    checked_by_name: '', purchase_remarks: '',
    lines: [emptyLine()],
  }
}

export default function PrnEditorModal({ editor, setEditor, meta, departments, materials, locations = [], currentUser, onSaved }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const prn = editor.prn
  const set = (patch) => setEditor((e) => ({ ...e, prn: { ...e.prn, ...patch } }))

  // Always map over the LATEST lines (functional update). A line patch was
  // previously built from a stale `prn.lines` closure, so the async stock
  // lookup would land later and wipe the description/UOM/material_id just set
  // by applyMaterial (fields "filled then vanished").
  const setLine = (key, patch) => setEditor((e) => ({
    ...e,
    prn: { ...e.prn, lines: e.prn.lines.map((l) => (l._key === key ? { ...l, ...patch } : l)) },
  }))
  const addLine = () => setEditor((e) => ({ ...e, prn: { ...e.prn, lines: [...e.prn.lines, emptyLine()] } }))
  const removeLine = (key) => setEditor((e) => ({ ...e, prn: { ...e.prn, lines: e.prn.lines.filter((l) => l._key !== key) } }))

// Per-line lookup sequence: bumped on every material change so a slow
  // in-flight response for a previous selection can never overwrite the current one.
  const seqRef = useRef({})

  const stockFor = async (key, id, qty, plantId = null) => {
    const seq = seqRef.current[key] ?? 0
    try {
      const { data } = await api.get('/prn/stock-lookup', {
        params: { material_id: id, required_qty: qty || undefined, plant_id: plantId ?? undefined },
      })
      if (seqRef.current[key] !== seq) return // stale — code changed meanwhile
      setLine(key, { available_stock: data.available_stock, reserved_stock: data.reserved_stock,
                     incoming_qty: data.incoming_qty, suggested_qty: data.suggested_qty,
                     plant_id: data.plant_id ?? null, location: data.location || 'Main Store' })
    } catch { /* stock unknown — leave blank, never assume zero */ }
  }

  const findLocal = (value) => {
    const v = value.trim().toLowerCase()
    return materials.find((x) => (x.item_code || '').toLowerCase() === v
      || (x.model || '').toLowerCase() === v || (x.name || '').toLowerCase() === v
      || x.label.toLowerCase() === v)
  }

  const applyMaterial = (key, m) => {
    const line = prn.lines.find((l) => l._key === key)
    const plantId = line?.plant_id ?? null
    // Fill description/stock from the material, but never clobber a UOM the user
    // picked by hand: the async code lookup can land after the pick and used to
    // overwrite (blank) the selection, so the field looked like it never changed.
    setEditor((e) => ({
      ...e,
      prn: {
        ...e.prn,
        lines: e.prn.lines.map((l) => (l._key === key ? {
          ...l, material_id: m.id, entry_mode: 'EXISTING', material_code: m.item_code || m.model || '',
          description: m.name || m.model, uom: l._uomTouched ? l.uom : (m.uom || ''),
        } : l)),
      },
    }))
    stockFor(key, m.id, line?.quantity, plantId)
  }

  // Change the inventory location for a line: the stock snapshot is re-read for
  // the selected location (locations are never summed).
  const setLocation = (key, value) => {
    seqRef.current[key] = (seqRef.current[key] ?? 0) + 1
    const plantId = value === '' ? null : Number(value)
    const loc = locations.find((x) => String(x.id ?? '') === value)
    const line = prn.lines.find((l) => l._key === key)
    setLine(key, { plant_id: plantId, location: loc?.name || 'Main Store' })
    if (line?.material_id) stockFor(key, line.material_id, line.quantity, plantId)
  }

  // Item Code cell: matches a master material by item_code or model; anything else
  // is a manual (Item Master Review Required) line. Matched lines stay EXISTING.
  // Typing/Backspace only stores the raw value — applying mid-edit made the code
  // jump to another item. The material loads only on blur (exact code confirmed)
  // or when a datalist option is deliberately picked. Clearing the code clears
  // the fields that material filled.
  const onCode = (key, value, deliberate = false) => {
    seqRef.current[key] = (seqRef.current[key] ?? 0) + 1
    if (!value.trim()) {
      setLine(key, { material_id: null, entry_mode: 'MANUAL', material_code: value,
        description: '', uom: '', _uomTouched: false,
        available_stock: null, reserved_stock: null, incoming_qty: null, suggested_qty: null })
      return
    }
    const m = deliberate && findLocal(value)
    if (m) applyMaterial(key, m)
    else setLine(key, { material_id: null, entry_mode: 'MANUAL', material_code: value })
  }

  // On blur, confirm the code: apply an exact local match (unless the line
  // already points at that material, so hand-edits aren't clobbered), else fall
  // back to a server lookup so a code outside the first page of the master still
  // resolves to its material (and therefore its stock).
  const resolveCode = async (key, value) => {
    if (!value.trim()) return
    const local = findLocal(value)
    if (local) {
      const line = prn.lines.find((l) => l._key === key)
      if (line?.material_id !== local.id) applyMaterial(key, local)
      return
    }
    const v = value.trim().toLowerCase()
    if (v.length < 2) return
    const seq = seqRef.current[key] ?? 0
    try {
      const { data } = await api.get('/prn/materials', { params: { search: value, limit: 20 } })
      if (seqRef.current[key] !== seq) return // stale — code changed meanwhile
      const m = (data || []).find((x) => (x.item_code || '').toLowerCase() === v
        || (x.model || '').toLowerCase() === v || (x.name || '').toLowerCase() === v)
      if (m) applyMaterial(key, m)
    } catch { /* left as manual */ }
  }

  const onMaterialDesc = (key, value) => {
    seqRef.current[key] = (seqRef.current[key] ?? 0) + 1
    if (!value.trim()) {
      setLine(key, { material_id: null, entry_mode: 'MANUAL', material_code: '',
        description: '', uom: '', _uomTouched: false,
        available_stock: null, reserved_stock: null, incoming_qty: null, suggested_qty: null })
      return
    }
    const m = findLocal(value)
    if (m) applyMaterial(key, m)
    else setLine(key, { material_id: null, entry_mode: 'MANUAL', material_code: '',
      description: value, uom: '', _uomTouched: false,
      available_stock: null, reserved_stock: null, incoming_qty: null, suggested_qty: null })
  }

  const resolveMaterialDesc = async (key, value) => {
    if (!value.trim()) return
    const local = findLocal(value)
    if (local) {
      const line = prn.lines.find((l) => l._key === key)
      if (line?.material_id !== local.id) applyMaterial(key, local)
      return
    }
    const v = value.trim().toLowerCase()
    if (v.length < 2) return
    const seq = seqRef.current[key] ?? 0
    try {
      const { data } = await api.get('/prn/materials', { params: { search: value, limit: 20 } })
      if (seqRef.current[key] !== seq) return // stale — code changed meanwhile
      const m = (data || []).find((x) => (x.item_code || '').toLowerCase() === v
        || (x.model || '').toLowerCase() === v || (x.name || '').toLowerCase() === v)
      if (m) applyMaterial(key, m)
    } catch { /* left as manual */ }
  }

  const uploadFor = async (lineId, file) => {
    const fd = new FormData()
    fd.append('file', file)
    try {
      await api.post(`/prn/${prn.id}/lines/${lineId}/attachment`, fd)
      const { data } = await api.get(`/prn/${prn.id}`)
      set({ lines: (data.lines || []).map(lineFromApi) })
    } catch (err) { setError('Upload failed: ' + (err.response?.data?.detail || err.message)) }
  }

  const payload = () => ({
    prn_date: prn.prn_date || null,
    department: prn.department || '',
    department_head: prn.department_head || '',
    company_name: prn.company_name || '',
    requested_by_name: prn.requested_by_name || '',
    required_by_date: prn.required_by_date || null,
    priority: prn.priority,
    requirement_type: prn.requirement_type,
    purpose: prn.purpose || '',
    production_reference: prn.production_reference || '',
    checked_by_name: prn.checked_by_name || '',
    purchase_remarks: prn.purchase_remarks || '',
    lines: prn.lines.map((l) => ({
      id: l.id || undefined,
      entry_mode: l.material_id ? 'EXISTING' : 'MANUAL',
      material_id: l.material_id || undefined,
      plant_id: l.material_id ? (l.plant_id ?? null) : undefined,
      material_code: l.material_code || '',
      description: l.description || '',
      specification: l.specification || '',
      quantity: Number(l.quantity) || 0,
      uom: l.uom || '',
      remarks: l.remarks || '',
      stock_override: l.stock_override === '' || l.stock_override == null ? null : Number(l.stock_override),
    })),
  })

  const save = async () => {
    setError('')
    if (prn.lines.length === 0) { setError('Add at least one material line.'); return }
    const bad = prn.lines.find((l) => !String(l.description || '').trim() || !(Number(l.quantity) > 0))
    if (bad) { setError('Each line needs a material description and a required quantity greater than zero.'); return }
    if (prn.prn_date && prn.required_by_date && prn.required_by_date < prn.prn_date) {
      setError('Required By Date cannot be earlier than the PRN Date.'); return
    }
    setSaving(true)
    try {
      if (editor.mode === 'new') await api.post('/prn', payload())
      else await api.patch(`/prn/${prn.id}`, payload())
      onSaved()
    } catch (err) {
      const d = err.response?.data?.detail
      setError(Array.isArray(d) ? d.map((x) => x.msg).join('; ') : (d || err.message))
    } finally { setSaving(false) }
  }

  const title = editor.mode === 'new' ? 'New PRN' : `Edit ${prn.prn_number}`

  return (
    <Modal open wide title={title} subtitle="Purchase Requisition Note" onClose={() => setEditor(null)}
      footer={<>
        {error && <span className="text-red-600 text-sm mr-auto">{error}</span>}
        <button onClick={() => setEditor(null)} className="btn btn-secondary">Cancel</button>
        <button onClick={save} disabled={saving} className="btn btn-primary">{saving ? 'Saving…' : 'Save Draft'}</button>
      </>}>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        <label className="text-xs">Company Name
          <input value={prn.company_name || ''} onChange={(e) => set({ company_name: e.target.value })} className="input w-full mt-1" />
        </label>
        <label className="text-xs">PRN No.
          <input value={prn.prn_number || '(auto on save)'} readOnly className="input w-full mt-1 bg-slate-50 font-mono" />
        </label>
        <label className="text-xs">PRN Date
          <input type="date" value={prn.prn_date || ''} onChange={(e) => set({ prn_date: e.target.value })} className="input w-full mt-1" />
        </label>
        <label className="text-xs">Department
          <input list="prn-depts" value={prn.department} onChange={(e) => set({ department: e.target.value })} className="input w-full mt-1" />
          <datalist id="prn-depts">{departments.map((d) => <option key={d} value={d} />)}</datalist>
        </label>
        <label className="text-xs">Department Head
          <input value={prn.department_head || ''} onChange={(e) => set({ department_head: e.target.value })} className="input w-full mt-1" />
        </label>
        <label className="text-xs">Requested By
          <input value={prn.requested_by_name ?? ''} onChange={(e) => set({ requested_by_name: e.target.value })}
            placeholder={currentUser?.full_name || currentUser?.username || 'Requester name'} className="input w-full mt-1" />
        </label>
        <label className="text-xs">Required Date
          <input type="date" value={prn.required_by_date || ''} onChange={(e) => set({ required_by_date: e.target.value })} className="input w-full mt-1" />
        </label>
        <label className="text-xs">Priority
          <select value={prn.priority} onChange={(e) => set({ priority: e.target.value })} className="input w-full mt-1">
            {meta.priorities.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label className="text-xs">Requirement Type
          <select value={prn.requirement_type} onChange={(e) => set({ requirement_type: e.target.value })} className="input w-full mt-1">
            {meta.requirement_types.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
      </div>
      <label className="text-xs block mb-4">Purpose of Requisition
        <textarea value={prn.purpose || ''} onChange={(e) => set({ purpose: e.target.value })} rows={2} className="input w-full mt-1" />
      </label>

      <div className="flex items-center justify-between mb-2">
        <div className="font-semibold text-slate-700 text-sm">Material Requirements</div>
        <button onClick={addLine} className="btn btn-secondary btn-sm"><Plus size={14} /> Add Row</button>
      </div>
      <div className="table-wrap">
        <table className="data-table table-dense">
          <thead><tr>
            <th className="w-10">Sr. No.</th><th className="min-w-40">Item Code</th><th className="min-w-56">Material Description</th>
            <th className="min-w-32">Specification</th><th className="min-w-28">UOM</th><th className="min-w-20">Required Qty.</th>
            <th className="min-w-28" title="Inventory stock (read-only) and optional PRN-specific override">Stock (Inventory / Override)</th>
            <th className="min-w-40">Purpose / Remarks</th><th></th>
          </tr></thead>
          <tbody>
            {prn.lines.map((l, i) => (
              <tr key={l._key}>
                <td className="text-xs text-slate-500">{i + 1}</td>
                <td>
                  <input list="prn-materials" value={l.material_code}
                    onChange={(e) => onCode(l._key, e.target.value, e.nativeEvent.inputType === 'insertReplacementText')}
                    onBlur={(e) => resolveCode(l._key, e.target.value)}
                    placeholder="Code or new item" className="input text-xs py-1 px-2 w-full font-mono" />
                </td>
                <td>
                  <div className="flex items-center gap-1">
                    <label className="text-slate-600 text-xs pr-1">Desc:</label>
                    <input list="prn-mat-desc" value={l.description}
                      onChange={(e) => onMaterialDesc(l._key, e.target.value)}
                      onBlur={(e) => resolveMaterialDesc(l._key, e.target.value)}
                      placeholder="Search material name" className="input text-xs py-1 px-2 w-full flex-1" />
                    <datalist id="prn-mat-desc">
                      {materials.map((m) => <option key={m.id} value={m.name || m.model} label={m.name || m.model}>{m.name || m.model}</option>)}
                    </datalist>
                  </div>
                  <input value={l.description} onChange={(e) => setLine(l._key, { description: e.target.value })}
                    placeholder={l.material_id ? '' : 'Describe material (Manual Entry – Item Master Review Required)'} className="input text-xs py-1 px-2 w-full hidden" />
                </td>
                <td><input value={l.specification} onChange={(e) => setLine(l._key, { specification: e.target.value })} className="input text-xs py-1 px-2 w-32" /></td>
                <td>
                  <select value={l.uom || ''} onChange={(e) => setLine(l._key, { uom: e.target.value, _uomTouched: true })} className="input text-xs py-1 px-2 w-28">
                    <option value="">—</option>
                    {l.uom && !UOMS.includes(l.uom) && <option value={l.uom}>{l.uom}</option>}
                    {UOMS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </td>
                <td><input type="number" min="0" step="any" value={l.quantity} onChange={(e) => setLine(l._key, { quantity: e.target.value })}
                  onBlur={(e) => l.material_id && stockFor(l._key, l.material_id, e.target.value, l.plant_id ?? null)} className="input text-xs py-1 px-2 w-20" /></td>
                <td className="text-xs" title="Inventory stock at request time (actual, read-only)">
                  <div className="text-slate-500 whitespace-nowrap">
                    Inv{l.material_id && l.location ? ` (${l.location})` : ''}: {l.available_stock == null ? 'Unknown' : fmtNum(l.available_stock)}
                  </div>
                  {l.incoming_qty != null && Number(l.incoming_qty) > 0 &&
                    <div className="text-slate-400 whitespace-nowrap" title="Open purchase order balance (incoming)">In: {fmtNum(l.incoming_qty)}</div>}
                  {l.material_id && locations.length > 1 &&
                    <select value={l.plant_id ?? ''} onChange={(e) => setLocation(l._key, e.target.value)}
                      title="Inventory location for this stock snapshot" className="input text-xs py-1 px-1 w-28 mt-1">
                      {locations.map((loc) => <option key={loc.id ?? 'main'} value={loc.id ?? ''}>{loc.name}</option>)}
                    </select>}
                  <input type="number" min="0" step="any" value={l.stock_override}
                    onChange={(e) => setLine(l._key, { stock_override: e.target.value })}
                    placeholder="Override" title="PRN stock estimate — does not change inventory"
                    className="input text-xs py-1 px-2 w-24 mt-1" />
                </td>
                <td><input value={l.remarks} onChange={(e) => setLine(l._key, { remarks: e.target.value })} className="input text-xs py-1 px-2 w-40" /></td>
                <td>
                  <div className="flex items-center gap-1">
                    {l.id ? (
                      <label title="Attach" className="btn-icon cursor-pointer">
                        <Paperclip size={14} />
                        <input type="file" className="hidden" onChange={(e) => e.target.files[0] && uploadFor(l.id, e.target.files[0])} />
                      </label>
                    ) : null}
                    <button onClick={() => removeLine(l._key)} className="btn-icon text-red-600" title="Remove"><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <datalist id="prn-materials">
        {materials.map((m) => <option key={m.id} value={m.item_code || m.model} label={m.name || m.model}>{m.name || m.model}</option>)}
      </datalist>
      <p className="text-xs text-slate-400 mt-2">
        Item Code matched to a material fills its description, UOM and inventory stock. Unmatched codes are
        <b> Manual Entry – Item Master Review Required</b> (stock unknown, not zero). A value typed under
        <b> Override</b> is a PRN estimate only — it never changes inventory.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4 border-t pt-4">
        <label className="text-xs">Checked By (Store)
          <input value={prn.checked_by_name || ''} onChange={(e) => set({ checked_by_name: e.target.value })} className="input w-full mt-1" />
        </label>
        <label className="text-xs">Purchase Department Remarks
          <textarea value={prn.purchase_remarks || ''} onChange={(e) => set({ purchase_remarks: e.target.value })} rows={2} className="input w-full mt-1" />
        </label>
      </div>
    </Modal>
  )
}
