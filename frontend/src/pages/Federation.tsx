import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Server, Plug, Power } from 'lucide-react'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'
import { useAuth } from '../lib/auth'

interface VmsRow {
  vms_id: string
  name: string
  vendor: string
  adapter_kind: string
  base_url: string | null
  auth_env_keys: string[]
  capabilities: string[]
  status: string
  last_discovered_at: string | null
  last_error: string | null
  enabled: boolean
}

interface DiscoverResult {
  vms: string
  ok: boolean
  reason?: string
  cameras_created?: number
  cameras_updated?: number
  streams_created?: number
  streams_disabled?: number
}

export default function Federation() {
  const { can } = useAuth()
  const [rows, setRows] = useState<VmsRow[]>([])
  const [adapterKinds, setAdapterKinds] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ name: '', vendor: '', adapter_kind: 'generic_hls', base_url: '', auth_env_keys: '' })

  const load = useCallback(() => {
    api.get<{ data: VmsRow[]; meta: { adapter_kinds: string[] } }>('/vms')
      .then((r) => {
        setRows(r.data)
        setAdapterKinds(r.meta.adapter_kinds)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const run = async (label: string, fn: () => Promise<{ data: DiscoverResult | { results?: DiscoverResult[] } }>) => {
    setBusy(label)
    setMsg(null)
    try {
      const r = await fn()
      const payload = r.data as DiscoverResult & { results?: DiscoverResult[] }
      const results: DiscoverResult[] = Array.isArray(payload) ? [payload] : payload.results ?? []
      const parts = results.map((x) =>
        x.ok
          ? `${x.vms}: +${x.cameras_created ?? 0} cams, +${x.streams_created ?? 0} streams`
          : `${x.vms}: FAILED (${x.reason ?? 'unknown'})`,
      )
      setMsg(parts.join(' · ') || 'Done')
      load()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Request failed')
    } finally {
      setBusy(null)
    }
  }

  const discoverAll = () =>
    run('all', () => api.post<{ data: { results: DiscoverResult[] } }>('/vms/discover-all', {}))

  const discoverOne = (id: string) =>
    run(id, () => api.post<{ data: DiscoverResult }>(`/vms/${id}/discover`, {}))

  const toggleEnabled = (v: VmsRow) =>
    api.patch(`/vms/${v.vms_id}`, { enabled: !v.enabled }).then(load).catch(() => {})

  const register = () => {
    api
      .post('/vms', {
        name: form.name,
        vendor: form.vendor,
        adapter_kind: form.adapter_kind,
        base_url: form.base_url || null,
        auth_env_keys: form.auth_env_keys ? form.auth_env_keys.split(',').map((s) => s.trim()).filter(Boolean) : [],
      })
      .then(() => {
        setShowForm(false)
        setForm({ name: '', vendor: '', adapter_kind: 'generic_hls', base_url: '', auth_env_keys: '' })
        load()
      })
      .catch((e) => setMsg(e instanceof Error ? e.message : 'Register failed'))
  }

  return (
    <div className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">VMS Federation</h1>
          <p className="text-xs text-ink-muted">
            Departmental VMS adapters — registry, capabilities, discovery and health (federation over replacement).
          </p>
        </div>
        <div className="flex items-center gap-2">
          {can('camera.write') && (
            <button onClick={discoverAll} disabled={busy !== null} className="btn-primary">
              <RefreshCw className={`h-4 w-4 ${busy === 'all' ? 'animate-spin' : ''}`} />
              {busy === 'all' ? 'Discovering…' : 'Discover from all'}
            </button>
          )}
          {can('user.manage') && (
            <button onClick={() => setShowForm((s) => !s)} className="btn-ghost">
              <Plug className="h-4 w-4" /> Register VMS
            </button>
          )}
        </div>
      </div>

      {msg && <div className="mb-4 rounded border border-line bg-white px-3 py-2 text-xs">{msg}</div>}

      {showForm && (
        <div className="panel mb-4 grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
          <label className="text-2xs font-semibold uppercase text-ink-muted">
            Name
            <input className="input-base mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="CITY-VMS-B" />
          </label>
          <label className="text-2xs font-semibold uppercase text-ink-muted">
            Vendor
            <input className="input-base mt-1" value={form.vendor} onChange={(e) => setForm({ ...form, vendor: e.target.value })} placeholder="Vendor B" />
          </label>
          <label className="text-2xs font-semibold uppercase text-ink-muted">
            Adapter
            <select className="input-base mt-1" value={form.adapter_kind} onChange={(e) => setForm({ ...form, adapter_kind: e.target.value })}>
              {adapterKinds.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </label>
          <label className="text-2xs font-semibold uppercase text-ink-muted md:col-span-2">
            Manifest / base URL
            <input className="input-base mt-1" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://vms-b.example.gov.in/cameras.json" />
          </label>
          <label className="text-2xs font-semibold uppercase text-ink-muted">
            Auth env vars (names, comma-sep)
            <input className="input-base mt-1" value={form.auth_env_keys} onChange={(e) => setForm({ ...form, auth_env_keys: e.target.value })} placeholder="VMS_B_USER,VMS_B_PASS" />
          </label>
          <div className="md:col-span-3">
            <button onClick={register} disabled={!form.name || !form.vendor} className="btn-primary">Save registration</button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {rows.map((v) => (
          <section key={v.vms_id} className="panel p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-ink-muted" />
                  <h2 className="truncate text-sm font-semibold">{v.name}</h2>
                  <span className={`badge ${v.status === 'ONLINE' ? 'badge-ok' : v.status === 'OFFLINE' ? 'badge-crit' : 'badge-neutral'}`}>
                    {v.status}
                  </span>
                  {!v.enabled && <span className="badge badge-neutral">DISABLED</span>}
                </div>
                <p className="mt-0.5 text-2xs text-ink-faint">
                  {v.vendor} · adapter <span className="font-mono">{v.adapter_kind}</span>
                  {v.base_url ? ` · ${v.base_url}` : ''}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {can('camera.write') && (
                  <button onClick={() => discoverOne(v.vms_id)} disabled={busy !== null} className="rounded border border-line bg-white p-1.5 text-ink-muted hover:bg-canvas" title="Discover now">
                    <RefreshCw className={`h-3.5 w-3.5 ${busy === v.vms_id ? 'animate-spin' : ''}`} />
                  </button>
                )}
                {can('user.manage') && (
                  <button onClick={() => toggleEnabled(v)} className="rounded border border-line bg-white p-1.5 text-ink-muted hover:bg-canvas" title={v.enabled ? 'Disable adapter' : 'Enable adapter'}>
                    <Power className={`h-3.5 w-3.5 ${v.enabled ? 'text-ok' : ''}`} />
                  </button>
                )}
              </div>
            </div>

            <div className="mt-3 flex flex-wrap gap-1">
              {v.capabilities.map((c) => (
                <span key={c} className="badge badge-neutral">{c}</span>
              ))}
            </div>

            <dl className="mt-3 space-y-1 text-2xs">
              <div className="flex justify-between gap-3">
                <dt className="text-ink-faint">Credentials</dt>
                <dd className="font-mono">{v.auth_env_keys.length ? v.auth_env_keys.join(', ') : 'none (env-resolved)'}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-ink-faint">Last discovery</dt>
                <dd>{fmtDateTime(v.last_discovered_at)}</dd>
              </div>
              {v.last_error && (
                <div className="rounded bg-crit/10 px-2 py-1 text-crit">
                  <span className="font-semibold">Last error:</span> <span className="font-mono">{v.last_error}</span>
                </div>
              )}
            </dl>
          </section>
        ))}
      </div>

      {rows.length === 0 && (
        <div className="panel p-8 text-center text-sm text-ink-muted">
          No VMS registered yet — the default adapters register on API startup.
        </div>
      )}
    </div>
  )
}
