/**
 * API client.
 *
 * One place knows about the token, the base URL and the server's error
 * envelope. Everything above this file deals in typed data or an ApiError, and
 * never in Response objects.
 */

const BASE = import.meta.env.VITE_API_URL ?? ''

const ACCESS_KEY = 'stylesense.access'
const REFRESH_KEY = 'stylesense.refresh'

export const tokens = {
  access: () => localStorage.getItem(ACCESS_KEY),
  refresh: () => localStorage.getItem(REFRESH_KEY),
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  },
}

export class ApiError extends Error {
  // Declared as fields rather than constructor parameter properties: the
  // project builds with `erasableSyntaxOnly`, which rules out the shorthand.
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }

  /** Field-level messages from a 422, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details.fields
    if (!Array.isArray(fields)) return {}
    return Object.fromEntries(
      fields.map((f: { field: string; message: string }) => [f.field, f.message]),
    )
  }
}

type Options = {
  method?: string
  body?: unknown
  params?: Record<string, string | number | boolean | undefined | null>
}

/** Refreshing is serialised: a page that fires six queries at once on an
 * expired token must not send six refresh requests and race. */
let refreshing: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const refresh_token = tokens.refresh()
  if (!refresh_token) return false

  refreshing ??= (async () => {
    try {
      const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token }),
      })
      if (!res.ok) return false
      const data = await res.json()
      tokens.set(data.access_token, data.refresh_token)
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()

  return refreshing
}

async function send<T>(path: string, options: Options, retry = true): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value))
    }
  }

  const headers: Record<string, string> = {}
  const access = tokens.access()
  if (access) headers.Authorization = `Bearer ${access}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(url.toString(), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    // A failed fetch is almost always the API being asleep or unreachable;
    // saying so beats "Failed to fetch".
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.')
  }

  // One transparent refresh-and-retry, then give up and let the app log out.
  if (response.status === 401 && retry && (await refreshAccessToken())) {
    return send<T>(path, options, false)
  }

  if (response.status === 204) return undefined as T

  const payload = await response.json().catch(() => null)

  if (!response.ok) {
    const error = payload?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'unknown_error',
      error?.message ?? response.statusText,
      error?.details ?? {},
    )
  }

  return payload as T
}

export const api = {
  get: <T>(path: string, params?: Options['params']) => send<T>(path, { params }),
  post: <T>(path: string, body?: unknown) => send<T>(path, { method: 'POST', body }),
  patch: <T>(path: string, body?: unknown) => send<T>(path, { method: 'PATCH', body }),
  delete: <T>(path: string) => send<T>(path, { method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Types mirrored from the API schemas
// ---------------------------------------------------------------------------

export type Page<T> = { items: T[]; total: number; limit: number; offset: number }

export type Role = 'admin' | 'member'

export type User = {
  id: string
  email: string
  full_name: string | null
  role: Role
  is_active: boolean
}

export type LeadStatus =
  | 'new' | 'queued' | 'sent' | 'delivered' | 'opened' | 'replied' | 'unsubscribed' | 'bounced'

export type Company = {
  id: string
  name: string
  domain: string | null
  industry: string | null
  region: string | null
  country: string | null
  employee_count: number | null
  source_url: string
}

export type Score = {
  total_score: number
  fit_score: number
  engagement_score: number
  status: LeadStatus
  breakdown: {
    fit: Record<string, number>
    engagement: Record<string, number>
    penalty: string | null
    band: 'hot' | 'warm' | 'cold'
  }
  computed_at: string
}

export type Lead = {
  id: string
  first_name: string
  last_name: string | null
  full_name: string
  job_title: string
  email: string | null
  linkedin_url: string | null
  source_url: string
  created_at: string
  company: Company
  score: Score | null
}

export type LeadEvent = {
  id: string
  event_type: string
  occurred_at: string
  campaign_id: string | null
  message_id: string | null
  metadata: Record<string, unknown>
}

export type ScoreHistory = {
  id: string
  old_score: number | null
  new_score: number
  delta: number
  reason: string
  created_at: string
}

export type LeadDetail = Lead & { events: LeadEvent[]; score_history: ScoreHistory[] }

export type Icp = {
  id: string
  name: string
  industry: string
  region: string
  employee_min: number | null
  employee_max: number | null
  titles: string[]
  keywords: string[]
  created_at: string
}

export type DiscoveryRun = {
  id: string
  icp_id: string
  status: 'running' | 'completed' | 'failed'
  requested_count: number
  companies_created: number
  leads_created: number
  leads_rejected: number
  error: string | null
  started_at: string | null
  completed_at: string | null
}

/** GET /discovery/runs/{id} adds the tool transcript: which queries ran, which
 *  pages were read, and why each rejected candidate was rejected. */
export type DiscoveryRunDetail = DiscoveryRun & {
  agent_log: {
    transcript?: Record<string, unknown>[]
    visited_urls?: string[]
    searches?: number
    fetches?: number
  }
}

export type Campaign = {
  id: string
  name: string
  description: string | null
  icp_id: string | null
  status: 'draft' | 'active' | 'paused' | 'completed'
  sender_name: string
  sender_email: string
  created_at: string
  lead_count: number
  sent_count: number
  opened_count: number
  replied_count: number
}

export type TokenProvenance = {
  value: string | null
  origin: string
  source_field: string | null
  source_url: string | null
  verdict: { grounded: boolean; reason: string; unsupported: string[] }
}

export type Message = {
  id: string
  subject: string
  body_text: string
  status: 'draft' | 'sent' | 'failed' | 'suppressed'
  to_address: string | null
  sent_at: string | null
  error: string | null
  tokens: Record<string, TokenProvenance>
  grounding_report: {
    checked: number
    blocked: number
    violations: Record<string, unknown>
    evidence_fields: string[]
  }
  dropped_sentences: string[]
}

export type ReplyIntent = 'interested' | 'needs_info' | 'not_now' | 'wrong_person' | 'unsubscribe'

export type Reply = {
  id: string
  lead_id: string
  raw_text: string
  intent: ReplyIntent
  confidence: number | null
  reasoning: string | null
  draft_response: string | null
  classifier_model: string | null
  approved: boolean
  approved_at: string | null
  created_at: string
}

export type Dashboard = {
  scope: 'all' | 'own'
  total_leads: number
  hot: number
  warm: number
  cold: number
  average_score: number
  by_status: { status: LeadStatus; count: number }[]
  emails_sent: number
  emails_opened: number
  replies: number
  unsubscribes: number
  by_owner: {
    user_id: string | null
    email: string | null
    full_name: string | null
    leads: number
    hot: number
  }[]
}

export type ProductProfile = {
  id: string
  name: string
  description: string
  sender_name: string
  sender_email: string
  segments: Record<string, unknown>
  pain_points: Record<string, { label: string; capability: string; signals: string[] }>
  research_signals: string[][]
  template: {
    subject_options: string[]
    body: { id: string; text: string; required: string[]; optional?: boolean }[]
    optional_tokens: Record<string, { prefix: string }>
  }
  updated_at: string
}
