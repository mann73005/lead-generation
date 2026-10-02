import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { PageHeader } from '../components/Layout'
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  ScoreMeter,
  Select,
  Table,
  Td,
  Textarea,
} from '../components/ui'
import {
  ApiError,
  api,
  type Campaign,
  type LeadDetail,
  type Message,
  type Page,
  type Reply,
} from '../lib/api'
import { INTENT_TONE, STATUS_TONE, dateTime, humanise, relativeTime } from '../lib/format'

export function LeadDetailPage() {
  const { leadId = '' } = useParams()
  const queryClient = useQueryClient()
  const [editingEmail, setEditingEmail] = useState(false)

  const lead = useQuery({
    queryKey: ['lead', leadId],
    queryFn: () => api.get<LeadDetail>(`/api/v1/leads/${leadId}`),
  })

  const replies = useQuery({
    queryKey: ['replies', leadId],
    queryFn: () => api.get<Page<Reply>>('/api/v1/replies', { lead_id: leadId }),
  })

  function refreshLead() {
    queryClient.invalidateQueries({ queryKey: ['lead', leadId] })
    queryClient.invalidateQueries({ queryKey: ['leads'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  if (lead.isLoading) return <Loading label="Loading lead" />
  if (lead.error) return <ErrorState error={lead.error} onRetry={() => lead.refetch()} />
  if (!lead.data) return null

  const data = lead.data
  const fit = Object.entries(data.score?.breakdown.fit ?? {})
  const engagement = Object.entries(data.score?.breakdown.engagement ?? {})

  return (
    <>
      <PageHeader
        title={data.full_name}
        description={`${data.job_title} · ${data.company.name}`}
        action={
          <Link to="/leads" className="text-[13px] text-ink-secondary hover:text-ink">
            ← Back to leads
          </Link>
        }
      />

      <div className="grid gap-6 p-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <OutreachPanel lead={data} onChanged={refreshLead} />
          <ReplyPanel
            lead={data}
            replies={replies.data?.items ?? []}
            onChanged={() => {
              refreshLead()
              queryClient.invalidateQueries({ queryKey: ['replies', leadId] })
            }}
          />

          <Card title="Activity">
            {data.events.length === 0 ? (
              <EmptyState
                title="Nothing has happened yet"
                description="Events appear here as the email is delivered, opened and replied to."
              />
            ) : (
              <ol className="divide-y divide-line">
                {[...data.events].reverse().map((event) => (
                  <li key={event.id} className="flex items-center gap-3 px-4 py-2.5">
                    <Badge tone={STATUS_TONE[event.event_type as never] ?? 'neutral'}>
                      {humanise(event.event_type)}
                    </Badge>
                    <span className="text-[12px] text-ink-muted">
                      {dateTime(event.occurred_at)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
        </div>

        <aside className="space-y-6">
          <Card title="Score">
            <div className="space-y-4 p-4">
              <div className="flex items-end gap-4">
                <div>
                  <div className="text-3xl font-semibold text-ink">
                    {data.score?.total_score ?? '—'}
                  </div>
                  <div className="text-[12px] text-ink-muted">out of 100</div>
                </div>
                <div className="flex-1">
                  <ScoreMeter score={data.score?.total_score ?? null} />
                </div>
              </div>

              <Breakdown
                title={`Fit · ${data.score?.fit_score ?? 0}`}
                rows={fit}
                empty="No ICP criteria matched."
              />
              <Breakdown
                title={`Engagement · ${data.score?.engagement_score ?? 0}`}
                rows={engagement}
                empty="No activity yet."
              />

              {data.score?.breakdown.penalty && (
                <Banner tone="critical">
                  Capped because this lead {humanise(data.score.breakdown.penalty).toLowerCase()}.
                </Banner>
              )}
            </div>
          </Card>

          <Card title="Why the score changed">
            {data.score_history.length === 0 ? (
              <EmptyState title="No changes recorded" />
            ) : (
              <Table>
                <tbody>
                  {[...data.score_history].reverse().map((entry) => (
                    <tr key={entry.id}>
                      <Td className="text-[13px]">{entry.reason}</Td>
                      <Td className="tnum w-[88px] text-right text-[13px] text-ink-secondary">
                        {entry.old_score ?? 0} → {entry.new_score}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>

          <Card
            title="Contact"
            action={
              <Button size="sm" variant="ghost" onClick={() => setEditingEmail(true)}>
                Edit
              </Button>
            }
          >
            <dl className="divide-y divide-line text-[13px]">
              <Row label="Email">
                {data.email ?? (
                  <span className="text-ink-muted">
                    Not found — discovery could not locate one
                  </span>
                )}
              </Row>
              <Row label="Title">{data.job_title}</Row>
              <Row label="Company">{data.company.name}</Row>
              <Row label="Industry">{data.company.industry ?? '—'}</Row>
              <Row label="Region">
                {[data.company.region, data.company.country].filter(Boolean).join(' · ') || '—'}
              </Row>
              <Row label="Headcount">{data.company.employee_count ?? '—'}</Row>
              <Row label="Source">
                <a
                  href={data.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-accent hover:underline"
                >
                  {new URL(data.source_url).hostname}
                </a>
              </Row>
            </dl>
          </Card>
        </aside>
      </div>

      {editingEmail && (
        <EmailEditor
          lead={data}
          onClose={() => setEditingEmail(false)}
          onSaved={() => {
            setEditingEmail(false)
            refreshLead()
          }}
        />
      )}
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 px-4 py-2.5">
      <dt className="w-[76px] shrink-0 text-ink-muted">{label}</dt>
      <dd className="min-w-0 flex-1 text-ink">{children}</dd>
    </div>
  )
}

function Breakdown({
  title,
  rows,
  empty,
}: {
  title: string
  rows: [string, number][]
  empty: string
}) {
  return (
    <div>
      <p className="mb-1.5 text-[12px] font-medium text-ink-muted">{title}</p>
      {rows.length === 0 ? (
        <p className="text-[13px] text-ink-muted">{empty}</p>
      ) : (
        <ul className="space-y-1">
          {rows.map(([key, value]) => (
            <li key={key} className="flex justify-between text-[13px]">
              <span className="text-ink-secondary">{humanise(key)}</span>
              <span className="tnum font-medium text-ink">
                {value > 0 ? '+' : ''}
                {value}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function EmailEditor({
  lead,
  onClose,
  onSaved,
}: {
  lead: LeadDetail
  onClose: () => void
  onSaved: () => void
}) {
  const [email, setEmail] = useState(lead.email ?? '')
  const [error, setError] = useState<string | null>(null)

  const save = useMutation({
    // An empty field clears the address rather than storing "": the column is
    // nullable precisely because a lead without a findable email is still a
    // lead worth ranking.
    mutationFn: () =>
      api.patch(`/api/v1/leads/${lead.id}`, { email: email.trim() === '' ? null : email.trim() }),
    onSuccess: onSaved,
    onError: (caught) =>
      setError(
        caught instanceof ApiError
          ? (caught.fieldErrors.email ?? caught.message)
          : 'Could not save.',
      ),
  })

  return (
    <Modal title="Edit contact email" onClose={onClose}>
      <div className="space-y-4 p-4">
        <Field
          label="Email address"
          hint="Leave blank if you do not have one. Outreach still sends to the configured sandbox inbox."
          error={error ?? undefined}
        >
          <Input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="person@company.com"
            autoFocus
          />
        </Field>
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------

function OutreachPanel({ lead, onChanged }: { lead: LeadDetail; onChanged: () => void }) {
  const [campaignId, setCampaignId] = useState('')
  const [draft, setDraft] = useState<Message | null>(null)
  const [error, setError] = useState<string | null>(null)

  const campaigns = useQuery({
    queryKey: ['campaigns'],
    queryFn: () => api.get<Page<Campaign>>('/api/v1/campaigns', { limit: 100 }),
  })

  const selected = campaignId || campaigns.data?.items[0]?.id || ''

  const generate = useMutation({
    mutationFn: () =>
      api.post<Message>(`/api/v1/campaigns/${selected}/leads/${lead.id}/messages`),
    onMutate: () => setError(null),
    onSuccess: setDraft,
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not generate a draft.'),
  })

  const send = useMutation({
    mutationFn: () => api.post<Message>(`/api/v1/messages/${draft!.id}/send`),
    onMutate: () => setError(null),
    onSuccess: (message) => {
      setDraft(message)
      onChanged()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not send.'),
  })

  const hasCampaigns = (campaigns.data?.items.length ?? 0) > 0

  return (
    <Card
      title="Outreach"
      action={
        hasCampaigns && (
          <Select
            value={selected}
            onChange={(event) => {
              setCampaignId(event.target.value)
              setDraft(null)
            }}
            className="h-8 w-[200px] text-[13px]"
            aria-label="Campaign"
          >
            {campaigns.data!.items.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </Select>
        )
      }
    >
      {!hasCampaigns ? (
        <EmptyState
          title="No campaign yet"
          description="Outreach is sent as part of a campaign, which carries the sender name and the unsubscribe link."
          action={
            <Link
              to="/campaigns"
              className="inline-flex h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-white hover:bg-accent-hover"
            >
              Create a campaign
            </Link>
          }
        />
      ) : (
        <div className="space-y-4 p-4">
          {error && <Banner tone="critical">{error}</Banner>}

          {!draft ? (
            <div className="flex items-center justify-between gap-4">
              <p className="text-[13px] text-ink-muted">
                The draft is built only from stored facts about this lead. Anything that cannot be
                traced to a source is left out.
              </p>
              <Button variant="primary" loading={generate.isPending} onClick={() => generate.mutate()}>
                Generate draft
              </Button>
            </div>
          ) : (
            <>
              <div className="rounded-md border border-line bg-plane">
                <div className="border-b border-line px-3.5 py-2.5">
                  <p className="text-[12px] text-ink-muted">Subject</p>
                  <p className="text-[13px] font-medium text-ink">{draft.subject}</p>
                </div>
                <pre className="px-3.5 py-3 text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
                  {draft.body_text}
                </pre>
              </div>

              <GroundingReport message={draft} />

              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-[12px] text-ink-muted">
                  {draft.status === 'sent' ? (
                    <>
                      Sent {relativeTime(draft.sent_at)} to{' '}
                      <span className="text-ink-secondary">{draft.to_address}</span>
                    </>
                  ) : (
                    <>
                      Will send to the configured sandbox inbox, never to the lead.
                    </>
                  )}
                </p>
                <div className="flex gap-2">
                  <Button onClick={() => setDraft(null)} disabled={send.isPending}>
                    Discard
                  </Button>
                  <Button
                    variant="primary"
                    loading={send.isPending}
                    disabled={draft.status === 'sent'}
                    onClick={() => send.mutate()}
                  >
                    {draft.status === 'sent' ? 'Sent' : 'Send'}
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </Card>
  )
}

function GroundingReport({ message }: { message: Message }) {
  const report = message.grounding_report
  const blocked = report.blocked > 0

  return (
    <div className="rounded-md border border-line px-3.5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={blocked ? 'warning' : 'good'}>
          {report.checked} values checked · {report.blocked} blocked
        </Badge>
        {message.dropped_sentences.length > 0 && (
          <Badge tone="neutral">{message.dropped_sentences.length} sentence(s) dropped</Badge>
        )}
      </div>

      {message.dropped_sentences.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-[12px] text-ink-muted">
          {message.dropped_sentences.map((entry) => (
            <li key={entry}>· {entry}</li>
          ))}
        </ul>
      )}

      {report.evidence_fields.length > 0 && (
        <p className="mt-2 text-[12px] text-ink-muted">
          Built from: {report.evidence_fields.join(', ')}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------

function ReplyPanel({
  lead,
  replies,
  onChanged,
}: {
  lead: LeadDetail
  replies: Reply[]
  onChanged: () => void
}) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)

  const classify = useMutation({
    mutationFn: () => api.post<Reply>('/api/v1/replies', { lead_id: lead.id, text: text.trim() }),
    onMutate: () => setError(null),
    onSuccess: () => {
      setText('')
      onChanged()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not classify that reply.'),
  })

  const approve = useMutation({
    mutationFn: (id: string) => api.post(`/api/v1/replies/${id}/approve`, {}),
    onSuccess: onChanged,
  })

  return (
    <Card title="Replies">
      <div className="space-y-4 p-4">
        <div>
          <Textarea
            rows={3}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Paste the reply you received…"
            aria-label="Reply text"
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <p className="text-[12px] text-ink-muted">
              Classified into one of five intents, with a response drafted for you to approve.
            </p>
            <Button
              variant="primary"
              disabled={text.trim().length < 2}
              loading={classify.isPending}
              onClick={() => classify.mutate()}
            >
              Analyse reply
            </Button>
          </div>
          {error && (
            <div className="mt-2">
              <Banner tone="critical">{error}</Banner>
            </div>
          )}
        </div>

        {replies.length > 0 && (
          <ul className="space-y-3 border-t border-line pt-4">
            {replies.map((reply) => (
              <li key={reply.id} className="rounded-md border border-line">
                <div className="flex flex-wrap items-center gap-2 border-b border-line px-3.5 py-2">
                  <Badge tone={INTENT_TONE[reply.intent]}>{humanise(reply.intent)}</Badge>
                  {reply.confidence != null && (
                    <span className="text-[12px] text-ink-muted">
                      {Math.round(reply.confidence * 100)}% confident
                    </span>
                  )}
                  <span className="ml-auto text-[12px] text-ink-muted">
                    {relativeTime(reply.created_at)}
                  </span>
                </div>

                <blockquote className="border-l-2 border-line-strong px-3.5 py-2.5 text-[13px] text-ink-secondary">
                  {reply.raw_text}
                </blockquote>

                {reply.draft_response && (
                  <div className="border-t border-line bg-plane px-3.5 py-2.5">
                    <p className="mb-1 text-[12px] font-medium text-ink-muted">
                      Suggested response — not sent
                    </p>
                    <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
                      {reply.draft_response}
                    </p>
                    <div className="mt-2 flex items-center gap-2">
                      {reply.approved ? (
                        <Badge tone="good">Approved {relativeTime(reply.approved_at)}</Badge>
                      ) : (
                        <Button
                          size="sm"
                          loading={approve.isPending}
                          onClick={() => approve.mutate(reply.id)}
                        >
                          Approve
                        </Button>
                      )}
                    </div>
                  </div>
                )}

                {reply.reasoning && (
                  <p className="border-t border-line px-3.5 py-2 text-[12px] text-ink-muted">
                    {reply.reasoning}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  )
}
