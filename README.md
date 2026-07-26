# Correct-Score Prediction Bot

Predicts likely scorelines for upcoming matches using a Poisson statistical
model (the same basic approach real analytics models use) — team attack/
defense strength calculated from this season's results so far, then used to
generate a full probability breakdown across scorelines, not just a single
guess.

## What changed in the thorough re-review (worth knowing)

- **Fixed a real data-truncation bug**: the API caps responses at 100
  matches by default; a full season can have 380. Late-season, this would
  have silently used incomplete training data. Fixed by explicitly
  requesting up to 500 per call, with a warning if the API ever indicates
  truncation anyway.
- **Fixed a theoretical division-by-zero** in the model (guarded, won't
  realistically happen with real football data, but doesn't crash if it
  ever did).
- **Fixed a real design gap — duplicate alerts**: with the bot running 3x/
  day, it would have re-sent the same match prediction every single run
  until kickoff. Now tracks "already sent" matches in `alerted_matches.json`,
  which the GitHub Actions workflow commits back to the repo after each run
  so the tracking survives between separate runs (each run starts a fresh
  container with no memory otherwise).
- **Corrected the rate limit, twice**: I initially said 10 req/min, then
  wrongly "corrected" that to 50/min based on a misread source. Checking
  football-data.org's own official documentation directly confirmed the
  ORIGINAL 10/min figure was right. The code now properly paces every API
  call at a safe interval so this is never an issue regardless of how many
  leagues are configured.
- **Widened from 5 to 10 leagues** — all of football-data.org's free-tier
  competitions that run continuously (excluding World Cup/Euros, which
  are periodic tournaments, mostly inactive most of the year).
- **Added a confidence filter** (`MIN_TOP_SCORELINE_PROB`, default 10%) —
  only alerts when the top predicted scoreline itself is reasonably
  concentrated. Empirically tested across several scenarios: this mostly
  reflects how concentrated the total expected-goals distribution is (a
  low-scoring expected match naturally concentrates probability onto fewer
  scorelines), not simply "biggest mismatch" — both are legitimate signals,
  just worth understanding accurately. A filtered-out match isn't
  permanently blocked — it's re-checked on the next run in case it becomes
  more predictable before kickoff.

## What's new since the first version

- **Widened to 10 leagues**: PL, PD, SA, BL1, FL1, CL, ELC, DED, PPL, BSA
  (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League,
  Championship, Eredivisie, Primeira Liga, Brazilian Série A) — all within
  football-data.org's free tier.
- **Runs 3x/day** (6am, 2pm, 10pm UTC) instead of once — confirmed safe
  after correcting an earlier mistake: their real rate limit is 50
  requests/minute, not 10 (that wrong number came from a competitor's
  comparison page, not football-data.org's own docs).
- **Deduplication**: each match is only ever alerted once, no matter how
  many times a day the bot runs. This required the workflow to commit a
  small state file (`alerted_matches.json`) back to the repo after each
  run — don't edit that file manually.
- **Confidence filter**: only alerts when the top predicted scoreline
  itself carries at least `MIN_TOP_SCORELINE_PROB` (10% by default) —
  filters out near-toss-up matches where probability is spread too thinly
  to be a meaningful call, surfacing more genuinely lopsided/predictable
  matchups instead.
- **Bug fixes from a full re-review**: guarded against a theoretical
  division-by-zero, and fixed a real data-truncation risk (the API caps
  responses at 100 items by default; a full season has up to 380 matches,
  so this now explicitly requests up to 500 to avoid silently incomplete
  training data later in a season).

## ⚠️ Read this before trusting any prediction

- **Even a well-calibrated model's top pick is usually right well under
  half the time.** Football is genuinely high-variance.
- **Tested thoroughly on synthetic data** — the Poisson math, shrinkage
  logic, confidence filter, and deduplication all have real passing tests.
  What's NOT tested is live football-data.org data quality — that needs
  your first real run.
- **Competition codes** (`PL`, `PD`, `SA`, `BL1`, `FL1`, `CL`, `ELC`,
  `DED`, `PPL`, `BSA`) are confirmed against football-data.org's own
  official coverage page — but worth a quick sanity check that your free
  account actually has access to all of them once you have a real key.
- **Early season = less reliable.** Shrinkage handles thin data
  conservatively, but more games played = more reliable predictions.

## Tennis — not included, here's why

Looked into it properly: correct-score IS a real, legitimate tennis
betting market (exact set score), and there's a well-established academic
model for it. But every live tennis data source found showed the same
"multiple branded sites, identical marketing language, no independent
verification" pattern that made SharpAPI and TheStatsAPI untrustworthy
earlier in this project. Parked rather than built on unverified ground —
revisit if you find a specific trusted provider.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`: a fresh Telegram bot, and a free API key from
**football-data.org**.

## Deployment

Same GitHub Actions pattern as your other bots — upload everything
including `.github/workflows/predict_scan.yml` AND `alerted_matches.json`
(the starter state file), add the 3 secrets (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `FOOTBALL_DATA_API_KEY`), test via **Run workflow**,
done. Runs 3x/day automatically after that (6am, 2pm, 10pm UTC).

**Important**: the workflow needs permission to commit back to your repo
(for the dedup state file) — this is already set in `predict_scan.yml`
(`permissions: contents: write`), nothing extra for you to configure.

## Config reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `COMPETITION_CODES` | PL,PD,SA,BL1,FL1,CL,ELC,DED,PPL,BSA | Which leagues to cover |
| `TOP_N_SCORELINES` | 5 | How many scorelines to show per match |
| `DAYS_AHEAD` | 3 | Only predict matches within this many days |
| `MIN_TOP_SCORELINE_PROB` | 0.10 | Only alert when the top pick is at least this concentrated |

