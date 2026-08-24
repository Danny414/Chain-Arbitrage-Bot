"""
Draw + win + goals prediction model.
Scores each fixture 0-100 for draw, home win, away win,
over 1.5, over 2.5, and GG (both teams to score).
Returns the best pick (highest score) per fixture for mixed accas.
"""
import math
from football_bot.config import (
    W_HOME_DRAW, W_AWAY_DRAW, W_H2H_DRAW, W_BALANCE, W_LEAGUE,
    W_WIN_FORM, W_WIN_OPP, W_WIN_H2H, W_WIN_ATTACK, W_WIN_LEAGUE,
    MIN_FORM_GAMES, H2H_MIN_GAMES, LEAGUES, MARKET_BASELINES
)


# ── Shared helpers ──────────────────────────────────────────────────────────

def _avg_scored(matches: list[dict], team_id: int) -> float:
    goals, games = 0, 0
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        ft = m.get("score", {}).get("fullTime", {})
        if m.get("homeTeam", {}).get("id") == team_id:
            goals += ft.get("home", 0) or 0
        else:
            goals += ft.get("away", 0) or 0
        games += 1
    return goals / games if games > 0 else 1.0


def _team_draw_rate(matches: list[dict], team_id: int, venue: str) -> tuple[float, int]:
    relevant = [
        m for m in matches
        if m.get("status") == "FINISHED" and (
            (venue == "home" and m.get("homeTeam", {}).get("id") == team_id) or
            (venue == "away" and m.get("awayTeam", {}).get("id") == team_id)
        )
    ]
    if len(relevant) < MIN_FORM_GAMES:
        return 0.25, len(relevant)
    draws = sum(
        1 for m in relevant
        if (m.get("score", {}).get("fullTime", {}).get("home") ==
            m.get("score", {}).get("fullTime", {}).get("away"))
    )
    return draws / len(relevant), len(relevant)


def _team_win_rate(matches: list[dict], team_id: int, venue: str) -> tuple[float, int]:
    relevant = [
        m for m in matches
        if m.get("status") == "FINISHED" and (
            (venue == "home" and m.get("homeTeam", {}).get("id") == team_id) or
            (venue == "away" and m.get("awayTeam", {}).get("id") == team_id)
        )
    ]
    if len(relevant) < MIN_FORM_GAMES:
        return 0.40 if venue == "home" else 0.30, len(relevant)
    wins = 0
    for m in relevant:
        ft = m.get("score", {}).get("fullTime", {})
        h, a = ft.get("home"), ft.get("away")
        if h is None or a is None:
            continue
        if venue == "home" and h > a:
            wins += 1
        elif venue == "away" and a > h:
            wins += 1
    return wins / len(relevant), len(relevant)


def _h2h_draw_rate(h2h_matches: list[dict]) -> tuple[float, int]:
    finished = [m for m in h2h_matches if m.get("status") == "FINISHED"]
    if len(finished) < H2H_MIN_GAMES:
        return 0.25, len(finished)
    draws = sum(
        1 for m in finished
        if (m.get("score", {}).get("fullTime", {}).get("home") ==
            m.get("score", {}).get("fullTime", {}).get("away"))
    )
    return draws / len(finished), len(finished)


def _h2h_winner_rates(h2h_matches: list[dict], home_id: int, away_id: int) -> tuple[float, float, int]:
    """Returns (home_team_win_rate, away_team_win_rate, games) across all H2H matches."""
    finished = [m for m in h2h_matches if m.get("status") == "FINISHED"]
    if len(finished) < H2H_MIN_GAMES:
        return 0.40, 0.30, len(finished)
    home_wins = away_wins = 0
    for m in finished:
        ft = m.get("score", {}).get("fullTime", {})
        h, a = ft.get("home"), ft.get("away")
        if h is None or a is None:
            continue
        match_home = m.get("homeTeam", {}).get("id")
        match_away = m.get("awayTeam", {}).get("id")
        if h > a:
            if match_home == home_id:
                home_wins += 1
            elif match_home == away_id:
                away_wins += 1
        elif a > h:
            if match_away == home_id:
                home_wins += 1
            elif match_away == away_id:
                away_wins += 1
    n = len(finished)
    return home_wins / n, away_wins / n, n


def _competitive_balance(home_form: list[dict], away_form: list[dict],
                          home_id: int, away_id: int) -> float:
    def avg_conceded(matches, team_id):
        goals, games = 0, 0
        for m in matches:
            if m.get("status") != "FINISHED":
                continue
            ft = m.get("score", {}).get("fullTime", {})
            if m.get("homeTeam", {}).get("id") == team_id:
                goals += ft.get("away", 0) or 0
            else:
                goals += ft.get("home", 0) or 0
            games += 1
        return goals / games if games > 0 else 1.0

    home_attack  = _avg_scored(home_form, home_id)
    away_attack  = _avg_scored(away_form, away_id)
    home_defence = avg_conceded(home_form, home_id)
    away_defence = avg_conceded(away_form, away_id)

    attack_diff   = abs(home_attack - away_attack) / max(home_attack, away_attack, 0.5)
    defence_score = 1 / (1 + (home_defence + away_defence) / 2)
    balance = (1 - attack_diff) * 0.6 + defence_score * 0.4
    return max(0.0, min(1.0, balance))


# ── Goals markets — venue-aware Poisson model ───────────────────────────────

def _avg_scored_venue(matches: list[dict], team_id: int, venue: str) -> float:
    """Goals per game scored by team in a specific venue (home or away)."""
    goals, games = 0, 0
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        ft = m.get("score", {}).get("fullTime", {})
        if venue == "home" and m.get("homeTeam", {}).get("id") == team_id:
            goals += ft.get("home", 0) or 0
            games += 1
        elif venue == "away" and m.get("awayTeam", {}).get("id") == team_id:
            goals += ft.get("away", 0) or 0
            games += 1
    # Need ≥3 venue-specific matches; otherwise fall back to overall average
    return goals / games if games >= 3 else _avg_scored(matches, team_id)


def _avg_conceded_venue(matches: list[dict], team_id: int, venue: str) -> float:
    """Goals per game conceded by team in a specific venue (home or away)."""
    goals, games = 0, 0
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        ft = m.get("score", {}).get("fullTime", {})
        if venue == "home" and m.get("homeTeam", {}).get("id") == team_id:
            goals += ft.get("away", 0) or 0
            games += 1
        elif venue == "away" and m.get("awayTeam", {}).get("id") == team_id:
            goals += ft.get("home", 0) or 0
            games += 1
    return goals / games if games >= 3 else (goals / games if games > 0 else 1.2)


def _poisson_goals_scores(
    home_form: list, away_form: list, home_id: int, away_id: int
) -> tuple[float, float, float]:
    """
    Estimate Over 1.5, Over 2.5 and GG probabilities (0-100 scale).
    Uses venue-specific attack/defence averages for accuracy:
      - home team attack = goals scored AT HOME
      - away team attack = goals scored AWAY
      - defensive weakness from the opponent's concession rate at that venue
    """
    lam_h_att = _avg_scored_venue(home_form, home_id, "home")    # home team scores at home
    lam_a_att = _avg_scored_venue(away_form, away_id, "away")    # away team scores on road
    lam_h_def = _avg_conceded_venue(home_form, home_id, "home")  # home team concedes at home
    lam_a_def = _avg_conceded_venue(away_form, away_id, "away")  # away team concedes on road

    # Expected goals: blend team's own attack with opponent's defensive weakness
    lam_h = (lam_h_att + lam_a_def) / 2
    lam_a = (lam_a_att + lam_h_def) / 2
    lam   = lam_h + lam_a

    # Poisson mass function
    p0 = math.exp(-lam)
    p1 = lam * p0
    p2 = (lam ** 2) * p0 / 2

    over15 = max(0.0, min(1.0, 1 - p0 - p1))
    over25 = max(0.0, min(1.0, 1 - p0 - p1 - p2))
    gg     = (1 - math.exp(-lam_h)) * (1 - math.exp(-lam_a))

    return round(over15 * 100, 1), round(over25 * 100, 1), round(gg * 100, 1)


# ── Main scoring function ───────────────────────────────────────────────────

def score_fixture(fixture: dict, home_form: list, away_form: list, h2h: list) -> dict:
    """
    Score a fixture for draw, home win, and away win likelihood.
    Returns the fixture enriched with all scores and the best pick for mixed acca.
    """
    home_id = fixture["home_id"]
    away_id = fixture["away_id"]
    league  = LEAGUES.get(fixture["league_code"], {})
    league_draw_rate = fixture["league_draw_rate"]
    league_home_rate = league.get("home_win", 0.44)
    league_away_rate = league.get("away_win", 0.29)

    # ── Draw score ──────────────────────────────────────────────────────────
    home_draw_rate, home_games = _team_draw_rate(home_form, home_id, "home")
    away_draw_rate, away_games = _team_draw_rate(away_form, away_id, "away")
    h2h_draw_rate,  h2h_games  = _h2h_draw_rate(h2h)
    balance    = _competitive_balance(home_form, away_form, home_id, away_id)
    league_fac = league_draw_rate / 0.30

    draw_raw = (
        home_draw_rate * W_HOME_DRAW +
        away_draw_rate * W_AWAY_DRAW +
        h2h_draw_rate  * W_H2H_DRAW +
        balance        * W_BALANCE +
        league_fac     * W_LEAGUE
    )
    draw_score = round(min(draw_raw * 100, 99), 1)

    # ── Home win score ──────────────────────────────────────────────────────
    home_win_rate, _ = _team_win_rate(home_form, home_id, "home")
    away_win_rate, _ = _team_win_rate(away_form, away_id, "away")
    home_h2h_rate, away_h2h_rate, _ = _h2h_winner_rates(h2h, home_id, away_id)

    home_attack = _avg_scored(home_form, home_id)
    away_attack = _avg_scored(away_form, away_id)
    max_atk = max(home_attack, away_attack, 0.5)
    home_atk_adv = max(0.0, (home_attack - away_attack) / max_atk)
    away_atk_adv = max(0.0, (away_attack - home_attack) / max_atk)

    home_win_raw = (
        home_win_rate        * W_WIN_FORM +
        (1 - away_win_rate)  * W_WIN_OPP +
        home_h2h_rate        * W_WIN_H2H +
        home_atk_adv         * W_WIN_ATTACK +
        league_home_rate     * W_WIN_LEAGUE
    )
    home_win_score = round(min(home_win_raw * 100, 99), 1)

    # ── Away win score ──────────────────────────────────────────────────────
    away_win_raw = (
        away_win_rate        * W_WIN_FORM +
        (1 - home_win_rate)  * W_WIN_OPP +
        away_h2h_rate        * W_WIN_H2H +
        away_atk_adv         * W_WIN_ATTACK +
        league_away_rate     * W_WIN_LEAGUE
    )
    away_win_score = round(min(away_win_raw * 100, 99), 1)

    # ── Goals markets ────────────────────────────────────────────────────────
    over15_score, over25_score, gg_score = _poisson_goals_scores(
        home_form, away_form, home_id, away_id
    )

    # ── Best pick for mixed acca — normalized so all 6 markets compete fairly ─
    # Raw scores are on different scales: Over 1.5 is ~72% in any league so
    # a raw 80 is barely above average, while a raw 80 draw score is excellent.
    # Normalize each market relative to its typical baseline before comparing.
    scores = {
        "draw":   draw_score,
        "home":   home_win_score,
        "away":   away_win_score,
        "over15": over15_score,
        "over25": over25_score,
        "gg":     gg_score,
    }
    def _norm(score: float, market: str) -> float:
        b = MARKET_BASELINES[market]
        return max(0.0, (score - b) / (100.0 - b) * 100.0)

    normalized = {k: _norm(v, k) for k, v in scores.items()}
    best_pick  = max(normalized, key=normalized.get)
    best_score = scores[best_pick]   # keep raw score for display / odds

    # ── Confidence labels ───────────────────────────────────────────────────
    def conf_label(s):
        if s >= 75: return "🟢 HIGH"
        if s >= 60: return "🟡 MED"
        return "🔴 LOW"

    return {
        **fixture,
        "draw_score":      draw_score,
        "home_win_score":  home_win_score,
        "away_win_score":  away_win_score,
        "over15_score":    over15_score,
        "over25_score":    over25_score,
        "gg_score":        gg_score,
        "best_pick":       best_pick,
        "best_score":      best_score,
        "confidence":      conf_label(draw_score),
        "home_draw_pct":   round(home_draw_rate * 100, 1),
        "away_draw_pct":   round(away_draw_rate * 100, 1),
        "h2h_draw_pct":    round(h2h_draw_rate  * 100, 1),
        "home_win_pct":    round(home_win_rate   * 100, 1),
        "away_win_pct":    round(away_win_rate   * 100, 1),
        "balance_score":   round(balance * 100, 1),
        "home_form_games": home_games,
        "away_form_games": away_games,
        "h2h_games":       h2h_games,
    }
