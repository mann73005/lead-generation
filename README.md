# StyleSense — lead generation and outreach platform

A sales console that takes a description of an ideal customer, finds real people
on the web who match it, scores them, writes outreach that only says things it
can prove, tracks what happens, and re-ranks the list as leads engage.

Built for the Full Stack + AI Engineer take-home. The LLM is one component
inside the system, not the system.

---

## Try it

| | |
|---|---|
| **Console** | https://stylesense-console.onrender.com |
| **API** | https://stylesense-api-vmwr.onrender.com |
| **API docs** | https://stylesense-api-vmwr.onrender.com/docs |
| **Sign in** | `demo@stylesense.ai` / `demo1234` |

> Both services are on Render's free tier and **sleep after ~15 minutes idle**.
> The first request takes roughly 50 seconds to wake them. If the console looks
> stuck on the login screen, give it a moment — or open
> [`/health`](https://stylesense-api-vmwr.onrender.com/health) first to warm the
> API.

A step-by-step walkthrough of every screen is in **[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**.

---

## What it does

```
ICP  →  discover  →  store  →  score  →  generate  →  send  →  track
                       ↑                                          │
                       └──────── re-score ─────── classify reply ─┘
```

1. **Define an ICP** — industry, region, headcount band, target job titles.
2. **Discovery** runs a bounded search-then-extract flow: deterministic
   ICP-derived searches, then an LLM with `search` and `fetch_page` tools reads
   the pages and extracts named people. Every lead stores the page it came from.
3. **Scoring** gives each lead 0–100 from fit (ICP match) and engagement
   (delivered, opened, replied), recomputed from the event history on every
   event, with a recorded reason for each change.
4. **Outreach** fills the fixed Appendix A skeleton from stored fields only. A
   sentence whose value cannot be verified is dropped rather than guessed.
5. **Tracking** records delivered, opened and unsubscribed as discrete events
   via a tracking pixel and a working unsubscribe link.
6. **Replies** are classified into five intents with a drafted response for a
   human to approve, and the score moves again.

---

## Running it locally

### Prerequisites

Python 3.12+, Node 20+, and a PostgreSQL database (Supabase's free tier works).

### Backend

```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp ../.env.example ../.env             # then fill it in — see below
alembic upgrade head
uvicorn app.main:app --reload
```

The API comes up on http://localhost:8000, with docs at `/docs`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local             # DEV_API_TARGET=http://localhost:8000
npm run dev
```

The console comes up on http://localhost:5173. In development it proxies
`/api`, `/t` and `/u` to the backend, so the browser stays on one origin.

### Tests

```bash
cd backend && python -m pytest                      # 192 tests
python scripts/evaluate_classifier.py               # classification accuracy
python scripts/evaluate_classifier.py --keyword     # the deterministic fallback
```

The suite runs against a real PostgreSQL database inside a transaction that is
rolled back, so it exercises the actual constraints and cascades without
leaving anything behind. It never reaches the network: all four providers are
replaced with mocks.

### Environment

Everything is read from the environment; nothing is committed. See
[`.env.example`](.env.example) for the full list.

| Variable | Needed for |
|---|---|
| `DATABASE_URL` | PostgreSQL. Supabase users: use the **session pooler** (port 5432), not the transaction pooler — the latter has no prepared statements and breaks migrations |
| `JWT_SECRET` | Token signing |
| `BOOTSTRAP_USER_EMAIL` / `_PASSWORD` | Seeds the first administrator on first boot |
| `GEMINI_API_KEY` | Discovery, token phrasing, reply classification |
| `TAVILY_API_KEY` | The `search` and `fetch_page` tools |
| `RESEND_API_KEY` | Sending |
| `EMAIL_OVERRIDE_TO` | **Every send is redirected here.** See Compliance |
| `CORS_ORIGINS` | The console's origin, in production |

`PUBLIC_BASE_URL` is deliberately optional: it is derived from the hosting
platform's own hostname variable, so the tracking pixel URL follows the real
domain instead of a value that silently goes stale on the next deploy.

---

## Architecture

```
React 19 + TypeScript (Vite)
        │  REST, JWT bearer
        ▼
FastAPI ── api/v1 ── services ── providers (Protocols)
                         │            │
                         │            ├── Gemini    (LLM)
                         │            ├── Tavily    (search + fetch)
                         │            └── Resend    (email)
                         ▼
                   PostgreSQL
```

### Data model

Fourteen tables across five concerns.

| Concern | Tables |
|---|---|
| Identity | `companies`, `leads`, `icps`, `users`, `product_profiles` |
| Discovery | `discovery_runs` (full tool transcript in JSONB) |
| Outreach | `campaigns`, `campaign_leads`, `email_messages` |
| Raw facts | `email_events` — append-only |
| Derived | `lead_scores` (one row per lead), `score_history` (append-only) |
| Compliance | `suppressed_emails` |

**The separation the brief asks for is physical.** `email_events` is append-only
and never updated. Scores, lifecycle status and every console filter are
projections over it. The scoring engine is a pure function of
`(lead, company, icp, events, reply_intent)` — delete every row in
`lead_scores`, replay the events, and the numbers come back identical. That is
what makes changing a weight safe.

Enums are `VARCHAR` + `CHECK` rather than native PostgreSQL enum types, so
adding a value stays an ordinary transactional migration.

### API shape

48 routes under `/api/v1`, plus two unauthenticated ones at the root.

```
POST   /auth/login · /auth/refresh · GET /auth/me
GET    /dashboard
CRUD   /users          (admin only)
CRUD   /icps · /companies · /leads · /campaigns · /events · /replies
GET    /product-profile · PATCH /product-profile
POST   /discovery/run · GET /discovery/runs · /discovery/runs/{id}
POST   /campaigns/{id}/leads/{lead_id}/messages     generate a draft
POST   /messages/{id}/send                          send it
GET    /t/{token}.png                               open pixel     (no auth)
GET    /u/{token}                                   unsubscribe    (no auth)
```

Lists take `limit`/`offset` and return `{items, total, limit, offset}`.
Leads additionally take `q`, `status`, `industry`, `min_score`, `max_score`,
`campaign_id`, `sort` and `order`.

Every failure — including request validation — leaves the API in one shape, so
the console has a single error branch:

```json
{ "error": { "code": "validation_error", "message": "…", "details": { "fields": [...] } } }
```

The two tracking routes are deliberately unauthenticated and outside `/api/v1`:
they are fetched by a mail client and clicked from an inbox, neither of which
carries a bearer token. Their opaque per-message tokens are what authorise them.

---

## Scoring

All weights live in [`backend/config/scoring.yaml`](backend/config/scoring.yaml).
There is not a single scoring constant in the Python source.

### Fit — what the lead is (max 60)

| Component | Points |
|---|---|
| Industry matches the ICP | 20 |
| Region or country matches | 12 |
| Headcount inside the ICP band | 8 |
| Job title contains a target title | 15 |
| Title shares distinguishing words only | 7 |
| Has an email address | 3 |
| Has a LinkedIn URL | 2 |

### Engagement — what the lead did (max 40)

| Component | Points |
|---|---|
| Delivered | 5 |
| Opened | 10 |
| Replied | 15 |
| Each repeat open | +2, capped at +4 |
| Reply intent | interested +6 · needs info +3 · not now −5 · wrong person −10 · unsubscribe −15 |

### Overrides

Unsubscribed caps the score at **0**; bounced caps it at **10**. Compliance and
deliverability are not tradeable against fit.

### Two deliberate choices

**60 + 40 = exactly 100, so the final clamp never binds.** An earlier version
used 70 + 45; every strong lead piled up at 100 and the top of the list lost its
ordering. The config is validated against this at load time.

**Sending scores nothing.** Delivery is our action, not the lead's. Only what
*they* do moves the number.

Bands: **hot ≥ 75**, **warm ≥ 50**, cold below.

---

## The AI components

### Discovery — bounded, not autonomous

The brief says a two-step search-then-extract flow is sufficient, and that is
what this is.

```
Phase A0  deterministic seed — 5 ICP-derived searches + fetch top 6   [0 LLM calls]
Phase A1  optional refinement — 1 turn, tools gated                   [1 LLM call]
Phase B   structured extraction against a response schema             [1 LLM call]
Phase C   Pydantic validation, then business validation               [0 LLM calls]
Phase D   persist + score
```

Seeding deterministically does two things: it keeps LLM calls off a metered free
tier, and it guarantees the model starts with real evidence. Left to itself the
agent spent its whole turn budget refining queries and never opened a page.

**The model never writes to the database.** Output passes Pydantic for shape,
then `app/ai/validation.py` for believability. A lead citing a page the agent
never fetched is discarded, not stored with a caveat.

Login-gated sites and job boards are filtered from results: the first return the
wall rather than the page, the second list vacancies rather than the people who
hold them.

### Grounding — the programmatic check

`app/ai/grounding.py`. The rule is mechanical, not a second model asking the
first one whether it was honest. A filled token may only contain *specifics*
already present in the evidence stored for that lead:

- **numbers** the evidence does not contain
- **proper nouns** the evidence does not contain

Ordinary prose is left alone. The check does not verify that a sentence is
*true*; it verifies that everything concrete it asserts came from a stored field
or a cited page — which is what makes the claim checkable by a human.

```
PASS   TechnoSport appointed a new head of supply chain operations
PASS   your 400 employees                      ← 400 is the stored headcount
BLOCK  TechnoSport recently opened 20 new stores        unsupported: ['20']
BLOCK  your expansion into Singapore and Dubai          unsupported: ['Singapore', 'Dubai']
```

Figures are compared as whole values with separators normalised, so a fabricated
`40` is not waved through by a stored `400`, and a claimed `1,200` matches a
stored `1200`.

When a required token fails, the **whole sentence** is dropped — the template is
modelled as sentences for exactly this reason. Optional tokens are omitted with
their connecting punctuation, so nothing is left reading `… - .`

Every verdict is persisted on the message and shown in the console beside the
draft, before anyone decides to send.

### Reply classification

Five intents fixed by the brief. A deterministic keyword pass runs first and is
used whenever the model is unavailable or returns a label outside the set, so an
exhausted quota degrades accuracy instead of disabling the feature.

**Measured against 8 hand-labelled replies** in
[`backend/data/labelled_replies.json`](backend/data/labelled_replies.json):

| Classifier | Accuracy |
|---|---|
| **LLM (Gemini)** | **8/8 — 100%** |
| Keyword fallback | 5/8 — 62.5% |

```bash
python scripts/evaluate_classifier.py
```

Two honest caveats. Eight examples cannot establish an accuracy figure to any
precision — the per-label breakdown matters more, because it catches a
classifier that never predicts a whole label. And the keyword rules are
deliberately **not** tuned against this set: fitting phrases to eight examples
would measure nothing.

The drafted response is persisted unsent and requires an explicit approval
action. Nothing in this system mails a reply on its own.

---

## Compliance

**GDPR / CAN-SPAM.** Every outbound email carries a working one-click
unsubscribe link and a `List-Unsubscribe` header; opting out writes the address
to a global suppression list that is checked inside the send path, so there is
no route to the provider that can bypass it. Discovered prospects are never
contacted: `EMAIL_OVERRIDE_TO` redirects every send to an inbox we control, and
the address actually used is recorded on the message.

A reply classified as an unsubscribe suppresses the address too — an opt-out
counts however it arrives, not only through the footer link.

---

## Key decisions

**Config over constants.** Three validated YAML files hold everything that is a
judgement call: scoring weights, discovery budgets and source rules and prompts,
and the product identity with its outreach template. Retuning them does not mean
editing code.

**The product profile is a table, not a file.** `config/product.yaml` seeds it
on first boot; after that the console owns it. Changing the pitch, the sender or
the template takes effect on the next generated email, with no redeploy.

**Vendor-neutral providers.** Search, fetch, LLM and email are Protocols with
neutral types. No service imports a vendor SDK. Gemini's wire format — including
the `thoughtSignature` its thinking models require to be echoed back — is
translated at the boundary.

**Mocks that fail realistically.** The brief allows mocking an unavailable
provider on the condition that the mock still fails realistically, so the mocks
reproduce empty result sets, unrenderable pages, overload errors and recipient
rejections — not just their happy paths.

**Quota as a fallback chain.** Gemini's free tier meters requests per day *per
model*, so a 429 falls through to the next model while a transient 503 retries
in place. The two are distinguished by reading the quota scope out of the error.

**Synchronous.** The brief permits it for core scope. A discovery run takes
30–90 seconds and the console shows a progress state rather than pretending
otherwise. A job queue is a stretch item.

---

## Scope notes

**The brief contradicts itself on authentication.** §3.1 requires authentication
and token management on all lead and campaign routes; §4 says to assume a single
user with no login. §3.1 is the graded Core Scope, so auth is implemented — JWT
access and refresh tokens, with refresh tokens rejected where an access token is
required — but kept to one bootstrapped account rather than a signup flow, which
satisfies both readings.

**§1 and §4 also disagree on background processing.** §1 lists it among the
things the assignment involves; §4 says synchronous calls are acceptable and §5
lists a job queue as a stretch item. The latter two win.

**§3.1 asks for clicks in the raw event table while §3.2 excludes click
tracking.** The `clicked` event type exists in the schema and is never emitted —
the schema stays extensible, the implementation stays in scope.

**Roles and per-user ownership go beyond the brief.** Leads, ICPs and campaigns
carry an owner; a salesperson sees their own, an administrator sees everyone's
and manages accounts. This was added at the reviewer's request during the build.
Ownership is enforced in the query rather than the UI, and asking for another
user's record returns 404 rather than 403 so the endpoint cannot confirm that an
id exists.

### Deliberately not built

Click tracking, multi-step follow-up sequences, real inbound email ingestion, a
job queue, MongoDB, and a self-replanning agent. All are listed as stretch items;
the brief warns that a shaky stretch attempt counts against you more than
skipping it.

---

## What I would build next

1. **A job queue.** Discovery blocks an HTTP request for up to 90 seconds. It
   should return a run id immediately and stream progress.
2. **Real inbound email.** The simulate-reply box has the same shape a provider
   webhook would post into, so this is a transport change rather than a rewrite.
3. **Deliverability.** Sending from a verified domain with SPF, DKIM and DMARC.
   Resend's shared sandbox domain lands in spam, which is fine for a demo and
   not fine for anything else.
4. **A bigger labelled set.** Eight replies measure almost nothing. A few
   hundred, with inter-annotator agreement, would let the classifier be tuned
   against something real.
5. **Scheduled rescoring and follow-up rules.** "No open after N days → resend"
   needs a scheduler, which arrives with the queue.
6. **Per-lead rescore on ICP edit.** Editing a profile currently leaves existing
   leads on their old numbers until their next event; a background rebuild would
   close that.

---

## Repository

```
backend/
  app/
    api/          routes — v1/ plus the unauthenticated tracking endpoints
    ai/           discovery, grounding, email building, classification
    core/         settings, database, security, errors, policy loaders
    models/       SQLAlchemy models
    providers/    Protocols + Gemini, Tavily, Resend, and the mocks
    schemas/      Pydantic request/response models
    services/     scoring, events, outreach, suppression, product profile
  config/         scoring.yaml · discovery.yaml · product.yaml
  data/           labelled_replies.json
  scripts/        evaluate_classifier.py
  tests/          192 tests
frontend/
  src/
    components/   layout, primitives, charts
    lib/          api client, auth, formatting
    pages/        login, dashboard, leads, lead detail, discovery, campaigns,
                  outreach profile, team
docs/
  USER_GUIDE.md   walkthrough of every screen
  SAMPLE_EMAILS.md  three generated emails with their grounding reports
```
