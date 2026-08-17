# Self-hosting Vetd under the GDPR

> Not legal advice — see the [pack README](README.md). This guide maps GDPR
> duties onto the controls Vetd actually ships, so "comply" becomes a list
> of things you can point at.

## 1. You are the controller

When you self-host Vetd, your company decides why and how candidate data is
processed — that makes you the **data controller** (Art. 4(7)). Vetd (the
project) has no role in your deployment: it never sees your data, exactly
like your database or web server don't make their vendors controllers.

Concretely, being the controller means:

- Candidate-facing notices name **your company**. Vetd renders them from
  your settings; the words are yours.
- Data-subject requests (access, deletion, rectification, objection) are
  **yours to answer**, within one month (Art. 12(3)). Vetd gives you the
  buttons; you own the response.
- Your lawful bases, retention choice, and security posture are yours to
  document — the templates in this pack pre-fill the Vetd-shaped parts.
- If you engage others to process the data (hosting provider, email relay,
  Google for interviews), they are **your** processors/recipients and
  belong in your records.

**Not established in the EU but hiring EU candidates?** You are likely in
territorial scope via Art. 3(2) and may need an EU representative
(Art. 27). This pack doesn't cover that appointment — check it before
targeting EU applicants.

## 2. Before your first candidate

Work through this once, before the careers page goes public.

**Identity & notice**

- [ ] Fill **Settings → Privacy** in the admin app: company legal name,
      privacy contact email, retention period, and (optionally) a URL to
      your own privacy policy. Unset fields fall back sensibly — the legal
      name falls back to your display name — but set them deliberately.
- [ ] Open your public privacy notice (linked from the careers-page footer;
      `/c/{your-slug}/privacy`, or `/privacy` in single-company mode) and
      read it as a candidate would. It renders your settings values,
      including the retention promise. If you set your own policy URL
      instead, make sure your policy actually covers everything the built-in
      notice does — quiz scoring, integrity telemetry, the Google Calendar
      leg, retention, and candidate rights.

**Retention**

- [ ] Choose the retention window consciously (**Settings → Privacy**,
      1–24 months, default 6). It is the number your notice promises and
      the purge enforces. Member-state expectations differ — pick for the
      strictest regime you hire in:
      - France (CNIL): maximum 2 years after last contact.
      - Germany: ~6 months is common practice (AGG §15 discrimination-claim
        window plus margin).
      - Poland (UODO): stricter — guidance leans toward deleting when the
        recruitment ends; blanket keep-for-claims justifications are viewed
        skeptically. Shorter is safer.
      - UK (ICO): 6–12 months typical.

**Deployment hardening**

- [ ] Work through the **production hardening checklist** at the bottom of
      `.env.example` — it exists because candidate PII lives in this stack.
      In short: HTTPS everywhere with `VETD_COOKIE_SECURE=true` (quiz,
      status, and interview links are bearer tokens; plain HTTP exposes
      them), TLS SMTP relay, change the MinIO defaults and don't expose its
      ports, keep the backend behind your reverse proxy, Redis AUTH outside
      the bundled compose network, and consider a separate
      `VETD_ENCRYPTION_KEY` for stored Google credentials.
- [ ] Enable **encryption at rest on your storage layer**. The app sets no
      S3 server-side-encryption headers by design — use MinIO KMS/SSE, disk
      encryption, or a provider that encrypts by default, for both the CV
      bucket and the Postgres volume.
- [ ] Host in the EU/EEA if you can. The only built-in third-country flow
      is Google Calendar (§6); don't add more by picking US hosting for the
      database and CV bucket.
- [ ] Decide your **backup policy before you hold candidate data**:
      encrypted backups, rotation window at or below your retention
      period, and a rule that you never restore erased candidates —
      completing the rotation is what completes an erasure. (Vetd doesn't
      ship backups; whatever you add must honor this.)
- [ ] Your reverse proxy and host keep their own logs. Vetd's bundled
      compose scrubs capability tokens from access logs and rotates them —
      apply the same discipline (don't log the full URLs of quiz, status,
      interview, or invite links — the token is the credential; keep
      retention bounded) at any layer you add in front.

## 3. Operating duties

**Access & portability requests (Art. 15/20).** Open the applicant, use the
**⋯ → Export data (JSON)** action, and hand the candidate the bundle plus
the CV file. The bundle contains everything Vetd stores about them:
identity, all their applications and messages, quiz attempts with scores,
per-question answers (with correctness, never the answer key), integrity
events and flags (with your staff's identifiers scrubbed), interview
records, note bodies, and a CV download link. Deliver it within one month
of the request. Exports are deliberately admin-mediated — there is no
candidate-side bulk download behind the status link, so a leaked link can
never become a PII dump.

**Recruiter notes are disclosable.** Notes about a candidate are that
candidate's personal data and are included in the export (bodies, without
author names). The notes UI reminds your team; make it culture: factual,
professional, nothing you wouldn't show the person.

**Rectification (Art. 16).** A candidate re-applying updates their name and
links. Their email — the delivery channel for every quiz/status link — is
fixed via **⋯ → Edit candidate email…** on the applicant.

**Erasure (Art. 17).** **⋯ → Erase candidate…** deletes the person across
*all* their applications: CV files first (the erasure aborts rather than
leave an orphaned CV), then best-effort deletion of any Google Calendar
events (failures are counted and shown — clean those up in the calendar by
hand), then the database records, leaving one anonymized count-only receipt
in the activity log. Honest limits — copies Vetd cannot reach:

- Emails already sent (in the candidate's and your mailboxes).
- Google Calendar events where deletion failed (reported to you).
- Free text your team typed into **your own tasks** (manual tasks aren't
  linked to candidates — check them after an erasure). The privacy-request
  tasks Vetd itself creates are handled for you: erasing a candidate
  deletes their request tasks, and completed request tasks are swept by
  the nightly job 90 days after they're marked done.
- Your backups (covered by your rotation rule, §2) and any logs kept by
  layers you run in front of Vetd.

You may *defer* erasure while your retention window (claims defense,
Art. 17(3)(e)) still runs — that's what the automatic purge is for. "Erase
now" is for when someone asks and you have no live reason to keep the data.

**Candidate-initiated requests.** The status page every candidate gets
carries **"Request a copy of my data"** and **"Ask for my data to be
deleted"**. Each creates a task on your dashboard (due in 14 days, deduped
per application) with the candidate's name and email in the note — the task
*is* the request; there is no auto-deletion. Answer like any other Art. 15/
17 request, within the month. The task doesn't outlive the person it names:
erasing the candidate removes it, and done request tasks are swept 90 days
after completion (the PII-free activity entry is the lasting record that a
request was received).

**Withdrawals.** A candidate withdrawing moves the application to
`withdrawn` — a pipeline state, not an erasure. The status page tells them
data is kept for your retention window unless they request deletion. The
purge clock starts at the withdrawal.

**Offboarding recruiters.** You are also the controller for your own
staff's accounts. **Team → ⋯ → Remove & anonymize…** tombstones the user:
email replaced with a random placeholder, password and Google sign-in
severed, saved interview availability wiped, calendar connection revoked
and deleted, account deactivated and sessions cut. It refuses while the
user still has upcoming interviews (reassign first) or is the last admin.

**Breach.** Read the [breach runbook](breach-runbook.md) once now, not
during the incident.

## 4. What runs automatically

- **Nightly retention purge** (03:17 UTC): every rejected or withdrawn
  application older than your window is erased with the same machinery as
  the manual button; candidates are removed entirely once their last
  application goes. The clock starts at the *decision* (rejection/
  withdrawal), not at apply. `hired` is excluded — an employee's record
  transitions to your HR retention rules, out of ATS scope. Months are
  counted as 31 days, so deletion never happens *earlier* than the notice
  promised. A storage failure skips just that application and retries the
  next night. There is deliberately **no off switch** (Art. 25 privacy by
  default) — if you need longer, raise the months and let the notice say
  so.
- Abandoned CV uploads (file picked, form never submitted) are swept after
  24 hours; expired team invites are swept nightly.
- **Status links expire after 30 days**; quiz links after their own
  deadline. Expired links can be re-issued, which invalidates the old one.
- Access logs in the bundled compose are token-scrubbed (capability tokens
  become `[token]`) and size-capped (json-file rotation), and application
  logs reference internal IDs, not candidate emails.

## 5. Legal bases (what to put in your records)

The pre-filled mapping — details and the full table live in the
[records template](records-of-processing-template.md):

| Activity | Basis |
|---|---|
| Receiving and reviewing applications | Art. 6(1)(b) — steps prior to a contract, at the candidate's request |
| Screening quiz | Art. 6(1)(b) — part of the application process the candidate enters |
| Integrity telemetry | Art. 6(1)(f) — legitimate interest (assessment fairness); see the [LIA](telemetry-legitimate-interests.md) |
| Notes, pipeline, activity log | Art. 6(1)(f) — managing recruitment |
| Post-decision retention | Art. 6(1)(f) — defense against legal claims, time-boxed by your window |
| Transactional emails | Art. 6(1)(b)/(f) — not marketing; no ePrivacy opt-in needed |
| Rate limiting (IPs) | Art. 6(1)(f) — abuse prevention |

Note what is *absent*: consent. The apply form deliberately has **no "I
consent to processing" checkbox** — the basis is Art. 6(1)(b), and a forced
consent checkbox in a power-imbalanced situation would be invalid (EDPB
Guidelines 05/2020) and misleading about the real basis. The form shows a
privacy notice instead. Don't "fix" this by adding a checkbox.

If candidates volunteer sensitive data in their message or CV, you didn't
ask for it (the form nudges them not to include it) — don't copy it into
notes, and weigh it for nothing.

## 6. The Google Calendar leg

Only relevant if your recruiters connect Google Calendar for interview
scheduling. When they do:

- Booking an interview creates an event on the **recruiter's own Google
  calendar** — your Google tenancy, under the recruiter's OAuth grant —
  with the candidate's full name in the title, their email as an attendee,
  and a Meet link. Google emails the invitation to the candidate directly.
- Availability is computed by reading the connected calendar's free/busy
  status, and Vetd stores the recruiter's refresh token encrypted. The
  candidate data Vetd writes to Google is limited to the interview events
  it creates. (Recruiters also see their own day's calendar events on
  their own dashboard — their data, shown only to them.)
- For your records: this is a transfer to Google LLC (US). Mechanisms:
  Google's data-processing terms incorporate SCCs, and Google is DPF-
  certified while that framework stands. The candidate-facing booking page
  and privacy notice already disclose the Google involvement.
- On erasure, Vetd deletes the events it created **best-effort** and
  reports failures; sent invitation emails are out of reach (§3).

Don't connect calendars if this transfer doesn't fit your posture —
interviews then simply happen outside Vetd.

## 7. Do you need a DPO? (Art. 37)

Answer three questions and write the answer down (there's a row for it in
the records template):

1. Are you a public authority?
2. Do your *core activities* consist of large-scale, regular and systematic
   monitoring of data subjects?
3. Do your core activities consist of large-scale processing of
   special-category or criminal-conviction data?

For a company using Vetd to hire for its own roles, the honest answers are
usually no/no/no — hiring is a support activity, not your core business,
and Vetd's telemetry is neither large-scale nor the kind of systematic
monitoring the trigger means. Then a DPO is not mandatory; you may still
appoint one voluntarily (the full Art. 37–39 duties then apply). If you're
a recruitment business processing candidates *at scale as your core
activity*, get advice — question 2 may genuinely bite.

## 8. What Vetd never does (cite these in your DPIA)

Product guarantees you can rely on, as shipped:

- **No cookies, no analytics, no fingerprinting** on any candidate-facing
  page (careers, apply, quiz, status, booking) — nothing to consent-banner.
  The embeddable jobs widget is equally clean.
- **No IP addresses or user agents in quiz telemetry** — the integrity
  record is three event types (blur, paste, resize), tied to the open
  question. No keystrokes, no clipboard contents, no screen capture.
- **No automated decisions**: no auto-reject, no auto-advance, no
  score-based filtering. Scores and flags are shown to humans who see the
  whole application. (Details: [AI Act statement](ai-act-statement.md).)
- **Answer keys never reach candidates**, timing and scoring are
  server-side, and every tenant's data is isolated by query-level tenancy
  checks.

If your fork changes any of the above, the pack's analyses need redoing —
see [the pack README](README.md).
