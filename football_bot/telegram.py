"""
Telegram interface for the Football Draw Bot.
"""
import aiohttp
from football_bot.config import FOOTBALL_TG_TOKEN, FOOTBALL_TG_CHAT_ID
from football_bot.utils import now_utc
from football_bot import state as fstate
from football_bot.alerts import build_performance_msg, build_paper_msg
from football_bot.paper_trading import STAKE_PER_ACCA, CURRENCY

TG_BASE  = f"https://api.telegram.org/bot{FOOTBALL_TG_TOKEN}"
_offset  = 0
_session = None


async def _get_session():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    return _session


async def send(msg: str, chat_id: str | None = None):
    cid = str(chat_id or FOOTBALL_TG_CHAT_ID)
    if not FOOTBALL_TG_TOKEN:
        print(f"[FootballTG MOCK] {msg[:120]}")
        return
    if not msg.strip():
        return
    session = await _get_session()
    payload = {
        "chat_id":                  cid,
        "text":                     msg,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(f"{TG_BASE}/sendMessage", json=payload) as r:
            if r.status == 400:
                payload["parse_mode"] = ""
                async with session.post(f"{TG_BASE}/sendMessage", json=payload):
                    pass
            elif not r.ok:
                text = await r.text()
                print(f"[FootballTG] {r.status}: {text[:80]}")
    except Exception as e:
        print(f"[FootballTG Error] {e}")


async def poll_commands():
    global _offset
    if not FOOTBALL_TG_TOKEN:
        return
    session = await _get_session()
    try:
        async with session.get(
            f"{TG_BASE}/getUpdates",
            params={"offset": _offset, "timeout": 3, "limit": 20}
        ) as r:
            if not r.ok:
                return
            data = await r.json()
    except Exception:
        return

    for update in data.get("result", []):
        _offset = update["update_id"] + 1
        msg  = update.get("message") or update.get("channel_post", {})
        text = (msg.get("text") or "").strip()
        cid  = str(msg.get("chat", {}).get("id", FOOTBALL_TG_CHAT_ID))
        if not text.startswith("/"):
            continue
        await _handle_command(text, cid)


async def _handle_command(text: str, cid: str):
    low = text.lower().split("@")[0].strip()

    # ── /signals ──────────────────────────────────────────────────
    if low == "/signals":
        from football_bot.utils import today_utc
        from football_bot.alerts import build_signal_msg, build_mixed_signal_msg
        today   = today_utc()
        signals = fstate.get_signals(today)
        if not signals:
            await send(
                f"📅 No signals posted yet today ({today}).\n"
                f"Signals auto-post at {fstate.cfg_signal_time()} UTC.",
                chat_id=cid,
            )
        else:
            await send(
                build_signal_msg(
                    signals.get("acca3",  []),
                    signals.get("acca5",  []),
                    [],
                    signals.get("mixed15",[]),
                    today,
                ),
                chat_id=cid,
            )
            mixed_msg = build_mixed_signal_msg(signals.get("mixed15", []), today)
            if mixed_msg:
                await send(mixed_msg, chat_id=cid)

    # ── /performance ───────────────────────────────────────────────
    elif low == "/performance":
        await send(build_performance_msg(), chat_id=cid)

    # ── /paper ────────────────────────────────────────────────────
    elif low == "/paper":
        await send(build_paper_msg(), chat_id=cid)

    # ── /history ──────────────────────────────────────────────────
    elif low == "/history":
        grades = fstate.get_recent_grades(7)
        if not grades:
            await send("📋 No results graded yet.", chat_id=cid)
        else:
            from football_bot.paper_trading import fmt_pnl, pnl_icon
            lines = ["📋 <b>Last 7 Match Days:</b>\n"]
            for g in grades:
                d  = g["date"]
                a3 = g.get("acca3", {})
                a5 = g.get("acca5", {})
                mx = g.get("mixed", {})

                def tag(r):
                    if not r:               return "—"
                    if r.get("win"):        return f"🏆 {r.get('result_str','?')}"
                    if r.get("hits",0) > 0: return f"⚡ {r.get('result_str','?')}"
                    return f"❌ {r.get('result_str','?')}"

                pb = fstate.get_paper_bet(d)
                pnl_str = ""
                if pb:
                    day_pnl = pb.get("net_pnl", pb.get("total_returned",0) - pb.get("total_staked",4000))
                    pnl_str = f"  {pnl_icon(day_pnl)} {fmt_pnl(day_pnl)}"

                lines.append(
                    f"<b>{d}</b>{pnl_str}\n"
                    f"  A3:{tag(a3)}  A5:{tag(a5)}  Mix:{tag(mx)}"
                )
            await send("\n".join(lines), chat_id=cid)

    # ── /grade [DATE] ──────────────────────────────────────────────
    elif low.startswith("/grade"):
        from football_bot.utils import today_utc
        from football_bot.alerts import build_grade_msg
        parts  = low.split()
        target = parts[1] if len(parts) > 1 else today_utc()
        grade  = fstate.get_grade(target)
        if not grade:
            await send(
                f"No grade for {target} yet.\n"
                f"Results are checked automatically after matches finish.",
                chat_id=cid,
            )
        else:
            await send(build_grade_msg(grade), chat_id=cid)

    # ── /leagues ──────────────────────────────────────────────────
    elif low == "/leagues":
        from football_bot.config import LEAGUES
        lines = ["🌍 <b>Covered Leagues:</b>\n"]
        for code, info in sorted(LEAGUES.items(),
                                  key=lambda x: x[1]["draw_rate"], reverse=True):
            lines.append(
                f"  {info['country']} <b>{info['name']}</b>  "
                f"Draw: {info['draw_rate']*100:.0f}%  "
                f"H: {info['home_win']*100:.0f}%  "
                f"A: {info['away_win']*100:.0f}%"
            )
        await send("\n".join(lines), chat_id=cid)

    # ── /setsignaltime HH:MM ──────────────────────────────────────
    elif low.startswith("/setsignaltime"):
        parts = text.split()
        if len(parts) < 2:
            await send(
                f"⏰ Signal time: <b>{fstate.cfg_signal_time()} UTC</b>\n"
                "Usage: /setsignaltime HH:MM",
                chat_id=cid,
            )
        else:
            try:
                val = parts[1].strip()
                h, m = val.split(":")
                if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                    raise ValueError
                val = f"{int(h):02d}:{int(m):02d}"
                fstate.set_signal_time(val)
                await send(f"✅ Signals will post at <b>{val} UTC</b>.", chat_id=cid)
            except Exception:
                await send("Usage: /setsignaltime HH:MM (e.g. /setsignaltime 08:30)", chat_id=cid)

    # ── /pause / /resume ──────────────────────────────────────────
    elif low == "/pause":
        fstate.set_paused(True)
        await send("⏸ <b>Football Draw Bot paused.</b> Use /resume to restart.", chat_id=cid)

    elif low == "/resume":
        fstate.set_paused(False)
        await send("▶️ <b>Football Draw Bot resumed.</b>", chat_id=cid)

    # ── /status ───────────────────────────────────────────────────
    elif low == "/status":
        from football_bot.utils import today_utc
        from football_bot.paper_trading import fmt_pnl, pnl_icon
        today  = today_utc()
        posted = fstate.get("last_signal_date", "") == today
        graded = fstate.get("last_grade_date",  "") == today
        paused = fstate.is_paused()
        perf   = fstate.get_performance()
        days   = perf.get("signal_days", 0)
        tp     = perf.get("total_picks", 0) or 1
        cp     = perf.get("correct_picks", 0)
        acc    = round(cp / tp * 100, 1)
        pt     = fstate.get_paper_stats()
        net    = pt.get("net_pnl", 0)
        roi    = round(net / pt.get("total_staked", 1) * 100, 1) if pt.get("total_staked") else 0
        await send(
            f"⚽ <b>Football Draw Bot — Status</b>\n"
            f"{'⏸ PAUSED' if paused else '▶️ RUNNING'}\n\n"
            f"Today ({today}):\n"
            f"  Signals: {'✅ posted' if posted else f'⏳ {fstate.cfg_signal_time()} UTC'}\n"
            f"  Results: {'✅ graded' if graded else '⏳ pending'}\n\n"
            f"All-time: <b>{days}</b> days  |  Pick acc: <b>{acc}%</b>\n"
            f"Paper P&L: {pnl_icon(net)} <b>{fmt_pnl(net)}</b>  (ROI {roi:+.1f}%)",
            chat_id=cid,
        )

    # ── /help ─────────────────────────────────────────────────────
    elif low == "/help":
        await send(
            "⚽ <b>Football Draw Bot — Commands</b>\n\n"
            "/signals — today's picks (Acca-3, 5, 10, Mixed-15)\n"
            "/paper — paper trading P&L report\n"
            "/performance — full accuracy & hit rate breakdown\n"
            "/history — last 7 days results + paper P&L\n"
            "/grade [DATE] — grade for a specific date (YYYY-MM-DD)\n"
            "/leagues — covered leagues with draw/home/away rates\n"
            "/status — bot status, pick accuracy, paper ROI\n"
            "/setsignaltime HH:MM — change daily signal time (UTC)\n"
            "/pause · /resume — pause/resume the bot\n\n"
            f"<b>Paper trading:</b> {CURRENCY}{STAKE_PER_ACCA:,} per acca "
            f"({CURRENCY}{STAKE_PER_ACCA*4:,}/day across all 4)\n"
            f"Odds estimated from model confidence scores\n\n"
            "<b>4 accas posted daily:</b>\n"
            "  🎯 Acca-3  — top 3 draw picks\n"
            "  🎰 Acca-5  — top 5 draw picks\n"
            "  🔟 Acca-10 — top 10 draw picks\n"
            "  🎲 Mixed-15 — best outcome per match\n\n"
            "<i>Results auto-graded. Paper bets auto-settled.</i>",
            chat_id=cid,
        )
