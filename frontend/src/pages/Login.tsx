import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { Button, Field, Input } from '../components/ui'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'

export function LoginPage() {
  const { user, loading, signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!loading && user) return <Navigate to="/" replace />

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await signIn(email.trim(), password)
    } catch (caught) {
      // The real message is shown rather than a generic one: a configuration
      // fault here ("the app is calling itself instead of the API") is
      // something the person deploying needs to read, and "please try again"
      // sends them round the same loop.
      setError(
        caught instanceof ApiError || caught instanceof Error
          ? caught.message
          : 'Could not sign in. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[360px]">
        <div className="mb-7 flex items-center gap-2.5">
          <span className="grid size-7 place-items-center rounded bg-ink text-[12px] font-bold text-white">
            S
          </span>
          <div>
            <p className="text-sm font-semibold tracking-tight">StyleSense</p>
            <p className="text-[12px] text-ink-muted">Sales console</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="panel space-y-4 p-5" noValidate>
          <div>
            <h1 className="text-base font-semibold text-ink">Sign in</h1>
            <p className="mt-0.5 text-[13px] text-ink-muted">
              Use the account your administrator created for you.
            </p>
          </div>

          <Field label="Email">
            <Input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              placeholder="you@company.com"
              required
              autoFocus
            />
          </Field>

          <Field label="Password">
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••"
              required
            />
          </Field>

          {/* Announced, not just coloured, so a screen reader reaches it. */}
          {error && (
            <p role="alert" className="rounded-md bg-critical-soft px-3 py-2 text-[13px] text-critical">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" className="w-full" loading={submitting}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  )
}
