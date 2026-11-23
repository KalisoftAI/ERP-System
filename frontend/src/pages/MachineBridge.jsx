import { useCallback, useEffect, useState } from 'react'
import { Activity, AlertTriangle, Cpu, Database, Radio, RefreshCw } from 'lucide-react'
import api from '../lib/api'
import { Badge, Card, Empty, Loading, PageHeader, PageTabs, StatCard } from '../components/ui'

const TABS = [
  { key: 'frames', label: 'Raw Frames', icon: <Radio size={15} /> },
  { key: 'transactions', label: 'Transactions', icon: <Database size={15} /> },
]

const fmtWhen = (value) => (value ? String(value).replace('T', ' ').slice(0, 19) : '-')

const statusClass = (value) => {
  const text = String(value || '').toUpperCase()
  if (['CONNECTED', 'SIMULATING', 'LISTENING', 'STABLE', 'PROCESSED', 'PARSED', 'SYNCED'].includes(text)) {
    return 'bg-green-100 text-green-700'
  }
  if (['PENDING', 'DUPLICATE', 'RAW', 'RETRY', 'CONNECTING', 'CONNECTED_NO_DATA', 'RECEIVING_UNPARSED', 'CONNECTED_STALE', 'UNSTABLE'].includes(text)) {
    return 'bg-amber-100 text-amber-700'
  }
  if (['DISCONNECTED', 'FAILED', 'DEAD', 'ERROR', 'CONFIG_ERROR', 'DEVICE_ERROR'].includes(text)) {
    return 'bg-red-100 text-red-700'
  }
  return 'bg-slate-100 text-slate-600'
}

export default function MachineBridge() {
  const [status, setStatus] = useState(null)
  const [frames, setFrames] = useState([])
  const [transactions, setTransactions] = useState([])
  const [tab, setTab] = useState('frames')
  const [parserStatus, setParserStatus] = useState('')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const params = {}
      if (parserStatus) params.parser_status = parserStatus
      if (search.trim()) params.search = search.trim()
      const [statusRes, framesRes, txnRes] = await Promise.all([
        api.get('/production/machine/status'),
        api.get('/production/machine/frames', { params: { ...params, page_size: 50 } }),
        api.get('/production/machine/transactions', { params: { page_size: 50 } }),
      ])
      setStatus(statusRes.data || {})
      setFrames(framesRes.data.items || [])
      setTransactions(txnRes.data.items || [])
      setError('')
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load machine bridge status')
    } finally {
      setLoading(false)
    }
  }, [parserStatus, search])

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [load])

  const connection = status?.connection || {}
  const config = connection.config || {}
  const frameCounts = status?.frames || {}
  const txnCounts = status?.counters || {}
  const lastFrame = status?.last_frame || null
  const lastTransaction = status?.last_transaction || null

  return (
    <div className="animate-fade-in-up">
      <PageHeader
        title="Machine Bridge"
        subtitle="Serial barcode and weighing feed, raw frames and ERP transaction inbox"
        actions={<button onClick={load} className="btn btn-secondary"><RefreshCw size={15} /> Refresh</button>}
      />

      {error && <div className="mb-4 rounded-lg bg-red-50 text-red-700 px-4 py-3 text-sm">{error}</div>}

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard label="Device Health" value={status?.device_health || connection.status || 'AWAITING_CONFIGURATION'} sub={`${config.device_host || '-'}:${config.device_port || '-'}`} icon={Cpu} />
        <StatCard label="Raw Frames Today" value={frameCounts.received_today || 0} sub={`${frameCounts.errors || 0} parse errors`} icon={Radio} />
        <StatCard label="Transactions" value={txnCounts.total || 0} sub={`${txnCounts.failed || 0} failed · ${txnCounts.duplicate || 0} duplicate`} icon={Database} />
        <StatCard label="Parser" value={config.parser_mode || '-'} sub={`dry_run=${String(config.dry_run ?? '-')}`} icon={Activity} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-4">
        <Card title="Current Reading" subtitle="Latest frame and ERP transaction seen by the API">
          {loading && !lastFrame && !lastTransaction ? <Loading /> : (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between gap-4"><span className="text-slate-500">Status</span><Badge className={statusClass(status?.device_health || connection.status)}>{status?.device_health || connection.status || '-'}</Badge></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Last seen</span><span>{fmtWhen(connection.last_seen_at)}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Last byte</span><span>{fmtWhen(config.last_byte_at)}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Valid reading</span><span>{fmtWhen(config.last_valid_reading_at)}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Barcode</span><span className="font-mono">{lastFrame?.barcode || config.last_barcode || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Gross weight</span><span>{lastFrame?.gross_weight ?? config.last_gross_weight ?? '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Transaction</span><span className="font-mono">{lastFrame?.transaction_id || lastTransaction?.transaction_uid || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">ERP result</span><Badge className={statusClass(lastTransaction?.status)}>{lastTransaction?.status || '-'}</Badge></div>
              <div className="pt-2 border-t border-gray-100 break-all font-mono text-xs text-slate-500">{lastFrame?.raw_text || 'No raw frame received yet'}</div>
              {(connection.last_error || lastFrame?.error_message || lastTransaction?.error_message) && (
                <div className="flex items-start gap-2 rounded-lg bg-red-50 text-red-700 px-3 py-2 text-xs">
                  <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                  <span>{connection.last_error || lastFrame?.error_message || lastTransaction?.error_message}</span>
                </div>
              )}
            </div>
          )}
        </Card>

        <Card title="Bridge Configuration" subtitle="Reported by the Windows bridge heartbeat">
          {loading && !connection.id ? <Loading /> : (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between gap-4"><span className="text-slate-500">Connection type</span><span>{connection.connection_type || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Device ID</span><span>{config.device_id || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Device MAC</span><span className="font-mono">{config.device_mac || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Gateway IP</span><span className="font-mono">{config.device_host || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">TCP port</span><span className="font-mono">{config.device_port || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Parser mode</span><span>{config.parser_mode || '-'}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Dry run</span><span>{String(config.dry_run ?? '-')}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">GCS upload</span><span>{String(config.gcs_upload_enabled ?? '-')}</span></div>
              <div className="flex justify-between gap-4"><span className="text-slate-500">Reading age</span><span>{config.reading_age_seconds == null ? '-' : `${Number(config.reading_age_seconds).toFixed(1)}s`}</span></div>
              <div className="pt-2 border-t border-gray-100 text-xs text-slate-500">{status?.integration_note || '-'}</div>
            </div>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <PageTabs tabs={TABS} active={tab} onChange={setTab} />
        <Card
          title={tab === 'frames' ? 'Raw Serial Frames' : 'ERP Transaction Inbox'}
          subtitle={tab === 'frames' ? 'Captured before parsing, including invalid readings' : 'Validation, dedupe and stock-posting outcome from ERP'}
          actions={tab === 'frames' ? (
            <div className="flex gap-2">
              <select value={parserStatus} onChange={(e) => setParserStatus(e.target.value)} className="input">
                <option value="">All statuses</option>
                <option value="RAW">RAW</option>
                <option value="PARSED">PARSED</option>
                <option value="ERROR">ERROR</option>
              </select>
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search barcode, text, error" className="input" />
            </div>
          ) : undefined}
        >
          {loading ? <Loading /> : tab === 'frames' ? (
            frames.length ? (
              <div className="overflow-x-auto">
                <table className="table">
                  <thead><tr><th>Time</th><th>Status</th><th>Barcode</th><th>Weight</th><th>Transaction</th><th>Raw Frame</th></tr></thead>
                  <tbody>
                    {frames.map((frame) => (
                      <tr key={frame.id}>
                        <td className="whitespace-nowrap">{fmtWhen(frame.created_at)}</td>
                        <td><Badge className={statusClass(frame.parser_status)}>{frame.parser_status}</Badge></td>
                        <td className="font-mono">{frame.barcode || '-'}</td>
                        <td>{frame.gross_weight ?? '-'}</td>
                        <td className="font-mono text-xs">{frame.transaction_id || '-'}</td>
                        <td className="max-w-md break-all font-mono text-xs text-slate-500">{frame.error_message || frame.raw_text || frame.raw_hex}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <Empty text="No serial frames captured yet" />
          ) : transactions.length ? (
            <div className="overflow-x-auto">
              <table className="table">
                <thead><tr><th>Time</th><th>Status</th><th>Barcode</th><th>Box</th><th>Source</th><th>Error</th></tr></thead>
                <tbody>
                  {transactions.map((txn) => (
                    <tr key={txn.id}>
                      <td className="whitespace-nowrap">{fmtWhen(txn.received_at)}</td>
                      <td><Badge className={statusClass(txn.status)}>{txn.status}</Badge></td>
                      <td className="font-mono">{txn.barcode || '-'}</td>
                      <td>{txn.box_number || '-'}</td>
                      <td>{txn.source || '-'}</td>
                      <td className="text-xs text-red-600">{txn.error_message || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <Empty text="No transactions received yet" />}
        </Card>
      </div>
    </div>
  )
}
