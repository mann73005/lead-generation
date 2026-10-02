import type { LeadStatus, ReplyIntent } from './api'

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const seconds = Math.round((Date.now() - then) / 1000)

  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Turn a snake_case enum value into something a person reads. */
export function humanise(value: string): string {
  return value.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

export const STATUS_TONE: Record<LeadStatus, 'neutral' | 'info' | 'good' | 'warning' | 'critical'> =
  {
    new: 'neutral',
    queued: 'neutral',
    sent: 'info',
    delivered: 'info',
    opened: 'warning',
    replied: 'good',
    bounced: 'critical',
    unsubscribed: 'critical',
  }

export const INTENT_TONE: Record<ReplyIntent, 'good' | 'info' | 'warning' | 'critical'> = {
  interested: 'good',
  needs_info: 'info',
  not_now: 'warning',
  wrong_person: 'warning',
  unsubscribe: 'critical',
}

export function band(score: number | null | undefined): 'hot' | 'warm' | 'cold' {
  if (score == null) return 'cold'
  if (score >= 75) return 'hot'
  if (score >= 50) return 'warm'
  return 'cold'
}
