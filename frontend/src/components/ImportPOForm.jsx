import { Plus } from 'lucide-react'
import { fmtNum } from '../lib/format'
import { SearchSelect } from './ui'

export const DEFAULT_TERMS = ['PICKUP WITHIN 7 DAYS AFTER RECEIPT OF PAYMENT','PAYMENT 100% AGAINST PI','DHL ACCOUNT NO.969265540','PAYMENT WILL BE DONE VIA WIRE TRANSFER AS PER PI','WIRE TRANSFER FEE AS PER PI']
export const DEFAULT_COMPANY = {companyName:'KALIKA ENTERPRISES',address1:'PLOT NO M-59,MIDC,AHMEDNAGAR',website:'Website: www.kalikaindia.com',phone:'Phone:+91 9405536016',approvedBy:'Approved By: [Mr.  Vishal Kumbharkar ]'}
export const DEFAULT_BILLING = {invoiceInFavor:'KALIKA ENTERPRISES',billingShipping1:'PLOT NO M-59,MIDC',billingShipping2:'AHMEDNAGAR,',zipCode:'414111',country:'INDIA'}

export default function ImportPOForm({ form, setForm, suppliers = [], suppliersLoading = false, suppliersError = '' }){
  const yellow = (e='')=> 'bg-yellow-50 border-yellow-200 '+e
  const pickSupplier = (id, manual) => {
    const s = id ? suppliers.find((ss) => String(ss.id) === String(id)) : null
    setForm({
      ...form,
      supplier_id: id || '',
      import_supplier_name: s ? (s.name || s.company || '') : (manual || ''),
      import_supplier_addr1: s ? (s.address || '') : '',
      import_supplier_addr2: '',
      import_supplier_email: s ? (s.email || '') : '',
    })
  }
  const calc=(ln)=>{const q=Number(ln.quantity||0);const r=Number(ln.rate_usd||ln.rate||0);return q*r}
  const setLine=(i,k,v)=>{const lines=[...(form.import_lines||form.lines||[])];lines[i]={...lines[i],[k]:v};if(k==='quantity'||k==='rate_usd'||k==='rate'){lines[i].amount=calc(lines[i])};setForm({...form,import_lines:lines,lines})}
  const addLine=()=>{const lines=[...(form.import_lines||form.lines||[])];lines.push({srno:lines.length+1,item_description:'',part_no:'',make:'',quantity:'',uom:'Nos',rate_usd:'',amount:''});setForm({...form,import_lines:lines,lines})}
  const removeLine=(i)=>{const lines=[...(form.import_lines||form.lines||[])];if(lines.length<=1)return;const f=lines.filter((_,idx)=>idx!==i).map((ln,idx)=>({...ln,srno:idx+1}));setForm({...form,import_lines:f,lines:f})}
  const lines=form.import_lines||form.lines||[]
  const total=lines.reduce((s,ln)=>s+Number(ln.amount||calc(ln)||0),0)
  return (<div className='text-sm'>
    <div className='grid grid-cols-12 gap-2 mb-3'>
      <div className='col-span-6'>
        <div className='border p-2 rounded space-y-1'>
          <div className='text-xs text-slate-500'>Company Name</div>
          <input className={yellow('input text-xs')} value={DEFAULT_COMPANY.companyName} readOnly />
          <input className={yellow('input text-xs')} value={DEFAULT_COMPANY.address1} readOnly />
          <input className={yellow('input text-xs')} value={DEFAULT_COMPANY.website} readOnly />
          <input className={yellow('input text-xs')} value={DEFAULT_COMPANY.phone} readOnly />
          <input className={yellow('input text-xs')} value={DEFAULT_COMPANY.approvedBy} readOnly />
        </div>
          <div className='border p-2 rounded mt-2 space-y-1'>
            <div className='text-xs text-slate-500 uppercase'>Supplier</div>
            <SearchSelect
              options={suppliers.map((s) => ({ id: s.id, label: s.name || s.company || `Supplier ${s.id}` }))}
              value={form.supplier_id || null}
              initialLabel={!form.supplier_id ? (form.import_supplier_name || '') : ''}
              placeholder='Search suppliers or type a new name'
              className='input text-xs'
              onChange={pickSupplier}
            />
            {suppliersLoading && <div className='text-[10px] text-slate-400'>Loading suppliers…</div>}
            {suppliersError && <div className='text-[10px] text-red-600'>Could not load suppliers. You can still enter details manually.</div>}
            {!suppliersLoading && !suppliersError && suppliers.length === 0 && (
              <div className='text-[10px] text-slate-400'>No existing suppliers found. Enter details manually.</div>
            )}
            <input className={'input text-xs'} value={form.import_supplier_name || ''} onChange={(e)=>setForm({...form,supplier_id:'',import_supplier_name:e.target.value})} placeholder='Supplier Name' />
            <input className={'input text-xs'} value={form.import_supplier_addr1 || ''} onChange={(e)=>setForm({...form,import_supplier_addr1:e.target.value})} placeholder='Supplier Address' />
            <input className={'input text-xs'} value={form.import_supplier_addr2 || ''} onChange={(e)=>setForm({...form,import_supplier_addr2:e.target.value})} placeholder='Address Line 2' />
            <input className={'input text-xs'} value={form.import_supplier_email || ''} onChange={(e)=>setForm({...form,import_supplier_email:e.target.value})} placeholder='Supplier Email' />
          </div>
      </div>
      <div className='col-span-6'>
          <div className='border p-2 rounded space-y-2'>
            <div className='flex items-center gap-2'><div className='w-32 text-xs text-slate-600'>DATE</div><input type='date' className={'input text-xs flex-1'} value={form.import_date||form.order_date||''} onChange={(e)=>setForm({...form,import_date:e.target.value,order_date:e.target.value})} /></div>
            <div className='flex items-center gap-2'><div className='w-32 text-xs text-slate-600'>PO NO</div><input className={'input text-xs flex-1'} value={form.po_number||''} onChange={(e)=>setForm({...form,po_number:e.target.value})} /></div>
            <div className='flex items-center gap-2'><div className='w-32 text-xs text-slate-600'>CUSTOMER ID</div><input className={'input text-xs flex-1 bg-yellow-50 border-yellow-200'} value={form.import_customer_id||'167428'} onChange={(e)=>setForm({...form,import_customer_id:e.target.value})} readOnly /></div>
            <div className='flex items-center gap-2'><div className='w-32 text-xs text-slate-600'>VALID UNTIL</div><input type='date' className={'input text-xs flex-1'} value={form.import_valid_until||''} onChange={(e)=>setForm({...form,import_valid_until:e.target.value})} /></div>
          </div>
        <div className='border p-2 rounded mt-2'>
          <div className='text-xs font-semibold mb-1'>DETAILS FOR BILLING AND SHIPPING</div>
          <div className='grid grid-cols-2 gap-1 text-xs'>
            <div className='text-slate-600'>Invoice in favor</div><input className={yellow('input text-xs')} value={DEFAULT_BILLING.invoiceInFavor} readOnly />
            <div className='text-slate-600'>Billing & Shipping</div><input className={yellow('input text-xs')} value={DEFAULT_BILLING.billingShipping1} readOnly />
            <div></div><input className={yellow('input text-xs')} value={DEFAULT_BILLING.billingShipping2} readOnly />
            <div className='text-slate-600'>ZIP CODE</div><input className={yellow('input text-xs')} value={DEFAULT_BILLING.zipCode} readOnly />
            <div className='text-slate-600'>COUNTRY</div><input className={yellow('input text-xs')} value={DEFAULT_BILLING.country} readOnly />
          </div>
        </div>
      </div>
    </div>

    <div className='text-xs mb-2'>We hereby confirm the order for follwing line items TO BE IMPORTED FROM YOU</div>
    <div className='overflow-x-auto'>
      <table className='w-full text-xs border'>
        <thead><tr className='bg-yellow-50'>
          <th className='border px-2 py-1'>SRNO</th><th className='border px-2 py-1'>ITEM DESCRIPTION</th><th className='border px-2 py-1'>PART NO</th><th className='border px-2 py-1'>MAKE</th><th className='border px-2 py-1'>QTY</th><th className='border px-2 py-1'>UOM</th><th className='border px-2 py-1'>RATE USD</th><th className='border px-2 py-1'>AMOUNT</th><th className='border px-2 py-1'></th>
        </tr></thead>
        <tbody>
          {lines.map((ln,i)=>{
            const amt=Number(ln.amount||calc(ln)||0)
            return (<tr key={i}>
              <td className='border px-1 py-1 text-center'>{ln.srno||i+1}</td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' value={ln.item_description||ln.description||''} onChange={(e)=>setLine(i,'item_description',e.target.value)} /></td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' value={ln.part_no||ln.item_code||''} onChange={(e)=>setLine(i,'part_no',e.target.value)} /></td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' value={ln.make||''} onChange={(e)=>setLine(i,'make',e.target.value)} /></td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' type='number' value={ln.quantity||''} onChange={(e)=>setLine(i,'quantity',e.target.value)} /></td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' value={ln.uom||'Nos'} onChange={(e)=>setLine(i,'uom',e.target.value)} /></td>
              <td className='border px-1 py-1'><input className='input w-full text-xs' type='number' value={ln.rate_usd||ln.rate||''} onChange={(e)=>setLine(i,'rate_usd',e.target.value)} /></td>
              <td className='border px-1 py-1 text-right'>{fmtNum(amt)}</td>
              <td className='border px-1 py-1 text-center'><button onClick={()=>removeLine(i)} className='text-red-500'>x</button></td>
            </tr>)
          })}
        </tbody>
        <tfoot><tr><td colSpan={7} className='border px-2 py-1 text-right font-semibold'>TOTAL AMOUNT USD</td><td className='border px-2 py-1 text-right font-semibold'>{fmtNum(total)}</td><td className='border'></td></tr></tfoot>
      </table>
    </div>
    <button onClick={addLine} className='btn btn-ghost mt-2 text-xs'><Plus size={12} className='inline mr-1'/>Add line</button>

    <div className='grid grid-cols-12 gap-2 mt-4'>
      <div className='col-span-6'>
        <div className='text-xs font-semibold mb-1'>TERMS & CONDITION</div>
        <table className='w-full text-xs border'><tbody>
          {DEFAULT_TERMS.map((t,i)=>(<tr key={i}><td className='border px-1 py-1 w-6'>{i+1}</td><td className='border px-1 py-1'><input className={yellow('input w-full text-xs')} value={t} readOnly /></td></tr>))}
        </tbody></table>
      </div>
      <div className='col-span-6 flex flex-col justify-end'>
        <div className='text-right'>
          <div className='text-xs mb-2'>For KALIKA ENTERPRISES</div>
          <div className='border-t w-48 ml-auto mt-8 pt-1 text-xs'>Authorized Signatory</div>
        </div>
      </div>
    </div>

    <div className='mt-4 text-xs'>
      <div>If you have any questions about this price quote, please contact</div>
      <div className='text-blue-600'>info@kalikaindia.com </div>
    </div>
  </div>)
}

