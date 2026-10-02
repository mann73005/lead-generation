import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { ColumnChart, FunnelChart } from '../components/charts'
import { PageHeader } from '../components/Layout'
import { Badge, Button, Card, EmptyState, ErrorState, Loading, ScoreMeter } from '../components/ui'
import { api, type Dashboard, type Lead, type Page } from '../lib/api'
import { useAuth } from '../lib/auth'
import { STATUS_TONE, humanise } from '../lib/format'

export function DashboardPage() {
  const { user } = useAuth()

  const summary = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get<Dashboard>('/api/v1/dashboard'),
  })

  const top = useQuery({
    queryKey: ['leads', 'top'],
    queryFn: () => api.get<Page<Lead>>('/api/v1/leads', { limit: 6, sort: 'score' }),
  })

  if (summary.isLoading) return <Loading label="Loading overview" />
  if (summary.error)
    return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />
  if (!summary.data) return null

  const data = summary.data
  const replyRate =
    data.emails_sent > 0 ? Math.round((data.replies / data.emails_sent) * 100) : null

  if (data.total_leads === 0) return <FirstRun />

  return (
    <>
      <PageHeader
        title="Overview"
        description={
          user?.role === 'admin'
            ? 'Every lead across the team.'
            : 'The leads assigned to you.'
        }
        action={
          <Link
            to="/leads?min_score=75"
            className="inline-flex h-9 items-center rounded-lg bg-accent px-3.5 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Work the hot list
          </Link>
        }
      />

      <div className="space-y-5 p-6">
        {/* One row of equal, compact tiles. The first carries the number the
            salesperson should act on this morning and is marked by the accent
            rule down its edge rather than by being twice as tall — stretching
            one tile forces every tile beside it to match. */}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Figure
            label="Ready to call today"
            value={data.hot}
            sub={
              data.hot === 0
                ? 'Nothing above 75 yet'
                : `Scoring 75+ of ${data.total_leads} leads`
            }
            lead
          />
          <Figure label="Leads" value={data.total_leads} sub={`${data.warm} worth working`} />
          <Figure label="Average score" value={data.average_score} sub="Across all leads" />
          <Figure
            label="Reply rate"
            value={replyRate === null ? '—' : `${replyRate}%`}
            sub={
              data.emails_sent === 0
                ? 'No emails sent yet'
                : `${data.replies} of ${data.emails_sent} sent`
            }
          />
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <Card title="Outreach funnel">
            <div className="p-4">
              <FunnelChart
                data={[
                  { label: 'Sent', value: data.emails_sent },
                  { label: 'Delivered', value: data.emails_sent },
                  { label: 'Opened', value: data.emails_opened },
                  { label: 'Replied', value: data.replies },
                ]}
                caption="Each stage counts distinct leads, so repeat opens do not inflate it."
              />
            </div>
          </Card>

          <Card title="Where the pipeline sits">
            <div className="p-4">
              <ColumnChart
                data={[
                  { label: 'Low', value: data.cold },
                  { label: 'Worth working', value: data.warm },
                  { label: 'Hot', value: data.hot },
                ]}
                caption="Leads by score band. Fit sets the starting number; engagement moves it."
              />
              {data.unsubscribes > 0 && (
                <p className="mt-3 border-t border-line pt-3 text-[12px] text-ink-muted">
                  {data.unsubscribes} lead{data.unsubscribes === 1 ? ' has' : 's have'}{' '}
                  unsubscribed and will not be contacted again.
                </p>
              )}
            </div>
          </Card>
        </div>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
          <Card
            title="Highest scoring leads"
            action={
              <Link to="/leads" className="text-[12px] text-accent hover:underline">
                View all
              </Link>
            }
          >
            {top.isLoading ? (
              <Loading />
            ) : (top.data?.items.length ?? 0) === 0 ? (
              <EmptyState title="No leads yet" />
            ) : (
              <ul className="divide-y divide-line">
                {top.data!.items.map((lead) => (
                  <li key={lead.id}>
                    <Link
                      to={`/leads/${lead.id}`}
                      className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-sunken/70"
                    >
                      <ScoreMeter score={lead.score?.total_score ?? null} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-ink">
                          {lead.full_name}
                        </span>
                        <span className="block truncate text-[12px] text-ink-muted">
                          {lead.job_title} · {lead.company.name}
                        </span>
                      </span>
                      <Badge tone={STATUS_TONE[lead.score?.status ?? 'new']}>
                        {humanise(lead.score?.status ?? 'new')}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <div className="space-y-5">
            <Card title="Pipeline by stage">
              {data.by_status.length === 0 ? (
                <EmptyState title="No activity yet" />
              ) : (
                <ul className="divide-y divide-line">
                  {[...data.by_status]
                    .sort((a, b) => b.count - a.count)
                    .map((row) => (
                      <li
                        key={row.status}
                        className="flex items-center justify-between px-4 py-2.5"
                      >
                        <Badge tone={STATUS_TONE[row.status]}>{humanise(row.status)}</Badge>
                        <span className="tnum text-[13px] font-medium text-ink">{row.count}</span>
                      </li>
                    ))}
                </ul>
              )}
            </Card>

            {user?.role === 'admin' && data.by_owner.length > 0 && (
              <Card title="By salesperson">
                <ul className="divide-y divide-line">
                  {data.by_owner.map((row) => (
                    <li
                      key={row.user_id ?? 'unassigned'}
                      className="flex items-center justify-between gap-3 px-4 py-2.5"
                    >
                      <span className="min-w-0 truncate text-[13px] text-ink">
                        {row.full_name || row.email || 'Unassigned'}
                      </span>
                      <span className="flex shrink-0 items-baseline gap-3">
                        <span className="tnum text-[13px] text-ink-secondary">{row.leads}</span>
                        <span className="tnum text-[12px] text-ink-muted">{row.hot} hot</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function Figure({
  label,
  value,
  sub,
  lead = false,
}: {
  label: string
  value: React.ReactNode
  sub: string
  lead?: boolean
}) {
  return (
    <div className={`panel relative overflow-hidden px-4 py-3.5 ${lead ? 'pl-[18px]' : ''}`}>
      {lead && <span className="absolute inset-y-0 left-0 w-[3px] bg-accent" />}
      <p className="text-[12px] font-medium text-ink-muted">{label}</p>
      {/* Proportional figures: tabular-nums gives every digit the width of a
          zero, which makes a standalone number look loose at display sizes.
          Columns of figures use .tnum instead. */}
      <p className="mt-1 text-[26px] leading-none font-semibold tracking-tight text-ink">
        {value}
      </p>
      <p className="mt-1 text-[12px] text-ink-muted">{sub}</p>
    </div>
  )
}

/** What a brand new account sees. Explaining the loop beats showing four
 *  panels of zeroes. */
function FirstRun() {
  const steps = [
    {
      title: 'Describe who you sell to',
      body: 'Industry, region, headcount and the job titles that matter. This drives both the search and the fit score.',
    },
    {
      title: 'Let discovery find them',
      body: 'It searches the live web, reads the pages it finds, and extracts real named people — each stored with the page it came from.',
    },
    {
      title: 'Send grounded outreach',
      body: 'Every claim in the email traces back to something on file. Anything that cannot be verified is dropped rather than guessed.',
    },
    {
      title: 'Work the ranked list',
      body: 'Opens and replies move a lead up the list, and every change records why.',
    },
  ]

  return (
    <>
      <PageHeader title="Overview" description="Nothing here yet — here is how it works." />
      <div className="p-6">
        <div className="panel mx-auto max-w-3xl p-8">
          <h2 className="text-lg font-semibold tracking-tight text-ink">
            Find the right people, and say something true to them
          </h2>
          <p className="mt-1.5 max-w-xl text-[13px] text-ink-secondary">
            This console takes a description of your ideal customer and turns it into a ranked
            list of real people worth calling.
          </p>

          <ol className="mt-7 space-y-5">
            {steps.map((step, index) => (
              <li key={step.title} className="flex gap-3.5">
                <span className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full bg-accent-soft text-[12px] font-semibold text-accent-hover">
                  {index + 1}
                </span>
                <span>
                  <span className="block text-[13px] font-medium text-ink">{step.title}</span>
                  <span className="mt-0.5 block max-w-xl text-[13px] text-ink-muted">
                    {step.body}
                  </span>
                </span>
              </li>
            ))}
          </ol>

          <div className="mt-7 flex gap-2.5">
            <Link
              to="/discovery"
              className="inline-flex h-9 items-center rounded-lg bg-accent px-4 text-sm font-medium text-white transition-colors hover:bg-accent-hover"
            >
              Set up discovery
            </Link>
            <Link to="/outreach">
              <Button>Review the pitch first</Button>
            </Link>
          </div>
        </div>
      </div>
    </>
  )
}
