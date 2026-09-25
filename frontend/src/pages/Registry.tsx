import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, Plus, Search } from 'lucide-react'
import { api, authHeaders } from '../lib/api'
import { fmtDate, statusBadge } from '../lib/format'

interface Cam {
  camera_id: string
  camera_code: string
  name: string
  department_id: string
  camera_type: string
  district: string | null
  connectivity_status: string
  maintenance_status: string
  status: string
  storage_type: string | null
  vendor: string | null
  install_date: string | null
}
interface Dept {
  department_id: string
  name: string
}

export default function Registry() {
  const [rows, setRows] = useState<Cam[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [depts, setDepts] = useState<Dept[]>([])
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState({ department_id: '', district: '', camera_type: '', connectivity: '', maintenance: '' })
  const [loading, setLoading] = useState(true)

  const qs = useMemo(() => {
    const p = new URLSearchParams({ page: String(page), page_size: '25' })
    if (search) p.set('search', search)
    Object.entries(filters).forEach(([k, v]) => v && p.set(k, v))
    return p.toString()
  }, [page, search, filters])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get<{ data: Cam[]; meta: { total: number } }>(`/cameras?${qs}`)
      setRows(r.data)
      setTotal(r.meta.total)
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

  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => {
    setPage(1)
    setFilters((f) => ({ ...f, [k]: e.target.value }))
  }

  const exportCsv = () => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    Object.entries(filters).forEach(([k, v]) => v && params.set(k, v))
    fetch(`/api/v1/cameras/export.csv?${params}`, { headers: authHeaders() })
      .then((r) => r.blob())
      .then((b) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b)
        a.download = 'cameras_export.csv'
        a.click()
      })
  }

  const pages = Math.max(1, Math.ceil(total / 25))

  return (
    <div className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Camera Registry</h1>
          <p className="text-xs text-ink-muted">{total.toLocaleString('en-IN')} cameras in your scope</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={exportCsv} className="btn-ghost">
            <Download className="h-4 w-4" /> Export CSV
          </button>
          <Link to="/onboarding" className="btn-primary">
            <Plus className="h-4 w-4" /> Add camera
          </Link>
        </div>
      </div>

      <div className="panel mb-3 flex flex-wrap items-center gap-2 p-3">
        <div className="relative min-w-56 flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => {
              setPage(1)
              setSearch(e.target.value)
            }}
            placeholder="Search name, code, district, vendor..."
            className="input-base pl-8"
          />
        </div>
        <select value={filters.department_id} onChange={set('department_id')} className="input-base w-44">
          <option value="">All departments</option>
          {depts.map((d) => (
            <option key={d.department_id} value={d.department_id}>{d.name}</option>
          ))}
        </select>
        <select value={filters.camera_type} onChange={set('camera_type')} className="input-base w-36">
          <option value="">All types</option>
          {['FIXED', 'PTZ', 'DOME', 'BULLET', 'ANPR'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <select value={filters.connectivity} onChange={set('connectivity')} className="input-base w-36">
          <option value="">Connectivity</option>
          {['ONLINE', 'OFFLINE', 'UNKNOWN'].map((t) => <option key={t}>{t}</option>)}
        </select>
        <select value={filters.maintenance} onChange={set('maintenance')} className="input-base w-36">
          <option value="">Maintenance</option>
          {['OK', 'DUE', 'FAULTY'].map((t) => <option key={t}>{t}</option>)}
        </select>
      </div>

      <div className="panel overflow-x-auto">
        <table className="table-base">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>District</th>
              <th>Connectivity</th>
              <th>Maintenance</th>
              <th>Installed</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr><td colSpan={8} className="py-8 text-center text-ink-muted">Loading cameras...</td></tr>
            )}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={8} className="py-8 text-center text-ink-muted">No cameras match these filters.</td></tr>
            )}
            {rows.map((c) => (
              <tr key={c.camera_id}>
                <td className="font-mono text-xs">
                  <Link to={`/registry/${c.camera_id}`} className="text-accent hover:underline">{c.camera_code}</Link>
                </td>
                <td className="font-medium">{c.name}</td>
                <td>{c.camera_type}</td>
                <td>{c.district ?? '-'}</td>
                <td><span className={statusBadge(c.connectivity_status)}>{c.connectivity_status}</span></td>
                <td><span className={statusBadge(c.maintenance_status)}>{c.maintenance_status}</span></td>
                <td>{fmtDate(c.install_date)}</td>
                <td><span className={statusBadge(c.status)}>{c.status}</span></td>
              </tr>
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
