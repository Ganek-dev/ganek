---
title: Roles
description: What admins, members and reviewers can do, and how a reviewer seat reaches only the candidates handed to it.
sidebar: { order: 2 }
---

Every teammate has one of three roles. Admins change it on the **Team** page, where you can also invite someone straight into a reviewer seat.

| Role | Can |
| --- | --- |
| Admin | Jobs, questions, team, branding. Everything a member can do. |
| Member | Day-to-day recruiting and applicant review. |
| Reviewer | Sees only candidates handed to them for an interview or a scorecard. |

Admins and members see every candidate in the company, and either can export applicants. Reviewers cannot.

## The reviewer seat

Companies often have colleagues who only judge candidates: a hiring manager, an engineer who runs technical interviews. A reviewer seat gives them a small surface at `/review` instead of the recruiting app. They sign in at the usual login page and land there.

**What a reviewer sees**, on the candidates handed to them:

- the candidate's name and the job
- the CV
- the screening questions and the candidate's answers (not your preferred answers or the match flags)
- the outcomes of a completed quiz: the score and, per question, correct, wrong or timed out
- their own interview (time and place)
- their own scorecard
- colleagues' submitted scorecards, only after they have submitted their own

**What a reviewer cannot do or see:** recruiter notes, the candidate's email, stage changes, the applicants list, jobs, the team page, settings or exports. A reviewer cannot send mail to candidates. They do receive the mails about their own work: scorecard requests, the reminder, and interview invites.

If a reviewer is the interviewer on an interview, their interview mail does not carry the candidate's email as an attendee and links to `/review`.

## How access is granted

A reviewer reaches a candidate through exactly two things:

1. a scorecard request for them, which is kept when they submit or decline it and removed when you dismiss it, or
2. a booked interview where they are the interviewer.

A submitted or declined request keeps the grant until the candidate's data is erased or purged. Dismissing the request, cancelling the interview, or removing the teammate ends the grant that request or interview gave. API keys belong to the company, so rotate them when you demote a teammate who may hold one. Anything else is a not-found, not a refusal, so a reviewer cannot tell which other candidates exist.

## Reviewer account

At `/review/account` a reviewer can change their display name (shown to teammates on scorecards), their interview location, and set up two-factor authentication.

Demoting a member to reviewer keeps their scorecards but limits them to granted candidates from then on. Promoting a reviewer to member keeps theirs too.

## Records

When a reviewer opens a candidate's judging page, the read-access trail records it as a view, plus a CV download and quiz answers when those are shown. The reviewer's candidate list is not logged. See the [compliance pack](/compliance/self-hosting-gdpr-guide/).
