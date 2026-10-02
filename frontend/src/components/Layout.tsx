import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../lib/auth'
import { Button } from './ui'

type NavItem = { to: string; label: string; adminOnly?: boolean }

const NAV: NavItem[] = [
  { to: '/', label: 'Overview' },
  { to: '/leads', label: 'Leads' },
  { to: '/discovery', label: 'Discovery' },
  { to: '/campaigns', label: 'Campaigns' },
  { to: '/outreach', label: 'Outreach profile' },
  { to: '/users', label: 'Team', adminOnly: true },
]

export function Layout() {
  const { user, signOut } = useAuth()
  const items = NAV.filter((item) => !item.adminOnly || user?.role === 'admin')

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-[216px] shrink-0 flex-col border-r border-line bg-surface">
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <span className="grid size-6 place-items-center rounded bg-ink text-[11px] font-bold text-white">
            S
          </span>
          <span className="text-[13px] font-semibold tracking-tight">StyleSense</span>
        </div>

        <nav className="flex-1 space-y-0.5 p-2">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                [
                  'block rounded-md px-2.5 py-1.5 text-[13px] transition-colors',
                  isActive
                    ? 'bg-sunken font-medium text-ink'
                    : 'text-ink-secondary hover:bg-sunken hover:text-ink',
                ].join(' ')
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          <div className="mb-2 min-w-0">
            <p className="truncate text-[13px] font-medium text-ink">
              {user?.full_name || user?.email}
            </p>
            <p className="truncate text-[12px] text-ink-muted">
              {user?.role === 'admin' ? 'Administrator' : 'Salesperson'}
            </p>
          </div>
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-3 border-b border-line bg-surface px-6 py-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
      </div>
      {action}
    </header>
  )
}
