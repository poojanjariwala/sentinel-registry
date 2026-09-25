import { useCallback, useEffect, useState } from 'react'
import { Download, Play } from 'lucide-react'
import { api, authHeaders } from '../lib/api'
import { fmtDateTime, fmtNumber, statusBadge } from '../lib/format'

interface DistrictRow {
  district: string
  cameras: number
  offline: number
  faulty: number
  ageing: number
  amc_expired: number
}
interface AgeingRow {
  camera_id: string
  camera_code: string
  name: string
  district: string | null
  install_date: string
  amc_end_date: string | null
  maintenance_status: string
}
interface GapResult {
  run_id: string
  total_cameras: number
  hex_covered: number
  hex_thin: number
  ageing_count: number
  amc_expired_count: number
  by_district: DistrictRow[]
  ageing_sample: AgeingRow[]
  generated_at: string | null
}
interface Dept { department_id: string; name: string; code: string }

export default function GapAnalysis() {
  const [depts, setDepts] = useState<Dept[]>([])
  const [selectedDepts, setSelectedDepts] = useState<string[]>([])
  const [resolution, setResolution] = useState(8)
  const [ageingYears, setAgeingYears] = useState(5)
  const [result, setResult] = useState<GapResult | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.get<{ data: Dept[] }>('/departments').then((r) => setDepts(r.data)).catch(() => {})
  }, [])

  const run = useCallback(async () => {
    setRunning(true)
    setErr(null)
    try {
      const r = await api.post<{ data: GapResult }>('/coverage/gap-analysis', {
        departments: selectedDepts.length ? selectedDepts : null,
        resolution,
        ageing_years: ageingYears,
      })
      setResult(r.data)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setRunning(false)
    }
  }, [selectedDepts, resolution, ageingYears])

  const toggleDept = (id: string) =>
    setSelectedDepts((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))

  return (
    <div className="p-5">
      <h1 className="text-lg font-semibold">Coverage Gap Analysis</h1>
      <p className="mb-4 text-xs text-ink-muted">
        Uncovered zones (H3 hex grid) and ageing infrastructure across your scope.
      </p>

      <div className="panel mb-4 flex flex-wrap items-end gap-4 p-4">
        <div>
          <span className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Departments</span>
          <div className="flex flex-wrap gap-1.5">
            {depts.map((d) => (
              <button
                key={d.department_id}
                onClick={() => toggleDept(d.department_id)}
                className={`rounded border px-2 py-1 text-2xs font-medium ${
                  selectedDepts.includes(d.department_id)
                    ? 'border-accent bg-accent-soft text-accent'
                    : 'border-line bg-white text-ink-muted hover:bg-canvas'
                }`}
              >
                {d.code}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Hex resolution</label>
          <select className="input-base w-36" value={resolution} onChange={(e) => setResolution(Number(e.target.value))}>
            {[6, 7, 8, 9].map((r) => <option key={r} value={r}>Resolution {r}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-2xs font-semibold uppercase text-ink-muted">Ageing threshold (years)</label>
          <input
            type="number"
            min={1}
            max={20}
            className="input-base w-40"
            value={ageingYears}
            onChange={(e) => setAgeingYears(Number(e.target.value))}
          />
        </div>
        <button onClick={run} disabled={running} className="btn-primary">
          <Play className="h-4 w-4" /> {running ? 'Analyzing...' : 'Run analysis'}
        </button>
      </div>

      {err && <div className="mb-4 rounded border border-crit/30 bg-crit/10 px-3 py-2 text-xs text-crit">{err}</div>}

      {result && (
        <div className="space-y-4 animate-fadeIn">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            {[
              ['Cameras analyzed', result.total_cameras],
              ['Hex cells covered', result.hex_covered],
              ['Thin cells', result.hex_thin],
              ['Ageing cameras', result.ageing_count],
              ['AMC expired', result.amc_expired_count],
            ].map(([k, v]) => (
              <div key={String(k)} className="panel px-4 py-3">
                <div className="text-xl font-semibold">{fmtNumber(v as number)}</div>
                <div className="text-2xs text-ink-faint">{k as string}</div>
              </div>
            ))}
          </div>

          <section className="panel overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>District</th>
                  <th>Cameras</th>
                  <th>Offline</th>
                  <th>Faulty</th>
                  <th>Ageing</th>
                  <th>AMC expired</th>
                </tr>
              </thead>
              <tbody>
                {result.by_district.map((d) => (
                  <tr key={d.district}>
                    <td className="font-medium">{d.district}</td>
                    <td>{fmtNumber(d.cameras)}</td>
                    <td>{d.offline > 0 ? <span className="badge badge-crit">{d.offline}</span> : d.offline}</td>
                    <td>{d.faulty > 0 ? <span className="badge badge-warn">{d.faulty}</span> : d.faulty}</td>
                    <td>{d.ageing > 0 ? <span className="badge badge-warn">{d.ageing}</span> : d.ageing}</td>
                    <td>{d.amc_expired > 0 ? <span className="badge badge-crit">{d.amc_expired}</span> : d.amc_expired}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="panel overflow-x-auto">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <h2 className="text-sm font-semibold">Ageing infrastructure (sample)</h2>
              <button
                className="btn-ghost"
                onClick={() => {
                  fetch(`/api/v1/coverage/runs/${result.run_id}/export.csv`, { headers: authHeaders() })
                    .then((r) => r.blob())
                    .then((b) => {
                      const a = document.createElement('a')
                      a.href = URL.createObjectURL(b)
                      a.download = `gap_analysis_${result.run_id.slice(0, 8)}.csv`
                      a.click()
                    })
                }}
              >
                <Download className="h-4 w-4" /> Export report
              </button>
            </div>
            <table className="table-base">
              <thead>
                <tr>
                  <th>Code</th>
                  <th>Name</th>
                  <th>District</th>
                  <th>Installed</th>
                  <th>AMC end</th>
                  <th>Maintenance</th>
                </tr>
              </thead>
              <tbody>
                {result.ageing_sample.slice(0, 25).map((a) => (
                  <tr key={a.camera_id}>
                    <td className="font-mono text-xs">{a.camera_code}</td>
                    <td>{a.name}</td>
                    <td>{a.district ?? '-'}</td>
                    <td>{a.install_date}</td>
                    <td>{a.amc_end_date ?? '-'}</td>
                    <td><span className={statusBadge(a.maintenance_status)}>{a.maintenance_status}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <p className="text-2xs text-ink-faint">
            Run {result.run_id} · {fmtDateTime(result.generated_at)}
          </p>
        </div>
      )}
    </div>
  )
}
