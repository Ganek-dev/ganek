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
| `data.candidate.first_name`, `data.candidate.last_name` | the name already split, for ATSs that want two fields |
| `data.candidate.links.github`, `.linkedin`, `.portfolio` | the profile links the candidate gave, `null` when empty |
| `data.message` | the candidate's cover message |
| `data.applied_at` | when they applied |
| `data.admin_url` | the applicant in Ganek, one click from your ATS record |
| `data.job.public_url` | the public page of the job |
| `data.job.title`, `data.job.slug` | the job they applied to |
| `data.stage`, `data.previous_stage` | where they are now and where they came from |
| `data.source` | how they found the job, when known |
| `data.quiz.score_percent`, `data.quiz.status`, `data.quiz.completed_at` | the screening result at summary level |
| `data.quiz.flags` | the integrity notes as short sentences, often empty |
| `data.quiz.summary` | one sentence for the ATS note field |
| `data.id` | the application id, for your own records |
| `data.test` | present and `true` only on the sample that **Send test** posts; real deliveries do not have it |

Nothing from inside the quiz travels: no answers, no keys, no raw telemetry. The CV is not in the payload either; see [the CV](#the-cv) below.

Zapier flattens nested JSON with a double underscore, so the same fields appear there as `data__candidate__email`, `data__job__title`, `data__quiz__score_percent`. Make shows them as a collection you expand.

## Zapier recipe

Webhooks by Zapier needs a Professional plan or above.

1. In Zapier, create a Zap with the trigger **Webhooks by Zapier, Catch Hook**. Copy the webhook URL.
2. In Ganek, open Settings, Developers, add a webhook endpoint with that URL and tick `stage.changed`. Keep the secret if you plan to verify signatures later.
3. In Ganek, click **Send test** on the endpoint; one sample `stage.changed` delivery arrives. Then click **Test trigger** in Zapier and the fields above appear. When Zapier learns the fields, tick only the event you are mapping, since an `application.created` sample has no quiz block.
4. Add a **Filter** step: continue only if `data__stage` exactly matches `interview` (or your stage) and `data__test` does not exist. Send test posts a sample at stage `interview`, so without the second condition it would create "Sample Candidate" in your ATS once the Zap is on.
5. Add the action from your ATS's Zapier app that creates a candidate or application. Map:
   - first and last name from `data__candidate__first_name` and `data__candidate__last_name` (a single-word name arrives with an empty first name, which Greenhouse and Personio refuse, so fix those by hand),
   - email from `data__candidate__email`,
   - the job from `data__job__title`, or pick the ATS job by hand if the action asks for an id,
   - the source from `data__source`,
   - the note from `data__quiz__summary`.
6. Turn the Zap on. From now on every candidate you move to that stage appears in the ATS within a minute.

## Make recipe

1. In Make, create a scenario starting with **Webhooks, Custom webhook**. Copy its URL.
2. Register the URL in Ganek under Settings, Developers with `stage.changed` ticked.
3. In Ganek, click **Send test** on the endpoint; one sample `stage.changed` delivery arrives and the fields above appear. When Make learns the fields, tick only the event you are mapping, since an `application.created` sample has no quiz block. Make detects the data structure from that first request. Click **Redetermine data structure** later if the shape changes.
4. Add a **Filter** on the connection: `data.stage` equal to `interview` and `data.test` does not exist. Send test posts a sample at stage `interview`, so without the second condition it would create "Sample Candidate" in your ATS once the scenario is on.
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

The export carries `candidate_name` and the split `first_name` and `last_name`, so Greenhouse and Personio import it without a spreadsheet step, except for a candidate who gave a single-word name: that row exports with an empty `first_name`, which both refuse, so fix it by hand. `candidate_email` is the join key, `job` the job title, `quiz_score_percent` and `integrity_flags` the screening result; map them to a note or a custom field.

## Verifying deliveries

Every request is signed; the verification snippets are in [API and embed widget](/api-embed/#webhooks). Zapier's Catch Hook cannot check the signature; its URL is the secret. If that is not enough for your processor records, receive the webhook on your own small service, verify it there, and forward to the ATS from it.
