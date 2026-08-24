"""
Result checker and performance grader.
Grades acca3, acca5, and mixed15 (draw/home/away/over1.5/over2.5/gg).
After grading, automatically settles paper trading bets.
"""
from football_bot import fetcher, state as fstate
from football_bot.config import FLEX_ALLOWED
from football_bot.utils import now_utc


async def check_results(target_date: str) -> dict | None:
    """
    Fetch results for target_date and grade all 4 accas.
    Returns grade dict or None if signals not found / games not finished.
    """
    signals = fstate.get_signals(target_date)
    if not signals:
        print(f"[Grader] No signals found for {target_date}")
        return None

    acca3   = signals.get("acca3",   [])
    acca5   = signals.get("acca5",   [])
    mixed15 = signals.get("mixed15", [])

    all_picks = {}
    for pick in acca3 + acca5 + mixed15:
        all_picks[pick["id"]] = pick

    if not all_picks:
        return None

    results = {}
    for match_id in all_picks:
        data = await fetcher.fetch_match_result(match_id)
        if data:
            results[match_id] = data

    unfinished = [
        mid for mid, d in results.items()
        if d.get("status") not in ("FINISHED", "AWARDED")
    ]
    if unfinished:
        print(f"[Grader] {len(unfinished)} match(es) not finished — will retry")
        return None

    def actual_outcome(match_data: dict) -> str | None:
        ft = match_data.get("score", {}).get("fullTime", {})
        h, a = ft.get("home"), ft.get("away")
        if h is None or a is None:
            return None
        if h == a: return "draw"
        if h > a:  return "home"
        return "away"

    def _flex_result(hits: int, total: int) -> dict:
        """Compute full_win / flex_win / any_win given FLEX_ALLOWED config."""
        allowed  = FLEX_ALLOWED.get(total, 0)
        required = max(1, total - allowed)
        full_win = (hits == total and total > 0)
        flex_win = (not full_win and hits >= required and total > 0)
        return {
            "allowed_losses": allowed,
            "required":       required,
            "win":            full_win,
            "flex_win":       flex_win,
            "any_win":        full_win or flex_win,
        }

    def grade_draw_acca(picks: list[dict]) -> dict:
        graded = []
        for pick in picks:
            mid     = pick["id"]
            data    = results.get(mid, {})
            ft      = data.get("score", {}).get("fullTime", {})
            outcome = actual_outcome(data) if data else None
            is_draw = (outcome == "draw")
            graded.append({
                **pick,
                "result":  f"{ft.get('home', '?')}–{ft.get('away', '?')}",
                "actual":  outcome or "?",
                "is_draw": is_draw,
                "status":  data.get("status", "UNKNOWN"),
            })
        hits  = sum(1 for g in graded if g["is_draw"])
        total = len(graded)
        pct   = round(hits / total * 100) if total else 0
        return {
            "picks":      graded,
            "hits":       hits,
            "total":      total,
            "result_str": f"{hits}/{total} ({pct}%)",
            "hit_pct":    pct,
            **_flex_result(hits, total),
        }

    def _goals_correct(best: str, ft: dict) -> bool:
        """Check if a goals-market prediction is correct given full-time score."""
        h, a = ft.get("home"), ft.get("away")
        if h is None or a is None:
            return False
        total = h + a
        if best == "over15": return total >= 2
        if best == "over25": return total >= 3
        if best == "gg":     return h > 0 and a > 0
        return False

    def grade_mixed_acca(picks: list[dict]) -> dict:
        graded = []
        for pick in picks:
            mid  = pick["id"]
            data = results.get(mid, {})
            ft   = data.get("score", {}).get("fullTime", {})
            outcome = actual_outcome(data) if data else None
            best    = pick.get("best_pick", "draw")

            if best in ("over15", "over25", "gg"):
                correct = _goals_correct(best, ft) if data else False
                actual_str = "✓" if correct else "✗"
            else:
                correct    = (outcome == best) if outcome else False
                actual_str = outcome or "?"

            graded.append({
                **pick,
                "result":  f"{ft.get('home', '?')}–{ft.get('away', '?')}",
                "actual":  actual_str,
                "correct": correct,
                "status":  data.get("status", "UNKNOWN"),
            })
        hits  = sum(1 for g in graded if g["correct"])
        total = len(graded)
        pct   = round(hits / total * 100) if total else 0
        return {
            "picks":      graded,
            "hits":       hits,
            "total":      total,
            "result_str": f"{hits}/{total} ({pct}%)",
            "hit_pct":    pct,
            **_flex_result(hits, total),
        }

    acca3_result = grade_draw_acca(acca3)
    acca5_result = grade_draw_acca(acca5)
    mixed_result = grade_mixed_acca(mixed15)
    empty_result = {"picks": [], "hits": 0, "total": 0, "win": False,
                    "flex_win": False, "any_win": False, "result_str": "n/a",
                    "hit_pct": 0, "allowed_losses": 0, "required": 0}

    graded_at = now_utc()
    fstate.save_grade(target_date, acca3_result, acca5_result,
                      empty_result, mixed_result, graded_at)

    grade = {
        "acca3":  acca3_result,
        "acca5":  acca5_result,
        "mixed":  mixed_result,
        "date":   target_date,
    }

    # Settle paper trading bets
    fstate.settle_paper_bet(target_date, grade)

    print(
        f"[Grader] {target_date} — "
        f"A3:{acca3_result['result_str']}  A5:{acca5_result['result_str']}  "
        f"Mix:{mixed_result['result_str']}"
    )
    return grade
