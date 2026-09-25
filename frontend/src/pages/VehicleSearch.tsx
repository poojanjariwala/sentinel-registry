import { FormEvent, useCallback, useEffect, useState } from 'react'
import { AlertTriangle, BellRing, Search, Tag, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { useAuth } from '../lib/auth'

interface Obs {
  observation_id: string
  captured_at: string
  plate_raw: string
  plate_normalized: string
  vehicle_class: string | null
  speed_kmph: number | null
  confidence: number
  engine: string
  stream_label: string
  vms_system: string
  camera_name: string
  district: string | null
}
interface Ev {
  event_id: string
  event_type: string
  label: string
  severity: string
  occurred_at: string
  stream_label: string
  camera_name: string
  district: string | null
}
interface Watch {
  watch_id: string
  plate_normalized: string
  reason: string
  severity: string
  owner_hint: string | null
}
interface Alert {
  alert_id: string
  plate_normalized: string
  severity: string
  status: string
  raised_at: string
  stream_label: string
  camera_name: string
  district: string | null
}

const sevBadge = (s: string) =>
  s === 'CRITICAL' ? 'badge badge-crit' : s === 'HIGH' ? 'badge badge-warn' : s === 'MEDIUM' ? 'badge badge-info' : 'badge badge-neutral'

export default function VehicleSearch() {
  const { can } = useAuth()
  const [plate, setPlate] = useState('GJ01AB1234')
  const [hours, setHours] = useState(24)
  const [obs, setObs] = useState<Obs[]>([])
  const [meta, setMeta] = useState<{ mode: string; total: number } | null>(null)
  const [searching, setSearching] = useState(false)
  const [events, setEvents] = useState<Ev[]>([])
  const [watch, setWatch] = useState<Watch[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [newWatch, setNewWatch] = useState({ plate: '', reason: '', severity: 'HIGH' })

  const search = useCallback(async () => {
    if (!plate.trim()) return
    setSearching(true)
    try {
      const r = await api.get<{ data: Obs[]; meta: { mode: string; total: number } }>(
        `/vehicles/search?plate=${encodeURIComponent(plate)}&hours=${hours}`,
      )
      setObs(r.data)
      setMeta(r.meta)
    } finally {
      setSearching(false)
    }
  }, [plate, hours])

  const loadFeeds = useCallback(() => {
    api.get<{ data: Ev[] }>('/events?hours=2&page_size=25').then((r) => setEvents(r.data)).catch(() => {})
    api.get<{ data: Alert[] }>('/alerts?hours=24&page_size=25').then((r) => setAlerts(r.data)).catch(() => {})
  }, [])

  const loadWatch = useCallback(() => {
    api.get<{ data: Watch[] }>('/watchlist').then((r) => setWatch(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    search()
    loadFeeds()
    loadWatch()
    const t = window.setInterval(loadFeeds, 15000)
    return () => window.clearInterval(t)
  }, [search, loadFeeds, loadWatch])

  const addWatch = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/watchlist', newWatch)
      setNewWatch({ plate: '', reason: '', severity: 'HIGH' })
      loadWatch()
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to add')
    }
  }

  const removeWatch = async (id: string) => {
    await api.delete(`/watchlist/${id}`)
    loadWatch()
  }

  const ack = async (id: string) => {
    await api.post(`/alerts/${id}/ack`)
    loadFeeds()
  }

  const close = async (id: string) => {
    await api.post(`/alerts/${id}/close`)
    loadFeeds()
  }

  return (
    <div className="space-y-4 p-5">
      <div>
        <h1 className="text-lg font-semibold">Vehicle Intelligence</h1>
        <p className="text-xs text-ink-muted">ANPR metadata search, camera-wise event index, watchlist and alerts.</p>
      </div>

      <section className="panel p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            search()
          }}
          className="flex flex-wrap items-center gap-2"
        >
          <div className="relative min-w-64 flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
            <input value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="GJ01AB1234 or partial…" className="input-base pl-8" />
          </div>
          <select value={hours} onChange={(e) => setHours(Number(e.target.value))} className="input-base w-40">
            {[1, 6, 24, 72, 168].map((h) => (
              <option key={h} value={h}>
                Last {h} hour{h > 1 ? 's' : ''}
              </option>
            ))}
          </select>
          <button className="btn-primary" disabled={searching}>
            {searching ? 'Searching…' : 'Search'}
          </button>
          {meta && (
            <span className="text-2xs text-ink-faint">
              {meta.total} sightings · match: {meta.mode}
            </span>
          )}
        </form>

        {obs.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Plate</th>
                  <th>Camera</th>
                  <th>District</th>
                  <th>VMS</th>
                  <th>Class</th>
                  <th>Speed</th>
                  <th>Conf.</th>
                </tr>
              </thead>
              <tbody>
                {obs.slice(0, 12).map((o) => (
                  <tr key={o.observation_id}>
                    <td className="whitespace-nowrap text-xs">{fmtDateTime(o.captured_at)}</td>
                    <td className="font-mono text-xs font-semibold">{o.plate_normalized}</td>
                    <td className="text-xs">{o.camera_name}</td>
                    <td className="text-xs">{o.district ?? '-'}</td>
                    <td className="text-2xs">{o.vms_system}</td>
                    <td className="text-xs">{o.vehicle_class ?? '-'}</td>
                    <td className="text-xs">{o.speed_kmph != null ? `${o.speed_kmph} km/h` : '-'}</td>
                    <td className="text-xs">{(o.confidence * 100).toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {obs.length > 12 && <p className="mt-1 text-2xs text-ink-faint">Showing 12 of {obs.length} results</p>}
          </div>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="panel p-4 lg:col-span-1">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <Tag className="h-4 w-4" /> Tagged events (live feed)
          </h2>
          <ul className="max-h-80 space-y-1.5 overflow-auto text-xs">
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

        <section className="panel p-4">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <BellRing className="h-4 w-4" /> Alerts
          </h2>
          <ul className="max-h-80 space-y-1.5 overflow-auto text-xs">
            {alerts.map((a) => (
              <li key={a.alert_id} className="rounded border border-line px-2.5 py-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono font-semibold">{a.plate_normalized}</span>
                  <span className={sevBadge(a.severity)}>{a.severity}</span>
                </div>
                <div className="mt-1 text-2xs text-ink-muted">
                  {a.camera_name} · {new Date(a.raised_at).toLocaleTimeString('en-IN')} · {a.status}
                </div>
                {a.status === 'OPEN' && can('camera.write') && (
                  <div className="mt-1.5 flex gap-1.5">
                    <button onClick={() => ack(a.alert_id)} className="btn-ghost !px-2 !py-0.5 text-2xs">Acknowledge</button>
                    <button onClick={() => close(a.alert_id)} className="btn-ghost !px-2 !py-0.5 text-2xs">Close</button>
                  </div>
                )}
              </li>
            ))}
            {alerts.length === 0 && <li className="py-4 text-center text-ink-faint">No alerts in the last 24 h.</li>}
          </ul>
        </section>

        <section className="panel p-4">
          <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4" /> Watchlist
          </h2>
          <ul className="max-h-52 space-y-1.5 overflow-auto text-xs">
            {watch.map((w) => (
              <li key={w.watch_id} className="flex items-center justify-between gap-2 rounded border border-line px-2.5 py-1.5">
                <div className="min-w-0">
                  <span className="font-mono font-semibold">{w.plate_normalized}</span> <span className={sevBadge(w.severity)}>{w.severity}</span>
                  <div className="truncate text-2xs text-ink-muted">{w.reason}</div>
                </div>
                {can('camera.write') && (
                  <button onClick={() => removeWatch(w.watch_id)} className="text-ink-faint hover:text-crit" aria-label="Remove">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                )}
              </li>
            ))}
          </ul>
          {can('camera.write') && (
            <form onSubmit={addWatch} className="mt-3 space-y-2 border-t border-line pt-3">
              <input required className="input-base" placeholder="Plate (e.g. GJ05ZX7788)" value={newWatch.plate} onChange={(e) => setNewWatch((w) => ({ ...w, plate: e.target.value }))} />
              <input className="input-base" placeholder="Reason" value={newWatch.reason} onChange={(e) => setNewWatch((w) => ({ ...w, reason: e.target.value }))} />
              <div className="flex gap-2">
                <select className="input-base" value={newWatch.severity} onChange={(e) => setNewWatch((w) => ({ ...w, severity: e.target.value }))}>
                  {['CRITICAL', 'HIGH', 'MEDIUM'].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
                <button className="btn-primary">Add</button>
              </div>
            </form>
          )}
        </section>
      </div>
    </div>
  )
}
