import { FormEvent, useCallback, useEffect, useState } from 'react'
import { FileSpreadsheet, ShieldAlert, Upload } from 'lucide-react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

interface Dept { department_id: string; name: string }
interface ImportResult {
  batch_id: string
  dry_run: boolean
  total_rows: number
  created: number
  updated: number
  errors: number
  warning_count: number
  report: {
    rows: { row: number; errors: string[] }[]
    warnings: { row: number; warnings: string[] }[]
  }
}

const EMPTY = {
  camera_code: '',
  name: '',
  department_id: '',
  camera_type: 'FIXED',
  latitude: '',
  longitude: '',
  district: '',
  vendor: '',
  storage_type: 'NVR',
  retention_days: '30',
  connectivity_status: 'UNKNOWN',
}

export default function Onboarding() {
  const { can } = useAuth()
  const [depts, setDepts] = useState<Dept[]>([])
  const [form, setForm] = useState(EMPTY)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)

  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [importing, setImporting] = useState(false)

  useEffect(() => {
    api.get<{ data: Dept[] }>('/departments').then((r) => setDepts(r.data)).catch(() => {})
  }, [])

  const submitManual = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMsg(null)
    try {
      await api.post('/cameras', {
        ...form,
        latitude: form.latitude ? parseFloat(form.latitude) : null,
        longitude: form.longitude ? parseFloat(form.longitude) : null,
        retention_days: form.retention_days ? parseInt(form.retention_days) : null,
      })
      setMsg({ kind: 'ok', text: `Camera ${form.camera_code} registered successfully.` })
      setForm(EMPTY)
    } catch (err) {
      setMsg({ kind: 'err', text: err instanceof Error ? err.message : 'Registration failed' })
    } finally {
      setBusy(false)
    }
  }

  const runImport = useCallback(async (dryRun: boolean) => {
    if (!file) return
    setImporting(true)
    setResult(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      // API returns an envelope: { data: ImportResult, meta, requestId }
      const r = await api.upload<{ data: ImportResult }>(`/cameras/import?dry_run=${dryRun}`, fd)
      setResult(r.data)
    } catch (err) {
      setMsg({ kind: 'err', text: err instanceof Error ? err.message : 'Import failed' })
    } finally {
      setImporting(false)
    }
  }, [file])

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  if (!can('camera.write') && !can('camera.import')) {
    return <div className="p-6 text-sm text-ink-muted">You do not have permission to onboard cameras.</div>
  }

  return (
    <div className="mx-auto max-w-5xl p-5">
      <h1 className="text-lg font-semibold">Camera Onboarding</h1>
      <p className="mb-4 text-xs text-ink-muted">Manual entry or bulk CSV/XLSX import with validation before commit.</p>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <h2 className="mb-3 text-sm font-semibold">Manual entry</h2>
          <form onSubmit={submitManual} className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Camera code *</label>
              <input required className="input-base" value={form.camera_code} onChange={set('camera_code')} placeholder="CAM-XXXX-001" />
            </div>
            <div className="col-span-2">
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Name *</label>
              <input required className="input-base" value={form.name} onChange={set('name')} />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Department *</label>
              <select required className="input-base" value={form.department_id} onChange={set('department_id')}>
                <option value="">Select...</option>
                {depts.map((d) => <option key={d.department_id} value={d.department_id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Type</label>
              <select className="input-base" value={form.camera_type} onChange={set('camera_type')}>
                {['FIXED', 'PTZ', 'DOME', 'BULLET', 'ANPR'].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Latitude *</label>
              <input required className="input-base" value={form.latitude} onChange={set('latitude')} placeholder="23.0225" />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Longitude *</label>
              <input required className="input-base" value={form.longitude} onChange={set('longitude')} placeholder="72.5714" />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">District</label>
              <input className="input-base" value={form.district} onChange={set('district')} />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Vendor</label>
              <input className="input-base" value={form.vendor} onChange={set('vendor')} />
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Storage</label>
              <select className="input-base" value={form.storage_type} onChange={set('storage_type')}>
                {['CLOUD', 'LOCAL', 'NVR', 'NONE'].map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Retention (days)</label>
              <input className="input-base" value={form.retention_days} onChange={set('retention_days')} />
            </div>
            <div className="col-span-2 flex items-center gap-2">
              <button disabled={busy} className="btn-primary">{busy ? 'Registering...' : 'Register camera'}</button>
              {msg && (
                <span className={`text-xs ${msg.kind === 'ok' ? 'text-ok' : 'text-crit'}`}>{msg.text}</span>
              )}
            </div>
          </form>
        </section>

        <section className="panel p-4">
          <h2 className="mb-3 text-sm font-semibold">Bulk import (CSV / XLSX)</h2>
          <p className="mb-3 text-xs text-ink-muted">
            Download the <a className="text-accent hover:underline" href="/api/v1/cameras/import-template.csv">template</a>,
            fill rows, then run a dry-run first. Commit applies only after validation passes your review.
          </p>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded border border-dashed border-line bg-canvas px-4 py-8 text-center hover:bg-accent-soft/40">
            <FileSpreadsheet className="h-6 w-6 text-ink-faint" />
            <span className="text-sm">{file ? file.name : 'Choose CSV or XLSX file'}</span>
            <input
              type="file"
              accept=".csv,.xlsx,.xlsm"
              className="hidden"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null)
                setResult(null)
              }}
            />
          </label>
          <div className="mt-3 flex gap-2">
            <button disabled={!file || importing} onClick={() => runImport(true)} className="btn-ghost">
              {importing ? 'Validating...' : 'Dry run'}
            </button>
            <button
              disabled={!file || importing || !result || (result.errors ?? 0) > 0}
              onClick={() => runImport(false)}
              className="btn-primary"
              title={result && (result.errors ?? 0) > 0 ? 'Fix reported errors before committing' : ''}
            >
              <Upload className="h-4 w-4" /> Commit import
            </button>
          </div>
          {result && (result.warning_count ?? 0) > 0 && (
            <p className="mt-2 text-2xs text-warn">
              {result.warning_count} row(s) have warnings (e.g. unknown site reference) but can still be committed.
            </p>
          )}

          {result && (
            <div className="mt-4 space-y-3 animate-fadeIn">
              <div className="grid grid-cols-5 gap-2 text-center">
                {[
                  ['Rows', result.total_rows],
                  ['Would create', result.created],
                  ['Would update', result.updated],
                  ['Warnings', result.warning_count ?? 0],
                  ['Errors', result.errors],
                ].map(([k, v]) => (
                  <div key={String(k)} className="rounded border border-line px-2 py-2">
                    <div className="text-lg font-semibold">{v as number}</div>
                    <div className="text-2xs text-ink-faint">{k as string}</div>
                  </div>
                ))}
              </div>
              {(result.report?.rows?.length ?? 0) > 0 && (
                <div className="rounded border border-crit/30 bg-crit/5 p-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-crit">
                    <ShieldAlert className="h-4 w-4" /> Row-level validation errors
                  </div>
                  <ul className="max-h-40 space-y-1 overflow-auto text-2xs">
                    {(result.report?.rows ?? []).map((r) => (
                      <li key={r.row}>
                        <span className="font-mono">Row {r.row}</span>: {r.errors.join('; ')}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(result.report?.warnings?.length ?? 0) > 0 && (
                <div className="rounded border border-warn/30 bg-warn/5 p-3">
                  <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold text-warn">
                    <ShieldAlert className="h-4 w-4" /> Warnings ({result.warning_count})
                  </div>
                  <ul className="max-h-32 space-y-1 overflow-auto text-2xs">
                    {(result.report?.warnings ?? []).slice(0, 20).map((r) => (
                      <li key={r.row}>
                        <span className="font-mono">Row {r.row}</span>: {r.warnings.join('; ')}
                      </li>
                    ))}
                  </ul>
                  {(result.report?.warnings?.length ?? 0) > 20 && (
                    <p className="mt-1 text-2xs text-ink-faint">
                      …and {(result.report?.warnings?.length ?? 0) - 20} more
                    </p>
                  )}
                </div>
              )}
              {!result.dry_run && (result.errors ?? 0) === 0 && (
                <div className="rounded border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok">
                  Import committed successfully.
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
