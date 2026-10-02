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
import { ApiError, api, type Campaign, type Page } from '../lib/api'
import { relativeTime } from '../lib/format'

export function CampaignsPage() {
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)

  const campaigns = useQuery({
    queryKey: ['campaigns'],
    queryFn: () => api.get<Page<Campaign>>('/api/v1/campaigns', { limit: 50 }),
  })

  return (
    <>
      <PageHeader
        title="Campaigns"
        description="A campaign carries the sender identity and the unsubscribe link for every email in it."
        action={
          <Button variant="primary" onClick={() => setCreating(true)}>
            New campaign
          </Button>
        }
      />

      <div className="p-6">
        <Card title={`${campaigns.data?.total ?? 0} campaigns`}>
          {campaigns.isLoading ? (
            <Loading />
          ) : campaigns.error ? (
            <ErrorState error={campaigns.error} onRetry={() => campaigns.refetch()} />
          ) : campaigns.data!.items.length === 0 ? (
            <EmptyState
              title="No campaigns yet"
              description="Create one before generating outreach — it supplies the sender name and the opt-out link."
              action={
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New campaign
                </Button>
              }
            />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Campaign</Th>
                  <Th className="w-[100px]">Status</Th>
                  <Th className="w-[80px] text-right">Leads</Th>
                  <Th className="w-[80px] text-right">Sent</Th>
                  <Th className="w-[80px] text-right">Opened</Th>
                  <Th className="w-[80px] text-right">Replied</Th>
                  <Th className="w-[90px] text-right">Created</Th>
                </tr>
              </thead>
              <tbody>
                {campaigns.data!.items.map((campaign) => (
                  <tr key={campaign.id} className="hover:bg-sunken/60">
                    <Td>
                      <span className="font-medium text-ink">{campaign.name}</span>
                      <span className="block text-[12px] text-ink-muted">
                        From {campaign.sender_name}
                      </span>
                    </Td>
                    <Td>
                      <Badge tone={campaign.status === 'active' ? 'good' : 'neutral'}>
                        {campaign.status}
                      </Badge>
                    </Td>
                    <Td className="tnum text-right">{campaign.lead_count}</Td>
                    <Td className="tnum text-right">{campaign.sent_count}</Td>
                    <Td className="tnum text-right">{campaign.opened_count}</Td>
                    <Td className="tnum text-right">{campaign.replied_count}</Td>
                    <Td className="text-right text-[12px] text-ink-muted">
                      {relativeTime(campaign.created_at)}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

      {creating && (
        <CampaignForm
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            queryClient.invalidateQueries({ queryKey: ['campaigns'] })
          }}
        />
      )}
    </>
  )
}

function CampaignForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({ name: '', sender_name: '', sender_email: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api.post<Campaign>('/api/v1/campaigns', {
        name: form.name.trim(),
        sender_name: form.sender_name.trim(),
        sender_email: form.sender_email.trim(),
      }),
    onMutate: () => {
      setErrors({})
      setMessage(null)
    },
    onSuccess: onCreated,
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
    <Modal title="New campaign" onClose={onClose}>
      <form
        className="space-y-4 p-4"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
        noValidate
      >
        <Field label="Campaign name" error={errors.name}>
          <Input value={form.name} onChange={set('name')} placeholder="Q1 fashion outreach" autoFocus />
        </Field>

        <Field
          label="Sender name"
          hint="Appears in the sign-off of every email in this campaign."
          error={errors.sender_name}
        >
          <Input value={form.sender_name} onChange={set('sender_name')} placeholder="Your name" />
        </Field>

        <Field
          label="Reply-to address"
          hint="Where a reply would land. Delivery itself always goes to the sandbox inbox."
          error={errors.sender_email}
        >
          <Input
            type="email"
            value={form.sender_email}
            onChange={set('sender_email')}
            placeholder="you@company.com"
          />
        </Field>

        {message && <Banner tone="critical">{message}</Banner>}

        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create
          </Button>
        </div>
      </form>
    </Modal>
  )
}
