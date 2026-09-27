import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, BellRing, Camera, Server, Radio } from 'lucide-react'
import { api } from '../lib/api'
import { fmtNumber } from '../lib/format'
import { useAuth } from '../lib/auth'

interface HealthSummary { total: number; ONLINE: number; OFFLINE: number; UNKNOWN: number }
interface VmsRow { vms_id: string; name: string; status: string; enabled: boolean; adapter_kind: string }
interface AlertRow {
  alert_id: string
  plate_normalized: string
  severity: string
  status: string
  raised_at: string
  camera_name: string
  district: string | null
}
interface EventRow {
  event_id: string
  event_type: string
  label: string
  severity: string
  occurred_at: string
  camera_name: string
}

const sevBadge = (s: string) =>
  s === 'CRITICAL' ? 'badge badge-crit' : s === 'HIGH' ? 'badge badge-warn' : s === 'MEDIUM' ? 'badge badge-info' : 'badge badge-neutral'

export default function Dashboard() {
  const { user } = useAuth()
  const [health, setHealth] = useState<HealthSummary | null>(null)
  const [vms, setVms] = useState<VmsRow[]>([])
  const [alerts, setAlerts] = useState<AlertRow[]>([])
  const [events, setEvents] = useState<EventRow[]>([])
  const [anpr, setAnpr] = useState<{ total: number; engines: Record<string, number> } | null>(null)

  useEffect(() => {
    const load = () => {
      api.get<{ data: HealthSummary }>('/streams/health/summary').then((r) => setHealth(r.data)).catch(() => {})
      api.get<{ data: VmsRow[] }>('/vms').then((r) => setVms(r.data)).catch(() => {})
      api.get<{ data: AlertRow[] }>('/alerts?hours=24&page_size=8').then((r) => setAlerts(r.data)).catch(() => {})
      api.get<{ data: EventRow[] }>('/events?hours=2&page_size=8').then((r) => setEvents(r.data)).catch(() => {})
    }
    load()
    const t = window.setInterval(load, 20000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    // ANPR throughput for the last 24h, split by engine (real edge-OCR vs simulated).
    api
      .get<{ data: { engine: string; total: number }[] }>('/vehicles/search/meta-engines')
      .then((r) => {
        const engines: Record<string, number> = {}
        let total = 0
        for (const row of r.data) {
          engines[row.engine] = row.total
          total += row.total
        }
        setAnpr({ total, engines })
      })
      .catch(() => {})
  }, [])

  const openAlerts = alerts.filter((a) => a.status === 'OPEN')

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold">Command Dashboard</h1>
        <p className="text-xs text-ink-muted">
          Statewide posture: camera health, federation status, ANPR throughput, live alerts. Welcome, {user?.name}.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="panel px-4 py-3">
          <div className="flex items-center gap-2 text-2xs font-semibold uppercase text-ink-muted"><Camera className="h-3.5 w-3.5" /> Cameras</div>
          <div className="mt-1 text-xl font-semibold">{health ? fmtNumber(health.total) : '—'}</div>
          <div className="text-2xs text-ink-faint">
            {health ? `${health.ONLINE} online · ${health.OFFLINE} offline` : 'loading…'}
          </div>
        </div>
        <div className="panel px-4 py-3">
          <div className="flex items-center gap-2 text-2xs font-semibold uppercase text-ink-muted"><Server className="h-3.5 w-3.5" /> VMS adapters</div>
          <div className="mt-1 text-xl font-semibold">{vms.length}</div>
          <div className="text-2xs text-ink-faint">
            {vms.filter((v) => v.enabled).length} enabled · {vms.filter((v) => v.status === 'ONLINE').length} online
          </div>
        </div>
        <div className="panel px-4 py-3">
          <div className="flex items-center gap-2 text-2xs font-semibold uppercase text-ink-muted"><Activity className="h-3.5 w-3.5" /> ANPR (24h)</div>
          <div className="mt-1 text-xl font-semibold">{anpr ? fmtNumber(anpr.total) : '—'}</div>
          <div className="text-2xs text-ink-faint">
            {anpr
              ? Object.entries(anpr.engines).map(([e, n]) => `${e}: ${n}`).join(' · ') || 'no reads yet'
              : 'loading…'}
          </div>
        </div>
        <div className="panel px-4 py-3">
          <div className="flex items-center gap-2 text-2xs font-semibold uppercase text-ink-muted"><BellRing className="h-3.5 w-3.5" /> Open alerts</div>
          <div className={`mt-1 text-xl font-semibold ${openAlerts.length ? 'text-crit' : ''}`}>{openAlerts.length}</div>
          <div className="text-2xs text-ink-faint">{alerts.length} raised in 24 h</div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4" /> Watchlist alerts (24 h)
          </h2>
          <ul className="max-h-72 space-y-1.5 overflow-auto text-xs">
            {alerts.map((a) => (
              <li key={a.alert_id} className="rounded border border-line px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold">{a.plate_normalized}</span>
                  <span className={sevBadge(a.severity)}>{a.severity} · {a.status}</span>
                </div>
                <div className="mt-1 text-2xs text-ink-muted">
                  {a.camera_name} · {a.district ?? '-'} · {new Date(a.raised_at).toLocaleTimeString('en-IN')}
                </div>
              </li>
            ))}
            {alerts.length === 0 && <li className="py-4 text-center text-ink-faint">No alerts in the last 24 h.</li>}
          </ul>
        </section>

        <section className="panel p-4">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <Radio className="h-4 w-4" /> Live detection feed (2 h)
          </h2>
          <ul className="max-h-72 space-y-1.5 overflow-auto text-xs">
            {events.map((e) => (
              <li key={e.event_id} className="rounded border border-line px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={sevBadge(e.severity)}>{e.event_type}</span>
                  <span className="text-2xs text-ink-faint">{new Date(e.occurred_at).toLocaleTimeString('en-IN')}</span>
                </div>
                <div className="mt-1 truncate text-2xs text-ink-muted">{e.label}</div>
              </li>
            ))}
            {events.length === 0 && <li className="py-4 text-center text-ink-faint">No recent events.</li>}
          </ul>
        </section>
      </div>
    </div>
  )
}
