import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { PageHeader } from '../components/Layout'
import {
  Badge,
  Banner,
  Button,
  Card,
  ErrorState,
  Field,
  Input,
  Loading,
  Textarea,
} from '../components/ui'
import { ApiError, api, type ProductProfile } from '../lib/api'
import { humanise } from '../lib/format'

export function OutreachProfilePage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState({
    name: '',
    description: '',
    sender_name: '',
    sender_email: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  const profile = useQuery({
    queryKey: ['product-profile'],
    queryFn: () => api.get<ProductProfile>('/api/v1/product-profile'),
  })

  // Seeded once the record arrives; the form owns the values from then on so
  // typing is not overwritten by a background refetch.
  useEffect(() => {
    if (profile.data) {
      setForm({
        name: profile.data.name,
        description: profile.data.description,
        sender_name: profile.data.sender_name,
        sender_email: profile.data.sender_email,
      })
    }
  }, [profile.data])

  const save = useMutation({
    mutationFn: () =>
      api.patch<ProductProfile>('/api/v1/product-profile', {
        name: form.name.trim(),
        description: form.description.trim(),
        sender_name: form.sender_name.trim(),
        sender_email: form.sender_email.trim() || undefined,
      }),
    onMutate: () => {
      setErrors({})
      setMessage(null)
    },
    onSuccess: () => {
      setMessage('Saved. The next generated email will use these details.')
      queryClient.invalidateQueries({ queryKey: ['product-profile'] })
    },
    onError: (caught) => {
      if (caught instanceof ApiError) {
        setErrors(caught.fieldErrors)
        if (Object.keys(caught.fieldErrors).length === 0) setMessage(caught.message)
      }
    },
  })

  if (profile.isLoading) return <Loading label="Loading profile" />
  if (profile.error) return <ErrorState error={profile.error} onRetry={() => profile.refetch()} />
  if (!profile.data) return null

  const set = (key: keyof typeof form) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((previous) => ({ ...previous, [key]: event.target.value }))

  return (
    <>
      <PageHeader
        title="Outreach profile"
        description="What you sell and who it comes from. Changes apply to the next email generated — no redeploy."
      />

      <div className="grid gap-6 p-6 xl:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
        <Card title="Your pitch">
          <form
            className="space-y-4 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              save.mutate()
            }}
            noValidate
          >
            <Field label="Product name" hint="Used in the body and the sign-off." error={errors.name}>
              <Input value={form.name} onChange={set('name')} />
            </Field>

            <Field
              label="What it does"
              hint="One phrase, completing 'we help apparel and fashion teams…'."
              error={errors.description}
            >
              <Textarea rows={3} value={form.description} onChange={set('description')} />
            </Field>

            <Field label="Default sender name" error={errors.sender_name}>
              <Input value={form.sender_name} onChange={set('sender_name')} />
            </Field>

            <Field
              label="Default reply-to"
              hint="A campaign can override this."
              error={errors.sender_email}
            >
              <Input type="email" value={form.sender_email} onChange={set('sender_email')} />
            </Field>

            {message && <Banner tone={save.isError ? 'critical' : 'good'}>{message}</Banner>}

            <Button type="submit" variant="primary" loading={save.isPending}>
              Save changes
            </Button>
          </form>
        </Card>

        <div className="space-y-6">
          <Card title="Email skeleton">
            <div className="space-y-3 p-4">
              <p className="text-[13px] text-ink-muted">
                The wording is fixed. Only the bracketed values are filled, and only from facts
                stored about the lead — a sentence whose value cannot be verified is dropped rather
                than guessed.
              </p>
              <ol className="space-y-2">
                {profile.data.template.body.map((sentence) => (
                  <li key={sentence.id} className="rounded-md border border-line px-3.5 py-2.5">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-[12px] font-medium text-ink-muted">{sentence.id}</span>
                      {sentence.optional && <Badge>optional</Badge>}
                    </div>
                    <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-ink">
                      {sentence.text}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          </Card>

          <Card title="Pain points">
            <div className="space-y-3 p-4">
              <p className="text-[13px] text-ink-muted">
                Each lead is matched to one of these, from what was observed about their company and
                from their own job title. The match decides the value-proposition sentence.
              </p>
              <ul className="space-y-2">
                {Object.entries(profile.data.pain_points).map(([key, pain]) => (
                  <li key={key} className="rounded-md border border-line px-3.5 py-2.5">
                    <p className="text-[13px] font-medium text-ink">{humanise(pain.label)}</p>
                    <p className="mt-0.5 text-[13px] text-ink-secondary">→ {pain.capability}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {pain.signals.slice(0, 6).map((signal) => (
                        <Badge key={signal}>{signal}</Badge>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
