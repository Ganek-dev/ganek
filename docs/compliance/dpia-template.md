# Data protection impact assessment — recruitment screening with Ganek

> Pre-filled template. Everything describing Ganek's behavior is filled in
> and accurate for the version you deployed it with; everything in
> `{curly braces}` is yours to complete. Not legal advice — see the
> [pack README](README.md).

**Controller:** `{legal name, address, contact}`
**DPO / responsible person:** `{name or "no DPO — see records, Art. 37 assessment"}`
**Assessment date:** `{date}` · **Author:** `{name}` · **Version:** `{n}`

## 1. Why a DPIA

Art. 35(1) requires a DPIA where processing is "likely to result in a high
risk". The WP248 screening criteria include *evaluation or scoring* and
*data concerning vulnerable data subjects* — candidate assessment meets the
first, and job applicants are the textbook power-imbalanced subjects for
the second. Two criteria met means a DPIA is the safe default, and several
national mandatory lists (e.g. Poland's UODO, the German DSK) explicitly
name recruitment assessment/scoring systems. Doing the assessment is cheap
with this template; skipping it is hard to defend.

## 2. Description of the processing

**Purpose.** Receiving and reviewing job applications for
`{company}`'s own open roles, including an optional timed multiple-choice
skill quiz per job, and scheduling interviews.

**Data subjects.** Job applicants (external), plus `{company}` recruiting
staff (accounts, calendar connections).

**Categories of data (candidates).**

| Category | Fields | Source |
|---|---|---|
| Identity & contact | Name, email | Apply form |
| Application content | CV file, links (portfolio/profiles), free-text message | Apply form |
| Assessment | Per-question answers with correctness, total and per-tag scores, time used | Quiz engine (server-side scoring) |
| Integrity telemetry | Events of exactly three types — window focus lost (with duration), paste occurred, window resized — each tied to the question that was open; derived review flags | Quiz page during an attempt |
| Scheduling | Chosen interview slot, timezone; Google Calendar event with name + email (only if used) | Booking page |
| Pipeline metadata | Stage history, decision timestamps, recruiter notes about the candidate, activity entries | Recruiting staff |

**Explicitly not collected:** IP addresses and user agents are not stored
in telemetry or application records (IPs appear only in short-lived
rate-limit counters and rotated access logs); no keystrokes, no clipboard
*contents* (paste is recorded as an event, never the pasted text), no
webcam/screen capture; no cookies or third-party trackers on any
candidate page; special-category data is not sought (the form asks
candidates to omit sensitive personal details).

**Flows.** Candidate applies (CV to object storage via presigned upload) →
optional quiz (questions served one at a time; timing and scoring
server-side; answer keys never sent to the client) → human review →
optional interview booking (event on the recruiter's Google calendar; Google
emails the invite) → decision, communicated by opt-in email.

**Storage & TTLs.** Postgres (application data) and S3-compatible object
storage (CVs), both under `{company}`'s control at `{hosting provider /
location}`; candidate status links expire after 30 days; quiz links expire
at their deadline; rejected/withdrawn applications are purged
`{retention_months}` months after the decision (nightly job); access logs
are token-scrubbed and rotation-capped.

**Recipients.** Recruiting staff (role-restricted); `{hosting provider}`;
`{email relay}`; Google LLC — only when an interview is scheduled and only
the event data (name, email, time, Meet link).

**Transfers.** None built-in except the Google Calendar leg (US) — SCCs
via Google's data-processing terms, DPF certification while that framework
stands. `{Add any transfer created by your hosting/email choices.}`

## 3. Necessity and proportionality

- **Lawful bases.** Application handling and the quiz run on Art. 6(1)(b)
  (pre-contractual steps at the candidate's request — the candidate
  initiates by applying); integrity telemetry, notes/pipeline, and
  time-boxed post-decision retention run on Art. 6(1)(f); the balancing
  for telemetry is documented in the
  [legitimate interests assessment](telemetry-legitimate-interests.md).
  No consent is collected because none of this validly runs on consent in
  a power-imbalanced setting (EDPB 05/2020).
- **Transparency.** Layered notices: privacy-notice block on the apply form
  (above Submit), full notice page per company, complete monitoring
  disclosure on the quiz start gate (desktop and mobile) *before* the
  attempt starts, Google disclosure on the booking page, controller
  identity + notice link in every candidate email.
- **Minimization.** Three telemetry event types and no more; no IP/UA in
  candidate records; quiz answers stored with correctness but answer keys
  never exposed; Google receives only event-level data; recruiter accounts
  hold no more than login + calendar linkage.
- **Retention.** Single configured window (`{retention_months}` months,
  default 6), automatically enforced, decision-anchored, no off switch;
  hired candidates transition to employee-record retention
  (`{your HR policy}`).
- **Data-subject rights.** Admin DSAR export (JSON bundle incl. scores,
  answers, telemetry, note bodies), candidate request buttons on the
  status page (copy of data / deletion) creating 14-day tasks, admin
  erasure across storage systems, email rectification, withdrawal at any
  time from the status page.
- **No automated decision-making.** Scores and flags never trigger
  rejection, advancement, or filtering; reviewers always see the full
  application. This keeps the processing outside Art. 22 (no decision
  based *solely* on automated processing) — and it is a product
  invariant, not a configuration.

## 4. Risks and mitigations

Assess likelihood and severity (`low / medium / high`) for your deployment;
the mitigation column states what Ganek already does — add your own.

| # | Risk to candidates | Mitigations in place | L | S | Residual |
|---|---|---|---|---|---|
| 1 | Unfair inference from integrity telemetry (a flagged event read as cheating) | Flags are informational only, reviewed by humans seeing the full context; complete prior disclosure at the gate; no auto-consequences; [LIA](telemetry-legitimate-interests.md) | `{}` | `{}` | `{}` |
| 2 | Assessment reduced to the score (de-facto automated rejection) | No auto-reject/filter/sort-cutoff in product; full application always displayed; pass-lines are visualization only; staff training `{yours}` | `{}` | `{}` | `{}` |
| 3 | Leaked candidate link (quiz/status/interview token) | Links are single-purpose signed tokens; status links expire in 30 days; no bulk PII behind any candidate link (DSAR is admin-mediated); tokens scrubbed from access logs; HTTPS `{confirm}` | `{}` | `{}` | `{}` |
| 4 | Breach of hiring data (DB, CV bucket, backups) | Tenancy isolation, RBAC, argon2 password hashing, encrypted Google tokens, rate limiting, hardening checklist applied `{confirm}`, storage-layer encryption `{confirm}`, [breach runbook](breach-runbook.md) | `{}` | `{}` | `{}` |
| 5 | Sensitive data volunteered in CV/message being used | Form guidance asks candidates to omit it; not copied into notes (policy `{confirm}`); weighed for nothing; erased with the application | `{}` | `{}` | `{}` |
| 6 | US transfer via Google Calendar | Only on interview scheduling; SCCs + DPF; event-level data only; best-effort deletion on erasure; disclosed at booking; alternative: don't connect calendars | `{}` | `{}` | `{}` |
| 7 | Data kept longer than justified | Automatic decision-anchored purge, notice states the window, no silent off switch; backups rotation ≤ window `{confirm}` | `{}` | `{}` | `{}` |
| 8 | Candidate unable to exercise rights | Status page carries request routes with 14-day task deadline; export/erase/rectify are one-click admin actions; one-month response tracked `{your process}` | `{}` | `{}` | `{}` |

`{Add deployment-specific risks: your hosting jurisdiction, additional
integrations, staff access from outside the EU, …}`

## 5. Consultation

Views of data subjects or their representatives sought: `{yes/no — for
routine own-hiring at this scale, controllers commonly document "not
sought; low residual risk, standard recruitment context"; do consult for
large-scale or unusual deployments}`. DPO advice: `{if applicable}`.

## 6. Outcome and sign-off

Conclusion: `{e.g. "Residual risks low; processing may proceed. No prior
consultation of the supervisory authority (Art. 36) required."}`

Signed: `{name, role, date}`

**Review triggers** — redo the affected parts before shipping any of:
adding analytics/cookies to candidate pages; any new telemetry event type
or non-informational use of flags; ML-based parsing, scoring, ranking, or
adaptive testing; automated stage changes; a talent-pool feature (adds a
consent-based activity); new processors or transfers; and in any case
review every `{12–24}` months.
