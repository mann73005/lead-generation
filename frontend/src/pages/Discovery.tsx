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
  Table,
  Td,
  Th,
} from '../components/ui'
import { ApiError, api, type DiscoveryRun, type Icp, type Page } from '../lib/api'
import { dateTime } from '../lib/format'

export function DiscoveryPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [runningFor, setRunningFor] = useState<string | null>(null)

  const icps = useQuery({
    queryKey: ['icps'],
    queryFn: () => api.get<Page<Icp>>('/api/v1/icps', { limit: 50 }),
  })
  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.get<Page<DiscoveryRun>>('/api/v1/discovery/runs', { limit: 20 }),
  })

  const run = useMutation({
    mutationFn: (icpId: string) =>
      api.post<DiscoveryRun>('/api/v1/discovery/run', { icp_id: icpId, count: 8 }),
    onMutate: (icpId) => {
      setError(null)
      setRunningFor(icpId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] })
      queryClient.invalidateQueries({ queryKey: ['leads'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Discovery could not be started.'),
    onSettled: () => setRunningFor(null),
  })

  return (
    <>
      <PageHeader
        title="Discovery"
        description="Describe who you sell to. Discovery searches the live web and extracts matching people."
      />

      <div className="grid gap-6 p-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <IcpForm onCreated={() => queryClient.invalidateQueries({ queryKey: ['icps'] })} />

        <div className="space-y-6">
          {error && <Banner tone="critical">{error}</Banner>}

          <Card title="Your profiles">
            {icps.isLoading ? (
              <Loading />
            ) : icps.error ? (
              <ErrorState error={icps.error} onRetry={() => icps.refetch()} />
            ) : icps.data!.items.length === 0 ? (
              <EmptyState
                title="No profiles yet"
                description="Create one on the left to tell discovery what to look for."
              />
            ) : (
              <ul className="divide-y divide-line">
                {icps.data!.items.map((icp) => (
                  <li key={icp.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-ink">{icp.name}</p>
                      <p className="mt-0.5 text-[12px] text-ink-muted">
                        {icp.industry} · {icp.region}
                        {icp.employee_min || icp.employee_max
                          ? ` · ${icp.employee_min ?? 'any'}–${icp.employee_max ?? 'any'} staff`
                          : ''}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {icp.titles.map((title) => (
                          <Badge key={title}>{title}</Badge>
                        ))}
                      </div>
                    </div>
                    <Button
                      variant="primary"
                      size="sm"
                      loading={runningFor === icp.id}
                      disabled={run.isPending}
                      onClick={() => run.mutate(icp.id)}
                    >
                      Find leads
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {run.isPending && (
              <p className="border-t border-line px-4 py-2.5 text-[12px] text-ink-muted">
                Searching the web and reading pages. This usually takes 30–90 seconds.
              </p>
            )}
          </Card>

          <Card title="Recent runs">
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
                    <Th className="w-[80px] text-right">Found</Th>
                    <Th className="w-[90px] text-right">Rejected</Th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data!.items.map((item) => (
                    <tr key={item.id}>
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
                      <Td className="tnum text-right">{item.leads_created}</Td>
                      <Td className="tnum text-right text-ink-muted">{item.leads_rejected}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
            <p className="border-t border-line px-4 py-2.5 text-[12px] text-ink-muted">
              Rejected candidates are ones whose source page could not be verified, or who are not
              in a buying role.
            </p>
          </Card>
        </div>
      </div>
    </>
  )
}

function IcpForm({ onCreated }: { onCreated: () => void }) {
  const [form, setForm] = useState({
    name: '',
    industry: '',
    region: '',
    employee_min: '',
    employee_max: '',
    titles: '',
    keywords: '',
  })
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
        // Comma-separated in the UI because that is how a salesperson thinks
        // about a title list; split and cleaned before it reaches the API.
        titles: form.titles.split(',').map((t) => t.trim()).filter(Boolean),
        keywords: form.keywords.split(',').map((k) => k.trim()).filter(Boolean),
      }),
    onMutate: () => {
      setErrors({})
      setMessage(null)
    },
    onSuccess: () => {
      setForm({
        name: '',
        industry: '',
        region: '',
        employee_min: '',
        employee_max: '',
        titles: '',
        keywords: '',
      })
      setMessage('Profile saved. Run it from the list to find leads.')
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
    <Card title="New profile">
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
          hint="Comma separated. These drive both the search and the fit score."
          error={errors.titles}
        >
          <Input
            value={form.titles}
            onChange={set('titles')}
            placeholder="Head of Merchandising, Supply Chain"
          />
        </Field>

        <Field label="Keywords" hint="Optional extra terms for the search.">
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
