import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { PageHeader } from '../components/Layout'
import { Badge, Card, EmptyState, ErrorState, Loading, Stat, Table, Td, Th } from '../components/ui'
import { api, type Dashboard } from '../lib/api'
import { useAuth } from '../lib/auth'
import { STATUS_TONE, humanise } from '../lib/format'

export function DashboardPage() {
  const { user } = useAuth()
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get<Dashboard>('/api/v1/dashboard'),
  })

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          user?.role === 'admin'
            ? 'Every lead across the team.'
            : 'The leads assigned to you.'
        }
      />

      <div className="p-6">
        {isLoading ? (
          <Loading label="Loading overview" />
        ) : error ? (
          <ErrorState error={error} onRetry={() => refetch()} />
        ) : !data ? null : (
          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <Stat
                label="Leads"
                value={data.total_leads}
                sub={`Average score ${data.average_score}`}
              />
              <Stat
                label="High priority"
                value={data.hot}
                sub="Scoring 75 or above"
                tone="good"
              />
              <Stat label="Worth working" value={data.warm} sub="Scoring 50–74" tone="warning" />
              <Stat label="Low priority" value={data.cold} sub="Below 50" tone="neutral" />
            </div>

            <Card title="Outreach funnel">
              {/* Counted as distinct leads, not events: three opens from one
                  person is one engaged lead. */}
              <div className="grid gap-px bg-line sm:grid-cols-4">
                {[
                  { label: 'Emails sent', value: data.emails_sent },
                  { label: 'Opened', value: data.emails_opened },
                  { label: 'Replied', value: data.replies },
                  { label: 'Unsubscribed', value: data.unsubscribes },
                ].map((item) => (
                  <div key={item.label} className="bg-surface px-4 py-3.5">
                    <p className="text-[12px] font-medium text-ink-muted">{item.label}</p>
                    <p className="mt-1 text-xl font-semibold text-ink">{item.value}</p>
                  </div>
                ))}
              </div>
              <p className="border-t border-line px-4 py-2 text-[12px] text-ink-muted">
                Each figure counts distinct leads, so repeat opens do not inflate it.
              </p>
            </Card>

            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="Pipeline by stage">
                {data.by_status.length === 0 ? (
                  <EmptyState
                    title="No activity yet"
                    description="Run a discovery to find leads, then send your first outreach."
                  />
                ) : (
                  <Table>
                    <tbody>
                      {data.by_status
                        .slice()
                        .sort((a, b) => b.count - a.count)
                        .map((row) => (
                          <tr key={row.status}>
                            <Td>
                              <Badge tone={STATUS_TONE[row.status]}>{humanise(row.status)}</Badge>
                            </Td>
                            <Td className="tnum text-right font-medium">{row.count}</Td>
                          </tr>
                        ))}
                    </tbody>
                  </Table>
                )}
              </Card>

              {user?.role === 'admin' && (
                <Card title="By salesperson">
                  {data.by_owner.length === 0 ? (
                    <EmptyState title="Nobody has leads yet" />
                  ) : (
                    <Table>
                      <thead>
                        <tr>
                          <Th>Person</Th>
                          <Th className="text-right">Leads</Th>
                          <Th className="text-right">High priority</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.by_owner.map((row) => (
                          <tr key={row.user_id ?? 'unassigned'}>
                            <Td>
                              <span className="text-ink">
                                {row.full_name || row.email || 'Unassigned'}
                              </span>
                            </Td>
                            <Td className="tnum text-right">{row.leads}</Td>
                            <Td className="tnum text-right">{row.hot}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </Card>
              )}
            </div>

            {data.total_leads === 0 && (
              <Card>
                <EmptyState
                  title="No leads yet"
                  description="Define who you are selling to, and discovery will go and find matching people on the web."
                  action={
                    <Link
                      to="/discovery"
                      className="inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-white hover:bg-accent-hover"
                    >
                      Set up discovery
                    </Link>
                  }
                />
              </Card>
            )}
          </div>
        )}
      </div>
    </>
  )
}
