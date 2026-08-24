"""
Win/loss tracker for dry-run (and future live) trades.
All trade records are persisted in state under the "trade_log" key.
"""
from datetime import datetime, timezone
import bot.state as state
from bot.utils import fmt_usd, now_utc


MAX_TRADE_LOG = 500


def record_trade(trade: dict):
    """Append a trade record and persist immediately."""
    log = state.get("trade_log", [])
    log.append(trade)
    if len(log) > MAX_TRADE_LOG:
        log = log[-MAX_TRADE_LOG:]
    state.set("trade_log", log)


def get_trades(limit: int = 10) -> list[dict]:
    return state.get("trade_log", [])[-limit:]


def get_all_trades() -> list[dict]:
    return state.get("trade_log", [])


def get_stats() -> dict:
    """Compute win/loss statistics over all recorded trades."""
    trades = get_all_trades()
    if not trades:
        return {}

    wins   = [t for t in trades if t.get("win")]
    losses = [t for t in trades if not t.get("win")]
    total  = len(trades)

    total_profit  = sum(t.get("net_profit", 0) for t in trades)
    total_gross   = sum(t.get("gross_profit", 0) for t in trades)
    total_fees    = sum(t.get("fees_est", 0) for t in trades)
    total_slip    = sum(t.get("slip_cost", 0) for t in trades)
    win_profits   = [t["net_profit"] for t in wins]
    loss_profits  = [t["net_profit"] for t in losses]

    best  = max(trades, key=lambda t: t.get("net_profit", 0)) if trades else None
    worst = min(trades, key=lambda t: t.get("net_profit", 0)) if trades else None

    # Running streak
    streak_type  = "win" if trades[-1].get("win") else "loss"
    streak_count = 0
    for t in reversed(trades):
        if t.get("win") == (streak_type == "win"):
            streak_count += 1
        else:
            break

    # Average spread on winning vs losing trades
    avg_win_spread  = (sum(t.get("spread_pct",0) for t in wins)  / len(wins))  if wins  else 0
    avg_loss_spread = (sum(t.get("spread_pct",0) for t in losses)/ len(losses)) if losses else 0

    return {
        "total":           total,
        "wins":            len(wins),
        "losses":          len(losses),
        "win_rate":        (len(wins) / total * 100) if total else 0,
        "total_profit":    total_profit,
        "total_gross":     total_gross,
        "total_fees":      total_fees,
        "total_slip":      total_slip,
        "avg_net":         total_profit / total if total else 0,
        "avg_win":         (sum(win_profits)  / len(wins))   if wins   else 0,
        "avg_loss":        (sum(loss_profits) / len(losses)) if losses else 0,
        "best_trade":      best,
        "worst_trade":     worst,
        "streak_type":     streak_type,
        "streak_count":    streak_count,
        "avg_win_spread":  avg_win_spread,
        "avg_loss_spread": avg_loss_spread,
    }


def fmt_trade(trade: dict, idx: int | None = None) -> str:
    """Format a single trade record for Telegram display."""
    result  = "✅ WIN " if trade.get("win") else "❌ LOSS"
    prefix  = f"#{idx}  " if idx is not None else ""
    sym     = trade.get("symbol", "?")
    chain   = trade.get("chain", "?")
    spread  = trade.get("spread_pct", 0)
    net     = trade.get("net_profit", 0)
    size    = trade.get("sim_size", 0)
    ts      = trade.get("timestamp", "")

    return (
        f"{prefix}{result}  <b>${sym}</b>  [{chain.upper()}]\n"
        f"  Size: ${size:.0f}  |  Spread: {spread:.2f}%  |  Net: <b>{fmt_usd(net)}</b>\n"
        f"  {ts}"
    )


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_today_trades() -> list[dict]:
    today = _today_utc()
    return [t for t in get_all_trades() if t.get("timestamp", "").startswith(today)]


def get_today_opportunities() -> list[dict]:
    today = _today_utc()
    return [o for o in state.get_opportunities() if o.get("detected_at", "").startswith(today)]


def get_today_stats() -> dict:
    trades = get_today_trades()
    if not trades:
        return {}
    wins   = [t for t in trades if t.get("win")]
    losses = [t for t in trades if not t.get("win")]
    total  = len(trades)
    total_profit = sum(t.get("net_profit", 0) for t in trades)
    best   = max(trades, key=lambda t: t.get("net_profit", 0)) if trades else None
    worst  = min(trades, key=lambda t: t.get("net_profit", 0)) if trades else None
    return {
        "total": total, "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / total * 100) if total else 0,
        "total_profit": total_profit,
        "avg_net": total_profit / total if total else 0,
        "best_trade": best, "worst_trade": worst,
    }


def build_daily_report() -> str:
    """Build the full daily summary message for Telegram."""
    from bot.config import CHAIN_EMOJIS
    today      = _today_utc()
    S          = "━" * 30
    mode       = state.get("automode", "off").upper()
    scan_count = state.get("scan_count", 0)

    # ── Opportunities today ───────────────────────────────────────────────
    opps       = get_today_opportunities()
    intra_opps = [o for o in opps if o.get("type") == "intra"]
    cross_opps = [o for o in opps if o.get("type") == "cross"]
    pos_opps   = [o for o in opps if o.get("net_profit", 0) > 0]
    best_opp   = max(opps, key=lambda o: o.get("spread_pct", 0)) if opps else None

    # ── Dry-run trades today ──────────────────────────────────────────────
    today_stats = get_today_stats()
    all_stats   = get_stats()

    # ── Section: opportunities ────────────────────────────────────────────
    opp_lines = []
    if best_opp:
        ce = CHAIN_EMOJIS.get(best_opp.get("chain", best_opp.get("buy_chain", "")), "🌐")
        opp_lines = [
            f"  Total detected: <b>{len(opps)}</b>  "
            f"({len(intra_opps)} intra · {len(cross_opps)} cross)",
            f"  Net-positive:   <b>{len(pos_opps)}</b>",
            f"  Best gap:  {ce} <b>${best_opp['symbol']}</b>  "
            f"{best_opp['spread_pct']:.2f}%  at {best_opp['detected_at'][11:16]} UTC",
        ]
    else:
        opp_lines = ["  No opportunities detected today."]

    # ── Section: dry-run trades ───────────────────────────────────────────
    if today_stats:
        wr       = today_stats["win_rate"]
        wr_icon  = "🟢" if wr >= 60 else "🟡" if wr >= 40 else "🔴"
        best_t   = today_stats.get("best_trade")
        worst_t  = today_stats.get("worst_trade")
        trade_lines = [
            f"  Trades:    <b>{today_stats['total']}</b>  "
            f"({today_stats['wins']}W / {today_stats['losses']}L)",
            f"  Win rate:  <b>{wr_icon} {wr:.1f}%</b>",
            f"  Net P&amp;L:   <b>{fmt_usd(today_stats['total_profit'])}</b>  "
            f"(avg {fmt_usd(today_stats['avg_net'])} / trade)",
        ]
        if best_t:
            trade_lines.append(
                f"  Best:   ✅ ${best_t['symbol']}  {fmt_usd(best_t['net_profit'])}"
            )
        if worst_t and worst_t != best_t:
            trade_lines.append(
                f"  Worst:  ❌ ${worst_t['symbol']}  {fmt_usd(worst_t['net_profit'])}"
            )
    else:
        trade_lines = [
            "  No dry-run trades today.",
            f"  Mode: <b>{mode}</b>  — use /automode dry to enable",
        ]

    # ── All-time footer ───────────────────────────────────────────────────
    if all_stats:
        all_wr   = all_stats.get("win_rate", 0)
        all_icon = "🟢" if all_wr >= 60 else "🟡" if all_wr >= 40 else "🔴"
        footer   = (
            f"All-time:  {all_icon} {all_wr:.1f}% win rate  |  "
            f"{all_stats['total']} trades  |  "
            f"{fmt_usd(all_stats['total_profit'])} net"
        )
    else:
        footer = "All-time: no trade data yet."

    lines = [
        f"📅 <b>DAILY REPORT — {today}</b>",
        S,
        f"🔍 <b>Opportunities Detected</b>",
        *opp_lines,
        S,
        f"🧪 <b>Dry-Run Performance</b>",
        *trade_lines,
        S,
        f"📊 <b>Bot Status</b>",
        f"  Scans completed: <b>{scan_count}</b>",
        f"  Tokens watched:  <b>{len(state.watchlist())}</b>  (SOL + BSC)",
        f"  Mode:            <b>{mode}</b>",
        f"  Confidence min:  <b>{state.cfg_confidence()}/100</b>",
        S,
        f"<i>{footer}</i>",
        f"⏰ Generated {now_utc()}",
    ]
    return "\n".join(lines)


def fmt_pnl_summary(stats: dict) -> str:
    """Format full P&L summary for Telegram."""
    if not stats:
        return "📊 No trades recorded yet. Dry-run mode is active."

    S = "━" * 30
    win_rate = stats["win_rate"]
    wr_icon  = "🟢" if win_rate >= 60 else "🟡" if win_rate >= 40 else "🔴"

    best  = stats.get("best_trade")
    worst = stats.get("worst_trade")

    best_line  = (f"  Best:    <b>{fmt_usd(best['net_profit'])}</b>  "
                  f"${best['symbol']} {best['spread_pct']:.1f}%") if best else ""
    worst_line = (f"  Worst:   <b>{fmt_usd(worst['net_profit'])}</b>  "
                  f"${worst['symbol']} {worst['spread_pct']:.1f}%") if worst else ""

    streak_icon = "🔥" if stats["streak_type"] == "win" else "🧊"
    mode_note = "🧪 <i>Dry-run mode — no real money involved</i>"

    lines = [
        f"📊 <b>DRY-RUN P&amp;L SUMMARY</b>",
        S,
        f"📈 <b>Performance</b>",
        f"  Trades:   <b>{stats['total']}</b>  ({stats['wins']}W / {stats['losses']}L)",
        f"  Win rate: <b>{wr_icon} {win_rate:.1f}%</b>",
        f"  Streak:   {streak_icon} {stats['streak_count']} {stats['streak_type']}s in a row",
        S,
        f"💰 <b>Profit &amp; Loss</b>",
        f"  Total net P&L:   <b>{fmt_usd(stats['total_profit'])}</b>",
        f"  Avg per trade:   <b>{fmt_usd(stats['avg_net'])}</b>",
        f"  Avg WIN:         <b>{fmt_usd(stats['avg_win'])}</b>",
        f"  Avg LOSS:        <b>{fmt_usd(stats['avg_loss'])}</b>",
        S,
        f"🔬 <b>Cost Breakdown</b>",
        f"  Gross earned:    {fmt_usd(stats['total_gross'])}",
        f"  Fees paid:       -{fmt_usd(stats['total_fees'])}",
        f"  Slippage cost:   -{fmt_usd(stats['total_slip'])}",
        S,
        f"🏆 <b>Extremes</b>",
        best_line,
        worst_line,
        S,
        f"📐 <b>Spread Analysis</b>",
        f"  Avg spread (wins):   {stats['avg_win_spread']:.2f}%",
        f"  Avg spread (losses): {stats['avg_loss_spread']:.2f}%",
        S,
        mode_note,
    ]
    return "\n".join(l for l in lines if l != "")
