import os

FOOTBALL_TG_TOKEN   = os.getenv("FOOTBALL_TG_TOKEN", "")
FOOTBALL_TG_CHAT_ID = os.getenv("FOOTBALL_TG_CHAT_ID", "")
FOOTBALL_API_KEY    = os.getenv("FOOTBALL_API_KEY", "")

FOOTBALL_API_BASE   = "https://api.football-data.org/v4"
API_RATE_LIMIT_SEC  = 7        # free tier: 10 calls/min → 1 every 6s, use 7 for safety
STATE_FILE          = "football_bot/state.json"

# ── Signal schedule (UTC) ──────────────────────────────────────────────────
SIGNAL_HOUR         = 9
SIGNAL_MINUTE       = 0
RESULT_CHECK_START  = 17
RESULT_CHECK_HOUR   = 23

# ── Draw prediction weights ────────────────────────────────────────────────
W_HOME_DRAW    = 0.25
W_AWAY_DRAW    = 0.25
W_H2H_DRAW     = 0.20
W_BALANCE      = 0.15
W_LEAGUE       = 0.15

# ── Win prediction weights ─────────────────────────────────────────────────
W_WIN_FORM     = 0.30   # team's venue win rate
W_WIN_OPP      = 0.20   # opponent's venue loss rate
W_WIN_H2H      = 0.20   # H2H win rate
W_WIN_ATTACK   = 0.20   # attack strength advantage
W_WIN_LEAGUE   = 0.10   # league baseline

# ── Accumulator sizes ──────────────────────────────────────────────────────
ACCA_3_SIZE     = 3
ACCA_5_SIZE     = 5
ACCA_MIXED_SIZE = 15

# Minimum draw score to be included in draw acca pool
MIN_DRAW_SCORE  = 52
# Minimum score for mixed acca (any outcome type)
MIN_MIXED_SCORE = 48

# ── Leagues covered (free tier, high draw rate) ────────────────────────────
LEAGUES = {
    # ── Tier 1 — existing leagues ──────────────────────────────────────────
    "ELC": {"name": "Championship",      "country": "England 🏴󠁧󠁢󠁥󠁮󠁧󠁿",    "draw_rate": 0.30, "home_win": 0.44, "away_win": 0.26},
    "BL2": {"name": "2. Bundesliga",     "country": "Germany 🇩🇪",      "draw_rate": 0.28, "home_win": 0.43, "away_win": 0.29},
    "SA":  {"name": "Serie A",           "country": "Italy 🇮🇹",        "draw_rate": 0.27, "home_win": 0.44, "away_win": 0.29},
    "DED": {"name": "Eredivisie",        "country": "Netherlands 🇳🇱",  "draw_rate": 0.27, "home_win": 0.46, "away_win": 0.27},
    "PPL": {"name": "Primeira Liga",     "country": "Portugal 🇵🇹",     "draw_rate": 0.27, "home_win": 0.46, "away_win": 0.27},
    "FL1": {"name": "Ligue 1",           "country": "France 🇫🇷",       "draw_rate": 0.26, "home_win": 0.44, "away_win": 0.30},
    "PD":  {"name": "La Liga",           "country": "Spain 🇪🇸",        "draw_rate": 0.26, "home_win": 0.46, "away_win": 0.28},
    "BL1": {"name": "Bundesliga",        "country": "Germany 🇩🇪",      "draw_rate": 0.25, "home_win": 0.45, "away_win": 0.30},
    "PL":  {"name": "Premier League",    "country": "England 🏴󠁧󠁢󠁥󠁮󠁧󠁿",    "draw_rate": 0.25, "home_win": 0.45, "away_win": 0.30},
    "BSA": {"name": "Série A",           "country": "Brazil 🇧🇷",       "draw_rate": 0.26, "home_win": 0.44, "away_win": 0.30},
    # ── Tier 2 — high-draw additions (all via ESPN free API) ──────────────
    "SCO": {"name": "Scottish Prem",     "country": "Scotland 🏴󠁧󠁢󠁳󠁣󠁴󠁿",    "draw_rate": 0.28, "home_win": 0.43, "away_win": 0.29},
    "BEL": {"name": "Belgian Pro Lge",  "country": "Belgium 🇧🇪",       "draw_rate": 0.27, "home_win": 0.44, "away_win": 0.29},
    "SB":  {"name": "Serie B",           "country": "Italy 🇮🇹",        "draw_rate": 0.29, "home_win": 0.43, "away_win": 0.28},
    "SD":  {"name": "Segunda División",  "country": "Spain 🇪🇸",        "draw_rate": 0.28, "home_win": 0.44, "away_win": 0.28},
    "FL2": {"name": "Ligue 2",           "country": "France 🇫🇷",       "draw_rate": 0.28, "home_win": 0.43, "away_win": 0.29},
    "EL1": {"name": "League One",        "country": "England 🏴󠁧󠁢󠁥󠁮󠁧󠁿",    "draw_rate": 0.28, "home_win": 0.43, "away_win": 0.29},
    "TSL": {"name": "Süper Lig",         "country": "Turkey 🇹🇷",        "draw_rate": 0.26, "home_win": 0.46, "away_win": 0.28},
    "GSL": {"name": "Super League",      "country": "Greece 🇬🇷",        "draw_rate": 0.27, "home_win": 0.44, "away_win": 0.29},
}

MIN_FORM_GAMES  = 5
H2H_MIN_GAMES   = 3

# ── Flex betting — losses allowed per acca ─────────────────────────────────
# e.g. FLEX_ALLOWED[3] = 1  →  Acca-3 wins even if 1 game fails (need 2/3)
FLEX_ALLOWED = {
    3:  1,   # Acca-3:   need 2/3
    5:  2,   # Acca-5:   need 3/5
    15: 3,   # Mixed-15: need 12/15
}

# ── Mixed acca scoring — market baselines and diversity caps ────────────────
# Baseline = typical hit-rate for that market in covered leagues (0-100 scale)
# A pick must be well above its baseline to win best_pick for its fixture.
MARKET_BASELINES: dict[str, float] = {
    "draw":   27,   # ~26-30% average draw rate
    "home":   44,   # ~44% average home win rate
    "away":   28,   # ~28% average away win rate
    "over15": 72,   # ~70-75% Over 1.5 in top European leagues
    "over25": 48,   # ~48-52% Over 2.5
    "gg":     53,   # ~52-56% both teams to score
}

# Maximum slots per outcome type in the 15-pick mixed acca
MIXED_MAX_PER_OUTCOME: dict[str, int] = {
    "draw":   5,
    "home":   4,
    "away":   3,
    "over15": 3,
    "over25": 3,
    "gg":     3,
}
