import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Grid3X3,
  LayoutGrid,
  Rows3,
  Radio,
  Activity,
  Save,
  Trash2,
  ScanLine,
  Sparkles,
  Layers,
  Cpu,
  RefreshCw,
  ExternalLink,
} from 'lucide-react'
import { api } from '../lib/api'
import { StreamRow, WallSummary, createWall, deleteWall, listWalls, useHlsStream } from '../lib/streams'
import { fmtDateTime } from '../lib/format'
import { useAuth } from '../lib/auth'
import {
  PlateDetection,
  detectFrame,
  toggleAnpr,
  getCachedCrops,
  CachedPlate,
} from '../lib/anpr'
import AnprModal from '../components/AnprModal'

const GRID_PRESETS = [
  { id: '2x2', label: '2×2', cols: 2, count: 4, icon: Grid3X3 },
  { id: '3x3', label: '3×3', cols: 3, count: 9, icon: LayoutGrid },
  { id: '1+5', label: '1+5', cols: 3, count: 6, icon: Rows3 },
]

function Tile({
  stream,
  startable,
  focused,
  anprActive,
  onFocus,
  onStart,
  onRetry,
  onToggleAnpr,
  onInspectAnpr,
}: {
  stream: StreamRow | null
  startable: boolean
  focused: boolean
  anprActive: boolean
  onFocus: () => void
  onStart: () => void
  onRetry: () => void
  onToggleAnpr: () => void
  onInspectAnpr: () => void
}) {
  const { videoRef, state } = useHlsStream(startable ? stream?.stream_id ?? null : null)
  const [detections, setDetections] = useState<PlateDetection[]>([])
  const isAnalyzingRef = useRef(false)

  // Live ANPR frame capture loop when ANPR is toggled ON
  useEffect(() => {
    if (!anprActive || state !== 'live' || !stream) {
      setDetections([])
      return
    }

    const intervalId = window.setInterval(async () => {
      const vid = videoRef.current
      if (!vid || vid.readyState < 2 || isAnalyzingRef.current) return

      try {
        isAnalyzingRef.current = true
        const offCanvas = document.createElement('canvas')
        offCanvas.width = vid.videoWidth || 640
        offCanvas.height = vid.videoHeight || 360
        const ctx = offCanvas.getContext('2d')
        if (ctx) {
          ctx.drawImage(vid, 0, 0, offCanvas.width, offCanvas.height)
          const b64 = offCanvas.toDataURL('image/jpeg', 0.8)
          const res = await detectFrame(b64, stream.stream_id, stream.camera_id, 0.25)
          setDetections(res.detections)
        }
      } catch {
        /* ignore error and keep feed playing */
      } finally {
        isAnalyzingRef.current = false
      }
    }, 1500)

    return () => window.clearInterval(intervalId)
  }, [anprActive, state, stream])

  return (
    <div
      className={`panel relative flex min-h-0 flex-col overflow-hidden transition-all ${
        focused ? 'ring-2 ring-accent' : ''
      }`}
      onClick={onFocus}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onFocus()}
    >
      <div className="relative flex-1 bg-black">
        <video
          ref={videoRef}
          muted
          autoPlay
          playsInline
          crossOrigin="anonymous"
          className="h-full w-full object-contain"
        />

        {/* Live Badge */}
        {state === 'live' && (
          <span className="absolute left-2 top-2 z-10 flex items-center gap-1 rounded bg-black/60 px-1.5 py-0.5 text-2xs font-semibold text-red-400 backdrop-blur-xs">
            <Radio className="h-3 w-3 animate-pulse" /> LIVE
          </span>
        )}

        {/* ANPR ON / OFF Toggle Button on the Live Feed */}
        {stream && state === 'live' && (
          <div className="absolute right-2 top-2 z-20 flex items-center gap-1.5">
            <button
              onClick={(e) => {
                e.stopPropagation()
                onToggleAnpr()
              }}
              className={`flex items-center gap-1 rounded px-2 py-0.5 text-2xs font-bold shadow transition-all ${
                anprActive
                  ? 'bg-emerald-600 text-white ring-1 ring-emerald-400 shadow-emerald-500/30'
                  : 'bg-black/70 text-white/80 hover:bg-black/90 hover:text-white'
              }`}
              title={anprActive ? 'ANPR Running (YOLO + OCR): Click to Turn Off' : 'Click to Turn ON ANPR on this feed'}
            >
              <ScanLine className={`h-3 w-3 ${anprActive ? 'animate-pulse text-emerald-200' : ''}`} />
              <span>{anprActive ? 'ANPR ON' : 'ANPR OFF'}</span>
            </button>
            {anprActive && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onInspectAnpr()
                }}
                className="rounded bg-black/70 p-1 text-white/80 hover:bg-black hover:text-white"
                title="Inspect in ANPR Studio"
              >
                <ExternalLink className="h-3 w-3" />
              </button>
            )}
          </div>
        )}

        {/* Real-time SVG Tactical Bounding Boxes & Plate Labels on the Live Feed */}
        {anprActive && detections.length > 0 && videoRef.current && (
          <svg
            className="pointer-events-none absolute inset-0 z-10 h-full w-full"
            viewBox={`0 0 ${videoRef.current.videoWidth || 640} ${videoRef.current.videoHeight || 360}`}
            preserveAspectRatio="xMidYMid meet"
          >
            {detections.map((d) => {
              const [x1, y1, x2, y2] = d.bbox
              const w = x2 - x1
              const h = y2 - y1
              const corner = Math.min(14, w / 3)
              const isHigh = d.confidence >= 0.6
              const strokeColor = isHigh ? '#00e676' : '#ffb300'

              return (
                <g key={d.crop_id} className="animate-fadeIn">
                  {/* Bounding Box */}
                  <rect
                    x={x1}
                    y={y1}
                    width={w}
                    height={h}
                    fill={isHigh ? 'rgba(0, 230, 118, 0.12)' : 'rgba(255, 179, 0, 0.12)'}
                    stroke={strokeColor}
                    strokeWidth="1.5"
                  />
                  {/* Tactical Corners */}
                  <path
                    d={`M ${x1} ${y1 + corner} L ${x1} ${y1} L ${x1 + corner} ${y1}
                        M ${x2 - corner} ${y1} L ${x2} ${y1} L ${x2} ${y1 + corner}
                        M ${x1} ${y2 - corner} L ${x1} ${y2} L ${x1 + corner} ${y2}
                        M ${x2 - corner} ${y2} L ${x2} ${y2} L ${x2} ${y2 - corner}`}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth="3"
                    strokeLinecap="round"
                  />
                  {/* Floating Plate Text Pill */}
                  <rect
                    x={x1}
                    y={Math.max(4, y1 - 22)}
                    width={Math.max(w, 120)}
                    height="18"
                    rx="3"
                    fill="#10141a"
                    stroke={strokeColor}
                    strokeWidth="1"
                  />
                  <text
                    x={x1 + 6}
                    y={Math.max(16, y1 - 9)}
                    fill="#ffffff"
                    fontSize="10.5"
                    fontWeight="bold"
                    fontFamily="monospace"
                  >
                    {d.plate_text} · {Math.round(d.confidence * 100)}%
                  </text>
                </g>
              )
            })}
          </svg>
        )}

        {/* State Overlays */}
        {state !== 'live' && (
          <div className="absolute inset-0 flex items-center justify-center bg-ink/80 text-xs text-white/80">
            {state === 'connecting'
              ? 'Connecting to camera…'
              : state === 'cooldown'
              ? 'Watch-time cooldown · click to retry later'
              : state === 'error'
              ? 'Feed unavailable · retries exhausted · click Start to retry'
              : startable
              ? 'Starting…'
              : (
                <button
                  className="flex items-center gap-2 rounded-full bg-white/10 px-4 py-2 text-xs text-white/90 ring-1 ring-white/25 hover:bg-white/20"
                  onClick={(e) => {
                    e.stopPropagation()
                    onStart()
                  }}
                >
                  ▶ Play this camera
                </button>
              )}
          </div>
        )}

        {state === 'cooldown' && (
          <button
            className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-2xs text-white/80 hover:bg-black/80"
            onClick={(e) => {
              e.stopPropagation()
              onRetry()
            }}
          >
            ↻ Retry
          </button>
        )}
      </div>

      {stream && (
        <div className="flex items-center justify-between gap-2 border-t border-line bg-white px-2.5 py-1.5">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="truncate text-xs font-medium">{stream.label}</span>
              {anprActive && (
                <span className="flex items-center gap-0.5 rounded bg-emerald-100 px-1 py-0.2 text-3xs font-bold text-emerald-800">
                  <Cpu className="h-2.5 w-2.5" /> AI
                </span>
              )}
            </div>
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
  const [playing, setPlaying] = useState(false)
  const [startedIds, setStartedIds] = useState<Set<string>>(new Set())
  const [activeAnprIds, setActiveAnprIds] = useState<Set<string>>(new Set())
  const [preset, setPreset] = useState(GRID_PRESETS[0])
  const [slots, setSlots] = useState<(string | null)[]>(Array(9).fill(null))
  const [focus, setFocus] = useState<string | null>(null)
  const [filters, setFilters] = useState({ q: '', vms_system: '', status: '' })
  const [vmsOptions, setVmsOptions] = useState<string[]>([])
  const [health, setHealth] = useState<{ ONLINE: number; OFFLINE: number; UNKNOWN: number; total: number } | null>(null)

  // Saved video walls
  const [walls, setWalls] = useState<WallSummary[]>([])
  const [wallName, setWallName] = useState('')
  const [selectedWallId, setSelectedWallId] = useState('')

  // ANPR Studio & Cached crops
  const [studioOpen, setStudioOpen] = useState(false)
  const [studioStream, setStudioStream] = useState<StreamRow | null>(null)
  const [cachedPlates, setCachedPlates] = useState<CachedPlate[]>([])

  const loadAnprData = useCallback(() => {
    getCachedCrops(undefined, 20)
      .then(setCachedPlates)
      .catch(() => {})
  }, [])

  useEffect(() => {
    listWalls().then(setWalls).catch(() => {})
    loadAnprData()
    const t = window.setInterval(loadAnprData, 5000)
    return () => window.clearInterval(t)
  }, [loadAnprData])

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

  // Per-stream ANPR toggle
  const toggleStreamAnpr = async (streamId: string) => {
    const isCurrentlyActive = activeAnprIds.has(streamId)
    const nextState = !isCurrentlyActive
    setActiveAnprIds((prev) => {
      const next = new Set(prev)
      if (nextState) next.add(streamId)
      else next.delete(streamId)
      return next
    })
    try {
      await toggleAnpr(nextState, streamId)
      loadAnprData()
    } catch {
      /* ignore */
    }
  }

  // Master ANPR toggle for all currently playing streams
  const toggleAllAnpr = async () => {
    const allOn = slots.some((id) => id && activeAnprIds.has(id))
    const next = !allOn
    const activeStreamIds = slots.filter((id): id is string => id !== null)

    setActiveAnprIds((prev) => {
      const updated = new Set(prev)
      activeStreamIds.forEach((id) => {
        if (next) updated.add(id)
        else updated.delete(id)
      })
      return updated
    })

    try {
      await toggleAnpr(next, null)
      loadAnprData()
    } catch {
      /* ignore */
    }
  }

  const saveCurrentWall = () => {
    const name = wallName.trim()
    if (!name) return
    const tiles = slots
      .map((id, slot) => (id ? { stream_id: id, slot } : null))
      .filter((t): t is { stream_id: string; slot: number } => t !== null)
    if (!tiles.length) return
    createWall(name, tiles)
      .then((w) => {
        setWalls((prev) => [w, ...prev.filter((x) => x.wall_id !== w.wall_id)])
        setSelectedWallId(w.wall_id)
        setWallName('')
      })
      .catch(() => {})
  }

  const applyWall = (w: WallSummary) => {
    const next: (string | null)[] = Array(9).fill(null)
    for (const t of w.tiles) if (t.slot < 9) next[t.slot] = t.stream_id
    setSlots(next)
    setStartedIds(new Set(w.tiles.map((t) => t.stream_id)))
  }

  const removeWall = (wallId: string) => {
    deleteWall(wallId)
      .then(() => {
        setWalls((prev) => prev.filter((w) => w.wall_id !== wallId))
        setSelectedWallId((cur) => (cur === wallId ? '' : cur))
      })
      .catch(() => {})
  }

  const anyAnprActive = activeAnprIds.size > 0

  return (
    <div className="flex h-full flex-col">
      {/* Top Bar */}
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
          {/* Master ANPR Toggle Button */}
          <button
            onClick={toggleAllAnpr}
            className={`flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-bold transition-all ${
              anyAnprActive
                ? 'bg-emerald-600 text-white shadow-sm ring-1 ring-emerald-400'
                : 'border border-line bg-white text-ink hover:bg-canvas'
            }`}
            title="Start or Stop ANPR processing on all active camera feeds"
          >
            <ScanLine className={`h-3.5 w-3.5 ${anyAnprActive ? 'animate-pulse text-emerald-200' : ''}`} />
            <span>{anyAnprActive ? `ANPR Active (${activeAnprIds.size})` : 'Start ANPR'}</span>
          </button>

          {/* ANPR Studio Launcher */}
          <button
            onClick={() => {
              setStudioStream(focusedRow)
              setStudioOpen(true)
            }}
            className="flex items-center gap-1.5 rounded border border-emerald-500/40 bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-100"
            title="Open ANPR Studio for video testing, OpenCV inspection & in-memory cache"
          >
            <Sparkles className="h-3.5 w-3.5 text-emerald-600" />
            <span>ANPR Studio & Video AI</span>
            {cachedPlates.length > 0 && (
              <span className="rounded-full bg-emerald-600 px-1.5 py-0.2 text-3xs font-mono font-bold text-white">
                {cachedPlates.length}
              </span>
            )}
          </button>

          <input
            value={filters.q}
            onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))}
            placeholder="Search camera, district…"
            className="input-base w-48"
          />

          <select
            value={filters.vms_system}
            onChange={(e) => setFilters((f) => ({ ...f, vms_system: e.target.value }))}
            className="input-base w-36"
          >
            <option value="">All VMS</option>
            {vmsOptions.map((v) => (
              <option key={v}>{v}</option>
            ))}
          </select>

          <select
            value={filters.status}
            onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}
            className="input-base w-28"
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

          <div className="flex items-center gap-1">
            <input
              value={wallName}
              onChange={(e) => setWallName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && saveCurrentWall()}
              placeholder="Save wall as…"
              className="input-base w-28"
            />
            <button
              onClick={saveCurrentWall}
              disabled={!wallName.trim()}
              className="flex items-center gap-1 rounded border border-line bg-white px-2 py-1.5 text-xs text-ink hover:bg-canvas disabled:opacity-40"
              title="Save current tile layout as a named wall"
            >
              <Save className="h-3.5 w-3.5" />
            </button>
            {walls.length > 0 && (
              <>
                <select
                  value={selectedWallId}
                  onChange={(e) => {
                    setSelectedWallId(e.target.value)
                    const w = walls.find((x) => x.wall_id === e.target.value)
                    if (w) applyWall(w)
                  }}
                  className="input-base w-32"
                  title="Load a saved wall layout"
                >
                  <option value="">Load wall…</option>
                  {walls.map((w) => (
                    <option key={w.wall_id} value={w.wall_id}>
                      {w.name}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => selectedWallId && removeWall(selectedWallId)}
                  disabled={!selectedWallId}
                  className="rounded border border-line bg-white px-2 py-1.5 text-ink-muted hover:bg-canvas disabled:opacity-40"
                  title="Delete selected wall"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Main Grid View */}
      <div className="flex flex-1 overflow-hidden">
        <div
          className="grid flex-1 gap-2 overflow-auto p-3"
          style={{ gridTemplateColumns: `repeat(${preset.cols}, minmax(0, 1fr))`, gridAutoRows: 'minmax(220px, 1fr)' }}
        >
          {slots.slice(0, preset.count).map((id, i) => {
            const s = id ? byId.get(id) ?? null : null
            const isAnprOn = id ? activeAnprIds.has(id) : false

            return (
              <Tile
                key={`${i}-${id ?? 'empty'}`}
                stream={s}
                startable={playing || (!!id && startedIds.has(id))}
                focused={focus === id}
                anprActive={isAnprOn}
                onFocus={() => setFocus(id)}
                onStart={() => id && setStartedIds((prev) => new Set(prev).add(id))}
                onToggleAnpr={() => id && toggleStreamAnpr(id)}
                onInspectAnpr={() => {
                  setStudioStream(s)
                  setStudioOpen(true)
                }}
                onRetry={() => {
                  if (!id) return
                  setStartedIds((prev) => {
                    const next = new Set(prev)
                    next.delete(id)
                    return next
                  })
                  window.setTimeout(() => setStartedIds((prev) => new Set(prev).add(id)), 100)
                }}
              />
            )
          })}
        </div>

        {/* Focused Camera Sidebar with ANPR Controls & In-Memory Cache */}
        {focusedRow && (
          <aside className="flex w-84 shrink-0 flex-col overflow-auto border-l border-line bg-white animate-fadeIn">
            <div className="border-b border-line p-4">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <h2 className="text-sm font-semibold leading-tight">{focusedRow.label}</h2>
                  <p className="text-2xs text-ink-faint">{focusedRow.camera_code}</p>
                </div>
                <button
                  onClick={() => setFocus(null)}
                  className="text-ink-faint hover:text-ink"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>

              {/* ANPR Dedicated Action Card in Sidebar */}
              <div className="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-50/50 p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ScanLine className="h-4 w-4 text-emerald-600" />
                    <span className="text-xs font-bold text-emerald-900">YOLO ANPR Engine</span>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-3xs font-bold ${
                      activeAnprIds.has(focusedRow.stream_id)
                        ? 'bg-emerald-600 text-white animate-pulse'
                        : 'bg-zinc-200 text-zinc-700'
                    }`}
                  >
                    {activeAnprIds.has(focusedRow.stream_id) ? 'ACTIVE' : 'OFF'}
                  </span>
                </div>
                <p className="mt-1 text-2xs text-emerald-800/80">
                  Model: YOLO11n · Crops cached in RAM · pytesseract OCR
                </p>
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => toggleStreamAnpr(focusedRow.stream_id)}
                    className={`flex-1 rounded py-1.5 text-xs font-bold text-white shadow-xs transition-colors ${
                      activeAnprIds.has(focusedRow.stream_id)
                        ? 'bg-red-600 hover:bg-red-500'
                        : 'bg-emerald-600 hover:bg-emerald-500'
                    }`}
                  >
                    {activeAnprIds.has(focusedRow.stream_id) ? '■ Stop ANPR' : '▶ Start ANPR'}
                  </button>
                  <button
                    onClick={() => {
                      setStudioStream(focusedRow)
                      setStudioOpen(true)
                    }}
                    className="rounded border border-emerald-600/30 bg-white px-2.5 py-1.5 text-xs font-medium text-emerald-800 hover:bg-emerald-50"
                    title="Open studio with video tools"
                  >
                    Studio
                  </button>
                </div>
              </div>
            </div>

            {/* Recent In-Memory Cached Crops for this Stream */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-xs font-bold text-ink">
                  <Layers className="h-3.5 w-3.5 text-emerald-600" />
                  <span>Recent Plate Crops (RAM Cache)</span>
                </div>
                <button
                  onClick={loadAnprData}
                  className="rounded p-1 text-ink-faint hover:bg-canvas hover:text-ink"
                  title="Refresh cache"
                >
                  <RefreshCw className="h-3 w-3" />
                </button>
              </div>

              {cachedPlates.length === 0 ? (
                <div className="rounded border border-dashed border-line p-4 text-center text-2xs text-ink-faint">
                  No plates cached in RAM yet. Start ANPR above to begin capturing plates.
                </div>
              ) : (
                <div className="space-y-2">
                  {cachedPlates.slice(0, 5).map((cp) => (
                    <div
                      key={cp.crop_id}
                      className="flex gap-2.5 rounded border border-line bg-canvas/40 p-2 text-xs"
                    >
                      {cp.crop_base64 && (
                        <img
                          src={cp.crop_base64}
                          alt={cp.plate_text}
                          className="h-10 w-16 rounded border border-line object-contain bg-black"
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-bold text-ink">{cp.plate_text}</span>
                          <span className="rounded bg-emerald-100 px-1 text-3xs font-semibold text-emerald-800">
                            {Math.round(cp.confidence * 100)}%
                          </span>
                        </div>
                        <div className="text-3xs text-ink-faint">
                          {new Date(cp.timestamp).toLocaleTimeString()} · RAM Cache
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <hr className="my-4 border-line" />

              <dl className="space-y-2 text-xs">
                {[
                  ['VMS system', focusedRow.vms_system],
                  ['Department', focusedRow.department],
                  ['District', focusedRow.district ?? '-'],
                  ['Protocol', focusedRow.protocol],
                  ['Status', focusedRow.status],
                  ['Latency', focusedRow.latency_ms != null ? `${focusedRow.latency_ms} ms` : '-'],
                  ['Last probe', fmtDateTime(focusedRow.last_probe_at)],
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="text-ink-faint">{k}</dt>
                    <dd className="text-right font-medium">{v}</dd>
                  </div>
                ))}
              </dl>

              {can('camera.write') && (
                <a
                  className="btn-ghost mt-4 block w-full text-center"
                  href={`/registry/${focusedRow.camera_id}`}
                >
                  Open camera record
                </a>
              )}
            </div>
          </aside>
        )}
      </div>

      {/* ANPR Studio Modal */}
      <AnprModal
        isOpen={studioOpen}
        onClose={() => setStudioOpen(false)}
        selectedStream={studioStream}
        activeStreams={rows}
      />
    </div>
  )
}
