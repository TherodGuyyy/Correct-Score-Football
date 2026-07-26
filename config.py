import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")

# football-data.org's free tier covers 12 competitions total; these 10 are
# the continuously-running leagues (excluding World Cup/Euros, which are
# periodic tournaments — mostly no matches most of the year, easy to add
# back in during an actual tournament window).
COMPETITION_CODES = os.getenv(
    "COMPETITION_CODES", "PL,PD,SA,BL1,FL1,CL,ELC,DED,PPL,BSA"
).split(",")

# How many top scorelines to show per match.
TOP_N_SCORELINES = int(os.getenv("TOP_N_SCORELINES", "5"))

# Only alert on upcoming matches within this many days (no point predicting
# something 2 months out with today's form data).
DAYS_AHEAD = int(os.getenv("DAYS_AHEAD", "3"))

# Only alert when the TOP predicted scoreline itself carries at least this
# much probability — a rough proxy for "this match is genuinely more
# predictable" (a lopsided favorite vs underdog) rather than a near-toss-up
# where probability is spread thinly across many plausible scorelines.
# Typical top-scoreline probabilities run roughly 7-9% for even matchups
# and can reach into the mid-teens for lopsided ones — 10% is a reasonable
# starting filter; lower it to see more matches, raise it to see fewer but
# more confident ones.
MIN_TOP_SCORELINE_PROB = float(os.getenv("MIN_TOP_SCORELINE_PROB", "0.10"))

RUN_ONCE = os.getenv("RUN_ONCE", "false").strip().lower() == "true"
