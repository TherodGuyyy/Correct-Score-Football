"""
Wrapper for football-data.org's v4 API. Built against their official,
well-documented API (running since 2013, genuinely established) — auth via
X-Auth-Token header, base URL https://api.football-data.org/v4.

Free tier: 12 major competitions, 10 requests/minute, current-season data
only (no multi-season history) — the poisson_model.py shrinkage logic is
specifically designed to handle that last limitation honestly.
"""

import logging
import time
import requests

log = logging.getLogger("footballdata_source")

BASE_URL = "https://api.football-data.org/v4"

# CONFIRMED from football-data.org's own official documentation (not a
# third party's claim): registered clients get 10 requests/minute. Pacing
# every call at this interval guarantees we never exceed that, regardless
# of how many competitions are configured or how fast the network responds.
MIN_SECONDS_BETWEEN_CALLS = 6.5  # 60/10 = 6.0s minimum; 6.5s for safety margin


class FootballDataSource:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("FOOTBALL_DATA_API_KEY is not set.")
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": api_key})
        self._last_call_time: float = 0.0

    def _pace_request(self) -> None:
        elapsed = time.time() - self._last_call_time
        if elapsed < MIN_SECONDS_BETWEEN_CALLS:
            time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
        self._last_call_time = time.time()

    def _get(self, path: str, params: dict = None) -> dict:
        self._pace_request()
        resp = self.session.get(f"{BASE_URL}{path}", params=params or {}, timeout=15)
        if resp.status_code == 429:
            # Free tier is rate-limited to 10 req/min — back off and retry
            # once rather than failing the whole run over a brief limit hit.
            log.warning("Rate limited, waiting 60s and retrying once...")
            time.sleep(60)
            self._last_call_time = time.time()
            resp = self.session.get(f"{BASE_URL}{path}", params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _warn_if_truncated(self, data: dict, competition_code: str) -> None:
        """
        Defensive check: even with limit=500 requested, if the API's own
        resultSet.count reports more matches exist than we actually
        received, warn loudly rather than silently using incomplete data.
        """
        result_set = data.get("resultSet", {})
        count = result_set.get("count")
        received = len(data.get("matches", []))
        if count is not None and received < count:
            log.warning(
                "%s: API reports %d total matches but only %d were returned — "
                "data may be truncated. Consider raising the limit further.",
                competition_code, count, received,
            )

    def get_finished_matches(self, competition_code: str) -> list[dict]:
        """
        Returns finished matches for the current season of a competition,
        converted into the shape poisson_model.py expects:
        [{"home_team": str, "away_team": str, "home_goals": int, "away_goals": int}]

        NOTE: the API defaults to a 100-item limit per request. A full
        season can have up to 380 matches (20-team league), so late in a
        season the default would silently truncate the training data
        without any error — explicitly requesting a higher limit avoids
        that.
        """
        data = self._get(
            f"/competitions/{competition_code}/matches",
            params={"status": "FINISHED", "limit": 500},
        )
        self._warn_if_truncated(data, competition_code)

        results = []
        for m in data.get("matches", []):
            score = m.get("score", {}).get("fullTime", {})
            home_goals, away_goals = score.get("home"), score.get("away")
            if home_goals is None or away_goals is None:
                log.warning("Finished match missing a final score, skipping: match id %s", m.get("id"))
                continue
            home_team = m.get("homeTeam", {}).get("name")
            away_team = m.get("awayTeam", {}).get("name")
            if not home_team or not away_team:
                log.warning("Match missing team name, skipping: match id %s", m.get("id"))
                continue
            results.append({
                "home_team": home_team,
                "away_team": away_team,
                "home_goals": home_goals,
                "away_goals": away_goals,
            })
        return results

    def get_upcoming_matches(self, competition_code: str) -> list[dict]:
        """
        Returns scheduled (not yet played) matches for a competition.
        [{"home_team": str, "away_team": str, "utc_date": str, "match_id": int}]
        """
        data = self._get(
            f"/competitions/{competition_code}/matches",
            params={"status": "SCHEDULED", "limit": 500},
        )
        self._warn_if_truncated(data, competition_code)

        results = []
        for m in data.get("matches", []):
            home_team = m.get("homeTeam", {}).get("name")
            away_team = m.get("awayTeam", {}).get("name")
            if not home_team or not away_team:
                continue
            results.append({
                "home_team": home_team,
                "away_team": away_team,
                "utc_date": m.get("utcDate"),
                "match_id": m.get("id"),
            })
        return results
