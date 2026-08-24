"""
Message formatters for the Football Draw Bot.
"""
from football_bot.utils import fmt_kickoff, now_utc
from football_bot import state as fstate
from football_bot.config import FLEX_ALLOWED
from football_bot.paper_trading import (
    fmt_stake, fmt_pnl, pnl_icon,
    draw_single_odds, pick_single_odds, STAKE_PER_ACCA, CURRENCY
)

S  = "━" * 32
S2 = "─" * 28

OUTCOME_ICON  = {"draw": "🟰", "home": "🏠", "away": "✈️",
                 "over15": "⚽", "over25": "🔥", "gg": "🎯"}
OUTCOME_LABEL = {"draw": "DRAW", "home": "HOME WIN", "away": "AWAY WIN",
                 "over15": "OVER 1.5", "over25": "OVER 2.5", "gg": "GG/BTTS"}


# ── Pick line formatters ────────────────────────────────────────────────────

def _draw_pick_line(i: int, p: dict) -> str:
    ko    = fmt_kickoff(p.get("kickoff", ""))
    score = p.get("draw_score", 0)
    conf  = p.get("confidence", "")
    odds  = draw_single_odds(p)
    return (
        f"  {i}. <b>{p['home_short']} vs {p['away_short']}</b>\n"
        f"     {p['league_country']} · {p['league_name']}\n"
        f"     ⏰ {ko} UTC  |  Score: <b>{score}/100</b> {conf}  @ {odds}\n"
        f"     📊 H: {p['home_draw_pct']}%  A: {p['away_draw_pct']}%  H2H: {p['h2h_draw_pct']}%"
    )


def _mixed_pick_line(i: int, p: dict) -> str:
    ko    = fmt_kickoff(p.get("kickoff", ""))
    best  = p.get("best_pick", "draw")
    score = p.get("best_score", 0)
    icon  = OUTCOME_ICON.get(best, "🟰")
    label = OUTCOME_LABEL.get(best, best.upper())
    odds  = pick_single_odds(p)
    dw  = p.get("draw_score", 0)
    hw  = p.get("home_win_score", 0)
    aw  = p.get("away_win_score", 0)
    o15 = p.get("over15_score", 0)
    o25 = p.get("over25_score", 0)
    gg  = p.get("gg_score", 0)
    goals_line = f"  O1.5:{o15}  O2.5:{o25}  GG:{gg}" if any([o15, o25, gg]) else ""
    return (
        f"  {i}. <b>{p['home_short']} vs {p['away_short']}</b>  {icon} <b>{label}</b>  @ {odds}\n"
        f"     {p['league_country']} · {p['league_name']}  |  ⏰ {ko} UTC\n"
        f"     Score: <b>{score}/100</b>  [D:{dw} H:{hw} A:{aw}{goals_line}]"
    )


# ── Signal messages ─────────────────────────────────────────────────────────

def _flex_label(n: int) -> str:
    """e.g. n=3 → '[Flex-1 · need 2/3]'"""
    allowed  = FLEX_ALLOWED.get(n, 0)
    required = n - allowed
    if allowed == 0:
        return ""
    return f"[Flex-{allowed} · need {required}/{n}]"


def build_signal_msg(acca3: list, acca5: list, _acca10_unused: list,
                     mixed15: list, match_date: str) -> str:
    """Draw accas message (Acca-3, Acca-5) with paper trade preview."""
    from football_bot.paper_trading import acca_odds

    def pot(picks, draw_only=True):
        o = acca_odds(picks, draw_only=draw_only)
        return f"{CURRENCY}{round(STAKE_PER_ACCA * o):,}"

    fl3 = _flex_label(len(acca3))
    fl5 = _flex_label(len(acca5))

    lines = [
        f"⚽ <b>DRAW SIGNALS — {match_date}</b>",
        f"<i>Paper trading {CURRENCY}{STAKE_PER_ACCA:,} per acca · flex bets active</i>",
        S,
        f"🎯 <b>ACCA-3</b> <i>{fl3}</i>  Top 3 draws  →  pot. <b>{pot(acca3)}</b>",
        "",
    ]
    for i, p in enumerate(acca3, 1):
        lines.append(_draw_pick_line(i, p))
        lines.append("")

    lines += [S, f"🎰 <b>ACCA-5</b> <i>{fl5}</i>  Top 5 draws  →  pot. <b>{pot(acca5)}</b>", ""]
    for i, p in enumerate(acca5, 1):
        lines.append(_draw_pick_line(i, p))
        lines.append("")

    lines += [
        S,
        f"📌 Bet <b>DRAW</b> on all listed matches",
        f"<i>Generated {now_utc()} | Score = multi-factor model 0–100</i>",
    ]
    return "\n".join(lines)


def build_mixed_signal_msg(mixed15: list, match_date: str) -> str:
    """Mixed-outcome accumulator message."""
    if not mixed15:
        return ""
    from football_bot.paper_trading import acca_odds
    counts = {}
    for p in mixed15:
        k = p.get("best_pick", "draw")
        counts[k] = counts.get(k, 0) + 1
    pot = f"{CURRENCY}{round(STAKE_PER_ACCA * acca_odds(mixed15, draw_only=False)):,}"
    fl  = _flex_label(len(mixed15))
    g_line = (
        f"  ⚽ {counts.get('over15',0)} O1.5"
        f"  🔥 {counts.get('over25',0)} O2.5"
        f"  🎯 {counts.get('gg',0)} GG"
    ) if any(counts.get(k, 0) for k in ("over15", "over25", "gg")) else ""

    lines = [
        f"🎲 <b>MIXED-{len(mixed15)} ACCA</b> <i>{fl}</i> <b>— {match_date}</b>",
        f"<i>Bot picks best outcome per match</i>  →  pot. <b>{pot}</b>",
        S,
        f"🟰 {counts.get('draw',0)} draws  🏠 {counts.get('home',0)} home  "
        f"✈️ {counts.get('away',0)} away{g_line}",
        "",
    ]
    for i, p in enumerate(mixed15, 1):
        lines.append(_mixed_pick_line(i, p))
        lines.append("")
    lines += [
        S,
        f"📌 Bet each match on outcome shown (🟰/🏠/✈️)",
        f"<i>Generated {now_utc()}</i>",
    ]
    return "\n".join(lines)


# ── Grade message ───────────────────────────────────────────────────────────

def _pct_bar(pct: int) -> str:
    filled = round(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def _acca_tag(win: bool, hits: int, total: int, flex_win: bool = False) -> str:
    if win:       return f"🏆 FULL HIT! {hits}/{total}"
    if flex_win:  return f"🟡 FLEX WIN {hits}/{total}"
    if hits > 0:  return f"❌ {hits}/{total} — not enough"
    return f"❌ 0/{total}"


def _get(grade: dict, key: str) -> dict:
    return grade.get(key) or grade.get(f"{key}_result") or {}


def build_grade_msg(grade: dict) -> str:
    acca3 = _get(grade, "acca3")
    acca5 = _get(grade, "acca5")
    mixed = _get(grade, "mixed")
    d     = grade.get("date", "")

    def draw_lines(res: dict) -> list[str]:
        lines = []
        for p in res.get("picks", []):
            icon = "✅" if p.get("is_draw") else "❌"
            lines.append(
                f"  {icon} <b>{p['home_short']} vs {p['away_short']}</b>  "
                f"{p.get('result', '?–?')}"
            )
        tag = _acca_tag(
            res.get("win", False), res.get("hits", 0), res.get("total", 0),
            flex_win=res.get("flex_win", False),
        )
        req = res.get("required")
        flex_note = f"  <i>({res.get('allowed_losses',0)} miss allowed)</i>" if req else ""
        lines.append(f"  → {tag}{flex_note}")
        return lines

    def mixed_lines(res: dict) -> list[str]:
        lines = []
        for p in res.get("picks", []):
            icon   = "✅" if p.get("correct") else "❌"
            best   = p.get("best_pick", "draw")
            olabel = OUTCOME_LABEL.get(best, best.upper())
            lines.append(
                f"  {icon} <b>{p['home_short']} vs {p['away_short']}</b>  "
                f"({olabel} → {p.get('result', '?–?')} [{p.get('actual','?')}])"
            )
        tag = _acca_tag(
            res.get("win", False), res.get("hits", 0), res.get("total", 0),
            flex_win=res.get("flex_win", False),
        )
        req = res.get("required")
        flex_note = f"  <i>({res.get('allowed_losses',0)} miss allowed)</i>" if req else ""
        lines.append(f"  → {tag}{flex_note}")
        return lines

    # Paper trading settlement
    paper_bet = fstate.get_paper_bet(d)
    paper_lines = []
    if paper_bet:
        day_staked   = paper_bet.get("total_staked", 4000)
        day_returned = paper_bet.get("total_returned", 0)
        day_pnl      = paper_bet.get("net_pnl", day_returned - day_staked)
        icon         = pnl_icon(day_pnl)

        def bet_row(key, label):
            b = paper_bet.get(key, {})
            if not b:
                return ""
            won      = b.get("won")
            full_win = b.get("full_win", won)
            flex_win = b.get("flex_win", False)
            payout   = b.get("payout", 0)
            odds     = b.get("odds", 0)
            if won is None:
                return f"  {label}: ⏳ pending  (odds: {odds})"
            if full_win:
                mark = "🏆"; suffix = ""
            elif flex_win:
                mark = "🟡"; suffix = " [flex]"
            else:
                mark = "❌"; suffix = ""
            ret = fmt_stake(payout) if won else fmt_stake(0)
            return f"  {mark} {label}: {ret}{suffix}  (odds: {odds})"

        paper_lines = [
            "",
            S,
            f"💰 <b>PAPER TRADING — {d}</b>",
            f"  Staked:   {fmt_stake(day_staked)}",
            bet_row("acca3", "Acca-3 "),
            bet_row("acca5", "Acca-5 "),
            bet_row("mixed", "Mixed  "),
            f"  Returned: {fmt_stake(day_returned)}",
            f"  Day P&L:  {icon} <b>{fmt_pnl(day_pnl)}</b>",
        ]
        paper_lines = [l for l in paper_lines if l != ""]  # remove empty rows

        # Running total
        pt = fstate.get_paper_stats()
        total_pnl = pt.get("net_pnl", 0)
        total_staked = pt.get("total_staked", 0)
        roi = round(total_pnl / total_staked * 100, 1) if total_staked else 0
        paper_lines += [
            f"  Running P&L: {pnl_icon(total_pnl)} <b>{fmt_pnl(total_pnl)}</b>  "
            f"(ROI {roi:+.1f}%  over {pt.get('days_bet',0)} days)",
        ]

    # Performance stats
    perf   = fstate.get_performance()
    roll7  = fstate.get_rolling_stats(7)
    roll30 = fstate.get_rolling_stats(30)
    days   = perf.get("signal_days", 0)
    tp = perf.get("total_picks", 0) or 1
    cp = perf.get("correct_picks", 0)
    pick_acc = round(cp / tp * 100, 1)
    acc_icon = "🟢" if pick_acc >= 40 else "🟡" if pick_acc >= 25 else "🔴"

    def arate(key):
        n = perf.get(f"{key}_correct", 0)
        return round(n / days * 100) if days else 0

    def rpct(roll, key):
        d = roll["days"] or 1
        return round(roll.get(f"{key}_hits", 0) / d * 100)

    lines = [
        f"📊 <b>RESULTS — {d}</b>",
        S,
        f"🎯 <b>ACCA-3</b>",
        *draw_lines(acca3),
        "",
        S,
        f"🎰 <b>ACCA-5</b>",
        *draw_lines(acca5),
    ]
    if mixed.get("total", 0) > 0:
        lines += ["", S, f"🎲 <b>MIXED-{mixed.get('total',15)}</b>", *mixed_lines(mixed)]

    lines += paper_lines

    lines += [
        "",
        S,
        f"📈 <b>Performance ({days} days)</b>",
        f"  Pick acc: {acc_icon} <b>{pick_acc}%</b>  ({cp}/{tp})",
        f"           All-time  7d   30d",
        f"  Acca-3:  {arate('acca3'):>5}%  {rpct(roll7,'acca3'):>3}%  {rpct(roll30,'acca3'):>4}%",
        f"  Acca-5:  {arate('acca5'):>5}%  {rpct(roll7,'acca5'):>3}%  {rpct(roll30,'acca5'):>4}%",
        f"  Mixed:   {arate('mixed'):>5}%  {rpct(roll7,'mixed'):>3}%  {rpct(roll30,'mixed'):>4}%",
        S,
        f"<i>Graded {now_utc()}</i>",
    ]
    return "\n".join(lines)


def build_no_fixtures_msg(match_date: str) -> str:
    return (
        f"📅 <b>No signals for {match_date}</b>\n\n"
        f"No fixtures found in our covered leagues today.\nCheck back tomorrow!"
    )


# ── /performance ────────────────────────────────────────────────────────────

def build_performance_msg() -> str:
    perf = fstate.get_performance()
    days = perf.get("signal_days", 0)
    if days == 0:
        return "📊 No results graded yet. Check back after the first match day!"

    tp = perf.get("total_picks", 0) or 1
    cp = perf.get("correct_picks", 0)
    pick_acc = round(cp / tp * 100, 1)
    acc_icon = "🟢" if pick_acc >= 40 else "🟡" if pick_acc >= 25 else "🔴"
    roll7  = fstate.get_rolling_stats(7)
    roll30 = fstate.get_rolling_stats(30)

    def arate(key):
        return round(perf.get(f"{key}_correct", 0) / days * 100) if days else 0

    def rpct(roll, key):
        d = roll["days"] or 1
        return round(roll.get(f"{key}_hits", 0) / d * 100)

    def outcome_line(outcome):
        picks   = perf.get(f"{outcome}_picks", 0) or 1
        correct = perf.get(f"{outcome}_correct", 0)
        pct     = round(correct / picks * 100, 1)
        icon    = OUTCOME_ICON.get(outcome, "")
        label   = OUTCOME_LABEL.get(outcome, outcome)
        return f"  {icon} {label:<10} {correct}/{picks}  ({pct}%)"

    # Paper trading summary
    pt           = fstate.get_paper_stats()
    pt_days      = pt.get("days_bet", 0)
    total_staked = pt.get("total_staked", 0)
    total_ret    = pt.get("total_returned", 0)
    net_pnl      = pt.get("net_pnl", 0)
    roi          = round(net_pnl / total_staked * 100, 1) if total_staked else 0
    best_win     = pt.get("best_day_win", 0)
    worst_loss   = pt.get("worst_day_loss", 0)

    recent = fstate.get_recent_grades(7)
    streak = 0
    for g in recent:
        if _get(g, "acca3").get("win"):
            streak += 1
        else:
            break

    leagues = perf.get("leagues", {})
    league_lines = []
    if leagues:
        from football_bot.config import LEAGUES as LCFG
        for code, lg in sorted(leagues.items(),
                                key=lambda x: x[1].get("correct",0)/max(x[1].get("picks",1),1),
                                reverse=True)[:6]:
            name = LCFG.get(code, {}).get("name", code)
            p, c = lg.get("picks", 0) or 1, lg.get("correct", 0)
            league_lines.append(f"  {name:<20} {c}/{p}  ({round(c/p*100)}%)")

    lines = [
        f"📊 <b>DRAW BOT — PERFORMANCE</b>",
        S,
        f"📅 Match days: <b>{days}</b>",
        S,
        f"🎯 <b>Pick Accuracy (draws)</b>",
        f"  {acc_icon} <b>{pick_acc}%</b>  ({cp}/{tp})",
        f"  {_pct_bar(int(pick_acc))}",
        S,
        f"📊 <b>Accumulator Hit Rate</b>",
        f"           All-time  7-day  30-day",
        f"  Acca-3:  {arate('acca3'):>5}%  {rpct(roll7,'acca3'):>4}%  {rpct(roll30,'acca3'):>5}%",
        f"  Acca-5:  {arate('acca5'):>5}%  {rpct(roll7,'acca5'):>4}%  {rpct(roll30,'acca5'):>5}%",
        f"  Mixed:   {arate('mixed'):>5}%  {rpct(roll7,'mixed'):>4}%  {rpct(roll30,'mixed'):>5}%",
    ]

    if any(perf.get(f"{o}_picks", 0) for o in ("draw", "home", "away")):
        lines += [
            S,
            f"🎲 <b>Mixed Acca — By Outcome</b>",
            outcome_line("draw"),
            outcome_line("home"),
            outcome_line("away"),
        ]

    if league_lines:
        lines += [S, f"🌍 <b>Top Leagues by Draw Accuracy</b>", *league_lines]

    if pt_days > 0:
        recent_bets = fstate.get_recent_paper_bets(7)
        recent_pnl  = sum(b.get("net_pnl", 0) for b in recent_bets)
        lines += [
            S,
            f"💰 <b>Paper Trading ({CURRENCY}{STAKE_PER_ACCA:,}/acca)</b>",
            f"  Days bet:      <b>{pt_days}</b>",
            f"  Total staked:  {fmt_stake(total_staked)}",
            f"  Total returned:{fmt_stake(total_ret)}",
            f"  Net P&L:       {pnl_icon(net_pnl)} <b>{fmt_pnl(net_pnl)}</b>",
            f"  ROI:           <b>{roi:+.1f}%</b>",
            f"  Last 7 days:   {pnl_icon(recent_pnl)} {fmt_pnl(recent_pnl)}",
            f"  Best day win:  {fmt_stake(best_win)}",
            f"  Worst day:     {fmt_pnl(worst_loss)}",
            f"  Acca wins:  A3:{pt.get('acca3_wins',0)}  A5:{pt.get('acca5_wins',0)}  "
            f"Mix:{pt.get('mixed_wins',0)}",
        ]

    if streak > 0:
        lines += [S, f"🔥 <b>{streak}</b>-day Acca-3 win streak"]

    lines += [S, f"<i>Updated {now_utc()}</i>"]
    return "\n".join(lines)


# ── /paper command ──────────────────────────────────────────────────────────

def build_paper_msg() -> str:
    """Dedicated paper trading report."""
    pt = fstate.get_paper_stats()
    pt_days = pt.get("days_bet", 0)
    if pt_days == 0:
        return (
            f"💰 <b>Paper Trading — No results yet</b>\n\n"
            f"Staking {CURRENCY}{STAKE_PER_ACCA:,} per accumulator ({CURRENCY}{STAKE_PER_ACCA*4:,}/day total).\n"
            f"First results will appear after today's matches are graded."
        )

    total_staked = pt.get("total_staked", 0)
    total_ret    = pt.get("total_returned", 0)
    net_pnl      = pt.get("net_pnl", 0)
    roi          = round(net_pnl / total_staked * 100, 1) if total_staked else 0
    best_win     = pt.get("best_day_win", 0)
    worst_loss   = pt.get("worst_day_loss", 0)

    recent_bets = fstate.get_recent_paper_bets(7)

    lines = [
        f"💰 <b>PAPER TRADING REPORT</b>",
        f"<i>{CURRENCY}{STAKE_PER_ACCA:,} per acca · {CURRENCY}{STAKE_PER_ACCA*4:,} per day</i>",
        S,
        f"📅 Days bet:       <b>{pt_days}</b>",
        f"💸 Total staked:   {fmt_stake(total_staked)}",
        f"💵 Total returned: {fmt_stake(total_ret)}",
        f"📈 Net P&L:        {pnl_icon(net_pnl)} <b>{fmt_pnl(net_pnl)}</b>",
        f"📊 ROI:            <b>{roi:+.1f}%</b>",
        S,
        f"🏆 Best day win:   {fmt_stake(best_win)}",
        f"📉 Worst day:      {fmt_pnl(worst_loss)}",
        S,
        f"🎯 Acca wins:",
        f"  Acca-3:  {pt.get('acca3_wins',0)} / {pt_days}  "
        f"({round(pt.get('acca3_wins',0)/pt_days*100) if pt_days else 0}%)",
        f"  Acca-5:  {pt.get('acca5_wins',0)} / {pt_days}  "
        f"({round(pt.get('acca5_wins',0)/pt_days*100) if pt_days else 0}%)",
        f"  Mixed:   {pt.get('mixed_wins',0)} / {pt_days}  "
        f"({round(pt.get('mixed_wins',0)/pt_days*100) if pt_days else 0}%)",
    ]

    if recent_bets:
        lines += [S, f"📋 <b>Last {len(recent_bets)} Days:</b>"]
        for b in recent_bets:
            d       = b.get("date", "")
            staked  = b.get("total_staked", 4000)
            ret     = b.get("total_returned", 0)
            day_pnl = b.get("net_pnl", ret - staked)
            wins    = []
            for key, label in [("acca3","A3"),("acca5","A5"),("mixed","Mix")]:
                if b.get(key, {}).get("won"):
                    wins.append(f"🏆{label}")
            win_str = "  ".join(wins) if wins else "❌ all lost"
            lines.append(
                f"  <b>{d}</b>  {pnl_icon(day_pnl)} {fmt_pnl(day_pnl)}  {win_str}"
            )

    lines += [S, f"<i>Updated {now_utc()}</i>"]
    return "\n".join(lines)
