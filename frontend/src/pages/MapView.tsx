import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import maplibregl, { Map as MLMap } from 'maplibre-gl'
import { Filter, Layers } from 'lucide-react'
import { api } from '../lib/api'
import { statusBadge } from '../lib/format'

interface Feature {
  id: string
  geometry: { coordinates: [number, number] }
  properties: Record<string, string | boolean | null>
}
interface GeoJSON {
  features: Feature[]
}
interface Dept {
  department_id: string
  name: string
  code: string
}

const DEPT_COLORS: Record<string, string> = {
  POLICE: '#1e4bd8',
  HOME: '#7c3aed',
  FCS: '#b45309',
  RTO: '#0f766e',
  HEALTH: '#be185d',
  MUNICIPAL: '#15803d',
  GSRTC: '#b91c1c',
}

export default function MapView() {
  const mapDiv = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MLMap | null>(null)
  const [fc, setFc] = useState<GeoJSON | null>(null)
  const [depts, setDepts] = useState<Dept[]>([])
  const [selected, setSelected] = useState<Feature | null>(null)
  const [filters, setFilters] = useState({ department_id: '', camera_type: '', status: '', connectivity: '' })
  const [showFilters, setShowFilters] = useState(true)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!mapDiv.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: mapDiv.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
      },
      center: [71.6, 22.4],
      zoom: 6.2,
    })
    map.addControl(new maplibregl.NavigationControl(), 'top-right')
    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    Object.entries(filters).forEach(([k, v]) => v && p.set(k, v))
    return p.toString()
  }, [filters])

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const r = await api.get<{ data: GeoJSON; meta: { count: number } }>(`/gis/cameras${qs ? `?${qs}` : ''}`)
      setFc(r.data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load cameras')
    } finally {
      setLoading(false)
    }
  }, [qs])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    api.get<{ data: Dept[] }>('/departments').then((r) => setDepts(r.data)).catch(() => {})
  }, [])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !fc) return
    const paint = () => {
      const src = map.getSource('cams') as maplibregl.GeoJSONSource | undefined
      if (!src) {
        map.addSource('cams', { type: 'geojson', data: fc as unknown as GeoJSON.FeatureCollection })
        map.addLayer({
          id: 'cams-circle',
          type: 'circle',
          source: 'cams',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3.5, 9, 7, 13, 11],
            'circle-color': [
              'match',
              ['get', 'department_id'],
              ...Object.entries(DEPT_COLORS).flat(),
              '#5b6472',
            ] as unknown as maplibregl.ExpressionSpecification,
            'circle-stroke-color': ['match', ['get', 'connectivity_status'], 'ONLINE', '#ffffff', 'OFFLINE', '#b91c1c', '#d1d5db'],
            'circle-stroke-width': 1.5,
            'circle-opacity': 0.92,
          },
        })
      } else {
        src.setData(fc as unknown as GeoJSON.FeatureCollection)
      }
    }
    if (map.isStyleLoaded()) paint()
    else map.on('load', paint)
  }, [fc])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const onClick = (e: maplibregl.MapMouseEvent & { features?: unknown[] }) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: ['cams-circle'] })
      if (feats.length) setSelected(feats[0] as unknown as Feature)
    }
    const onHover = (e: maplibregl.MapMouseEvent) => {
      const feats = map.queryRenderedFeatures(e.point, { layers: ['cams-circle'] })
      map.getCanvas().style.cursor = feats.length ? 'pointer' : ''
    }
    map.on('click', onClick)
    map.on('mousemove', onHover)
    return () => {
      map.off('click', onClick)
      map.off('mousemove', onHover)
    }
  }, [fc])

  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) =>
    setFilters((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="flex h-full">
      {showFilters && (
        <aside className="w-64 shrink-0 space-y-4 overflow-auto border-r border-line bg-white p-4">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Filter className="h-4 w-4" /> Layers & filters
          </div>
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Department</label>
            <select value={filters.department_id} onChange={set('department_id')} className="input-base">
              <option value="">All departments</option>
              {depts.map((d) => (
                <option key={d.department_id} value={d.department_id}>{d.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Camera type</label>
            <select value={filters.camera_type} onChange={set('camera_type')} className="input-base">
              <option value="">All types</option>
              {['FIXED', 'PTZ', 'DOME', 'BULLET', 'ANPR'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Status</label>
            <select value={filters.status} onChange={set('status')} className="input-base">
              <option value="">Any status</option>
              {['ACTIVE', 'PENDING_VALIDATION', 'DECOMMISSIONED'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">Connectivity</label>
            <select value={filters.connectivity} onChange={set('connectivity')} className="input-base">
              <option value="">Any connectivity</option>
              {['ONLINE', 'OFFLINE', 'UNKNOWN'].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>
          <div className="border-t border-line pt-3">
            <div className="mb-2 flex items-center gap-2 text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              <Layers className="h-3.5 w-3.5" /> Department colors
            </div>
            <ul className="space-y-1">
              {Object.entries(DEPT_COLORS).map(([code, color]) => (
                <li key={code} className="flex items-center gap-2 text-xs text-ink-muted">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: color }} />
                  {code}
                </li>
              ))}
            </ul>
          </div>
        </aside>
      )}
      <div className="relative flex-1">
        <div ref={mapDiv} className="h-full w-full" />
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex items-center gap-2">
          <button className="btn-ghost pointer-events-auto" onClick={() => setShowFilters((s) => !s)}>
            <Filter className="h-3.5 w-3.5" /> {showFilters ? 'Hide' : 'Show'} filters
          </button>
          <span className="pointer-events-none rounded border border-line bg-white/95 px-2.5 py-1.5 text-2xs text-ink-muted shadow-sm">
            {loading ? 'Loading cameras...' : `${fc?.features.length ?? 0} cameras in view scope`}
          </span>
        </div>
        {err && (
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded border border-crit/30 bg-crit/10 px-3 py-2 text-xs text-crit">
            {err}
          </div>
        )}
        {selected && (
          <div className="absolute bottom-4 left-4 z-10 w-80 rounded border border-line bg-white shadow-lg animate-fadeIn">
            <div className="flex items-start justify-between border-b border-line px-3 py-2">
              <div>
                <div className="text-sm font-semibold">{String(selected.properties.name)}</div>
                <div className="font-mono text-2xs text-ink-faint">{String(selected.properties.camera_code)}</div>
              </div>
              <button onClick={() => setSelected(null)} className="text-ink-faint hover:text-ink" aria-label="Close">✕</button>
            </div>
            <dl className="space-y-1.5 px-3 py-2.5 text-xs">
              {[
                ['Department', String(selected.properties.department_name ?? '-')],
                ['Type', String(selected.properties.camera_type)],
                ['District', String(selected.properties.district ?? '-')],
                ['Connectivity', String(selected.properties.connectivity_status)],
                ['Maintenance', String(selected.properties.maintenance_status)],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-2">
                  <dt className="text-ink-faint">{k}</dt>
                  <dd className="text-right font-medium">{v}</dd>
                </div>
              ))}
            </dl>
            <div className="border-t border-line px-3 py-2">
              <span className={statusBadge(String(selected.properties.connectivity_status))}>
                {String(selected.properties.connectivity_status)}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
