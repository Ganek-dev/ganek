---
title: Send candidates to your ATS
description: Hand screened candidates to Greenhouse, Lever, Personio, Recruitee or any other ATS through a Zapier or Make recipe on the webhook, or through the CSV export.
sidebar: { order: 3 }
---

Ganek sits in front of your applicant tracking system, not instead of it. Once a candidate has done the quiz and you have moved them on, they should show up in your ATS under the right job without retyping. Two routes exist today: a no-code recipe on the [webhooks](/api-embed/#webhooks), and the applicant export. A built-in "Send to ATS" is on the roadmap; until then the recipe below is the push.

## Which candidates cross over

Not every applicant belongs in the ATS. The webhook fires `stage.changed` on every move, so the recipe filters on the stage you treat as "screened", usually `interview`. Applicants you reject or leave in `screening` never leave Ganek. If you want every application mirrored, subscribe to `application.created` instead and skip the filter.

## What the webhook carries

Every delivery is JSON with an `event`, a `created_at` and a `data` object. For `stage.changed`:

| Field | Meaning |
| --- | --- |
| `data.candidate.name`, `data.candidate.email` | the candidate; email is the key every ATS deduplicates on |
| `data.job.title`, `data.job.slug` | the job they applied to |
| `data.stage`, `data.previous_stage` | where they are now and where they came from |
| `data.source` | how they found the job, when known |
| `data.quiz.score_percent`, `data.quiz.status`, `data.quiz.completed_at` | the screening result at summary level |
| `data.quiz.flags` | the integrity notes as short sentences, often empty |
| `data.id` | the application id, for your own records |

Nothing from inside the quiz travels: no answers, no keys, no raw telemetry. The CV is not in the payload either; see [the CV](#the-cv) below.

Zapier flattens nested JSON with a double underscore, so the same fields appear there as `data__candidate__email`, `data__job__title`, `data__quiz__score_percent`. Make shows them as a collection you expand.

## Zapier recipe

Webhooks by Zapier needs a Professional plan or above.

1. In Zapier, create a Zap with the trigger **Webhooks by Zapier, Catch Hook**. Copy the webhook URL.
2. In Ganek, open Settings, Developers, add a webhook endpoint with that URL and tick `stage.changed`. Keep the secret if you plan to verify signatures later.
3. Move any applicant to a new stage (or back and forth) so one delivery arrives, then click **Test trigger** in Zapier. The fields above appear.
4. Add a **Filter** step: continue only if `data__stage` exactly matches `interview` (or your stage).
5. Add the action from your ATS's Zapier app that creates a candidate or application. Map:
   - name fields from `data__candidate__name` (split with a Formatter step if the ATS wants first and last name separately),
   - email from `data__candidate__email`,
   - the job from `data__job__title`, or pick the ATS job by hand if the action asks for an id,
   - the source from `data__source`,
   - a note or tag with the score, for example `Ganek screening: {{data__quiz__score_percent}}%`.
6. Turn the Zap on. From now on every candidate you move to that stage appears in the ATS within a minute.

## Make recipe

1. In Make, create a scenario starting with **Webhooks, Custom webhook**. Copy its URL.
2. Register the URL in Ganek under Settings, Developers with `stage.changed` ticked.
3. Move an applicant between stages once; Make detects the data structure from that first request. Click **Redetermine data structure** later if the shape changes.
4. Add a **Filter** on the connection: `data.stage` equal to `interview`.
5. Add your ATS module's create-candidate action and map the fields as in the Zapier recipe.

Make answers every delivery with `200 Accepted`, which Ganek records as delivered. If a scenario is switched off, Make returns `410 Gone` after five days and the Developers page shows the deliveries as failed; re-enable the scenario and re-register the webhook.

## The CV

The webhook does not carry the CV and there is no API route for it yet. Today the file is downloaded from the applicant page in Ganek and attached in the ATS by hand, or the ATS's own CV auto-match on the candidate's email picks it up when you import it. Carrying a CV download in the webhook for API keys is the next step on the [roadmap](https://github.com/Ganek-dev/ganek).

## CSV route

For a batch, export the applicants ([Export CSV](/api-embed/#applicant-export) on the Applicants page, filtered by job and stage) and import the file with your ATS's own spreadsheet import:

- Greenhouse: Configure, Bulk Import, Begin Candidate Import, map the columns to the template.
- Lever: Settings, Import; Full Name and Stage are required.
- Personio: Settings, Data imports, Recruiting; map the columns in the "Configure columns" step.
- Recruitee: Settings, Apps and plugins, Import; CSV UTF-8.

The export has one `candidate_name` column. Greenhouse and Personio want first and last name separately, so split the column in your spreadsheet first. `candidate_email` is the join key, `job` the job title, `quiz_score_percent` and `integrity_flags` the screening result; map them to a note or a custom field.

## Verifying deliveries

Every request is signed; the verification snippets are in [API and embed widget](/api-embed/#webhooks). Zapier's Catch Hook cannot check the signature; its URL is the secret. If that is not enough for your processor records, receive the webhook on your own small service, verify it there, and forward to the ATS from it.
