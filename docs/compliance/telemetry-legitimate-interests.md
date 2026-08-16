# Legitimate interests assessment — quiz integrity telemetry

> The balancing analysis (Art. 6(1)(f)) behind Vetd's integrity monitoring,
> written to be attached to your [DPIA](dpia-template.md) and referenced
> from your [records](records-of-processing-template.md). Not legal
> advice — see the [pack README](README.md). Sign and date it as the
> controller: `{company, assessor, date}`.

## What exactly is processed

During a quiz attempt — and only then — the quiz page records events of
exactly three types, each tagged with the question that was open:

1. **blur** — the window lost focus (tab switch, app switch), with the
   duration until focus returned;
2. **paste** — a paste occurred on the quiz page (the event only; the
   pasted *content* is never read or transmitted);
3. **resize** — the window was resized.

Stored with the attempt, summarized into flags for the reviewing recruiter.
**Not** collected: IP address, user agent, keystrokes, clipboard contents,
mouse movement, screen or camera capture, anything outside the attempt.
Flags are informational — they never score, reject, or gate anything.

## 1. Purpose test — is the interest legitimate?

The interest is **assessment integrity**: a timed screening quiz only has
value (to the company *and* to honest candidates) if attempts are
comparable. Detecting signals consistent with off-screen lookup or pasted
answers is the same interest family as fraud prevention and security
monitoring — recognised legitimate interests. Honest candidates share it:
their result should not compete against assisted ones. The interest is
real, present, and lawful. **Passed.**

## 2. Necessity test — is this way the least intrusive that works?

Alternatives considered:

- **No monitoring:** the screen's purpose (a credible, fair first-pass
  signal) collapses — scores become unverifiable and the honest majority
  is harmed. Not adequate.
- **Proctoring (webcam/screen recording/lockdown browsers):** vastly more
  intrusive; plainly disproportionate for a ~10-minute screening quiz.
- **Server-side-only design measures** (large randomized pools, per-attempt
  option shuffling, one-question-at-a-time serving, server timing): Vetd
  does all of these *first*; telemetry only covers what they cannot see —
  live assistance during the attempt.

The chosen design is the minimal marginal step: three coarse event types,
question-tagged, occurrence-level, during the attempt only. Each maps
directly to the risk (leaving the screen; pasting a fetched answer; making
room for a second window). Nothing broader is collected, and correlation
value would not justify more. **Passed.**

## 3. Balancing test

**Weight against:** candidates are in a power imbalance and cannot
negotiate; behavioral monitoring during an assessment can feel
surveillance-like; misread flags could unfairly color a review.

**Weight for, and mitigations:**

- **Full prior disclosure.** The quiz start gate — desktop and mobile —
  lists the three monitored signals *before* the attempt begins, states
  that events are tied to the open question, stored with the attempt,
  reviewed by humans, and never auto-score. Also disclosed in the apply
  confirmation and the privacy notice. No surprise monitoring.
- **Reasonable expectations.** A candidate who starts a timed,
  explicitly-rules-gated assessment reasonably expects integrity measures;
  these are far short of the proctoring that is common in assessment
  contexts.
- **Informational use only.** Flags never reject, filter, or rank. A
  reviewer sees the whole application, and the product enforces that no
  automated consequence exists to trigger.
- **Minimal, occurrence-level data.** No identifiers beyond the attempt
  context; no content capture; benign explanations (a notification, a
  window manager quirk) remain visible as exactly what they are — a
  15-second blur, not an accusation.
- **A real alternative.** The gate states it: candidates may skip the quiz
  and their application remains reviewable. Declining monitoring does not
  cost them the application — this is the practical objection route
  (Art. 21 requests go to the privacy contact like any other).
- **Time-boxed.** Telemetry lives and dies with the application record
  under the configured retention window.

Residual tension is modest and the safeguards are structural (product
invariants, not policy promises). **Balance favors the processing.**

## 4. ePrivacy note (Art. 5(3))

Under the EDPB's broad reading (Guidelines 2/2023), script-driven
collection of terminal-equipment information is within Art. 5(3), which
permits it without consent where **strictly necessary for a service
explicitly requested** by the user. Position taken: the candidate
explicitly starts a rules-gated, timed assessment whose credibility *is*
the service; occurrence-level integrity signals are integral to delivering
it, analogous to the accepted fraud-prevention/security uses. A consent
gate would be self-defeating in a way that illustrates the necessity: an
attempt with monitoring declined cannot deliver a comparable result, which
is the thing being requested.

The contrary reading — that the assessment is requestable *without*
monitoring, making telemetry consent-gated — is acknowledged. This is a
judgment call made in the open; deployments at scale, or in member states
with strict ePrivacy enforcement practice, should put this specific
question to counsel. *(Marked for legal review before any hosted-service
use of this analysis.)*

## 5. Standing conditions and review triggers

This assessment holds **only** while all of the following stay true:

- exactly the three event types above, occurrence-level, attempt-scoped;
- no IP/user-agent/content capture in telemetry;
- flags informational only — no automated consequence of any kind;
- full disclosure at the gate on every device class before the attempt;
- skipping the quiz leaves the application reviewable;
- telemetry is deleted with the application per the retention window.

Any change — a new event type, weighting flags into scores, gating stages
on flags, expanded capture — **invalidates this LIA**; redo it (and the
DPIA risk table) before shipping. Upstream Vetd treats these conditions as
product invariants; forks that alter them inherit the re-assessment duty.
