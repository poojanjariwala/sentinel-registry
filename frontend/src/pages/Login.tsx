import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radar } from 'lucide-react'
import { useAuth } from '../lib/auth'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('state.admin@sentinel.local')
  const [password, setPassword] = useState('Sentinel@2026')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      navigate('/map')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-canvas p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2">
          <Radar className="h-7 w-7 text-accent" />
          <div>
            <h1 className="text-lg font-semibold leading-tight">Sentinel Registry</h1>
            <p className="text-2xs text-ink-faint">Centralised CCTV Registry & GIS Mapping</p>
          </div>
        </div>
        <form onSubmit={submit} className="panel space-y-4 p-5">
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              Official email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="input-base"
              placeholder="name@department.gujarat.gov.in"
            />
          </div>
          <div>
            <label className="mb-1 block text-2xs font-semibold uppercase tracking-wide text-ink-muted">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="input-base"
            />
          </div>
          {error && <div className="rounded border border-crit/30 bg-crit/10 px-3 py-2 text-xs text-crit">{error}</div>}
          <button type="submit" disabled={busy} className="btn-primary w-full">
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
          <p className="text-2xs leading-relaxed text-ink-faint">
            Development demo accounts are pre-seeded. Access is restricted to your assigned
            department scope and every action is audited.
          </p>
        </form>
      </div>
    </div>
  )
}
