import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { api, setToken, getToken } from './api'

export interface CurrentUser {
  user_id: string
  name: string
  email: string
  status: string
  department_id: string | null
  roles: string[]
  permissions: string[]
}

interface AuthState {
  user: CurrentUser | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  can: (perm: string) => boolean
}

const AuthContext = createContext<AuthState>({
  user: null,
  loading: true,
  login: async () => {},
  logout: () => {},
  can: () => false,
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setLoading(false)
      return
    }
    api
      .get<{ data: CurrentUser }>('/auth/me')
      .then((r) => setUser(r.data))
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const r = await api.post<{ data: { accessToken: string; user: CurrentUser } }>('/auth/login', {
      email,
      password,
    })
    setToken(r.data.accessToken)
    setUser(r.data.user)
  }

  const logout = () => {
    api.post('/auth/logout').catch(() => {})
    setToken(null)
    setUser(null)
  }

  const can = (perm: string) => !!user?.permissions.includes(perm)

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, can }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
