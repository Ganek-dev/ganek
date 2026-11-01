---
title: Scorecards
description: Hand a candidate to a colleague, get criteria ratings, a recommendation and a comment back, and see who is holding the candidate up.
sidebar: { order: 1 }
---

A scorecard is a structured answer from a colleague about one candidate: a rating per criterion, a recommendation and a comment, on a form the job defines. Until the answer arrives you see who is holding the candidate up and for how long. Scorecards are visualization only: a recommendation is a display value. It never changes a quiz score or a stage, and Ganek never rejects anyone automatically. The quiz decides who you talk to; people decide what happens next.

## The template

A template is an ordered list of criteria, up to 20. Each criterion has a label (for example "Problem solving") and an optional hint that the reviewer sees under it.

- **Company default.** An admin edits it under **Settings -> Hiring -> Default scorecard** (`/admin/hiring`). New jobs copy it when they are created.
- **Per job.** Open the job and use the **Scorecard** section of the edit form to add, remove and reorder criteria for that job. Changing the company default later does not touch existing jobs.

Reviewers rate each criterion from 1 to 4, or choose "Not assessed". The recommendation has four fixed choices with no middle: Strong no, No, Yes, Strong yes. There is also one free-text comment.

When a request is created, the job's criteria are copied onto it. Editing the template afterwards does not change requests that already exist, and a submitted scorecard keeps the criteria it was answered against.

## Requesting a scorecard

Open a candidate and use the **Request** control on the Scorecards card. Pick any active teammate (you cannot request one from yourself, and a teammate with an open or submitted request is not offered again). The teammate gets one mail with a link to the form, and the task shows on their dashboard.

Booking an interview also requests a scorecard from the interviewer automatically. That request starts waiting when the interview ends, and if the interview moves, the wait moves with it. If the candidate cancels the interview, the request it created is withdrawn.

## Waiting on, reminders, decline and dismiss

An open request reads "Waiting on Jane Doe for 4 days" on the candidate and as a "waiting" item in your dashboard queue; the reviewer sees the matching task on theirs.

- **Reminder.** One mail, three days after the request, or three days after the interview ended. Nothing follows it. Requesting again starts the clock and the single reminder over.
- **Decline.** The reviewer can choose "I did not assess this candidate". The row reads "Declined by Jane Doe" and you can **Request again**.
- **Dismiss.** You can dismiss an open request. It disappears from the reviewer's list and they lose any access the request gave them (see [Roles](/roles/)).
- **Submit and edit.** After submitting, the reviewer can edit their answers for 24 hours. A submitted scorecard shows the recommendation, the ratings, the comment and the date.

## What the candidate's data export contains

A candidate's access request (the data bundle) includes their submitted scorecards: the criteria with ratings, the recommendation and the comment. It leaves out the reviewer's name, because colleague names are third-party personal data. Open, declined and dismissed requests hold no assessment and are not exported. Erasing a candidate, or the retention purge, removes their scorecards with the application. See the [compliance pack](/compliance/self-hosting-gdpr-guide/).
