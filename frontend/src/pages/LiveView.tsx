import { useCallback, useEffect, useMemo, useState } from 'react'
import { Grid3X3, LayoutGrid, Rows3, Radio, Activity } from 'lucide-react'
import { api } from '../lib/api'
import { StreamRow, useHlsStream } from '../lib/streams'
import { fmtDateTime } from '../lib/format'
import { useAuth } from '../lib/auth'

const GRID_PRESETS = [
  { id: '2x2', label: '2×2', cols: 2, count: 4, icon: Grid3X3 },
  { id: '3x3', label: '3×3', cols: 3, count: 9, icon: LayoutGrid },
  { id: '1+5', label: '1+5', cols: 3, count: 6, icon: Rows3 },
]

function Tile({
  stream,
  startable,
  focused,
  onFocus,
  onStart,
  onRetry,
}: {
  stream: StreamRow | null
  startable: boolean
  focused: boolean
  onFocus: () => void
  onStart: () => void
  onRetry: () => void
}) {
  const { videoRef, state } = useHlsStream(startable ? stream?.stream_id ?? null : null)

  return (
    <div
      className={`panel relative flex min-h-0 flex-col overflow-hidden ${focused ? 'ring-2 ring-accent' : ''}`}
      onClick={onFocus}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onFocus()}
    >
      <div className="relative flex-1 bg-black">
        <video ref={videoRef} muted autoPlay playsInline className="h-full w-full object-contain" />
        {state === 'live' && (
          <span className="absolute left-2 top-2 flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-2xs font-semibold text-red-400">
            <Radio className="h-3 w-3 animate-pulse" /> LIVE
          </span>
        )}
        {state !== 'live' && (
          <div className="absolute inset-0 flex items-center justify-center bg-ink/80 text-xs text-white/80">
            {state === 'connecting' ? 'Connecting to camera…'
              : state === 'cooldown' ? 'Watch-time cooldown · click to retry later'
              : state === 'error' ? 'Feed unavailable · retries exhausted · click Start to retry'
              : startable ? 'Starting…'
              : (
                <button
                  className="flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs text-white/90 ring-1 ring-white/25 hover:bg-white/20"
                  onClick={(e) => { e.stopPropagation(); onStart() }}
                >
                  ▶ Play this camera
                </button>
              )}
          </div>
        )}
        {state === 'cooldown' && (
          <button
            className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-2xs text-white/80 hover:bg-black/80"
            onClick={(e) => { e.stopPropagation(); onRetry() }}
          >
            ↻ Retry
          </button>
        )}
      </div>
      {stream && (
        <div className="flex items-center justify-between gap-2 border-t border-line bg-white px-2.5 py-1.5">
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">{stream.label}</div>
            <div className="truncate text-2xs text-ink-faint">
              {stream.vms_system} · {stream.district ?? '-'}
            </div>
          </div>
          <span
            className={`badge ${
              stream.status === 'ONLINE' ? 'badge-ok' : stream.status === 'OFFLINE' ? 'badge-crit' : 'badge-neutral'
            }`}
          >
            {stream.status}
          </span>
        </div>
      )}
    </div>
  )
}

export default function LiveView() {
  const { can } = useAuth()
  const [rows, setRows] = useState<StreamRow[]>([])
  // Click-to-start (grid etiquette, ADR-007): the origin enforces a per-account
  // watch-time quota, so streams open on explicit user action, never all at
  // once on page load.
  const [playing, setPlaying] = useState(false)
  // Individually started tiles (per-tile Play button) - kept separate from the
  // global Start live flag so one click never opens the whole wall.
  const [startedIds, setStartedIds] = useState<Set<string>>(new Set())
  const [preset, setPreset] = useState(GRID_PRESETS[0])
  const [slots, setSlots] = useState<(string | null)[]>(Array(9).fill(null))
  const [focus, setFocus] = useState<string | null>(null)
  const [filters, setFilters] = useState({ q: '', vms_system: '', status: '' })
  const [vmsOptions, setVmsOptions] = useState<string[]>([])
  const [health, setHealth] = useState<{ ONLINE: number; OFFLINE: number; UNKNOWN: number; total: number } | null>(null)

  useEffect(() => {
    const qs = new URLSearchParams()
    if (filters.q) qs.set('q', filters.q)
    if (filters.vms_system) qs.set('vms_system', filters.vms_system)
    if (filters.status) qs.set('status', filters.status)
    api
      .get<{ data: StreamRow[]; meta: { vms_systems: string[] } }>(`/streams?${qs}`)
      .then((r) => {
        setRows(r.data)
        setVmsOptions(r.meta.vms_systems)
        setSlots((prev) => {
          const valid = prev.map((id) => (id && r.data.some((s) => s.stream_id === id) ? id : null))
          const available = r.data.map((s) => s.stream_id).filter((id) => !valid.includes(id))
          return valid.map((id) => id ?? available.shift() ?? null)
        })
      })
      .catch(() => {})
  }, [filters])

  const loadHealth = useCallback(() => {
    api.get<{ data: typeof health }>('/streams/health/summary').then((r) => setHealth(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    loadHealth()
    const t = window.setInterval(loadHealth, 30000)
    return () => window.clearInterval(t)
  }, [loadHealth])

  const byId = useMemo(() => new Map(rows.map((r) => [r.stream_id, r])), [rows])
  const focusedRow = focus ? byId.get(focus) ?? null : null

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-white px-4 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold">Unified Live View</h1>
          {health && (
            <div className="flex items-center gap-2 text-2xs">
              <span className="badge badge-ok">ONLINE {health.ONLINE}</span>
              <span className="badge badge-crit">OFFLINE {health.OFFLINE}</span>
              <span className="badge badge-neutral">UNK {health.UNKNOWN}</span>
              <Activity className="h-3.5 w-3.5 text-ink-faint" />
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={filters.q}
            onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            placeholder="Search camera, district…"
            className="input-base w-52"
          />
          <select
            value={filters.vms_system}
            onChange={(e) => setFilters((f) => ({ ...f, vms_system: e.target.value }))}
            className="input-base w-40"
          >
            <option value="">All VMS</option>
            {vmsOptions.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>
          <select
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            className="input-base w-32"
          >
            <option value="">Any status</option>
            {['ONLINE', 'OFFLINE', 'UNKNOWN'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {playing ? (
            <button
              onClick={() => {
                setPlaying(false)
                setStartedIds(new Set())
              }}
              className="flex items-center gap-1 rounded border border-line bg-white px-2.5 py-1.5 text-xs text-ink hover:bg-canvas"
            >
              ■ Stop live
            </button>
          ) : (
            <button
              onClick={() => setPlaying(true)}
              className="flex items-center gap-1 rounded bg-accent px-2.5 py-1.5 text-xs text-white hover:opacity-90"
              title="Opens the first tiles; each tile can also be started individually"
            >
              ▶ Start live
            </button>
          )}
          <div className="flex overflow-hidden rounded border border-line">
            {GRID_PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => {
                  setPreset(p)
                  setSlots((prev) => {
                    const next = prev.slice(0, p.count)
                    while (next.length < p.count) next.push(null)
                    return next
                  })
                }}
                className={`flex items-center gap-1 px-2.5 py-1.5 text-xs ${
                  preset.id === p.id ? 'bg-accent text-white' : 'bg-white text-ink-muted hover:bg-canvas'
                }`}
              >
                <p.icon className="h-3.5 w-3.5" /> {p.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div
          className="grid flex-1 gap-2 overflow-auto p-3"
          style={{ gridTemplateColumns: `repeat(${preset.cols}, minmax(0, 1fr))`, gridAutoRows: 'minmax(220px, 1fr)' }}
        >
          {slots.slice(0, preset.count).map((id, i) => (
            <Tile
              key={`${i}-${id ?? 'empty'}`}
              stream={id ? byId.get(id) ?? null : null}
              startable={playing || (!!id && startedIds.has(id))}
              focused={focus === id}
              onFocus={() => setFocus(id)}
              onStart={() => id && setStartedIds((s) => new Set(s).add(id))}
              onRetry={() => {
                if (!id) return
                setStartedIds((s) => {
                  const next = new Set(s)
                  next.delete(id)
                  return next
                })
                window.setTimeout(() => setStartedIds((s) => new Set(s).add(id)), 100)
              }}
            />
          ))}
        </div>

        {focusedRow && (
          <aside className="w-80 shrink-0 overflow-auto border-l border-line bg-white p-4 animate-fadeIn">
            <div className="mb-3 flex items-start justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold leading-tight">{focusedRow.label}</h2>
                <p className="text-2xs text-ink-faint">{focusedRow.camera_code}</p>
              </div>
              <button onClick={() => setFocus(null)} className="text-ink-faint hover:text-ink" aria-label="Close">✕</button>
            </div>
            <dl className="space-y-2 text-xs">
              {[
                ['VMS system', focusedRow.vms_system],
                ['Department', focusedRow.department],
                ['District', focusedRow.district ?? '-'],
                ['Protocol', focusedRow.protocol],
                ['Status', focusedRow.status],
                ['Latency', focusedRow.latency_ms != null ? `${focusedRow.latency_ms} ms` : '-'],
                ['Last probe', fmtDateTime(focusedRow.last_probe_at)],
                ['Analytics', focusedRow.analytics_enabled ? 'Enabled (ANPR)' : 'Disabled'],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-ink-faint">{k}</dt>
                  <dd className="text-right font-medium">{v}</dd>
                </div>
              ))}
            </dl>
            {can('camera.write') && (
              <a
                className="btn-ghost mt-4 w-full"
                href={`/registry/${focusedRow.camera_id}`}
              >
                Open camera record
              </a>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}
