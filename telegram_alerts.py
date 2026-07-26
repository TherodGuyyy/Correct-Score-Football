import logging
import requests

import config

log = logging.getLogger("telegram_alerts")


def _format_message(home_team: str, away_team: str, top_scorelines: list, outcomes: dict) -> str:
    lines = [
        f"⚽ {home_team} vs {away_team}",
        "",
        f"Outcome odds: Home {outcomes['home']*100:.0f}% · "
        f"Draw {outcomes['draw']*100:.0f}% · Away {outcomes['away']*100:.0f}%",
        "",
        "Most likely scorelines:",
    ]
    for h, a, p in top_scorelines:
        lines.append(f"  {h}-{a}  ({p*100:.1f}%)")
    lines.append("")
    lines.append("⚠️ Statistical estimate, not a guarantee — even the top "
                  "pick is usually right well under half the time. Football "
                  "is genuinely high-variance.")
    return "\n".join(lines)


def send_prediction(home_team: str, away_team: str, top_scorelines: list, outcomes: dict) -> bool:
    message = _format_message(home_team, away_team, top_scorelines, outcomes)
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error("Telegram not configured — would have sent:\n%s", message)
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": config.TELEGRAM_CHAT_ID, "text": message}, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error("Failed to send Telegram alert: %s", e)
        return False
