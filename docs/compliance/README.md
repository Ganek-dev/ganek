# Ganek compliance pack (GDPR)

Documents for companies that self-host Ganek and process candidates in (or
from) the EU/EEA and UK. If that is you, **you are the data controller**
for your candidates' data - Ganek is software you run, and this pack exists
to make your controller duties practical instead of theoretical.

> **This is not legal advice.** These documents are engineering artifacts:
> they describe accurately what Ganek does with personal data and map that
> onto GDPR obligations using primary sources and regulator guidance. They
> are a strong starting point, not a substitute for your own review - for
> anything with real legal stakes (large volumes, special situations, a
> dispute), have your own counsel look at your filled-in versions.

## "GDPR-ready", not "GDPR compliant"

Compliance is a property of a *deployment* and its controller - the
retention you configure, the notices you publish, how you answer requests -
never of software alone. Ganek ships as **GDPR-ready**:

- **Per-company privacy notices**, rendered by the app from your settings
  (Settings → Privacy), linked from the careers page, apply form, and every
  candidate email.
- **Retention automation**: a nightly purge deletes rejected/withdrawn
  applications after your configured window (default 6 months). On by
  default; you can raise the window, not silently disable deletion.
- **Erasure tooling**: a one-click admin erasure that deletes the database
  records, the CV file, and (best-effort) Google Calendar events.
- **DSAR export**: a per-candidate JSON bundle of everything Ganek holds
  about them, including quiz answers, scores, and integrity events.
- **Candidate request routes**: the application status page lets candidates
  request a copy of their data or ask for deletion - each lands as a task
  in your dashboard.
- **No cookies, no trackers** on any candidate-facing page, and no IP or
  user-agent in quiz telemetry.
- **No automated decisions**: scores and integrity flags inform humans;
  Ganek never auto-rejects, auto-advances, or auto-filters anyone.
- **EU-hostable**: one compose stack you can run entirely on EU
  infrastructure. The only third-country flow is Google Calendar/Meet, and
  only if your recruiters connect it.

## What's in the pack

| Document | What it is | When you need it |
|---|---|---|
| [Self-hosting GDPR guide](self-hosting-gdpr-guide.md) | "You are the controller" + setup and operating checklists mapped to product controls | Before your first candidate; keep at hand for requests |
| [DPIA template](dpia-template.md) | Pre-filled data protection impact assessment for the quiz + telemetry processing | Before going live (recommended; mandatory in several member states for recruitment scoring) |
| [Records of processing template](records-of-processing-template.md) | Art. 30 record pre-filled with Ganek's processing activities | Keep current from day one - the small-company derogation does not apply to recruitment |
| [Breach runbook](breach-runbook.md) | Detect → assess → notify steps with Ganek-specific containment levers, plus a breach register template | When something goes wrong (read it once before that) |
| [Telemetry legitimate interests assessment](telemetry-legitimate-interests.md) | The balancing analysis behind quiz integrity monitoring | Attach to your DPIA/records; redo if you fork telemetry |
| [AI Act statement](ai-act-statement.md) | Why Ganek's deterministic scoring is not an AI system, and the guardrail that keeps it that way | Procurement/vendor-assessment questionnaires |

## If you change Ganek

These documents describe **upstream Ganek as shipped**. Adding analytics or
cookies to candidate pages, new telemetry event types, ML-based parsing,
scoring or ranking, or any automated stage change invalidates parts of this
pack - at minimum redo the
[telemetry LIA](telemetry-legitimate-interests.md) and the
[AI Act statement](ai-act-statement.md), and revisit the DPIA's risk table.

## Hosted ganek.io

The hosted service (when it launches) ships its own controller/processor
pack: a data processing agreement, sub-processor list, and processor breach
notification terms. This directory covers self-hosting only.
