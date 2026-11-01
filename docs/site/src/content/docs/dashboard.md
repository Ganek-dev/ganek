---
title: Dashboard and Reports
description: What the status chips on your open roles mean, who each candidate is waiting on, and what the Reports page counts.
sidebar: { order: 0 }
---

The dashboard shows where each open role stands today. Reports shows how candidates moved through your pipeline over a period. Both describe the process, never a person. Nothing here decides anything: Ganek never rejects a candidate on its own, and there are no benchmarks or pass lines on any chart.

## Open roles

The Open roles board has one row per role: published jobs, plus closed jobs that still have live candidates. Closing a job stops new applications, not the interviews in progress, so a closed role with candidates in the pipeline stays on the board with a "Closed" tag until the last one is resolved. Drafts never appear. A live candidate is one who is not hired, rejected or withdrawn.

Each row shows a status chip, live candidates per stage, how many are waiting on you (and the longest wait), how many are overdue, new applications and movement this week, and days open.

### Status chips

The chip is decided by the first rule that matches, top to bottom:

| Chip | Rule |
|---|---|
| Empty | No live candidates. |
| Stalled | There are live candidates, but nobody moved in the last stage-limit days. |
| Needs attention | At least one candidate is overdue. |
| On track | Anything else: candidates moved recently and nobody is overdue. |

"Moved" means a stage change, a new application, or a completed quiz. Hover a chip for the sentence behind it. Roles are sorted Stalled first, then Needs attention, On track and Empty. A stalled role also lands in your queue as one item, which you can dismiss like any other.

### Waiting on you or on the candidate

Every live candidate is waiting on exactly one side, counted from a date. The first rule that matches wins:

| Situation | Waiting on | Counted from |
|---|---|---|
| An interview was requested and is not booked yet, at any stage | Candidate | The request |
| An interview is booked and has not ended yet, at any stage | Candidate | The request |
| An interview is booked and has ended, at any stage | You | The end of the interview |
| Stage New, quiz sent and not expired, or in progress | Candidate | The quiz invitation |
| Stage New, anything else (no quiz, quiz completed, expired or invalidated) | You | The completion, the expiry, or the move into the stage |
| Stage Screening, no interview | You | The move into the stage |
| Stage Interview, no interview requested or it was cancelled | You | The move into the stage |
| Stage Offer, no interview | Candidate | The move into the stage |

A candidate is overdue when they are waiting on you for more than the stage limit, counted in UTC calendar days. Candidates waiting on the other side are never overdue.

### The stage limit

The stage limit is 7 days by default and can be set from 1 to 60. An admin changes it under **Settings -> Hiring -> Pipeline**. It drives both "overdue" and the Stalled chip.

## Reports

Reports (`/admin/reports`) is for admins and recruiters; reviewers do not see it. Filter by period (30 days, 90 days, 12 months, all) and optionally by job.

The period picks a cohort: the applications created in that window. Every number on the page is about that cohort, and the deltas compare it with the previous period of the same length. With "all" there are no deltas.

- **Funnel.** Steps are Applied, Screening, Interview, Offer, Hired. A candidate counts as having reached a step if their history or current stage is that step or a later one, so a skipped stage still counts as reached. Rejected and withdrawn are outcomes, not steps: for each step Reports shows how many were rejected from there, withdrew from there, and how many are still here, meaning live at that stage right now. A line under the funnel counts quizzes invited, completed and expired.
- **Time in stage.** The median number of days in each stage, over completed stays only. Beside it, the oldest live candidate per stage, so you look at the slowest case and not just the count.
- **Time to hire.** The median days from application to hire, for hires in the cohort.
- **Sources** and the **score distribution** and **applications per week** charts, for the same cohort.

Every median is shown with its n. Below 3 data points it shows "-" instead of a number, because a median of one or two cases says nothing.

### Diagnosis

With at least 10 applications in the cohort, Reports adds one or two plain sentences: the step most candidates left from (rejected or withdrew), and the stage with the longest median time. Below 10 it says there is not enough data yet. It states what the numbers show and gives no advice and no verdict on any candidate.
