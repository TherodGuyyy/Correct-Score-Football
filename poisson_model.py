"""
Poisson-based correct-score prediction model.

THIS IS THE SAME BASIC APPROACH used by real sports analytics models (a
simplified version of what's sometimes called the Dixon-Coles model). Here's
the actual logic, in plain terms:

1. Every team has an "attack strength" (how many more/fewer goals they
   score than a league-average team) and "defense strength" (how many
   more/fewer goals they concede than a league-average team) — tracked
   separately for home and away, since home advantage is real.

2. For an upcoming match, combine the home team's attack strength with the
   away team's defense weakness (and vice versa) to get an expected goal
   count for each side — this is the Poisson "λ" (lambda) parameter.

3. Goals in football follow a Poisson distribution reasonably well (rare,
   roughly-independent events over 90 minutes) — so given an expected goal
   count, you can calculate the probability of ANY exact scoreline (0-0,
   2-1, 3-3, whatever), not just win/draw/loss.

HONEST LIMITATIONS:
- This assumes home and away goals are independent, which isn't quite true
  in reality (there's a small real correlation, especially in low-scoring
  games) — the full Dixon-Coles model adds a correction for this. This is
  the simpler, still-legitimate version.
- Even a well-calibrated model's single "most likely" scoreline is usually
  only right 15-25% of the time — football is genuinely high-variance. This
  gives you a full probability breakdown, not a confident prediction.
- Early in a season, there's less data per team — this model shrinks
  thin-data teams toward the league average (see SHRINKAGE_GAMES below)
  rather than overreacting to 1-2 games, but it's still less reliable
  early on than after 10+ games per team.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

# How many "average team" games worth of prior belief to blend in before
# trusting a team's own observed rate. Higher = more conservative/stable
# early in a season, slower to react to a team's actual current form.
SHRINKAGE_GAMES = 6

MAX_GOALS_CONSIDERED = 6  # scorelines beyond 6-6 are negligible probability


@dataclass
class TeamStats:
    team: str
    games_home: int = 0
    games_away: int = 0
    goals_scored_home: int = 0
    goals_conceded_home: int = 0
    goals_scored_away: int = 0
    goals_conceded_away: int = 0


@dataclass
class LeagueAverages:
    avg_home_goals: float
    avg_away_goals: float


def compute_league_averages(finished_matches: list[dict]) -> LeagueAverages:
    """
    finished_matches: [{"home_team": str, "away_team": str,
                         "home_goals": int, "away_goals": int}, ...]
    """
    if not finished_matches:
        # Sensible football-wide fallback if we have zero data yet —
        # roughly matches typical league-wide scoring rates.
        return LeagueAverages(avg_home_goals=1.5, avg_away_goals=1.2)

    total_home = sum(m["home_goals"] for m in finished_matches)
    total_away = sum(m["away_goals"] for m in finished_matches)
    n = len(finished_matches)
    return LeagueAverages(avg_home_goals=total_home / n, avg_away_goals=total_away / n)


def compute_team_stats(finished_matches: list[dict]) -> dict[str, TeamStats]:
    stats: dict[str, TeamStats] = {}

    def get(team: str) -> TeamStats:
        if team not in stats:
            stats[team] = TeamStats(team=team)
        return stats[team]

    for m in finished_matches:
        home = get(m["home_team"])
        away = get(m["away_team"])
        home.games_home += 1
        home.goals_scored_home += m["home_goals"]
        home.goals_conceded_home += m["away_goals"]
        away.games_away += 1
        away.goals_scored_away += m["away_goals"]
        away.goals_conceded_away += m["home_goals"]

    return stats


def _shrunk_rate(observed_total: int, observed_games: int, league_avg: float,
                  shrinkage_games: int = SHRINKAGE_GAMES) -> float:
    """
    Blends a team's own observed goals-per-game with the league average,
    weighted by how many games they've actually played. With 0 games, this
    returns exactly the league average (no data = no opinion). With many
    games, it converges toward the team's own true observed rate.
    """
    # Treat it as: (observed goals + shrinkage_games * league_avg) /
    #              (observed games + shrinkage_games)
    # — equivalent to starting every team with `shrinkage_games` worth of
    # "phantom" league-average games before their real games count.
    return (observed_total + shrinkage_games * league_avg) / (observed_games + shrinkage_games)


def get_team_strengths(
    team: str,
    team_stats: dict[str, TeamStats],
    league_avgs: LeagueAverages,
) -> dict:
    """
    Returns shrunk (regularized) per-team rates, safe to call even for a
    team with zero games recorded yet (returns pure league-average rates).
    """
    s = team_stats.get(team, TeamStats(team=team))
    return {
        "attack_home": _shrunk_rate(s.goals_scored_home, s.games_home, league_avgs.avg_home_goals),
        "defense_home": _shrunk_rate(s.goals_conceded_home, s.games_home, league_avgs.avg_away_goals),
        "attack_away": _shrunk_rate(s.goals_scored_away, s.games_away, league_avgs.avg_away_goals),
        "defense_away": _shrunk_rate(s.goals_conceded_away, s.games_away, league_avgs.avg_home_goals),
    }


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        lam = 0.01  # guard against a degenerate zero expected-goals case
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def predict_scoreline_matrix(
    home_team: str,
    away_team: str,
    team_stats: dict[str, TeamStats],
    league_avgs: LeagueAverages,
    max_goals: int = MAX_GOALS_CONSIDERED,
) -> dict[tuple[int, int], float]:
    """
    Returns a probability for every (home_goals, away_goals) combination
    from (0,0) up to (max_goals, max_goals). Probabilities sum to ~1.0
    across the whole grid (not exactly 1.0, since we cut off at max_goals —
    the tail beyond that is genuinely negligible).
    """
    home_strengths = get_team_strengths(home_team, team_stats, league_avgs)
    away_strengths = get_team_strengths(away_team, team_stats, league_avgs)

    # Defensive guard: league averages should never realistically be exactly
    # zero with real football data, but avoid a crash if they somehow were
    # (e.g. a data quality issue upstream) rather than raising ZeroDivisionError.
    safe_avg_home = league_avgs.avg_home_goals if league_avgs.avg_home_goals > 0 else 1.5
    safe_avg_away = league_avgs.avg_away_goals if league_avgs.avg_away_goals > 0 else 1.2

    # Expected goals: home attack vs away defense, and vice versa —
    # normalized against league averages so a "1.0" strength means exactly
    # league-average.
    lambda_home = (
        (home_strengths["attack_home"] / safe_avg_home)
        * (away_strengths["defense_away"] / safe_avg_home)
        * safe_avg_home
    )
    lambda_away = (
        (away_strengths["attack_away"] / safe_avg_away)
        * (home_strengths["defense_home"] / safe_avg_away)
        * safe_avg_away
    )

    matrix = {}
    for h in range(max_goals + 1):
        p_h = _poisson_pmf(h, lambda_home)
        for a in range(max_goals + 1):
            p_a = _poisson_pmf(a, lambda_away)
            matrix[(h, a)] = p_h * p_a

    return matrix


def get_top_scorelines(matrix: dict[tuple[int, int], float], n: int = 5) -> list[tuple[int, int, float]]:
    ranked = sorted(matrix.items(), key=lambda kv: kv[1], reverse=True)
    return [(h, a, prob) for (h, a), prob in ranked[:n]]


def outcome_probabilities(matrix: dict[tuple[int, int], float]) -> dict[str, float]:
    """Collapses the full scoreline grid into simple home/draw/away totals —
    useful as a sanity check against what bookmakers imply."""
    home_win = sum(p for (h, a), p in matrix.items() if h > a)
    draw = sum(p for (h, a), p in matrix.items() if h == a)
    away_win = sum(p for (h, a), p in matrix.items() if h < a)
    return {"home": home_win, "draw": draw, "away": away_win}
