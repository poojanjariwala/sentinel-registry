import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, MonitorPlay, Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime, statusBadge } from '../lib/format'

interface Cam {
  camera_id: string
  camera_code: string
  name: string
  department_id: string
  camera_type: string
  ownership: string
  public_facing: boolean
  vendor: string | null
  model: string | null
  ip_address: string | null
  latitude: number | null
  longitude: number | null
  district: string | null
  taluka: string | null
  address: string | null
  connectivity_status: string
  storage_type: string | null
  retention_days: number | null
  install_date: string | null
  amc_vendor: string | null
  amc_end_date: string | null
  maintenance_status: string
  status: string
  coverage_radius_m: number | null
  created_at: string | null
  updated_at: string | null
}

export default function CameraDetail() {
  const { cameraId } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [cam, setCam] = useState<Cam | null>(null)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<Partial<Cam>>({})
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!cameraId) return
    const r = await api.get<{ data: Cam }>(`/cameras/${cameraId}`)
    setCam(r.data)
    setForm({})
  }, [cameraId])

  useEffect(() => {
    load().catch((e) => setErr(e instanceof Error ? e.message : 'Failed to load camera'))
  }, [load])

  const save = async () => {
    if (!cameraId) return
    setSaving(true)
    setErr(null)
    try {
      await api.patch(`/cameras/${cameraId}`, form)
      setEditing(false)
      await load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setSaving(false)
    }
  }

  if (!cam) return <div className="p-6 text-sm text-ink-muted">{err ?? 'Loading...'}</div>

  const field = (k: keyof Cam, label: string, editable: false | 'text' | 'date' = false) => (
    <div className="flex justify-between gap-3 py-1.5">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="text-right font-medium">
        {editing && editable === 'text' ? (
          <input
            className="input-base w-48 text-right"
            value={String((form[k] as string) ?? (cam[k] as string) ?? '')}
            onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
          />
        ) : editing && editable === 'date' ? (
          <input
            type="date"
            className="input-base w-40 text-right"
            value={String((form[k] as string) ?? (cam[k] as string) ?? '').slice(0, 10)}
            onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))}
          />
        ) : (
          String(cam[k] ?? '-')
        )}
      </dd>
    </div>
  )

  const setConn = (v: string) => setForm((f) => ({ ...f, connectivity_status: v as Cam['connectivity_status'] }))
  const setMaint = (v: string) => setForm((f) => ({ ...f, maintenance_status: v as Cam['maintenance_status'] }))
  const setStatus = (v: string) => setForm((f) => ({ ...f, status: v as Cam['status'] }))

  return (
    <div className="p-5">
      <button onClick={() => navigate(-1)} className="mb-4 flex items-center gap-1.5 text-xs text-ink-muted hover:text-ink">
        <ArrowLeft className="h-3.5 w-3.5" /> Back
      </button>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">{cam.name}</h1>
          <p className="font-mono text-xs text-ink-faint">{cam.camera_code}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={statusBadge(cam.connectivity_status)}>{cam.connectivity_status}</span>
          <span className={statusBadge(cam.maintenance_status)}>{cam.maintenance_status}</span>
          {can('camera.read') && (
            <a href="/live" className="btn-ghost" title="Open the unified live view">
              <MonitorPlay className="h-3.5 w-3.5" /> View live
            </a>
          )}
          {can('camera.write') && (
            <button
              onClick={() => (editing ? save() : setEditing(true))}
              disabled={saving}
              className={editing ? 'btn-primary' : 'btn-ghost'}
            >
              <Pencil className="h-3.5 w-3.5" /> {editing ? (saving ? 'Saving...' : 'Save changes') : 'Edit'}
            </button>
          )}
        </div>
      </div>

      {err && <div className="mb-4 rounded border border-crit/30 bg-crit/10 px-3 py-2 text-xs text-crit">{err}</div>}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Asset details</h2>
          <dl className="divide-y divide-line/60 text-sm">
            {field('camera_type', 'Camera type', 'text')}
            {field('vendor', 'Vendor', 'text')}
            {field('model', 'Model', 'text')}
            {field('ip_address', 'IP address', 'text')}
            {field('ownership', 'Ownership')}
            {field('public_facing', 'Public facing')}
          </dl>
        </section>

        <section className="panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Location</h2>
          <dl className="divide-y divide-line/60 text-sm">
            {field('district', 'District', 'text')}
            {field('taluka', 'Taluka', 'text')}
            {field('address', 'Address', 'text')}
            <div className="flex justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Coordinates</dt>
              <dd className="font-mono text-xs">
                {cam.latitude ?? '-'}, {cam.longitude ?? '-'}
              </dd>
            </div>
          </dl>
        </section>

        <section className="panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Operations</h2>
          <dl className="divide-y divide-line/60 text-sm">
            <div className="flex items-center justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Connectivity</dt>
              <dd>
                {editing ? (
                  <select className="input-base w-36" value={form.connectivity_status ?? cam.connectivity_status} onChange={(e) => setConn(e.target.value)}>
                    {['ONLINE', 'OFFLINE', 'UNKNOWN'].map((v) => <option key={v}>{v}</option>)}
                  </select>
                ) : (
                  <span className={statusBadge(cam.connectivity_status)}>{cam.connectivity_status}</span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Maintenance</dt>
              <dd>
                {editing ? (
                  <select className="input-base w-36" value={form.maintenance_status ?? cam.maintenance_status} onChange={(e) => setMaint(e.target.value)}>
                    {['OK', 'DUE', 'FAULTY'].map((v) => <option key={v}>{v}</option>)}
                  </select>
                ) : (
                  <span className={statusBadge(cam.maintenance_status)}>{cam.maintenance_status}</span>
                )}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Registry status</dt>
              <dd>
                {editing ? (
                  <select className="input-base w-44" value={form.status ?? cam.status} onChange={(e) => setStatus(e.target.value)}>
                    {['ACTIVE', 'PENDING_VALIDATION', 'DECOMMISSIONED'].map((v) => <option key={v}>{v}</option>)}
                  </select>
                ) : (
                  <span className={statusBadge(cam.status)}>{cam.status}</span>
                )}
              </dd>
            </div>
            {field('storage_type', 'Storage', 'text')}
            {field('retention_days', 'Retention (days)')}
          </dl>
        </section>

        <section className="panel p-4">
          <h2 className="mb-2 text-sm font-semibold">Lifecycle & AMC</h2>
          <dl className="divide-y divide-line/60 text-sm">
            {field('install_date', 'Install date', 'date')}
            {field('amc_vendor', 'AMC vendor', 'text')}
            {field('amc_end_date', 'AMC end date', 'date')}
            {field('coverage_radius_m', 'Coverage radius (m)')}
            <div className="flex justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Record created</dt>
              <dd>{fmtDateTime(cam.created_at)}</dd>
            </div>
            <div className="flex justify-between gap-3 py-1.5">
              <dt className="text-ink-faint">Record updated</dt>
              <dd>{fmtDateTime(cam.updated_at)}</dd>
            </div>
          </dl>
        </section>
      </div>
    </div>
  )
}
