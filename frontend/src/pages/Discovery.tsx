import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

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
  Table,
  Td,
  Th,
} from '../components/ui'
import {
  ApiError,
  api,
  type DiscoveryRun,
  type DiscoveryRunDetail,
  type Icp,
  type Page,
} from '../lib/api'
import { dateTime } from '../lib/format'

export function DiscoveryPage() {
  const queryClient = useQueryClient()
  const [target, setTarget] = useState<Icp | null>(null)
  const [openRun, setOpenRun] = useState<string | null>(null)

  const icps = useQuery({
    queryKey: ['icps'],
    queryFn: () => api.get<Page<Icp>>('/api/v1/icps', { limit: 50 }),
  })
  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get<Page<DiscoveryRun>>('/api/v1/discovery/runs', { limit: 15 }),
  })

  return (
    <>
      <PageHeader
        title="Discovery"
        description="Describe who you sell to. Discovery searches the live web, reads what it finds, and extracts real people."
      />

      <div className="grid gap-5 p-6 xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <IcpForm onCreated={() => queryClient.invalidateQueries({ queryKey: ['icps'] })} />

        <div className="space-y-5">
          <Card title="Saved profiles">
            {icps.isLoading ? (
              <Loading />
            ) : icps.error ? (
              <ErrorState error={icps.error} onRetry={() => icps.refetch()} />
            ) : icps.data!.items.length === 0 ? (
              <EmptyState
                title="No profiles yet"
                description="Create one on the left. It tells discovery what to look for, and it is what the fit score is measured against."
              />
            ) : (
              <ul className="divide-y divide-line">
                {icps.data!.items.map((icp) => (
                  <li key={icp.id} className="flex flex-wrap items-start gap-3 px-4 py-3.5">
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium text-ink">{icp.name}</p>
                      <p className="mt-0.5 text-[12px] text-ink-muted">
                        {icp.industry} · {icp.region}
                        {icp.employee_min || icp.employee_max
                          ? ` · ${icp.employee_min ?? 'any'}–${icp.employee_max ?? 'any'} staff`
                          : ''}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {icp.titles.map((title) => (
                          <Badge key={title}>{title}</Badge>
                        ))}
                      </div>
                    </div>
                    <Button variant="primary" size="sm" onClick={() => setTarget(icp)}>
                      Run discovery
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Run history">
            {runs.isLoading ? (
              <Loading />
            ) : runs.data!.items.length === 0 ? (
              <EmptyState title="No runs yet" />
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Started</Th>
                    <Th className="w-[110px]">Result</Th>
                    <Th className="w-[80px] text-right">Kept</Th>
                    <Th className="w-[90px] text-right">Rejected</Th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data!.items.map((item) => (
                    <tr
                      key={item.id}
                      onClick={() => setOpenRun(item.id)}
                      tabIndex={0}
                      role="link"
                      onKeyDown={(event) => event.key === 'Enter' && setOpenRun(item.id)}
                      className="cursor-pointer transition-colors hover:bg-sunken/70 focus-visible:bg-sunken"
                    >
                      <Td className="text-[13px] text-ink-secondary">
                        {dateTime(item.started_at)}
                        {item.error && (
                          <span className="mt-0.5 block text-[12px] text-critical">
                            {item.error}
                          </span>
                        )}
                      </Td>
                      <Td>
                        <Badge
                          tone={
                            item.status === 'completed'
                              ? 'good'
                              : item.status === 'failed'
                                ? 'critical'
                                : 'info'
                          }
                        >
                          {item.status}
                        </Badge>
                      </Td>
                      <Td className="tnum text-right font-medium">{item.leads_created}</Td>
                      <Td className="tnum text-right text-ink-muted">{item.leads_rejected}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <p className="border-t border-line px-4 py-2.5 text-[12px] text-ink-muted">
              Open a run to see the queries it issued, the pages it read, and why each rejected
              candidate was rejected.
            </p>
          </Card>
        </div>
      </div>

      {openRun && <RunDetailDialog runId={openRun} onClose={() => setOpenRun(null)} />}

      {target && (
        <RunDialog
          icp={target}
          onClose={() => setTarget(null)}
          onDone={() => {
            queryClient.invalidateQueries({ queryKey: ['runs'] })
            queryClient.invalidateQueries({ queryKey: ['icps'] })
            queryClient.invalidateQueries({ queryKey: ['leads'] })
            queryClient.invalidateQueries({ queryKey: ['dashboard'] })
          }}
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------------------

function RunDialog({
  icp,
  onClose,
  onDone,
}: {
  icp: Icp
  onClose: () => void
  onDone: () => void
}) {
  const [count, setCount] = useState(8)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    industry: icp.industry,
    region: icp.region,
    employee_min: icp.employee_min?.toString() ?? '',
    employee_max: icp.employee_max?.toString() ?? '',
    titles: icp.titles.join(', '),
    keywords: icp.keywords.join(', '),
  })
  const [result, setResult] = useState<DiscoveryRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = useMutation({
    mutationFn: async () => {
      // Edits are saved to the profile before the run rather than applied as
      // one-off overrides. The same profile is what the fit score is measured
      // against, so a lead scored on criteria the run did not use would be
      // quietly wrong.
      if (editing) {
        await api.patch<Icp>(`/api/v1/icps/${icp.id}`, {
          industry: draft.industry.trim(),
          region: draft.region.trim(),
          employee_min: draft.employee_min ? Number(draft.employee_min) : null,
          employee_max: draft.employee_max ? Number(draft.employee_max) : null,
          titles: draft.titles.split(',').map((t) => t.trim()).filter(Boolean),
          keywords: draft.keywords.split(',').map((k) => k.trim()).filter(Boolean),
        })
      }
      return api.post<DiscoveryRun>('/api/v1/discovery/run', { icp_id: icp.id, count })
    },
    onMutate: () => setError(null),
    onSuccess: (data) => {
      setResult(data)
      onDone()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Discovery could not run.'),
  })

  const set = (key: keyof typeof draft) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setDraft((previous) => ({ ...previous, [key]: event.target.value }))

  return (
    <Modal title="Run discovery" onClose={run.isPending ? () => {} : onClose} width="max-w-xl">
      <div className="space-y-4 p-4">
        <div className="rounded-lg border border-line bg-plane p-3">
          <div className="flex items-start justify-between gap-3">
            <p className="text-[13px] font-medium text-ink">{icp.name}</p>
            {!result && (
              <Button size="sm" variant="ghost" onClick={() => setEditing((on) => !on)}>
                {editing ? 'Cancel edit' : 'Edit for this run'}
              </Button>
            )}
          </div>

          {editing && !result ? (
            <div className="mt-3 space-y-3">
              <p className="text-[12px] text-ink-muted">
                These changes are saved to the profile, so the fit score stays measured against
                what the run actually used.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Industry">
                  <Input value={draft.industry} onChange={set('industry')} />
                </Field>
                <Field label="Region">
                  <Input value={draft.region} onChange={set('region')} />
                </Field>
                <Field label="Min headcount">
                  <Input
                    type="number"
                    min={0}
                    value={draft.employee_min}
                    onChange={set('employee_min')}
                  />
                </Field>
                <Field label="Max headcount">
                  <Input
                    type="number"
                    min={0}
                    value={draft.employee_max}
                    onChange={set('employee_max')}
                  />
                </Field>
              </div>
              <Field label="Target job titles" hint="Comma separated.">
                <Input value={draft.titles} onChange={set('titles')} />
              </Field>
              <Field label="Keywords">
                <Input value={draft.keywords} onChange={set('keywords')} />
              </Field>
            </div>
          ) : (
            <>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
                <Row label="Industry" value={icp.industry} />
                <Row label="Region" value={icp.region} />
                <Row
                  label="Headcount"
                  value={
                    icp.employee_min || icp.employee_max
                      ? `${icp.employee_min ?? 'any'}–${icp.employee_max ?? 'any'}`
                      : 'Any'
                  }
                />
                <Row label="Keywords" value={icp.keywords.join(', ') || 'None'} />
              </dl>
              <div className="mt-2.5 flex flex-wrap gap-1">
                {icp.titles.map((title) => (
                  <Badge key={title}>{title}</Badge>
                ))}
              </div>
            </>
          )}
        </div>

        {result ? (
          <>
            <Banner tone={result.leads_created > 0 ? 'good' : 'warning'}>
              {result.leads_created > 0
                ? `Found ${result.leads_created} lead${result.leads_created === 1 ? '' : 's'} across ${result.companies_created} new compan${result.companies_created === 1 ? 'y' : 'ies'}.`
                : 'The run finished but nothing survived validation. Try widening the profile.'}
              {result.leads_rejected > 0 &&
                ` ${result.leads_rejected} candidate(s) were rejected.`}
            </Banner>
            <div className="flex justify-end">
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </div>
          </>
        ) : (
          <>
            <Field
              label="How many leads to look for"
              hint="A smaller number finishes faster. The agent stops early if it runs out of good evidence."
            >
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={1}
                  max={15}
                  value={count}
                  onChange={(event) => setCount(Number(event.target.value))}
                  className="flex-1 accent-[var(--color-accent)]"
                  disabled={run.isPending}
                />
                <span className="tnum w-8 text-right text-[13px] font-semibold text-ink">
                  {count}
                </span>
              </div>
            </Field>

            {error && <Banner tone="critical">{error}</Banner>}
            {run.isPending && (
              <Banner tone="info">
                Searching, reading pages and extracting people. This usually takes 30–90 seconds —
                leave this open.
              </Banner>
            )}

            <div className="flex justify-end gap-2">
              <Button onClick={onClose} disabled={run.isPending}>
                Cancel
              </Button>
              <Button variant="primary" loading={run.isPending} onClick={() => run.mutate()}>
                Start run
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------

function RunDetailDialog({ runId, onClose }: { runId: string; onClose: () => void }) {
  const detail = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.get<DiscoveryRunDetail>(`/api/v1/discovery/runs/${runId}`),
  })

  return (
    <Modal title="Run detail" onClose={onClose} width="max-w-2xl">
      {detail.isLoading ? (
        <Loading />
      ) : detail.error ? (
        <ErrorState error={detail.error} onRetry={() => detail.refetch()} />
      ) : !detail.data ? null : (
        <div className="space-y-4 p-4">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px] sm:grid-cols-4">
            <Row label="Started" value={dateTime(detail.data.started_at)} />
            <Row label="Asked for" value={String(detail.data.requested_count)} />
            <Row label="Kept" value={String(detail.data.leads_created)} />
            <Row label="Rejected" value={String(detail.data.leads_rejected)} />
          </dl>

          {detail.data.error && <Banner tone="critical">{detail.data.error}</Banner>}

          <section>
            <h3 className="mb-1.5 text-[12px] font-semibold text-ink-muted">
              Pages the agent actually read
            </h3>
            {(detail.data.agent_log.visited_urls ?? []).length === 0 ? (
              <p className="text-[13px] text-ink-muted">None.</p>
            ) : (
              <ul className="space-y-1">
                {detail.data.agent_log.visited_urls!.map((url) => (
                  <li key={url}>
                    <a
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[12px] break-all text-accent hover:underline"
                    >
                      {url}
                    </a>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-1.5 text-[12px] text-ink-muted">
              A lead may only cite a page from this list. Anything else is discarded.
            </p>
          </section>

          <section>
            <h3 className="mb-1.5 text-[12px] font-semibold text-ink-muted">
              What the agent did — {detail.data.agent_log.searches ?? 0} searches,{' '}
              {detail.data.agent_log.fetches ?? 0} fetches
            </h3>
            <ol className="max-h-[260px] space-y-1.5 overflow-y-auto rounded-lg border border-line bg-plane p-3">
              {(detail.data.agent_log.transcript ?? []).map((entry, index) => (
                <li
                  key={index}
                  className="font-mono text-[11px] leading-relaxed break-all text-ink-secondary"
                >
                  {JSON.stringify(entry)}
                </li>
              ))}
            </ol>
          </section>

          <div className="flex justify-end">
            <Button onClick={onClose}>Close</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="truncate text-ink">{value}</dd>
    </>
  )
}

// ---------------------------------------------------------------------------

function IcpForm({ onCreated }: { onCreated: () => void }) {
  const empty = {
    name: '',
    industry: '',
    region: '',
    employee_min: '',
    employee_max: '',
    titles: '',
    keywords: '',
  }
  const [form, setForm] = useState(empty)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api.post<Icp>('/api/v1/icps', {
        name: form.name.trim(),
        industry: form.industry.trim(),
        region: form.region.trim(),
        employee_min: form.employee_min ? Number(form.employee_min) : null,
        employee_max: form.employee_max ? Number(form.employee_max) : null,
        // Comma-separated in the UI because that is how a salesperson lists
        // titles; split and cleaned before it reaches the API.
        titles: form.titles.split(',').map((t) => t.trim()).filter(Boolean),
        keywords: form.keywords.split(',').map((k) => k.trim()).filter(Boolean),
      }),
    onMutate: () => {
      setErrors({})
      setMessage(null)
    },
    onSuccess: () => {
      setForm(empty)
      setMessage('Saved. Run it from the list to find leads.')
      onCreated()
    },
    onError: (caught) => {
      if (caught instanceof ApiError) {
        setErrors(caught.fieldErrors)
        if (Object.keys(caught.fieldErrors).length === 0) setMessage(caught.message)
      }
    },
  })

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setForm((previous) => ({ ...previous, [key]: event.target.value }))

  return (
    <Card title="Define a profile">
      <form
        className="space-y-3.5 p-4"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
        noValidate
      >
        <Field label="Name" error={errors.name}>
          <Input value={form.name} onChange={set('name')} placeholder="Fashion brands in India" />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Industry" error={errors.industry}>
            <Input value={form.industry} onChange={set('industry')} placeholder="Fashion" />
          </Field>
          <Field label="Region" error={errors.region}>
            <Input value={form.region} onChange={set('region')} placeholder="India" />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Min headcount">
            <Input
              type="number"
              min={0}
              value={form.employee_min}
              onChange={set('employee_min')}
              placeholder="50"
            />
          </Field>
          <Field label="Max headcount">
            <Input
              type="number"
              min={0}
              value={form.employee_max}
              onChange={set('employee_max')}
              placeholder="5000"
            />
          </Field>
        </div>

        <Field
          label="Target job titles"
          hint="Comma separated. These drive the search and the fit score."
          error={errors.titles}
        >
          <Input
            value={form.titles}
            onChange={set('titles')}
            placeholder="Head of Merchandising, Supply Chain"
          />
        </Field>

        <Field label="Keywords" hint="Optional extra search terms.">
          <Input value={form.keywords} onChange={set('keywords')} placeholder="apparel, retail" />
        </Field>

        {message && <Banner tone={create.isError ? 'critical' : 'good'}>{message}</Banner>}

        <Button type="submit" variant="primary" className="w-full" loading={create.isPending}>
          Save profile
        </Button>
      </form>
    </Card>
  )
}
