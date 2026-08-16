# Personal data breach runbook (Art. 33/34)

> Read once *before* an incident. Not legal advice — see the
> [pack README](README.md). The 72-hour clock starts when you become
> *aware* of a breach — this runbook exists so those hours go into
> response, not research.

A "personal data breach" is any security incident leading to accidental or
unlawful destruction, loss, alteration, unauthorised disclosure of, or
access to personal data — not just "hacks". A stolen laptop with an
admin session, a CV bucket left public, a database backup emailed to the
wrong address, ransomware making data unavailable: all breaches.

## 1. Detect and contain

**Where candidate data lives in a Vetd deployment** — check what's touched:

| Store | Contents |
|---|---|
| Postgres | Everything: identities, applications, scores, telemetry, notes |
| S3/MinIO `cvs/` bucket | CV files |
| Container/host/proxy logs | Token-scrubbed access lines with client IPs (app-side); whatever *your* proxy logs |
| Recruiters' Google calendars | Interview events: candidate name + email (only if calendar connected) |
| Email relay / mailboxes | Sent candidate mails incl. quiz/status links |
| Backups | Copies of the above (`{your inventory}`) |

**Containment levers, in escalation order:**

- **Rotate `VETD_SECRET_KEY`** — the nuclear lever: instantly invalidates
  *every* outstanding candidate link (quiz/status/interview/invite) and all
  admin sessions. Recruiters log in again; candidates with live processes
  need re-sent links (quiz links can be re-issued from the applicant view).
  Unless you set a separate `VETD_ENCRYPTION_KEY`, this also severs stored
  Google Calendar connections (recruiters reconnect).
- **Rotate `VETD_ENCRYPTION_KEY`** (if set) — invalidates stored Google
  refresh tokens only; recruiters reconnect their calendars.
- **Revoke Google access** at the account level (Google Account →
  Security → third-party access) for affected recruiters, and/or delete
  the OAuth client's credentials in Google Cloud Console.
- **Rotate infrastructure credentials**: database password, S3/MinIO keys
  (both the app pair and the root pair), SMTP credentials, Redis password.
- **Deactivate compromised admin accounts** (Team page — deactivation cuts
  their sessions) or use Remove & anonymize for a departed insider.
- Take the stack offline (`docker compose down`) if exposure is ongoing —
  candidate-facing downtime beats continued leakage.

Preserve evidence while containing: copy logs *out* before rotation-capped
files roll over; note timestamps of everything you do.

## 2. Assess the risk (same day)

Establish, and write into the register as you go:

- **What happened, when, and when you became aware** (the Art. 33 clock).
- **Categories and approximate numbers** of data subjects and records —
  the applicant list and per-job counts give you numbers fast.
- **Sensitivity in context:** hiring data is reputationally sensitive —
  who applied where (their current employer must not learn), quiz scores
  and integrity flags (easily misread out of context), CVs (rich identity
  data, sometimes volunteered sensitive details), recruiter notes.
- **Likelihood and severity of harm** to the people affected:
  identity-misuse potential, reputational/employment harm, distress.
  Confidentiality of one status link ≪ the candidates table.

Three notification tiers follow from the assessment:

1. **No risk likely** (e.g. encrypted disk lost with keys safe, or data
   unavailable briefly with no access): document in the register, no
   notifications.
2. **Risk likely:** notify your supervisory authority within **72 hours**
   of awareness (Art. 33). Late notification must explain the delay.
3. **High risk:** additionally tell the affected candidates **without
   undue delay** (Art. 34) — plain language, direct email.

If you cannot decide within 72 hours, notify the authority in phases —
initial notification with what you know, supplemented later (Art. 33(4)).

## 3. Notify

**To the supervisory authority** (`{your authority + their breach portal
URL}`), per Art. 33(3):

- Nature of the breach; categories and approximate numbers of subjects and
  records.
- Name and contact of your DPO or contact point.
- Likely consequences.
- Measures taken or proposed (containment from §1, mitigation, and what
  affected people should do).

**To candidates (high-risk cases), Art. 34** — plain language, at minimum
the last three bullets above. Template to adapt:

> We are writing to inform you about a security incident at `{company}`
> affecting data from your job application for `{role}`. On `{date}` we
> discovered that `{what happened, plainly}`. The information involved was
> `{categories}`. We have `{measures taken}`. For you this may mean
> `{likely consequences}`; we recommend `{concrete advice, e.g. "be alert
> to emails claiming to come from our hiring team — we will not send you
> further links until this is resolved"}`. Questions: `{privacy contact
> email}`.

**If you run Vetd for another company** (agency/service setup): you are a
processor for them — notify *that controller* without undue delay
(Art. 33(2)); the notification duties above are theirs.

## 4. Record — always

Every breach goes in the register, including tier-1 non-notified ones with
the reasoning — Art. 33(5) makes the register itself a compliance duty,
and "we assessed and decided no risk" is only defensible in writing.

Afterwards: post-mortem → fix the cause (hardening checklist gap? backup
handling? access process?) → update the [DPIA](dpia-template.md) risk table
if the incident revealed a risk it missed.

## Breach register (template)

| Date detected | Nature (what/how) | Data & subjects (categories, ~counts) | Likely consequences | Measures taken | DPA notified (date / why not) | Subjects notified (date / why not) |
|---|---|---|---|---|---|---|
| `{}` | `{}` | `{}` | `{}` | `{}` | `{}` | `{}` |
