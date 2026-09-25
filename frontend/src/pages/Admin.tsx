import { FormEvent, useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { fmtDateTime } from '../lib/format'

interface U {
  user_id: string
  name: string
  email: string
  status: string
  roles: string[]
  department_id: string | null
  last_login_at: string | null
}
interface D { department_id: string; name: string; code: string }

export default function Admin() {
  const [users, setUsers] = useState<U[]>([])
  const [depts, setDepts] = useState<D[]>([])
  const [roles, setRoles] = useState<string[]>([])
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [form, setForm] = useState({ name: '', email: '', password: '', role: 'OPERATOR', department_id: '' })

  const load = useCallback(async () => {
    const [u, d, r] = await Promise.all([
      api.get<{ data: U[] }>('/users'),
      api.get<{ data: D[] }>('/departments'),
      api.get<{ data: { name: string }[] }>('/roles'),
    ])
    setUsers(u.data)
    setDepts(d.data)
    setRoles(r.data.map((x) => x.name))
  }, [])

  useEffect(() => {
    load().catch(() => setMsg({ kind: 'err', text: 'Failed to load admin data' }))
  }, [load])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setMsg(null)
    try {
      await api.post('/users', {
        ...form,
        department_id: form.department_id || null,
      })
      setMsg({ kind: 'ok', text: `User ${form.email} created.` })
      setForm({ name: '', email: '', password: '', role: 'OPERATOR', department_id: '' })
      await load()
    } catch (err) {
      setMsg({ kind: 'err', text: err instanceof Error ? err.message : 'Failed to create user' })
    }
  }

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  return (
    <div className="mx-auto max-w-5xl p-5">
      <h1 className="text-lg font-semibold">Administration</h1>
      <p className="mb-4 text-xs text-ink-muted">Users, roles and department scope management.</p>

      <div className="grid gap-4 lg:grid-cols-3">
        <section className="panel p-4 lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold">Users</h2>
          <table className="table-base">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Roles</th>
                <th>Last login</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.user_id}>
                  <td className="font-medium">{u.name}</td>
                  <td className="text-xs">{u.email}</td>
                  <td>{u.roles.join(', ')}</td>
                  <td className="text-xs">{fmtDateTime(u.last_login_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel p-4">
          <h2 className="mb-3 text-sm font-semibold">Create user</h2>
          <form onSubmit={submit} className="space-y-3">
            <input required className="input-base" placeholder="Full name" value={form.name} onChange={set('name')} />
            <input required type="email" className="input-base" placeholder="Email" value={form.email} onChange={set('email')} />
            <input required type="password" minLength={8} className="input-base" placeholder="Password (min 8 chars)" value={form.password} onChange={set('password')} />
            <select className="input-base" value={form.role} onChange={set('role')}>
              {roles.map((r) => <option key={r}>{r}</option>)}
            </select>
            <select className="input-base" value={form.department_id} onChange={set('department_id')}>
              <option value="">No department (state-wide roles)</option>
              {depts.map((d) => <option key={d.department_id} value={d.department_id}>{d.name}</option>)}
            </select>
            <button className="btn-primary w-full">Create user</button>
            {msg && <p className={`text-xs ${msg.kind === 'ok' ? 'text-ok' : 'text-crit'}`}>{msg.text}</p>}
          </form>
        </section>
      </div>

      <section className="panel mt-4 p-4">
        <h2 className="mb-2 text-sm font-semibold">Departments</h2>
        <table className="table-base">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
            </tr>
          </thead>
          <tbody>
            {depts.map((d) => (
              <tr key={d.department_id}>
                <td className="font-mono text-xs">{d.code}</td>
                <td>{d.name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  )
}
