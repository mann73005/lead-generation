import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { PageHeader } from '../components/Layout'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Loading,
  ScoreMeter,
  Select,
  Table,
  Td,
  Th,
} from '../components/ui'
import { api, type Lead, type Page } from '../lib/api'
import { STATUS_TONE, humanise, relativeTime } from '../lib/format'

const PAGE_SIZE = 25

/** The four views a salesperson actually switches between, as one control
 *  rather than four separate inputs they have to assemble themselves. */
const VIEWS = [
  { id: 'all', label: 'All', params: {} },
  { id: 'hot', label: 'Hot', params: { min_score: '75' } },
  { id: 'opened', label: 'Opened', params: { status: 'opened' } },
  { id: 'replied', label: 'Replied', params: { status: 'replied' } },
] as const

const STATUSES = ['new', 'sent', 'delivered', 'opened', 'replied', 'unsubscribed', 'bounced']

function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean)
  return (parts[0]?.[0] ?? '?').concat(parts[1]?.[0] ?? '').toUpperCase()
}

export function LeadsPage() {
  const navigate = useNavigate()
  // Filters live in the URL so a filtered view can be shared and survives a
  // reload and the back button.
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [panelOpen, setPanelOpen] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!panelOpen) return
    const onPointer = (event: MouseEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setPanelOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    return () => document.removeEventListener('mousedown', onPointer)
  }, [panelOpen])

  const page = Number(params.get('page') ?? 0)
  const query = {
    q: params.get('q') ?? undefined,
    status: params.get('status') ?? undefined,
    industry: params.get('industry') ?? undefined,
    min_score: params.get('min_score') ?? undefined,
    sort: params.get('sort') ?? 'score',
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['leads', query],
    queryFn: () => api.get<Page<Lead>>('/api/v1/leads', query),
    placeholderData: (previous) => previous,
  })

  function update(changes: Record<string, string | undefined>, { keepPage = false } = {}) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!keepPage) next.delete('page')
    setParams(next, { replace: true })
  }

  const activeView =
    VIEWS.find((view) =>
      Object.entries(view.params).every(([key, value]) => params.get(key) === value),
    ) ?? VIEWS[0]

  const advanced = ['industry', 'sort'].filter((key) => params.get(key)).length
  const hasAnyFilter = ['q', 'status', 'industry', 'min_score'].some((key) => params.get(key))

  const total = data?.total ?? 0
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1)

  return (
    <>
      <PageHeader
        title="Leads"
        description="Ranked by score. The top of this list is where to spend today."
        action={
          <Link
            to="/discovery"
            className="inline-flex h-9 items-center rounded-lg bg-accent px-3.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Find more leads
          </Link>
        }
      />

      <div className="space-y-4 p-6">
        <div className="flex flex-wrap items-center gap-2">
          {/* Segmented view switcher */}
          <div className="inline-flex rounded-lg border border-line bg-surface p-0.5">
            {VIEWS.map((view) => (
              <button
                key={view.id}
                onClick={() =>
                  update({ status: undefined, min_score: undefined, ...view.params })
                }
                className={[
                  'rounded-[7px] px-3 py-1.5 text-[13px] transition-colors',
                  activeView.id === view.id
                    ? 'bg-sunken font-medium text-ink'
                    : 'text-ink-secondary hover:text-ink',
                ].join(' ')}
              >
                {view.label}
              </button>
            ))}
          </div>

          <form
            className="relative flex-1 sm:max-w-xs"
            onSubmit={(event) => {
              event.preventDefault()
              update({ q: search.trim() || undefined })
            }}
          >
            <svg
              viewBox="0 0 20 20"
              className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-ink-muted"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <circle cx="9" cy="9" r="5.25" />
              <path d="m13 13 4 4" strokeLinecap="round" />
            </svg>
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search name, title or company"
              className="pl-8"
              aria-label="Search leads"
            />
          </form>

          <div ref={panelRef} className="relative">
            <Button onClick={() => setPanelOpen((open) => !open)} aria-expanded={panelOpen}>
              Filters
              {advanced > 0 && (
                <span className="ml-0.5 rounded bg-accent-soft px-1.5 text-[11px] font-semibold text-accent-hover">
                  {advanced}
                </span>
              )}
            </Button>

            {panelOpen && (
              <div className="panel absolute right-0 z-20 mt-1.5 w-[260px] space-y-3 p-3 shadow-lg">
                <label className="block">
                  <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
                    Status
                  </span>
                  <Select
                    value={params.get('status') ?? ''}
                    onChange={(event) => update({ status: event.target.value || undefined })}
                  >
                    <option value="">Any status</option>
                    {STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {humanise(status)}
                      </option>
                    ))}
                  </Select>
                </label>

                <label className="block">
                  <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
                    Industry
                  </span>
                  <Input
                    defaultValue={params.get('industry') ?? ''}
                    placeholder="e.g. Fashion"
                    onBlur={(event) => update({ industry: event.target.value.trim() || undefined })}
                  />
                </label>

                <label className="block">
                  <span className="mb-1 block text-[12px] font-medium text-ink-secondary">
                    Sort by
                  </span>
                  <Select
                    value={params.get('sort') ?? 'score'}
                    onChange={(event) =>
                      update({ sort: event.target.value === 'score' ? undefined : event.target.value })
                    }
                  >
                    <option value="score">Score</option>
                    <option value="created_at">Recently added</option>
                    <option value="name">Name</option>
                  </Select>
                </label>

                {hasAnyFilter && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full"
                    onClick={() => {
                      setSearch('')
                      setParams({}, { replace: true })
                      setPanelOpen(false)
                    }}
                  >
                    Clear everything
                  </Button>
                )}
              </div>
            )}
          </div>

          <span className="ml-auto text-[12px] text-ink-muted">
            {isFetching && !isLoading ? 'Updating…' : `${total} lead${total === 1 ? '' : 's'}`}
          </span>
        </div>

        <Card>
          {isLoading ? (
            <Loading label="Loading leads" />
          ) : error ? (
            <ErrorState error={error} onRetry={() => refetch()} />
          ) : total === 0 ? (
            <EmptyState
              title={hasAnyFilter ? 'No leads match this view' : 'No leads yet'}
              description={
                hasAnyFilter
                  ? 'Nothing here with these filters. Try "All", or widen the search.'
                  : 'Describe who you sell to and discovery will go and find matching people.'
              }
              action={
                hasAnyFilter ? (
                  <Button
                    onClick={() => {
                      setSearch('')
                      setParams({}, { replace: true })
                    }}
                  >
                    Clear filters
                  </Button>
                ) : (
                  <Link
                    to="/discovery"
                    className="inline-flex h-9 items-center rounded-lg bg-accent px-3.5 text-sm font-medium text-white hover:bg-accent-hover"
                  >
                    Find leads
                  </Link>
                )
              }
            />
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th className="w-[120px]">Score</Th>
                    <Th>Lead</Th>
                    <Th className="hidden md:table-cell">Company</Th>
                    <Th className="w-[118px]">Status</Th>
                    <Th className="hidden w-[90px] text-right lg:table-cell">Added</Th>
                  </tr>
                </thead>
                <tbody>
                  {data!.items.map((lead) => (
                    // The whole row is the target, not just the name: a table
                    // where only one cell navigates is a table people misclick.
                    <tr
                      key={lead.id}
                      onClick={() => navigate(`/leads/${lead.id}`)}
                      tabIndex={0}
                      role="link"
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') navigate(`/leads/${lead.id}`)
                      }}
                      className="group cursor-pointer transition-colors hover:bg-sunken/70 focus-visible:bg-sunken"
                    >
                      <Td>
                        <ScoreMeter score={lead.score?.total_score ?? null} />
                      </Td>
                      <Td>
                        <div className="flex items-center gap-2.5">
                          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-sunken text-[11px] font-semibold text-ink-secondary">
                            {initials(lead.full_name)}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate font-medium text-ink group-hover:text-accent-hover">
                              {lead.full_name}
                            </span>
                            <span className="block truncate text-[12px] text-ink-muted">
                              {lead.job_title}
                            </span>
                          </span>
                        </div>
                      </Td>
                      <Td className="hidden md:table-cell">
                        <span className="block truncate text-ink-secondary">
                          {lead.company.name}
                        </span>
                        <span className="block truncate text-[12px] text-ink-muted">
                          {[lead.company.industry, lead.company.region]
                            .filter(Boolean)
                            .join(' · ') || 'No industry on file'}
                        </span>
                      </Td>
                      <Td>
                        <Badge tone={STATUS_TONE[lead.score?.status ?? 'new']}>
                          {humanise(lead.score?.status ?? 'new')}
                        </Badge>
                        {!lead.email && (
                          <span className="mt-1 block text-[11px] text-ink-muted">No email</span>
                        )}
                      </Td>
                      <Td className="hidden text-right text-[12px] text-ink-muted lg:table-cell">
                        {relativeTime(lead.created_at)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>

              {lastPage > 0 && (
                <div className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-[12px] text-ink-muted">
                    {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      disabled={page === 0}
                      onClick={() => update({ page: String(page - 1) }, { keepPage: true })}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      disabled={page >= lastPage}
                      onClick={() => update({ page: String(page + 1) }, { keepPage: true })}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  )
}
