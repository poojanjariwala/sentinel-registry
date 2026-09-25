import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'

interface E {
  audit_event_id: string
  actor_label: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  request_id: string | null
  ip_address: string | null
  before_state: Record<string, unknown> | null
  after_state: Record<string, unknown> | null
  occurred_at: string | null
}

const ACTIONS = [
  'LOGIN_SUCCESS', 'LOGIN_FAILED', 'CAMERA_CREATE', 'CAMERA_UPDATE', 'CAMERA_DELETE',
  'CAMERA_IMPORT', 'CAMERA_EXPORT', 'COVERAGE_RUN_CREATE', 'USER_CREATE', 'PERMISSION_DENIED',
]

export default function Audit() {
  const [rows, setRows] = useState<E[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const qs = useMemo(() => {
    const p = new URLSearchParams({ page: String(page), page_size: '25' })
    if (action) p.set('action', action)
    if (actor) p.set('actor', actor)
    return p.toString()
  }, [page, action, actor])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get<{ data: E[]; meta: { total: number } }>(`/audit?${qs}`)
      setRows(r.data)
      setTotal(r.meta.total)
    } finally {
      setLoading(false)
    }
  }, [qs])

  useEffect(() => {
    load()
  }, [load])

  const pages = Math.max(1, Math.ceil(total / 25))

  return (
    <div className="p-5">
      <div className="mb-4">
        <h1 className="text-lg font-semibold">Audit Trail</h1>
        <p className="text-xs text-ink-muted">{total.toLocaleString('en-IN')} audited events · append-only</p>
      </div>

      <div className="panel mb-3 flex flex-wrap items-center gap-2 p-3">
        <select value={action} onChange={(e) => { setPage(1); setAction(e.target.value) }} className="input-base w-52">
          <option value="">All actions</option>
          {ACTIONS.map((a) => <option key={a}>{a}</option>)}
        </select>
        <input
          value={actor}
          onChange={(e) => { setPage(1); setActor(e.target.value) }}
          placeholder="Filter by actor email..."
          className="input-base w-64"
        />
      </div>

      <div className="panel overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Resource</th>
              <th>IP</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={6} className="py-8 text-center text-ink-muted">Loading audit trail...</td></tr>}
            {rows.map((e) => (
              <>
                <tr
                  key={e.audit_event_id}
                  className="cursor-pointer"
                  onClick={() => setExpanded(expanded === e.audit_event_id ? null : e.audit_event_id)}
                >
                  <td className="whitespace-nowrap text-xs">{fmtDateTime(e.occurred_at)}</td>
                  <td className="text-xs">{e.actor_label ?? '-'}</td>
                  <td>
                    <span className={`badge ${e.action.includes('FAILED') || e.action.includes('DENIED') ? 'badge-crit' : 'badge-neutral'}`}>
                      {e.action}
                    </span>
                  </td>
                  <td className="text-xs">
                    {e.resource_type}
                    {e.resource_id && <span className="ml-1 font-mono text-2xs text-ink-faint">{e.resource_id.slice(0, 8)}…</span>}
                  </td>
                  <td className="font-mono text-2xs">{e.ip_address ?? '-'}</td>
                  <td className="text-2xs text-ink-faint">{expanded === e.audit_event_id ? 'Hide' : 'Details'}</td>
                </tr>
                {expanded === e.audit_event_id && (
                  <tr key={`${e.audit_event_id}-detail`}>
                    <td colSpan={6} className="bg-canvas">
                      <div className="grid gap-3 p-2 md:grid-cols-2">
                        <div>
                          <div className="mb-1 text-2xs font-semibold uppercase text-ink-muted">Before</div>
                          <pre className="max-h-40 overflow-auto rounded border border-line bg-white p-2 font-mono text-2xs">
                            {JSON.stringify(e.before_state ?? {}, null, 2)}
                          </pre>
                        </div>
                        <div>
                          <div className="mb-1 text-2xs font-semibold uppercase text-ink-muted">After</div>
                          <pre className="max-h-40 overflow-auto rounded border border-line bg-white p-2 font-mono text-2xs">
                            {JSON.stringify(e.after_state ?? {}, null, 2)}
                          </pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-ink-muted">
        <span>Page {page} of {pages}</span>
        <div className="flex gap-2">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="btn-ghost">Previous</button>
          <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)} className="btn-ghost">Next</button>
        </div>
      </div>
    </div>
  )
}
