import { Outlet, NavLink } from 'react-router-dom'
import { StatusDot } from '../components/StatusDot'

const NAV_ITEMS = [
  { to: '/', label: 'Overview' },
  { to: '/activity', label: 'Activity' },
  { to: '/peers', label: 'Peers' },
  { to: '/skills', label: 'Skills' },
  // F4+ routes:
  // { to: '/sessions', label: 'Sessions' },
  // { to: '/workflows', label: 'Workflows' },
  // { to: '/metering', label: 'Metering' },
  { to: '/settings', label: 'Settings' },
]

export function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header
        className="flex items-center justify-between px-6 py-3"
        style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold" style={{ color: 'var(--accent-blue)' }}>
            AgentFax
          </span>
          <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
            Dashboard
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          <StatusDot status="online" />
          <span>Connected</span>
          <a
            href="/legacy"
            className="ml-4 underline"
            style={{ color: 'var(--text-muted)' }}
          >
            Legacy UI
          </a>
        </div>
      </header>

      {/* Navigation */}
      <nav
        className="flex gap-0 px-6"
        style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}
      >
        {NAV_ITEMS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `px-4 py-2.5 text-sm border-b-2 transition-colors ${
                isActive
                  ? 'border-[var(--accent-blue)] text-[var(--text-primary)]'
                  : 'border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Content */}
      <main className="flex-1 p-6">
        <Outlet />
      </main>
    </div>
  )
}
