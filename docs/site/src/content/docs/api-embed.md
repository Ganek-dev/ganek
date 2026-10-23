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

The admin UI talks to the same backend under `/api/v1/` with a session cookie and the tenancy of the signed-in user. The interactive OpenAPI reference is served by your own instance at `/api/docs` (schema at `/api/openapi.json`). API keys and outbound webhooks (new application to Slack) are on the roadmap; until then the session cookie is the only credential.

### Applicant export

Admins can pull the current applicant list as a file from the Applicants page (Export CSV / Export JSON), or directly:

```
GET /api/v1/applications/export?format=csv        # or format=json
GET /api/v1/applications/export?format=csv&job_id=<uuid>&stage=screening
```

Rows are flat and spreadsheet-shaped: candidate name and email, job, stage, applied and decided timestamps, source, quiz status, score in percent, completion time, a one-line integrity summary, CV filename and the candidate's message. No internal ids and nothing from inside the quiz (answers, keys) are included; the candidate email is the join key for your ATS. Every export is written to the activity log with who pulled it and how many rows.

Breaking changes to public endpoints carry a deprecation note in the release notes.
