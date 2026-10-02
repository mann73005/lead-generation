import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

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
  Modal,
  Select,
  Table,
  Td,
  Th,
} from '../components/ui'
import { ApiError, api, type Page, type User } from '../lib/api'
import { useAuth } from '../lib/auth'

export function UsersPage() {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const users = useQuery({
    queryKey: ['users'],
    queryFn: () => api.get<Page<User>>('/api/v1/users', { limit: 100 }),
  })

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<User> }) =>
      api.patch<User>(`/api/v1/users/${id}`, body),
    onMutate: () => setError(null),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not update that account.'),
  })

  return (
    <>
      <PageHeader
        title="Team"
        description="Salespeople see only their own leads. Administrators see everyone's."
        action={
          <Button variant="primary" onClick={() => setCreating(true)}>
            Add person
          </Button>
        }
      />

      <div className="space-y-4 p-6">
        {error && <Banner tone="critical">{error}</Banner>}

        <Card title={`${users.data?.total ?? 0} accounts`}>
          {users.isLoading ? (
            <Loading />
          ) : users.error ? (
            <ErrorState error={users.error} onRetry={() => users.refetch()} />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Person</Th>
                  <Th className="w-[140px]">Role</Th>
                  <Th className="w-[110px]">Status</Th>
                  <Th className="w-[120px] text-right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {users.data!.items.map((person) => {
                  const isSelf = person.id === me?.id
                  return (
                    <tr key={person.id} className="hover:bg-sunken/60">
                      <Td>
                        <span className="font-medium text-ink">
                          {person.full_name || person.email}
                        </span>
                        {person.full_name && (
                          <span className="block text-[12px] text-ink-muted">{person.email}</span>
                        )}
                      </Td>
                      <Td>
                        <Select
                          value={person.role}
                          // Self-demotion is refused by the API too; disabling it
                          // here just avoids offering an action that cannot work.
                          disabled={isSelf || update.isPending}
                          className="h-7 text-[13px]"
                          aria-label={`Role for ${person.email}`}
                          onChange={(event) =>
                            update.mutate({
                              id: person.id,
                              body: { role: event.target.value as User['role'] },
                            })
                          }
                        >
                          <option value="member">Salesperson</option>
                          <option value="admin">Administrator</option>
                        </Select>
                      </Td>
                      <Td>
                        <Badge tone={person.is_active ? 'good' : 'neutral'}>
                          {person.is_active ? 'Active' : 'Deactivated'}
                        </Badge>
                      </Td>
                      <Td className="text-right">
                        {isSelf ? (
                          <span className="text-[12px] text-ink-muted">You</span>
                        ) : (
                          <Button
                            size="sm"
                            variant={person.is_active ? 'danger' : 'secondary'}
                            disabled={update.isPending}
                            onClick={() =>
                              update.mutate({
                                id: person.id,
                                body: { is_active: !person.is_active },
                              })
                            }
                          >
                            {person.is_active ? 'Deactivate' : 'Reactivate'}
                          </Button>
                        )}
                      </Td>
                    </tr>
                  )
                })}
              </tbody>
            </Table>
          )}
          <p className="border-t border-line px-4 py-2.5 text-[12px] text-ink-muted">
            Deactivating someone signs them out immediately. Their leads and history stay intact and
            attributed to them.
          </p>
        </Card>
      </div>

      {creating && (
        <UserForm
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false)
            queryClient.invalidateQueries({ queryKey: ['users'] })
          }}
        />
      )}
    </>
  )
}

function UserForm({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [form, setForm] = useState({
    email: '',
    full_name: '',
    password: '',
    role: 'member' as User['role'],
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () =>
      api.post<User>('/api/v1/users', {
        email: form.email.trim(),
        full_name: form.full_name.trim() || null,
        password: form.password,
        role: form.role,
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

  return (
    <Modal title="Add a person" onClose={onClose}>
      <form
        className="space-y-4 p-4"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
        noValidate
      >
        <Field label="Email" error={errors.email}>
          <Input
            type="email"
            value={form.email}
            onChange={(event) => setForm({ ...form, email: event.target.value })}
            placeholder="name@company.com"
            autoFocus
          />
        </Field>

        <Field label="Full name">
          <Input
            value={form.full_name}
            onChange={(event) => setForm({ ...form, full_name: event.target.value })}
            placeholder="Optional"
          />
        </Field>

        <Field label="Temporary password" hint="At least 8 characters." error={errors.password}>
          <Input
            type="text"
            value={form.password}
            onChange={(event) => setForm({ ...form, password: event.target.value })}
            placeholder="Share this with them directly"
          />
        </Field>

        <Field label="Role">
          <Select
            value={form.role}
            onChange={(event) => setForm({ ...form, role: event.target.value as User['role'] })}
          >
            <option value="member">Salesperson — sees only their own leads</option>
            <option value="admin">Administrator — sees everything</option>
          </Select>
        </Field>

        {message && <Banner tone="critical">{message}</Banner>}

        <div className="flex justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={create.isPending}>
            Create account
          </Button>
        </div>
      </form>
    </Modal>
  )
}
