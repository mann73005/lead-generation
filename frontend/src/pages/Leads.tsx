import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

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

const STATUSES = ['new', 'sent', 'delivered', 'opened', 'replied', 'unsubscribed', 'bounced']

export function LeadsPage() {
  // Filters live in the URL so a filtered view can be shared, reloaded and
  // navigated back to.
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')

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

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    // Any filter change invalidates the current page offset.
    next.delete('page')
    setParams(next, { replace: true })
  }

  const hasFilters = ['q', 'status', 'industry', 'min_score'].some((key) => params.get(key))
  const total = data?.total ?? 0
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1)

  return (
    <>
      <PageHeader
        title="Leads"
        description="Ranked by score. The highest numbers are the ones worth a call today."
        action={
          <Link
            to="/discovery"
            className="inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Find leads
          </Link>
        }
      />

      <div className="space-y-4 p-6">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            setFilter('q', search.trim())
          }}
        >
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search name, title, email or company"
            className="h-9 w-[280px]"
            aria-label="Search leads"
          />
          <Select
            value={params.get('status') ?? ''}
            onChange={(event) => setFilter('status', event.target.value)}
            aria-label="Filter by status"
            className="w-[150px]"
          >
            <option value="">All statuses</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {humanise(status)}
              </option>
            ))}
          </Select>
          <Input
            value={params.get('industry') ?? ''}
            onChange={(event) => setFilter('industry', event.target.value)}
            placeholder="Industry"
            className="w-[150px]"
            aria-label="Filter by industry"
          />
          <Select
            value={params.get('min_score') ?? ''}
            onChange={(event) => setFilter('min_score', event.target.value)}
            aria-label="Minimum score"
            className="w-[150px]"
          >
            <option value="">Any score</option>
            <option value="75">75+ (high)</option>
            <option value="50">50+ (worth working)</option>
          </Select>
          <Button type="submit" size="md">
            Apply
          </Button>
          {hasFilters && (
            <Button variant="ghost" onClick={() => setParams({}, { replace: true })} type="button">
              Clear
            </Button>
          )}
        </form>

        <Card
          title={`${total} lead${total === 1 ? '' : 's'}`}
          action={
            isFetching && !isLoading ? (
              <span className="text-[12px] text-ink-muted">Updating…</span>
            ) : null
          }
        >
          {isLoading ? (
            <Loading label="Loading leads" />
          ) : error ? (
            <ErrorState error={error} onRetry={() => refetch()} />
          ) : total === 0 ? (
            <EmptyState
              title={hasFilters ? 'No leads match these filters' : 'No leads yet'}
              description={
                hasFilters
                  ? 'Try widening the score range or clearing the search.'
                  : 'Define an ideal customer profile and run discovery to populate this list.'
              }
              action={
                hasFilters ? (
                  <Button onClick={() => setParams({}, { replace: true })}>Clear filters</Button>
                ) : (
                  <Link
                    to="/discovery"
                    className="inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-white hover:bg-accent-hover"
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
                    <Th className="w-[110px]">Score</Th>
                    <Th>Lead</Th>
                    <Th>Company</Th>
                    <Th className="w-[120px]">Status</Th>
                    <Th className="w-[140px]">Email</Th>
                    <Th className="w-[90px] text-right">Added</Th>
                  </tr>
                </thead>
                <tbody>
                  {data!.items.map((lead) => (
                    <tr key={lead.id} className="group hover:bg-sunken/60">
                      <Td>
                        <ScoreMeter score={lead.score?.total_score ?? null} />
                      </Td>
                      <Td>
                        <Link to={`/leads/${lead.id}`} className="block min-w-0">
                          <span className="font-medium text-ink group-hover:text-accent">
                            {lead.full_name}
                          </span>
                          <span className="block truncate text-[12px] text-ink-muted">
                            {lead.job_title}
                          </span>
                        </Link>
                      </Td>
                      <Td>
                        <span className="block truncate text-ink-secondary">
                          {lead.company.name}
                        </span>
                        <span className="block truncate text-[12px] text-ink-muted">
                          {[lead.company.industry, lead.company.region]
                            .filter(Boolean)
                            .join(' · ') || '—'}
                        </span>
                      </Td>
                      <Td>
                        <Badge tone={STATUS_TONE[lead.score?.status ?? 'new']}>
                          {humanise(lead.score?.status ?? 'new')}
                        </Badge>
                      </Td>
                      <Td>
                        {lead.email ? (
                          <span className="block truncate text-[12px] text-ink-secondary">
                            {lead.email}
                          </span>
                        ) : (
                          <span className="text-[12px] text-ink-muted">Not found</span>
                        )}
                      </Td>
                      <Td className="text-right text-[12px] text-ink-muted">
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
                      onClick={() => setFilter('page', String(page - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      disabled={page >= lastPage}
                      onClick={() => setFilter('page', String(page + 1))}
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
