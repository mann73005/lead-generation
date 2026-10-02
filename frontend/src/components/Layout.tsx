import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../lib/auth'

/** Inline so the icon set stays small, consistent in weight, and ours — an
 *  icon library would drag in hundreds of glyphs for the seven used here. */
const ICONS: Record<string, ReactNode> = {
  overview: <path d="M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3v-5H7v5H4a1 1 0 0 1-1-1V9.5Z" />,
  leads: (
    <>
      <circle cx="7.5" cy="7" r="2.75" />
      <path d="M3 16.5c0-2.3 2-4 4.5-4s4.5 1.7 4.5 4" />
      <path d="M13.5 9.5a2.25 2.25 0 1 0 0-4.5" />
      <path d="M14 16.5c0-1.8-.5-3-1.5-3.8" />
    </>
  ),
  discovery: (
    <>
      <circle cx="9" cy="9" r="5.25" />
      <path d="m13 13 4 4" />
    </>
  ),
  campaigns: (
    <>
      <rect x="2.75" y="4.75" width="14.5" height="10.5" rx="1.5" />
      <path d="m3 6 7 4.5L17 6" />
    </>
  ),
  outreach: (
    <>
      <path d="M4 4.75h12M4 9h12M4 13.25h7" />
    </>
  ),
  team: (
    <>
      <circle cx="10" cy="6.5" r="2.5" />
      <path d="M4.5 16c0-2.6 2.4-4.5 5.5-4.5s5.5 1.9 5.5 4.5" />
    </>
  ),
}

type NavItem = { to: string; label: string; icon: keyof typeof ICONS; adminOnly?: boolean }

const NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'overview' },
  { to: '/leads', label: 'Leads', icon: 'leads' },
  { to: '/discovery', label: 'Discovery', icon: 'discovery' },
  { to: '/campaigns', label: 'Campaigns', icon: 'campaigns' },
  { to: '/outreach', label: 'Outreach profile', icon: 'outreach' },
  { to: '/users', label: 'Team', icon: 'team', adminOnly: true },
]

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg
      viewBox="0 0 20 20"
      className="size-[18px] shrink-0"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {ICONS[name]}
    </svg>
  )
}

function initials(user: { full_name: string | null; email: string }): string {
  const source = user.full_name?.trim() || user.email
  const parts = source.split(/[\s@._-]+/).filter(Boolean)
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase()
}

export function Layout() {
  const { user, signOut } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Click-outside and Escape, because a menu that only closes by clicking its
  // own trigger feels broken.
  useEffect(() => {
    if (!menuOpen) return
    const onPointer = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setMenuOpen(false)
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  const items = NAV.filter((item) => !item.adminOnly || user?.role === 'admin')

  return (
    <div className="flex min-h-screen bg-plane">
      <aside className="sticky top-0 flex h-screen w-[232px] shrink-0 flex-col border-r border-line bg-surface">
        <div className="flex h-[58px] items-center gap-2.5 px-4">
          <span className="grid size-7 place-items-center rounded-[7px] bg-ink text-[12px] font-bold text-white">
            S
          </span>
          <div className="min-w-0">
            <p className="truncate text-[13px] leading-tight font-semibold tracking-tight">
              StyleSense
            </p>
            <p className="truncate text-[11px] leading-tight text-ink-muted">Sales console</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2.5 py-2">
          <p className="px-2.5 pt-2 pb-1.5 text-[11px] font-semibold tracking-wider text-ink-muted uppercase">
            Workspace
          </p>
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                [
                  'flex items-center gap-2.5 rounded-lg px-2.5 py-[7px] text-[13px] transition-colors',
                  isActive
                    ? 'bg-accent-soft font-medium text-accent-hover'
                    : 'text-ink-secondary hover:bg-sunken hover:text-ink',
                ].join(' ')
              }
            >
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div ref={menuRef} className="relative border-t border-line p-2.5">
          {menuOpen && (
            <div
              role="menu"
              className="panel absolute right-2.5 bottom-[calc(100%-2px)] left-2.5 z-20 overflow-hidden shadow-lg"
            >
              <div className="border-b border-line px-3 py-2.5">
                <p className="truncate text-[13px] font-medium text-ink">
                  {user?.full_name || user?.email}
                </p>
                <p className="truncate text-[12px] text-ink-muted">{user?.email}</p>
              </div>
              <button
                role="menuitem"
                onClick={signOut}
                className="w-full px-3 py-2 text-left text-[13px] text-critical transition-colors hover:bg-critical-soft"
              >
                Sign out
              </button>
            </div>
          )}

          <button
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-sunken"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-full bg-sunken text-[12px] font-semibold text-ink-secondary">
              {user ? initials(user) : '?'}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] leading-tight font-medium text-ink">
                {user?.full_name || user?.email}
              </span>
              <span className="block truncate text-[11px] leading-tight text-ink-muted">
                {user?.role === 'admin' ? 'Administrator' : 'Salesperson'}
              </span>
            </span>
            <svg
              viewBox="0 0 16 16"
              className={`size-3.5 shrink-0 text-ink-muted transition-transform ${menuOpen ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={1.6}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="m4 10 4-4 4 4" />
            </svg>
          </button>
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
  action?: ReactNode
}) {
  return (
    <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface/85 px-6 py-3.5 backdrop-blur">
      <div className="min-w-0">
        <h1 className="truncate text-[17px] font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
      </div>
      {action}
    </header>
  )
}
