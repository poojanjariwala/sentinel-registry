import { Outlet, NavLink, Navigate, useNavigate } from 'react-router-dom'
import { MapPin, Table2, Upload, ScanSearch, ShieldCheck, ScrollText, LogOut, Radar, MonitorPlay, CarFront, Network } from 'lucide-react'
import { useAuth } from './lib/auth'

const NAV = [
  { to: '/live', label: 'Live View', icon: MonitorPlay, perm: 'camera.read' },
  { to: '/federation', label: 'VMS Federation', icon: Network, perm: 'camera.read' },
  { to: '/map', label: 'GIS Map', icon: MapPin, perm: 'camera.read' },
  { to: '/vehicles', label: 'Vehicle Intelligence', icon: CarFront, perm: 'camera.read' },
  { to: '/registry', label: 'Camera Registry', icon: Table2, perm: 'camera.read' },
  { to: '/onboarding', label: 'Onboarding', icon: Upload, perm: 'camera.write' },
  { to: '/gap', label: 'Gap Analysis', icon: ScanSearch, perm: 'coverage.run' },
  { to: '/admin', label: 'Administration', icon: ShieldCheck, perm: 'user.manage' },
  { to: '/audit', label: 'Audit Trail', icon: ScrollText, perm: 'audit.read' },
]

export default function App() {
  const { user, loading, logout } = useAuth()
  const navigate = useNavigate()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center text-ink-muted text-sm">
        Loading session...
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />

  const visibleNav = NAV.filter((n) => !n.perm || user.permissions.includes(n.perm))

  return (
    <div className="flex h-full">
      <aside className="flex w-56 shrink-0 flex-col border-r border-line bg-white">
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <Radar className="h-5 w-5 text-accent" />
          <div>
            <div className="text-sm font-semibold leading-tight">Sentinel Registry</div>
            <div className="text-2xs text-ink-faint">CCTV Asset Visibility</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2 py-3">
          {visibleNav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded px-3 py-2 text-sm ${
                  isActive ? 'bg-accent-soft text-accent font-medium' : 'text-ink-muted hover:bg-canvas'
                }`
              }
            >
              <n.icon className="h-4 w-4" />
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line px-4 py-3">
          <div className="truncate text-sm font-medium">{user.name}</div>
          <div className="truncate text-2xs text-ink-faint">{user.roles.join(', ')}</div>
          <button
            onClick={() => {
              logout()
              navigate('/login')
            }}
            className="mt-2 flex items-center gap-1.5 text-2xs text-ink-muted hover:text-crit"
          >
            <LogOut className="h-3.5 w-3.5" /> Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto bg-canvas">
        <Outlet />
      </main>
    </div>
  )
}
