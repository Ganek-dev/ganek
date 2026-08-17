# Records of processing activities (Art. 30) — Vetd recruitment

> Pre-filled template. `{Curly braces}` are yours. Not legal advice — see
> the [pack README](README.md).

Keep this record even if you have fewer than 250 employees: the Art. 30(5)
derogation excludes processing that is more than occasional, and running an
open hiring pipeline is exactly that. This is the document a supervisory
authority asks for first.

**Controller:** `{legal name}`, `{address}`, `{contact email/phone}`
**Representative (Art. 27, non-EU controllers only):** `{name or n/a}`
**DPO:** `{name, or "not designated — assessed under Art. 37, see below"}`
**DPO assessment (keep current):** `{e.g. "Not required: not a public
authority; recruitment for our own roles is a support activity, not our
core activity; no large-scale monitoring or special-category processing.
Assessed {date}."}`

**Shared technical and organisational measures (Art. 32), referenced by
every activity below:** TLS everywhere (`{confirm}`); tenant isolation
enforced at query level; role-based admin access; argon2 password hashing;
signed, purpose-bound, expiring candidate links (status 30 days); Google
refresh tokens stored encrypted; per-IP rate limiting; access logs
token-scrubbed and rotation-capped; application logs carry internal IDs,
not emails; encryption at rest on database and CV storage (`{your
mechanism}`); encrypted backups with rotation ≤ retention window and no
restore of erased subjects (`{confirm}`); hardening checklist from
`.env.example` applied (`{date}`).

Retention below uses **W** = your configured window (Settings → Privacy,
default 6 months), enforced by the nightly purge from the decision date.

---

## Activity 1 — Application intake and review

- **Purpose:** receiving and assessing applications for our own open roles.
- **Legal basis:** Art. 6(1)(b) (steps prior to a contract, at the
  candidate's request).
- **Data subjects:** job applicants.
- **Data:** name, email, CV file, links, free-text message, stage history.
- **Recipients:** recruiting staff; `{hosting provider}` (infrastructure);
  `{email relay}` (transactional email).
- **Transfers:** none (see Activity 6 for the only built-in transfer).
  `{Adjust if your hosting/email providers are outside the EU/EEA.}`
- **Retention:** W months after rejection/withdrawal; hired → employee
  records per `{HR policy}`.

## Activity 2 — Skill screening quiz

- **Purpose:** job-related knowledge screening as part of the application.
- **Legal basis:** Art. 6(1)(b). Candidates who skip the quiz remain
  reviewable — stated at the start gate.
- **Data:** served questions, per-question answers with correctness,
  total and per-tag scores, server-measured timing.
- **Recipients:** recruiting staff; `{hosting provider}`.
- **Transfers:** none.
- **Retention:** with the application (W).

## Activity 3 — Quiz integrity telemetry

- **Purpose:** assessment fairness (deterring/flagging assistance during
  the timed quiz). Balancing documented in the
  [legitimate interests assessment](telemetry-legitimate-interests.md).
- **Legal basis:** Art. 6(1)(f).
- **Data:** events of three types — focus lost (with duration), paste
  occurred, window resized — tied to the open question; derived flags.
  No IP, no user agent, no keystrokes, no clipboard contents.
- **Recipients:** recruiting staff (informational flags only).
- **Transfers:** none.
- **Retention:** with the attempt (W).

## Activity 4 — Pipeline management, notes, activity log

- **Purpose:** organising the hiring process; internal accountability.
- **Legal basis:** Art. 6(1)(f) (managing recruitment).
- **Data:** stage changes with decision timestamps, recruiter notes about
  candidates (disclosable to the candidate on request), activity entries.
- **Recipients:** recruiting staff.
- **Transfers:** none.
- **Retention:** with the application (W); erasure receipts and purge
  receipts are anonymized counts and persist.

## Activity 5 — Candidate communications

- **Purpose:** transactional email — application confirmation, quiz
  invitation and reminder (including re-issued links), decision updates
  (opt-in per send), interview invitation, cancellation, and reminder.
- **Legal basis:** Art. 6(1)(b)/(f). No marketing, no newsletter — no
  ePrivacy opt-in involved.
- **Data:** name, email, application/interview context; every mail carries
  controller identity and the privacy-notice link.
- **Recipients:** `{email relay}`.
- **Transfers:** `{per your relay}`.
- **Retention:** sent mail per `{your mailbox policy}`; Vetd logs email
  events by internal reference only.

## Activity 6 — Interview scheduling via Google Calendar

*(Delete this activity if your recruiters never connect Google Calendar.)*

- **Purpose:** offering interview slots from recruiters' real availability;
  calendar invitations with a Meet link.
- **Legal basis:** Art. 6(1)(b) (scheduling a step the candidate requested).
- **Data:** candidate name (event title), email (attendee), interview
  time; recruiter free/busy status is read to compute slots.
- **Recipients:** Google LLC (recruiter's connected calendar; Google sends
  the invitation email to the candidate directly).
- **Transfers:** USA — Google's data-processing terms (SCCs); Google is
  DPF-certified while that framework stands.
- **Retention:** Vetd deletes its events best-effort on erasure/purge;
  calendar copies per `{your Google Workspace retention}`.

## Activity 7 — Post-decision retention for claims defense

- **Purpose:** ability to respond to discrimination/selection-process
  claims within statutory windows.
- **Legal basis:** Art. 6(1)(f).
- **Data:** the closed application record as-is.
- **Recipients:** recruiting staff; `{legal advisers on need}`.
- **Transfers:** none.
- **Retention:** exactly W months from the decision, then automatic purge.
  W chosen with member-state context in mind (`{note your reasoning — see
  the guide §2}`).

## Activity 8 — Abuse prevention on public endpoints

- **Purpose:** rate limiting and platform security on apply/quiz/status
  endpoints.
- **Legal basis:** Art. 6(1)(f).
- **Data:** client IP addresses in short-lived counters (≈60-second
  windows); staff login email addresses in failed-login lockout counters
  (`lockout:{email}` keys, ~15-minute window); rotation-capped,
  token-scrubbed access logs.
- **Recipients:** operations staff.
- **Transfers:** none.
- **Retention:** rate-limit counters expire in ~1 minute, lockout
  counters in ~15 minutes; logs bounded by rotation
  (`{state your proxy/host log retention too}`).

## Activity 9 — Recruiter user accounts

- **Purpose:** authentication and authorisation of our own staff in the
  hiring tool.
- **Legal basis:** Art. 6(1)(b) (employment relationship) / 6(1)(f).
- **Data subjects:** our recruiting staff.
- **Data:** email, password hash or Google sign-in linkage, role, last
  login, saved interview availability, encrypted Google Calendar refresh
  token (if connected).
- **Recipients:** `{hosting provider}`; Google LLC (sign-in / calendar, if
  used).
- **Transfers:** as Activity 6 where Google is used.
- **Retention:** for the employment; on offboarding the account is
  anonymized in place (email tombstoned, credentials severed, calendar
  connection revoked and deleted).

---

`{Add activities your deployment introduces — additional integrations,
analytics on the admin side, imports/exports to other HR systems, …}`

**Record maintained by:** `{name}` · **Last reviewed:** `{date}`
