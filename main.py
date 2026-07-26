"""
Correct-score prediction bot — main entry point.

For each competition:
  1. Fetch this season's finished matches (the training data)
  2. Fit the Poisson model (team attack/defense strengths, with shrinkage
     for teams with few games played so far)
  3. Fetch upcoming matches within DAYS_AHEAD
  4. Predict the top-N most likely scorelines for each, plus a home/draw/
     away breakdown as a sanity-check summary
  5. Send each as a Telegram message — but only ONCE per match, even
     though this runs multiple times a day. Since GitHub Actions starts a
     fresh container every run (no memory carries over), "already
     alerted" tracking is saved to a small JSON file that the workflow
     commits back to the repo after each run — see
     .github/workflows/predict_scan.yml for the commit-back step.

Run with: python main.py
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

import config
from footballdata_source import FootballDataSource
from poisson_model import (
    compute_league_averages, compute_team_stats,
    predict_scoreline_matrix, get_top_scorelines, outcome_probabilities,
)
from telegram_alerts import send_prediction

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

ALERTED_STATE_PATH = Path(__file__).parent / "alerted_matches.json"


def _load_alerted_state() -> dict:
    if ALERTED_STATE_PATH.exists():
        try:
            return json.loads(ALERTED_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Couldn't read alerted_matches.json (%s) — starting fresh.", e)
    return {}


def _save_alerted_state(state: dict) -> None:
    ALERTED_STATE_PATH.write_text(json.dumps(state, indent=2))


def _prune_old_entries(state: dict, max_age_days: int = 14) -> dict:
    """Drop match IDs whose kickoff was more than max_age_days ago, so this
    file doesn't grow forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    pruned = {}
    for match_id, alerted_at_iso in state.items():
        try:
            alerted_at = datetime.fromisoformat(alerted_at_iso)
            if alerted_at >= cutoff:
                pruned[match_id] = alerted_at_iso
        except ValueError:
            continue  # malformed entry, drop it
    return pruned



def _within_days_ahead(utc_date_str: str, days_ahead: int) -> bool:
    try:
        match_time = datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    now = datetime.now(timezone.utc)
    return now <= match_time <= now + timedelta(days=days_ahead)


def process_competition(source: FootballDataSource, code: str, alerted_state: dict) -> int:
    try:
        finished = source.get_finished_matches(code)
    except Exception as e:
        log.error("Failed to fetch finished matches for %s: %s", code, e)
        return 0

    if len(finished) < 10:
        log.warning(
            "Only %d finished matches so far for %s — predictions will lean "
            "heavily on league averages rather than real team form. Still "
            "safe (shrinkage handles this), just less sharp early in a season.",
            len(finished), code,
        )

    league_avgs = compute_league_averages(finished)
    team_stats = compute_team_stats(finished)

    try:
        upcoming = source.get_upcoming_matches(code)
    except Exception as e:
        log.error("Failed to fetch upcoming matches for %s: %s", code, e)
        return 0

    relevant = [m for m in upcoming if _within_days_ahead(m["utc_date"], config.DAYS_AHEAD)]
    log.info("%s: %d finished matches used for fitting, %d upcoming matches in window",
              code, len(finished), len(relevant))

    sent = 0
    for match in relevant:
        match_key = f"{code}_{match['match_id']}"
        if match_key in alerted_state:
            log.info("Already alerted for %s vs %s — skipping (sent on an earlier run today/this week)",
                      match["home_team"], match["away_team"])
            continue

        matrix = predict_scoreline_matrix(match["home_team"], match["away_team"], team_stats, league_avgs)
        top = get_top_scorelines(matrix, n=config.TOP_N_SCORELINES)
        outcomes = outcome_probabilities(matrix)

        if top[0][2] < config.MIN_TOP_SCORELINE_PROB:
            log.info(
                "%s vs %s -> top pick %d-%d only %.1f%% (below %.0f%% confidence "
                "threshold) — skipping for now, too close to a toss-up. Will "
                "re-check on the next run in case it becomes more predictable "
                "before kickoff.",
                match["home_team"], match["away_team"], top[0][0], top[0][1],
                top[0][2] * 100, config.MIN_TOP_SCORELINE_PROB * 100,
            )
            continue

        log.info("%s vs %s -> top pick %d-%d (%.1f%%)",
                  match["home_team"], match["away_team"], top[0][0], top[0][1], top[0][2] * 100)

        if send_prediction(match["home_team"], match["away_team"], top, outcomes):
            alerted_state[match_key] = datetime.now(timezone.utc).isoformat()
            sent += 1

    return sent


def main():
    if not config.FOOTBALL_DATA_API_KEY:
        raise SystemExit("FOOTBALL_DATA_API_KEY is not set — get a free key from football-data.org")

    source = FootballDataSource(config.FOOTBALL_DATA_API_KEY)
    alerted_state = _prune_old_entries(_load_alerted_state())

    total_sent = 0
    for code in config.COMPETITION_CODES:
        code = code.strip()
        if not code:
            continue
        total_sent += process_competition(source, code, alerted_state)

    _save_alerted_state(alerted_state)
    log.info("Done. Sent %d new prediction(s) this run.", total_sent)


if __name__ == "__main__":
    main()
