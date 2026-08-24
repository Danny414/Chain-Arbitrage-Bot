"""
Signal builder — produces 3 accumulator types from today's scored fixtures:
  acca3   — top 3 draw picks
  acca5   — top 5 draw picks
  mixed15 — top 15 picks by best outcome (draw/home/away/over1.5/over2.5/gg)
"""
from football_bot.config import (
    ACCA_3_SIZE, ACCA_5_SIZE, ACCA_MIXED_SIZE,
    MIN_DRAW_SCORE, MIN_MIXED_SCORE,
    MARKET_BASELINES, MIXED_MAX_PER_OUTCOME,
)
from football_bot.analyzer import score_fixture
from football_bot import fetcher
import asyncio


_OUTCOME_SCORE_KEYS = {
    "draw":   "draw_score",
    "home":   "home_win_score",
    "away":   "away_win_score",
    "over15": "over15_score",
    "over25": "over25_score",
    "gg":     "gg_score",
}


def _build_mixed_diverse(scored: list[dict], size: int, min_score: float) -> list[dict]:
    """
    Build a diverse mixed acca from all scored fixtures.

    Algorithm:
    1. For every fixture rank its 6 outcomes by *normalized* score
       (raw score minus market baseline, so all markets compete fairly).
    2. Sort fixtures by their best normalized score (strongest picks first).
    3. Greedily assign each fixture the best outcome not yet at its cap.
    4. If not enough picks above min_score, retry with threshold=0.
    """
    def _norm(score: float, market: str) -> float:
        b = MARKET_BASELINES[market]
        return max(0.0, (score - b) / (100.0 - b) * 100.0)

    # Pre-rank each fixture's outcomes by normalized score
    fixture_options: list[tuple[float, dict, list]] = []
    for fix in scored:
        opts = sorted(
            [(out, fix.get(key, 0), _norm(fix.get(key, 0), out))
             for out, key in _OUTCOME_SCORE_KEYS.items()],
            key=lambda x: x[2], reverse=True,
        )
        fixture_options.append((opts[0][2], fix, opts))

    fixture_options.sort(key=lambda x: x[0], reverse=True)

    # Two passes: respect min_score first, fall back to any score if needed
    for threshold in (min_score, 0):
        counts: dict[str, int] = {k: 0 for k in _OUTCOME_SCORE_KEYS}
        result: list[dict] = []
        for _, fix, opts in fixture_options:
            if len(result) >= size:
                break
            for outcome, raw, _norm_val in opts:
                if raw < threshold:
                    continue
                if counts[outcome] >= MIXED_MAX_PER_OUTCOME.get(outcome, 5):
                    continue
                result.append({**fix, "best_pick": outcome, "best_score": raw})
                counts[outcome] += 1
                break
        if len(result) >= min(size, len(scored)):
            break

    return result


async def build_signals(fixtures: list[dict]) -> tuple[list, list, list, list]:
    """
    Returns (acca3, acca5, [], mixed15).
    acca3/acca5 are draw-only picks.
    mixed15 picks the highest-confidence outcome per match from:
      draw, home win, away win, over 1.5, over 2.5, GG (BTTS).
    The empty list keeps the 4-tuple signature for backward compatibility.
    """
    if not fixtures:
        return [], [], [], []

    scored = []
    for fix in fixtures:
        try:
            home_form, away_form, h2h = await asyncio.gather(
                fetcher.fetch_team_form(fix["home_id"], limit=20),
                fetcher.fetch_team_form(fix["away_id"], limit=20),
                fetcher.fetch_h2h(fix["id"]),
            )
            result = score_fixture(fix, home_form, away_form, h2h)
            scored.append(result)
            print(
                f"  [{fix['league_code']}] {fix['home_short']} vs {fix['away_short']}"
                f" → Draw: {result['draw_score']}  "
                f"Home: {result['home_win_score']}  Away: {result['away_win_score']}"
                f"  O1.5: {result['over15_score']}  O2.5: {result['over25_score']}"
                f"  GG: {result['gg_score']}"
                f"  Best: {result['best_pick'].upper()} ({result['best_score']})"
            )
        except Exception as e:
            print(f"[Signals] Error scoring {fix.get('home_name')} vs {fix.get('away_name')}: {e}")

    if not scored:
        return [], [], [], []

    # ── Draw accas (acca3, acca5) ────────────────────────────────────────────
    draw_eligible = sorted(scored, key=lambda x: x["draw_score"], reverse=True)
    above_min     = [s for s in draw_eligible if s["draw_score"] >= MIN_DRAW_SCORE]
    pool          = above_min if len(above_min) >= ACCA_3_SIZE else draw_eligible

    acca3 = pool[:ACCA_3_SIZE]
    acca5 = pool[:ACCA_5_SIZE]

    # ── Mixed acca — diverse 6-outcome selection with caps ──────────────────
    mixed15 = _build_mixed_diverse(scored, ACCA_MIXED_SIZE, MIN_MIXED_SCORE)

    return acca3, acca5, [], mixed15
