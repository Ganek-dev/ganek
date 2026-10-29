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

Scope `read` covers `GET /api/v1/applications`, `GET /api/v1/applications/{id}` and the export above. Scope `write` adds `PATCH /api/v1/applications/{id}/stage`; stage changes made with a key show in the activity log without a person as actor, and a `GET /api/v1/applications/{id}` with a key lands in that applicant's read-access trail under the key's name. Keys never reach the key-management endpoints themselves, and revoking one cuts it off immediately. Payloads are the same as the admin UI sees: quiz results stay at the summary level, never answers or keys.

### Webhooks

Admins register HTTPS endpoints under Settings, Developers and pick events: `application.created`, `stage.changed`, `quiz.completed`. Each event becomes one delivery per subscribed endpoint, posted by the worker as JSON:

```json
{
  "id": "6d1e...",
  "event": "stage.changed",
  "created_at": "2026-10-23T18:04:11+00:00",
  "data": {
    "id": "c17a...",
    "stage": "screening",
    "previous_stage": "new",
    "source": null,
    "created_at": "2026-10-23T17:58:02+00:00",
    "candidate": { "name": "Jane Applicant", "email": "jane@example.com" },
    "job": { "id": "9b2f...", "title": "Backend Engineer", "slug": "backend-engineer" },
    "quiz": { "status": "completed", "score_percent": 83, "completed_at": "...", "flags": ["left the tab 2x (~5s)"] }
  }
}
```

`quiz` is `null` until an assessment exists and only ever carries the summary: no answers, no keys, no raw integrity events. Failed deliveries retry with backoff (1 min, 5 min, 15 min, 1 h) and park as `failed` after five attempts; the Developers page shows the last delivery per endpoint and "Send test" posts a `ping`.

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

Admins can pull the current applicant list as a file from the Applicants page (Export CSV / Export JSON), or directly:

```
GET /api/v1/applications/export?format=csv        # or format=json
GET /api/v1/applications/export?format=csv&job_id=<uuid>&stage=screening
```

Rows are flat and spreadsheet-shaped: candidate name and email, job, stage, applied and decided timestamps, source, quiz status, score in percent, completion time, a one-line integrity summary, the extra-time multiplier when one was granted, CV filename and the candidate's message. No internal ids and nothing from inside the quiz (answers, keys) are included; the candidate email is the join key for your ATS. Every export is written to the activity log with who pulled it and how many rows.

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
