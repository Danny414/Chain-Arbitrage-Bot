"""
Paper trading engine for the Football Draw Bot.
Simulates ₦1,000 bets on each of the 4 accumulators per match day.
Odds are estimated from the model's own confidence scores.
"""

STAKE_PER_ACCA = 1_000   # Nigerian Naira per accumulator
CURRENCY       = "₦"


# ── Odds estimation ─────────────────────────────────────────────────────────
# Maps model score (0-100) to realistic bookmaker-style decimal odds.
# These mimic typical European sportsbook prices.

def _draw_odds(score: float) -> float:
    """Draw score 80 → ~2.85 | 65 → ~3.20 | 50 → ~3.70 | 40 → ~4.10"""
    return round(max(2.70, min(4.50, 5.20 - score / 100 * 2.80)), 2)

def _home_odds(score: float) -> float:
    """Home win score 80 → ~1.75 | 65 → ~2.15 | 50 → ~2.65"""
    return round(max(1.55, min(4.00, 4.30 - score / 100 * 3.00)), 2)

def _away_odds(score: float) -> float:
    """Away win score 80 → ~2.10 | 65 → ~2.85 | 50 → ~3.65"""
    return round(max(2.00, min(5.50, 5.80 - score / 100 * 4.00)), 2)

def _over15_odds(score: float) -> float:
    """Over 1.5 score 80 → ~1.25 | 60 → ~1.40 | 40 → ~1.60"""
    return round(max(1.15, min(1.75, 2.05 - score / 100 * 1.10)), 2)

def _over25_odds(score: float) -> float:
    """Over 2.5 score 80 → ~1.65 | 60 → ~1.90 | 40 → ~2.20"""
    return round(max(1.55, min(2.45, 2.90 - score / 100 * 1.60)), 2)

def _gg_odds(score: float) -> float:
    """GG/BTTS score 80 → ~1.60 | 60 → ~1.85 | 40 → ~2.10"""
    return round(max(1.50, min(2.25, 2.70 - score / 100 * 1.40)), 2)

def pick_single_odds(pick: dict) -> float:
    outcome = pick.get("best_pick", "draw")
    if outcome == "draw":   return _draw_odds(pick.get("draw_score", 50))
    if outcome == "home":   return _home_odds(pick.get("home_win_score", 50))
    if outcome == "away":   return _away_odds(pick.get("away_win_score", 50))
    if outcome == "over15": return _over15_odds(pick.get("over15_score", 60))
    if outcome == "over25": return _over25_odds(pick.get("over25_score", 50))
    if outcome == "gg":     return _gg_odds(pick.get("gg_score", 55))
    return _away_odds(50)

def draw_single_odds(pick: dict) -> float:
    return _draw_odds(pick.get("draw_score", 50))

def acca_odds(picks: list[dict], draw_only: bool = True) -> float:
    total = 1.0
    for p in picks:
        total *= draw_single_odds(p) if draw_only else pick_single_odds(p)
    return round(total, 2)


# ── Bet placement ───────────────────────────────────────────────────────────

def place_bets(date: str, acca3: list, acca5: list,
               _acca10_unused: list, mixed15: list) -> dict:
    """
    Build paper bet records for today's 3 accumulators.
    Returns a bet_record dict to be saved in state.
    (_acca10_unused kept for backward-compatible call sites.)
    """
    def make_bet(picks: list, draw_only: bool = True) -> dict:
        odds    = acca_odds(picks, draw_only=draw_only)
        pot_win = round(STAKE_PER_ACCA * odds)
        return {
            "stake":         STAKE_PER_ACCA,
            "odds":          odds,
            "potential_win": pot_win,
            "settled":       False,
            "won":           None,
            "payout":        0,
            "legs":          len(picks),
        }

    return {
        "date":         date,
        "acca3":        make_bet(acca3,   draw_only=True),
        "acca5":        make_bet(acca5,   draw_only=True),
        "mixed":        make_bet(mixed15, draw_only=False),
        "total_staked": STAKE_PER_ACCA * 3,
    }


# ── Bet settlement ──────────────────────────────────────────────────────────

def settle_bets(bet_record: dict, grade: dict) -> tuple[dict, int]:
    """
    Settle all 4 bets against graded results.
    Supports flex wins: pays out on winning legs' individual odds only.
    Returns (updated_bet_record, net_day_pnl).
    """
    total_staked   = bet_record.get("total_staked", STAKE_PER_ACCA * 4)
    total_returned = 0

    def _flex_payout(result: dict, draw_only: bool) -> int:
        """Product of each winning pick's single-leg odds × stake."""
        winning = [
            p for p in result.get("picks", [])
            if (p.get("is_draw") if draw_only else p.get("correct"))
        ]
        flex_odds = 1.0
        for p in winning:
            flex_odds *= draw_single_odds(p) if draw_only else pick_single_odds(p)
        return round(STAKE_PER_ACCA * flex_odds)

    def _settle(key: str, result_key: str, draw_only: bool = True):
        bet    = bet_record.get(key, {})
        result = grade.get(result_key) or grade.get(key, {})
        if not bet or bet.get("settled"):
            return
        full_win = result.get("win", False)
        flex_win = result.get("flex_win", False)
        if full_win:
            payout = round(bet["stake"] * bet["odds"])
        elif flex_win:
            payout = _flex_payout(result, draw_only)
        else:
            payout = 0
        bet["settled"]  = True
        bet["won"]      = full_win or flex_win
        bet["full_win"] = full_win
        bet["flex_win"] = flex_win
        bet["payout"]   = payout
        bet_record[key] = bet
        return payout

    total_returned += _settle("acca3", "acca3", draw_only=True)  or 0
    total_returned += _settle("acca5", "acca5", draw_only=True)  or 0
    total_returned += _settle("mixed", "mixed", draw_only=False) or 0

    bet_record["total_returned"] = total_returned
    bet_record["net_pnl"]        = total_returned - total_staked
    return bet_record, total_returned - total_staked


# ── Formatting helpers ──────────────────────────────────────────────────────

def fmt_stake(amount: int) -> str:
    return f"{CURRENCY}{amount:,.0f}"

def fmt_pnl(amount: int) -> str:
    sign = "+" if amount >= 0 else ""
    return f"{sign}{CURRENCY}{amount:,.0f}"

def pnl_icon(amount: int) -> str:
    if amount > 0:   return "🟢"
    if amount == 0:  return "🟡"
    return "🔴"
