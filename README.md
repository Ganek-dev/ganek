# Vetd

**Open-source careers pages with built-in skill screening.**

Vetd gives any company a branded careers page, job posting management, and applicant tracking — plus an optional twist: after a candidate submits their CV, Vetd can serve a short, timed multiple-choice quiz matched to the job's skill tags (Python job → python/asyncio/fastapi questions, ~15 seconds each). Recruiters see applications ranked with real signal instead of just a pile of PDFs.

> ⚠️ **Status: pre-alpha.** Under active development, not yet usable. Watch/star to follow along.

## Why

- No good open-source alternative to hosted careers pages / ATS-lite tools exists.
- Engineering roles drown in low-signal applications; a 2-minute knowledge screen is a fair, fast first filter.
- Your hiring data should be able to live on your infrastructure.

## Features (v1 target)

- 🏢 Branded careers page (theme tokens, logo, custom slug) with SEO-friendly SSR and Google Jobs structured data
- 📋 Job posting management with markdown descriptions and tags
- 📥 Application intake with CV upload
- ⏱️ Tag-matched screening quizzes: open question bank + your own private questions, per-job configuration, server-side timing and scoring, cheat-resistant by design
- 📊 ATS-lite: pipeline stages, quiz scores with per-tag breakdown, integrity flags, notes
- 🐳 Self-host with one `docker compose up` — or use the hosted version at vetd.dev (coming later)
- 🧩 Domain-agnostic engine: engineering first, any field via community question packs

## Quiz integrity, in short

Everything that matters is server-authoritative: questions are served one at a time, timing and scoring happen server-side, correct answers never reach the client, pools are large and randomized, options are shuffled per attempt. Focus-loss and paste telemetry is surfaced to recruiters as flags — Vetd never auto-rejects anyone.

## Quickstart (self-host)

```bash
git clone https://github.com/vetd-dev/vetd && cd vetd
cp .env.example .env        # edit as needed
docker compose up
# open http://localhost:3000 and follow the setup wizard
```

## Contributing

Code and question-pack contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). The question bank especially benefits from many eyes: [questions/README.md](questions/README.md).

## License

[AGPL-3.0](LICENSE). You can self-host Vetd freely, including commercially, for your own hiring. If you offer Vetd as a service to others, the AGPL requires you to share your modifications.
