"""
Persistent state for the Football Draw Bot.
Completely separate from the arbitrage bot state.
"""
import json, os, copy
from football_bot.config import STATE_FILE

_perf_defaults = {
    "signal_days":    0,
    "acca3_correct":  0, "acca3_partial":  0, "acca3_nil":  0,
    "acca5_correct":  0, "acca5_partial":  0, "acca5_nil":  0,
    "acca10_correct": 0, "acca10_partial": 0, "acca10_nil": 0,
    "mixed_correct":  0, "mixed_partial":  0, "mixed_nil":  0,
    "total_picks":    0, "correct_picks":  0,
    "draw_picks":     0, "draw_correct":   0,
    "home_picks":     0, "home_correct":   0,
    "away_picks":     0, "away_correct":   0,
    "leagues":        {},
}

_paper_defaults = {
    "days_bet":      0,
    "total_staked":  0,
    "total_returned":0,
    "net_pnl":       0,
    "best_day_win":  0,   # largest single-day return
    "worst_day_loss":0,   # largest single-day loss (negative)
    "acca3_wins":    0,
    "acca5_wins":    0,
    "acca10_wins":   0,
    "mixed_wins":    0,
    "bets":          [],  # list of settled bet records
}

_defaults = {
    "signal_log":       [],
    "result_log":       [],
    "performance":      _perf_defaults.copy(),
    "paper_trading":    _paper_defaults.copy(),
    "signal_time":      "09:00",
    "last_signal_date": "",
    "last_grade_date":  "",
    "paused":           False,
}

_state = {}


def load():
    global _state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            _state = {**copy.deepcopy(_defaults), **saved}

            perf = copy.deepcopy(_perf_defaults)
            perf.update(saved.get("performance", {}))
            if "leagues" not in perf:
                perf["leagues"] = {}
            _state["performance"] = perf

            paper = copy.deepcopy(_paper_defaults)
            paper.update(saved.get("paper_trading", {}))
            _state["paper_trading"] = paper

            print(f"[FootballState] Loaded from {STATE_FILE}")
            save()
            return
        except Exception as e:
            print(f"[FootballState] Load error: {e} — using defaults")
    _state = copy.deepcopy(_defaults)
    save()


def save():
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(_state, f, indent=2)


def get(key, default=None):
    return _state.get(key, default)


def set(key, value):
    _state[key] = value
    save()


def is_paused() -> bool:
    return _state.get("paused", False)


def set_paused(v: bool):
    _state["paused"] = v
    save()


def cfg_signal_time() -> str:
    return _state.get("signal_time") or "09:00"


def set_signal_time(hhmm: str):
    _state["signal_time"] = hhmm
    save()


# ── Signal log ──────────────────────────────────────────────────────────────

def save_signals(date: str, acca3: list, acca5: list,
                 acca10: list, mixed15: list, posted_at: str):
    log = _state.setdefault("signal_log", [])
    _state["signal_log"] = [e for e in log if e.get("date") != date]
    _state["signal_log"].append({
        "date":      date,
        "acca3":     acca3,
        "acca5":     acca5,
        "acca10":    acca10,
        "mixed15":   mixed15,
        "posted_at": posted_at,
    })
    _state["last_signal_date"] = date
    save()


def get_signals(date: str) -> dict | None:
    for entry in _state.get("signal_log", []):
        if entry.get("date") == date:
            return entry
    return None


def get_recent_signals(n: int = 7) -> list:
    return sorted(_state.get("signal_log", []),
                  key=lambda x: x.get("date", ""), reverse=True)[:n]


# ── Result / grade log ──────────────────────────────────────────────────────

def save_grade(date: str, acca3_result: dict, acca5_result: dict,
               acca10_result: dict, mixed_result: dict, graded_at: str):
    log = _state.setdefault("result_log", [])
    _state["result_log"] = [e for e in log if e.get("date") != date]
    _state["result_log"].append({
        "date":          date,
        "acca3":         acca3_result,
        "acca5":         acca5_result,
        "acca10":        acca10_result,
        "mixed":         mixed_result,
        "graded_at":     graded_at,
    })
    _state["last_grade_date"] = date

    perf = _state.setdefault("performance", copy.deepcopy(_perf_defaults))
    perf["signal_days"] += 1

    def _update_acca(key: str, result: dict):
        hits  = result.get("hits", 0)
        total = result.get("total", 0)
        if total == 0:
            return
        if hits == total:
            perf[f"{key}_correct"] += 1
        elif hits > 0:
            perf[f"{key}_partial"] += 1
        else:
            perf[f"{key}_nil"] += 1

    _update_acca("acca3",  acca3_result)
    _update_acca("acca5",  acca5_result)
    _update_acca("acca10", acca10_result)
    _update_acca("mixed",  mixed_result)

    for result in (acca3_result, acca5_result):
        for pick in result.get("picks", []):
            perf["total_picks"]   += 1
            perf["correct_picks"] += 1 if pick.get("is_draw") else 0
            perf["draw_picks"]    += 1
            perf["draw_correct"]  += 1 if pick.get("is_draw") else 0
            code = pick.get("league_code", "")
            if code:
                lg = perf["leagues"].setdefault(code, {"picks": 0, "correct": 0})
                lg["picks"]   += 1
                lg["correct"] += 1 if pick.get("is_draw") else 0

    for pick in mixed_result.get("picks", []):
        outcome = pick.get("best_pick", "draw")
        correct = pick.get("correct", False)
        perf[f"{outcome}_picks"]   += 1
        perf[f"{outcome}_correct"] += 1 if correct else 0

    save()


def get_grade(date: str) -> dict | None:
    for entry in _state.get("result_log", []):
        if entry.get("date") == date:
            return entry
    return None


def get_performance() -> dict:
    return _state.get("performance", copy.deepcopy(_perf_defaults))


def get_recent_grades(n: int = 7) -> list:
    return sorted(_state.get("result_log", []),
                  key=lambda x: x.get("date", ""), reverse=True)[:n]


def get_rolling_stats(days: int = 7) -> dict:
    grades = get_recent_grades(days)
    stats = {
        "days": len(grades),
        "acca3_hits": 0, "acca5_hits": 0, "acca10_hits": 0, "mixed_hits": 0,
        "picks": 0, "correct": 0,
    }
    for g in grades:
        for key in ("acca3", "acca5", "acca10", "mixed"):
            if g.get(key, {}).get("win"):
                stats[f"{key}_hits"] += 1
        for rkey in ("acca3", "acca5"):
            r = g.get(rkey, {})
            stats["picks"]   += r.get("total", 0)
            stats["correct"] += r.get("hits", 0)
    return stats


# ── Paper trading ────────────────────────────────────────────────────────────

def save_paper_bet(date: str, bet_record: dict):
    """Save an unsettled paper bet for today."""
    pt = _state.setdefault("paper_trading", copy.deepcopy(_paper_defaults))
    bets = pt.setdefault("bets", [])
    pt["bets"] = [b for b in bets if b.get("date") != date]
    pt["bets"].append(bet_record)
    save()


def settle_paper_bet(date: str, grade: dict):
    """
    Settle today's paper bets against the graded results.
    Updates running totals in paper_trading stats.
    """
    from football_bot.paper_trading import settle_bets as _settle
    pt   = _state.setdefault("paper_trading", copy.deepcopy(_paper_defaults))
    bets = pt.setdefault("bets", [])

    bet_record = next((b for b in bets if b.get("date") == date), None)
    if not bet_record:
        return

    updated, net_pnl = _settle(bet_record, grade)

    # Replace in list
    pt["bets"] = [b for b in bets if b.get("date") != date]
    pt["bets"].append(updated)

    # Update cumulative stats
    pt["days_bet"]       += 1
    pt["total_staked"]   += updated.get("total_staked", 4000)
    returned              = updated.get("total_returned", 0)
    pt["total_returned"] += returned
    pt["net_pnl"]        += net_pnl

    if net_pnl > pt.get("best_day_win", 0):
        pt["best_day_win"] = net_pnl
    if net_pnl < pt.get("worst_day_loss", 0):
        pt["worst_day_loss"] = net_pnl

    for key in ("acca3", "acca5", "acca10", "mixed"):
        if updated.get(key, {}).get("won"):
            pt[f"{key}_wins"] = pt.get(f"{key}_wins", 0) + 1

    print(
        f"[PaperTrading] {date} settled — "
        f"net: {'₦' if net_pnl >= 0 else '-₦'}{abs(net_pnl):,}  "
        f"returned: ₦{returned:,}  "
        f"total P&L: {'₦' if pt['net_pnl'] >= 0 else '-₦'}{abs(pt['net_pnl']):,}"
    )
    save()


def get_paper_stats() -> dict:
    return _state.get("paper_trading", copy.deepcopy(_paper_defaults))


def get_paper_bet(date: str) -> dict | None:
    pt = _state.get("paper_trading", {})
    return next((b for b in pt.get("bets", []) if b.get("date") == date), None)


def get_recent_paper_bets(n: int = 7) -> list:
    pt = _state.get("paper_trading", {})
    bets = [b for b in pt.get("bets", []) if b.get("total_returned") is not None]
    return sorted(bets, key=lambda x: x.get("date", ""), reverse=True)[:n]


def get_ungraded_signal_dates(exclude_today: str = "") -> list[str]:
    """Return past signal dates that have no grade recorded yet."""
    graded = {e.get("date") for e in _state.get("result_log", [])}
    return [
        e.get("date") for e in _state.get("signal_log", [])
        if e.get("date") and e.get("date") != exclude_today
        and e.get("date") not in graded
    ]


def save_match_meta(meta: dict):
    """Persist ESPN match_id → {espn_league, home_id, away_id} so grading survives restarts."""
    existing = _state.get("espn_match_meta", {})
    existing.update(meta)
    _state["espn_match_meta"] = existing
    save()


def get_match_meta() -> dict:
    return _state.get("espn_match_meta", {})
