# AI Act statement

> For vendor-assessment and procurement questionnaires. Describes upstream
> Ganek as shipped; not legal advice - see the [pack README](README.md).

**Ganek does not contain an AI system.** Employment and recruitment tools
are a headline category of the EU AI Act (Annex III high-risk), so the
question deserves a direct answer rather than a shrug. Two independent
grounds, in order of strength:

**1. Ganek's scoring is not an "AI system" under Art. 3(1).** The quiz
engine is deterministic, human-authored rules end to end: questions are
selected from a pool by explicit tag/difficulty configuration, options are
shuffled on every serve, and the score is
`correct answers ÷ questions served`, with per-tag breakdowns computed the
same way. There is no machine learning, no training data, no statistical
model, no adaptivity, and no inference beyond executing rules a human wrote
and can read. The Commission's guidelines on the AI-system definition
(February 2025) exclude systems that operate solely on rules defined by
natural persons; Ganek's engine is squarely that. (The guidelines are
non-binding, which is why ground 2 exists.)

**2. Even for genuine recruitment AI, the Annex III clock runs to
2 December 2027.** The AI Omnibus amendments (in force 27 July 2026)
deferred the high-risk obligations that would cover employment/recruitment
AI systems to that date. Ganek doesn't rely on this - ground 1 is the
answer - but it bounds the risk of a definitional dispute today.

**GDPR Art. 22 adjacency.** No decision about a candidate is taken by
Ganek: scores and integrity flags are displayed to reviewers who always see
the full application, and the product contains **no automated rejection,
advancement, filtering, or ranking cutoff** - there is nothing to
configure, because the mechanism doesn't exist. Under the SCHUFA line of
case law the danger zone is a score a decision-maker "draws strongly on"
without meaningful human involvement; Ganek's design keeps humans doing the
deciding with full context, and the candidate-facing privacy notice
discloses the scoring and flagging anyway.

## The guardrail

This statement stays true only while the engine stays deterministic. Any
of the following would create an AI system, likely land it in Annex III
4(a) (high-risk: recruitment), and reopen the Art. 22 analysis:

- ML-based CV parsing, scoring, or candidate ranking;
- adaptive/dynamic testing that models the candidate;
- automated stage changes, filtering, or rejection - however implemented;
- any model-derived "fit" or personality inference.

Upstream Ganek's position: **no such feature ships without redoing the AI
Act and Art. 22 analyses first** - it is a deliberate product boundary,
not an accident of roadmap. If your fork or deployment adds any of the
above, this statement no longer describes your system, and the compliance
obligations (provider *and* deployer duties under the AI Act) become
yours to assess.
