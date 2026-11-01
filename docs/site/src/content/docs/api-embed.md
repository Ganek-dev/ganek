---
title: API and embed widget
description: The public jobs feed, the embed widget for your own website, and where the rest of the API is documented.
sidebar: { order: 2 }
---

Careers pages on Ganek are server-rendered with Google Jobs structured data, so they are the page search engines should index. The public API and the widget exist for your own marketing site and for integrations.

## Public jobs feed

No authentication, CORS open, cached for 60 seconds:

```
GET {origin}/api/v1/public/companies/{slug}/jobs-feed
```

`slug` is your careers slug (Settings, Branding). In `single` mode the shorter `GET /api/v1/public/company/jobs-feed` returns the same thing.

```json
{
  "company": "Your Company",
  "brand_primary": "#7E14FF",
  "jobs": [
    {
      "title": "Senior Frontend Engineer",
      "slug": "senior-frontend-engineer",
      "location": "Remote, Europe",
      "remote_policy": "remote",
      "employment_type": "full_time",
      "tags": ["react", "typescript", "senior"],
      "apply_url": "https://jobs.example.com/c/your-company/jobs/senior-frontend-engineer",
      "posted_at": "2026-07-10T09:00:00Z"
    }
  ]
}
```

`apply_url` points at the Ganek careers page for the role, which is where the application form and the quiz live. Only published jobs appear.

## Embed widget

One script tag renders the open roles on any page, styled from your brand colour, with no cookies and no tracking:

```html
<script src="https://YOUR-GANEK/embed/jobs.js" data-workspace="your-company"></script>
```

Attributes:

| Attribute | Values | Default |
|---|---|---|
| `data-workspace` | your careers slug | required |
| `data-theme` | `auto`, `light`, `dark` | `auto` |
| `data-tags` | `false` hides the tag chips | shown |

The admin Developers page shows the snippet with your slug filled in, a live preview, and a sample of the feed.

## Other public endpoints

Everything a candidate's browser calls is under `/api/v1/public/` and rate-limited per IP (see [Configuration](/configuration/#rate-limits-and-quotas)):

| Endpoint | Purpose |
|---|---|
| `GET /companies/{slug}` and `/companies/{slug}/jobs/{job_slug}` | Careers page and job posting data (the SSR pages use these). |
| `GET /companies/{slug}/privacy` | The rendered privacy notice. |
| `GET /companies/{slug}/logo/{digest}` | The company logo with an immutable cache header. |
| `POST .../apply/upload-url` then `POST .../apply` | CV upload via a presigned ticket, then the application. Size and type restricted. |
| `/quiz/{token}/...` | The quiz flow: one question at a time, timing and scoring server-side. The correct answer never leaves the server. |
| `/applications/{token}/...` | The candidate status page: withdraw, request a data copy, request deletion. |
| `/interviews/{token}/...` | Interview booking and rescheduling. |

Tokens in these paths are capability links sent by email. Treat them as secrets.

## Admin API

The admin UI talks to the same backend under `/api/v1/` with a session cookie and the tenancy of the signed-in user. The interactive OpenAPI reference is served by your own instance at `/api/docs` (schema at `/api/openapi.json`). ### API keys

Admins create keys under Settings, Developers. The secret (`gk_...`) is shown once; the list keeps only a prefix. Send it as a bearer token:

```
curl -H "Authorization: Bearer gk_..." https://your-instance/api/v1/applications
```

Scope `read` covers `GET /api/v1/applications`, `GET /api/v1/applications/{id}`, the export above, `GET /api/v1/applications/{id}/cv` (a 302 to a download link that works for ten minutes; fetches land in the applicant's read-access trail under the key's name, and repeats by the same key inside ten minutes count once) and `GET /api/v1/applications/{id}/cv-url` (the same link as `{"download_url": "..."}` for clients that cannot follow a redirect, or that would forward the `Authorization` header to the storage host). Scope `write` adds `PATCH /api/v1/applications/{id}/stage`; stage changes made with a key show in the activity log without a person as actor, and a `GET /api/v1/applications/{id}` with a key lands in that applicant's read-access trail under the key's name. Keys never reach the key-management endpoints themselves, and revoking one cuts it off immediately. Payloads are the same as the admin UI sees: quiz results stay at the summary level, never answers or keys.

### Candidate emails: send later

A rejection email can be held back instead of going out at once, so a rejection does not land minutes after the interview. Pass `send_after` (ISO 8601 with an offset, for example `2026-11-03T09:00:00+01:00`, between one minute and 14 days ahead) together with `stage=rejected` and `notify_candidate` on `PATCH /api/v1/applications/{id}/stage`, or with `notify_candidates` on `POST /api/v1/applications/bulk-reject` and on `POST /api/v1/applications/bulk-stage` with `stage=rejected`. Without `send_after` the mail goes out as before.

The held mail sits as `scheduled` in `GET /api/v1/applications/{id}/emails`, with its `send_after`. `POST /api/v1/applications/{id}/emails/{email_id}/cancel` (session only, not API keys) marks it `cancelled`; once it is no longer scheduled the route answers 409. Moving the candidate out of rejected cancels it too. Until the mail goes out the candidate's status page keeps showing the previous stage, and if the candidate withdraws in that window the mail is cancelled. The stage itself changes immediately for the team; only the mail waits.

A rejected row can be mailed again by sending `stage=rejected` plus `notify_candidate` on the same route, unless a rejection mail is already scheduled for it (409). Reason and note cannot change with that resend. The data copy lists the outbox rows for the applicant with their status, so scheduled and cancelled mails show there. The public demo shows nothing here because it sends no mail.

### Screening questions

A job can ask a few plain questions on the apply form, below the CV: yes/no, single choice, short text, or an acknowledgment the candidate has to tick. Yes/no and single choice questions may carry a preferred answer. The recruiter sees every answer on the applicant with a mark where it differs from the preferred one, the list shows an "N mismatches" chip and offers a Screening filter. Nothing else happens: no answer ever moves a stage, sends an email or touches the quiz score. Admins keep a default set under Settings, Hiring; every new job starts with a copy of it and edits it freely.

```json
"screening_questions": [
  { "id": "sq_7f3a9c2e", "type": "yes_no", "prompt": "Can you work in Germany without sponsorship?", "options": null, "preferred": "yes", "required": true },
  { "id": "sq_1b2c3d4e", "type": "single_choice", "prompt": "Days on site per week?", "options": ["0", "1-2", "3+"], "preferred": "1-2", "required": false },
  { "id": "sq_9a8b7c6d", "type": "acknowledgment", "prompt": "I confirm the information above is accurate", "options": null, "preferred": null, "required": true }
]
```

The field lives on `POST`/`PATCH`/`GET /api/v1/jobs` and, for the company default set, on `PATCH /api/v1/company/settings` (admins) and `GET /api/v1/company/summary` (every role). At most 20 questions; ids are generated when omitted; an acknowledgment is always required and has no preferred answer. The public job detail carries the questions without `preferred`, and the apply payload takes `screening_answers: [{"question_id": "sq_...", "answer": "no"}]` (a string for choices and text, `true` for an acknowledgment, `null` or omitted for a skipped optional question); the server answers 422 with the offending question ids when a required one is missing or a value does not fit. The stored answers keep a snapshot of the question as it was asked, so editing a question later applies to future applicants only.

`GET /api/v1/applications` and the export accept `screening=match` (every preferred answer matched, none missed), `screening=mismatch` (any missed) or `screening=unanswered` (any skipped). Each application in the admin payload carries `screening_answers` with `preferred` and `match`; the candidate status page and the data-copy bundle show prompt and answer only.

### Webhooks

Admins register HTTPS endpoints under Settings, Developers and pick events: `application.created`, `stage.changed`, `quiz.completed`. Each event becomes one delivery per subscribed endpoint, posted by the worker as JSON:

```json
{
  "id": "6d1e...",
  "event": "stage.changed",
  "created_at": "2026-10-23T18:04:11+00:00",
  "data": {
    "id": "c17a...",
    "stage": "interview",
    "previous_stage": "screening",
    "source": null,
    "created_at": "2026-10-23T17:58:02+00:00",
    "applied_at": "2026-10-23T17:58:02+00:00",
    "message": "Happy to relocate.",
    "admin_url": "https://jobs.example.com/admin/applicants?selected=c17a...",
    "candidate": {
      "name": "Jane Applicant",
      "first_name": "Jane",
      "last_name": "Applicant",
      "email": "jane@example.com",
      "links": { "github": "https://github.com/jane", "linkedin": null, "portfolio": null }
    },
    "job": {
      "id": "9b2f...",
      "title": "Backend Engineer",
      "slug": "backend-engineer",
      "public_url": "https://jobs.example.com/jobs/backend-engineer"
    },
    "quiz": {
      "status": "completed",
      "score_percent": 83,
      "completed_at": "2026-10-23T18:01:40+00:00",
      "flags": ["left the tab 2x (~5s)"],
      "summary": "Ganek screening: 83% (8 questions), completed 2026-10-23, 1 integrity note"
    },
    "cv": {
      "filename": "jane-applicant-cv.pdf",
      "size_bytes": 184233,
      "url": "https://jobs.example.com/api/v1/applications/c17a.../cv"
    }
  }
}
```

`first_name` and `last_name` split the name (everything before the last space, then the last token), so an ATS that wants them separately needs no extra step, except that a single-word name has an empty `first_name`, which Greenhouse and Personio refuse, so fix those by hand; `quiz.summary` is one sentence for an ATS note field. `quiz` is `null` until an assessment exists and only ever carries the summary: no answers, no keys, no raw integrity events. `cv.url` is not the file, it is the key-protected `GET /api/v1/applications/{id}/cv` route above, because a delivery can be retried for over an hour and a download link inside it would have expired by then. Failed deliveries retry with backoff (1 min, 5 min, 15 min, 1 h) and park as `failed` after five attempts; the Developers page shows the last delivery per endpoint and "Send test" posts a realistic sample of the first event the endpoint subscribes to, with `"test": true` in `data`; receivers should ignore deliveries with `test: true`. The sample application does not exist, so its admin link opens no applicant and its CV link answers 404 when fetched with a key.

**Verify the signature.** Every request carries `X-Ganek-Timestamp` (unix seconds), `X-Ganek-Delivery` (the id, for de-duplication) and `X-Ganek-Signature: sha256=<hex>`, an HMAC-SHA256 of `"<timestamp>.<raw body>"` with the endpoint secret shown once at creation. Reject stale timestamps to block replays:

```python
import hmac, hashlib, time

def verify(secret: str, headers: dict[str, str], raw_body: bytes) -> bool:
    ts = headers["X-Ganek-Timestamp"]
    if abs(time.time() - int(ts)) > 300:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers["X-Ganek-Signature"])
```

```js
import { createHmac, timingSafeEqual } from "node:crypto";

export function verify(secret, headers, rawBody) {
  const ts = headers["x-ganek-timestamp"];
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return false;
  const expected = "sha256=" + createHmac("sha256", secret).update(`${ts}.`).update(rawBody).digest("hex");
  return timingSafeEqual(Buffer.from(expected), Buffer.from(headers["x-ganek-signature"]));
}
```

Endpoint URLs must be public `https://` addresses; localhost and private ranges are refused. Deliveries carry the candidate's name and email, so the service behind an endpoint is a processor you list in your own records of processing.

### Applicant export

Staff (admins and members, not reviewers) can pull the current applicant list as a file from the Applicants page (Export CSV / Export JSON), or directly:

```
GET /api/v1/applications/export?format=csv        # or format=json
GET /api/v1/applications/export?format=csv&job_id=<uuid>&stage=screening
```

Rows are flat and spreadsheet-shaped: candidate name, plus first and last name split for ATS imports (everything before the last space, then the last token; a single-word name leaves first name empty), email, job, stage, applied and decided timestamps, source, quiz status, score in percent, completion time, a one-line integrity summary, the extra-time multiplier when one was granted, CV filename, the candidate's message and `screening_mismatches` (how many preferred screening answers were missed; blank when the job asked none). No internal ids and nothing from inside the quiz (answers, keys) are included; the candidate email is the join key for your ATS. Every export is written to the activity log with who pulled it and how many rows.

### Extra time on the quiz

A timed quiz measures reading speed as well as knowledge. When a candidate asks for extended time as an accommodation (a screen reader, dyslexia, a motor impairment), an admin opens the applicant's integrity review page and sets Extra time to 1.5x or 2x per question. If the candidate has not started yet, the same quiz and link stay valid and the invite is sent again with the new timing. If they already started, finished or let the link expire, a fresh quiz is issued with the multiplier and the previous attempt is kept as history, exactly like the integrity re-invite. Later re-issues keep the grant.

The grant is recorded on the attempt with who set it and when, shows as a chip on the review page and as a column in the export, and never changes scoring or integrity flags. The candidate simply sees the longer limit on the intro screen and in the email. Setting Extra time back to None removes it.

```
POST /api/v1/applications/{id}/quiz/extra-time
{"time_multiplier": 2}        # 1, 1.5 or 2; admins only
```

Breaking changes to public endpoints carry a deprecation note in the release notes.

## Google Jobs markup

Every published job page carries a `JobPosting` script (schema.org JSON-LD) built from the job and the company:

| JobPosting field | Comes from |
| --- | --- |
| `title`, `description` | the job title and the description, markdown rendered to HTML |
| `datePosted` | the publish date |
| `validThrough` | "Closes on", when set |
| `employmentType` | the employment type |
| `hiringOrganization` | the company name, website and logo from Settings |
| `jobLocation` | the location; a remote job sets `jobLocationType: TELECOMMUTE` instead |
| `baseSalary` | the salary range, currency and period, when set |

The job page in the admin shows the exact JSON and checks the properties Google requires: title, description, datePosted, hiringOrganization and a location or TELECOMMUTE. Paste the public job URL into Google's Rich Results Test to confirm what Google sees. Draft and closed jobs emit nothing, preview links emit nothing, and a demo instance switches the markup off because its vacancies are fictional.
