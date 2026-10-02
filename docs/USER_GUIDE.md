# User guide

How to use the StyleSense console, what every number means, and why it behaves
the way it does.

| | |
|---|---|
| **Console** | https://stylesense-console.onrender.com |
| **Sign in** | `demo@stylesense.ai` / `demo1234` (administrator) |

> **First load is slow.** Both services run on Render's free tier and sleep
> after ~15 minutes idle. The first request takes roughly 50 seconds to wake
> them, and the login screen will sit there until it does. This is the hosting
> tier, not the app. Opening
> [the API health check](https://stylesense-api-vmwr.onrender.com/health) first
> warms it up.

---

## Contents

1. [The idea in one minute](#1-the-idea-in-one-minute)
2. [Signing in, and the two roles](#2-signing-in-and-the-two-roles)
3. [Overview](#3-overview)
4. [Discovery — finding leads](#4-discovery--finding-leads)
5. [Leads — working the list](#5-leads--working-the-list)
6. [The lead page](#6-the-lead-page)
7. [Campaigns](#7-campaigns)
8. [Outreach profile](#8-outreach-profile)
9. [Team](#9-team-administrators-only)
10. [A full walkthrough](#10-a-full-walkthrough)
11. [Things that will surprise you](#11-things-that-will-surprise-you)

---

## 1. The idea in one minute

A salesperson at StyleSense AI sells demand forecasting and inventory tools to
fashion brands. Finding people to call is slow and manual.

This console does the loop:

```
describe who you sell to  →  it finds real people on the web
                          →  scores them 0–100
                          →  writes an email that only says things it can prove
                          →  sends it, watches for opens and replies
                          →  moves the lead up or down the list
```

The part that matters most is **"only says things it can prove."** The system
refuses to put a claim in an email unless that claim traces back to something it
actually read and stored. You can see what it refused, every time.

---

## 2. Signing in, and the two roles

Sign in with the credentials above. There is no public signup — an
administrator creates accounts.

| Role | Sees | Can do |
|---|---|---|
| **Salesperson** | Only their own leads, profiles and campaigns | Everything about their own list |
| **Administrator** | Everyone's | All of the above, plus create and deactivate accounts |

This is enforced in the database query, not by hiding things in the interface.
Asking for another person's lead by its id returns "does not exist" rather than
"not allowed" — telling you it exists would already be telling you something.

Your account lives at the bottom of the left sidebar. Click it for your email
and **Sign out**.

---

## 3. Overview

The landing screen. If you have no leads yet it explains the loop instead of
showing four panels of zeroes.

### The four tiles

| Tile | What it means |
|---|---|
| **Ready to call today** | Leads scoring 75 or above. The number to act on — marked with the accent rule down its edge |
| **Leads** | Everything in your pipeline |
| **Average score** | Across all your leads. Moves as people engage |
| **Reply rate** | Replies ÷ emails sent |

### Outreach funnel

Sent → Delivered → Opened → Replied, with the conversion from the previous
stage beside each.

**Each stage counts distinct leads, not events.** Three opens from one person is
one engaged lead. A funnel that double-counts flatters itself.

### Where the pipeline sits

Leads by score band. Fit sets the starting number; engagement moves it. A
pipeline that is all "Low" means the ICP is too broad or nobody has engaged yet.

### Highest scoring leads

The top six, clickable straight through to the lead page. This is the shortcut
for "who do I call now".

### By salesperson *(administrators only)*

Leads and hot leads per person.

---

## 4. Discovery — finding leads

Two steps: describe who you want, then run it.

### Defining a profile

| Field | What it does |
|---|---|
| **Name** | For you only |
| **Industry** | Used in the search **and** worth 20 points of fit |
| **Region** | Used in the search **and** worth 12 points of fit |
| **Min / max headcount** | Worth 8 points when a company falls inside the band |
| **Target job titles** | Comma separated. Drive the search **and** up to 15 points of fit |
| **Keywords** | Optional extra search terms |

The profile is not just a search query — **it is what the fit score is measured
against.** A lead found under "Fashion / India / Head of Merchandising" is
scored on how well it matches exactly that.

Good starting point:

```
Name       Fashion brands in India
Industry   Fashion
Region     India
Headcount  50 – 5000
Titles     Head of Merchandising, Supply Chain, Demand Planning
Keywords   apparel, retail
```

### Running it

Click **Run discovery** on a saved profile. The dialog shows what will be used
and lets you change two things:

- **How many leads to look for** (1–15). Smaller finishes faster.
- **Edit for this run** — adjust industry, region, headcount, titles or
  keywords.

> Those edits are **saved to the profile**, not applied as a one-off. The same
> profile is what the fit score is measured against, so a lead scored on
> criteria the run did not actually use would be quietly wrong.

A run takes **30–90 seconds**. Leave the dialog open. When it finishes it tells
you how many leads it kept and how many candidates it rejected.

### What it is actually doing

```
1. Five searches built from your profile — no AI involved
2. Fetch the most promising pages and read them
3. The model may run one more search/fetch round if it needs to
4. Extract named people as structured data
5. Validate, twice
6. Store, and score
```

LinkedIn and job boards are filtered out automatically. LinkedIn returns a login
wall rather than a page, so a lead sourced from one could never be verified; job
boards list vacancies rather than the people holding them.

### Run history — click any row

This is the most interesting screen in the app. It opens the agent's transcript:

- **Pages the agent actually read.** A lead may only cite a page from this list.
- **What the agent did** — every search query, every fetch, every refusal.
- **Why each rejected candidate was rejected.**

Common rejection reasons:

| Reason | Meaning |
|---|---|
| `unvisited_source_url` | It cited a page it never opened. Discarded — a plausible citation is still a fabrication |
| `not_a_buying_role` | A researcher, professor or intern. A paper on demand forecasting published by a retailer looks like a perfect match and its authors have nothing to buy |
| `placeholder_name` | "N/A", "John Doe" |
| `duplicate_in_batch` | Same person twice in one run |

If a run finds nothing, the profile is usually too narrow, or the region and
industry produce mostly job adverts.

---

## 5. Leads — working the list

Sorted by score, highest first. The top of this list is where to spend your day.

### The view switcher

| View | Shows |
|---|---|
| **All** | Everything |
| **Hot** | Scoring 75+ |
| **Opened** | Opened the email but not replied — the follow-up list |
| **Replied** | Replied — the ones waiting on you |

### Search and filters

Search covers name, job title, email and company. **Filters** opens the rest:
status, industry, and sort order. The badge on the button shows how many
advanced filters are active.

**Filters live in the URL.** You can bookmark a filtered view, share it, reload
it, and the back button works.

### Reading a row

```
52     Sachin Tandon          TechnoSport          Delivered
warm   Supply Chain Head      Fashion · Asia       No email        4h ago
```

The bar under the score is the same number drawn — colour alone would not be
readable for a colour-blind user. **"No email"** means discovery could not find
an address; the lead is still worth ranking, and you can add one yourself.

Click anywhere on the row to open it.

---

## 6. The lead page

Where the actual work happens.

### Score (right-hand side)

The number, then its two halves:

**Fit** — what this lead *is*. Does not change unless you edit the lead or the
profile.

```
Industry match      +20
Region match        +12
Title exact match   +15
```

**Engagement** — what this lead *did*. Changes as they act.

```
Delivered            +5
Opened              +10
```

Fit caps at 60 and engagement at 40, totalling exactly 100. A flawless-fit lead
who has never engaged tops out at 60, so it can never outrank a merely good lead
who replied. That is the ranking a salesperson actually wants.

**Sending scores nothing.** Delivery is your action, not theirs.

### Why the score changed

Every movement, with its reason:

```
Lead discovered         0 → 47
Email delivered        47 → 52
Email opened           52 → 62
Reply received — interested   62 → 83
```

Nothing is ever incremented in place. The score is recomputed from the whole
event history each time, which is why changing a weight re-ranks everything
correctly instead of drifting.

### Contact

Company facts, and the **source** — the page this lead was found on. Click it;
that is the evidence.

**Edit** changes the email address. You can also clear it: discovery often finds
a decision maker whose address is not public, and that lead is still worth
ranking. Outreach goes to the sandbox inbox either way.

### Outreach

Pick a campaign, then **Generate draft**. Nothing is sent.

The draft arrives with its **grounding report**:

```
14 values checked · 0 blocked
1 sentence(s) dropped
  · ps: optional, no grounded content
Built from: company.name, lead.observed_signal, pain_points.stockouts
```

| Line | Meaning |
|---|---|
| **values checked** | Tokens filled in the template |
| **blocked** | Values rejected for containing a number or name not in the stored evidence |
| **dropped** | Sentences removed because a required value could not be verified |
| **Built from** | The stored fields the copy came from |

Read it, then **Send**. Sending is always an explicit action — nothing goes out
on its own.

> **The email goes to the configured sandbox inbox, never to the lead.** The
> lead's real address stays on the record for you to see; delivery is
> redirected. The panel says so, and the sent message records the address that
> was actually used.

### Replies

Paste a reply and press **Analyse reply**. You get:

- **An intent** — interested, needs info, not now, wrong person, unsubscribe
- **A confidence**
- **A drafted response** — persisted unsent

The score moves immediately, and the lead's status becomes *Replied*.

**Approve** records that you accepted the draft. It does not send it — outbound
replies are out of scope, and an approve button that quietly mailed someone
would be a surprising thing to find.

A reply classified as **unsubscribe** suppresses the address and zeroes the
score. An opt-out counts however it arrives.

### Activity

Every event with its timestamp. This is the raw record everything else is
derived from.

---

## 7. Campaigns

A campaign carries the **sender name** that signs every email in it and the
**unsubscribe link** that each recipient gets. You need one before you can
generate outreach.

The table shows leads, sent, opened and replied — again counted as distinct
leads.

Reply-to is where a reply would land. Delivery still goes to the sandbox inbox.

---

## 8. Outreach profile

What you sell and who it comes from. **Changes take effect on the next generated
email — no redeploy.**

| Field | Where it appears |
|---|---|
| **Product name** | The body and the sign-off |
| **What it does** | Completes "we help apparel and fashion teams…" |
| **Default sender name** | The *Best,* line, unless the campaign overrides it |
| **Default reply-to** | Where replies would go |

### Email skeleton

The fixed wording, sentence by sentence. **It is not editable here, by design** —
only the bracketed values are filled, and only from stored facts. A sentence
whose value cannot be verified is dropped rather than guessed.

### Pain points

Each lead is matched to one of four, from what was observed about their company
*and* from their own job title. The match decides the value-proposition
sentence.

The job title matters: a Head of Supply Chain owns allocation whether or not any
article happens to mention a stockout. Without that second signal most
well-evidenced leads matched nothing and lost the sentence entirely.

---

## 9. Team *(administrators only)*

Create accounts, change roles, deactivate people.

**Deactivating signs someone out immediately** — the account is re-read from the
database on every request rather than trusted from the token, so it does not
wait for the token to expire. Their leads and history stay intact and attributed
to them.

Two things you cannot do, both refused by the API as well as hidden here:
deactivate your own account, and remove your own administrator role. Either
would leave the console with no way back in. The last active administrator
cannot be demoted for the same reason.

---

## 10. A full walkthrough

Roughly five minutes, and it exercises the whole loop.

1. **Sign in.**
2. **Discovery → Define a profile.** Use the example in section 4. Save.
3. **Run discovery.** Set the count to 5. Wait 30–90 seconds.
4. **Open the run in Run history.** Look at the pages it read and what it
   rejected. This is the evidence behind everything that follows.
5. **Leads.** The new leads are ranked. Open the top one.
6. Read the **score breakdown** — which criteria matched, and what each was
   worth.
7. **Campaigns → New campaign** if you do not have one.
8. Back on the lead: **Generate draft.** Read the email, then read the grounding
   report beside it. Note what was dropped and why.
9. **Send.** The lead moves to *Delivered* and the score rises by 5.
10. **Check the inbox** configured as the sandbox address. Open the email —
    that fires the tracking pixel, records an *opened* event, and the score
    rises another 10. *(Gmail blocks images in Spam; mark it "not spam" and open
    it from the inbox.)*
11. Back on the lead: **paste a reply** — try *"Sounds interesting, can we talk
    Tuesday?"* — and press **Analyse reply**.
12. Watch the intent, the drafted response, and the score move again.
13. **Overview.** The funnel and the distribution have changed.

---

## 11. Things that will surprise you

**The first page load takes about 50 seconds.** Free-tier hosting sleeps when
idle.

**Emails land in Spam.** They are sent from Resend's shared sandbox domain,
which has no SPF/DKIM/DMARC of its own. Production would send from a verified
domain. Mark it "not spam" to open it properly.

**The tracking pixel will not fire from the Spam folder.** Gmail blocks images
there entirely. Move the message to the inbox first, and allow images if
prompted.

**Most leads have no email address.** News articles and leadership pages name
people without publishing addresses. The system stores what it finds, refuses to
guess, and strips shared mailboxes like `info@` — those are real addresses but
not a person's, and mailing them is how a sending domain gets blocklisted.

**Discovery sometimes finds nothing.** Rejecting a lead that cited a page it
never read is working correctly, not failing. The run history tells you which it
was.

**The AI may be out of quota.** Gemini's free tier allows 20 requests per day
*per model*. The app falls through a chain of models, and reply classification
falls back to a deterministic classifier rather than breaking. Discovery needs
the model and will report a clear failure.

**Two salespeople see different lists.** That is the point. Sign in as an
administrator to see everything.
