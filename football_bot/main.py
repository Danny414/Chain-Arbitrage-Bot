#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         FOOTBALL DRAW PREDICTION BOT                        ║
║                                                              ║
║  Accumulators:  Acca-3 · Acca-5 · Acca-10 · Mixed-15       ║
║  Paper trading: ₦1,000 per acca (₦4,000/day)               ║
║  Performance:   per % — 7d / 30d / all-time + per-league   ║
╚══════════════════════════════════════════════════════════════╝
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from football_bot.config import FOOTBALL_TG_TOKEN, FOOTBALL_API_KEY
from football_bot.utils import now_utc, today_utc
from football_bot import state as fstate
from football_bot import fetcher, telegram as tg
from football_bot.fetcher import validate_api_key
from football_bot.signals import build_signals
from football_bot.grader import check_results
from football_bot import paper_trading as pt
from football_bot.alerts import (
    build_signal_msg, build_mixed_signal_msg,
    build_grade_msg, build_no_fixtures_msg,
)


async def main():
    print("=" * 62)
    print("  FOOTBALL DRAW PREDICTION BOT")
    print("=" * 62)

    if not FOOTBALL_TG_TOKEN:
        print("[ERROR] FOOTBALL_TG_TOKEN secret not set.")
        return
    if not FOOTBALL_API_KEY:
        print("[ERROR] FOOTBALL_API_KEY secret not set.")
        return

    fstate.load()
    perf  = fstate.get_performance()
    pstat = fstate.get_paper_stats()
    print(f"✅ State loaded — {perf.get('signal_days', 0)} match days on record")
    print(f"✅ Signal time: {fstate.cfg_signal_time()} UTC daily")
    print(f"✅ Paper trading: {pt.CURRENCY}{pt.STAKE_PER_ACCA:,}/acca  |  "
          f"Running P&L: {pt.fmt_pnl(pstat.get('net_pnl', 0))}")
    print(f"\nListening for commands...")

    await tg.send(
        f"⚽ <b>Football Draw Bot — Online</b>\n"
        f"4 accumulators · Paper trading {pt.CURRENCY}{pt.STAKE_PER_ACCA:,}/acca\n"
        f"Running P&L: {pt.pnl_icon(pstat.get('net_pnl',0))} "
        f"<b>{pt.fmt_pnl(pstat.get('net_pnl',0))}</b>\n"
        f"Send /help for commands  |  {now_utc()}"
    )

    # Validate API key before entering the main loop
    print("[Startup] Validating FOOTBALL_API_KEY...")
    key_ok, key_msg = await validate_api_key()
    if not key_ok:
        err = (
            f"⚠️ <b>Football API key invalid!</b>\n"
            f"Error: <code>{key_msg}</code>\n\n"
            f"Signals cannot be fetched until this is fixed.\n"
            f"1. Go to <a href='https://www.football-data.org/client/register'>football-data.org</a>\n"
            f"2. Register for a free account → copy your API token\n"
            f"3. Update the <b>FOOTBALL_API_KEY</b> secret in Replit\n"
            f"4. Restart the Football Draw Bot"
        )
        print(f"[Startup] ⚠️  API key rejected: {key_msg}")
        await tg.send(err)
    else:
        print("[Startup] ✅ API key valid")

    await asyncio.gather(
        _signal_loop(),
        _grade_loop(),
        _command_loop(),
    )


async def _signal_loop():
    while True:
        try:
            if not fstate.is_paused():
                today = today_utc()
                last  = fstate.get("last_signal_date", "")
                # Post as soon as the bot is online if signals haven't gone
                # out yet today — no scheduled time gate.
                if last != today:
                    print(f"\n[SignalLoop] Match day {today} — building signals...")
                    await _post_signals(today)
        except Exception as e:
            print(f"[SignalLoop Error] {e}")
        await asyncio.sleep(30)


async def _post_signals(match_date: str):
    await tg.send(
        f"⚽ <b>Analysing fixtures for {match_date}...</b>\n"
        f"4 accumulators + paper bets coming shortly."
    )
    try:
        fixtures = await fetcher.fetch_todays_fixtures()
        if not fixtures:
            print(f"[Signals] No qualifying fixtures for {match_date}")
            await tg.send(build_no_fixtures_msg(match_date))
            fstate.set("last_signal_date", match_date)
            return

        print(f"[Signals] Scoring {len(fixtures)} fixtures...")
        acca3, acca5, acca10, mixed15 = await build_signals(fixtures)

        if not acca3:
            await tg.send(build_no_fixtures_msg(match_date))
            fstate.set("last_signal_date", match_date)
            return

        # Save signals
        fstate.save_signals(match_date, acca3, acca5, acca10, mixed15, now_utc())

        # Place paper bets (before sending so odds show in message)
        bet_record = pt.place_bets(match_date, acca3, acca5, acca10, mixed15)
        fstate.save_paper_bet(match_date, bet_record)

        total_pot = sum(
            bet_record.get(k, {}).get("potential_win", 0)
            for k in ("acca3", "acca5", "mixed")
        )
        print(
            f"[PaperTrading] Bets placed — "
            f"A3:{pt.fmt_stake(bet_record['acca3']['potential_win'])}  "
            f"A5:{pt.fmt_stake(bet_record['acca5']['potential_win'])}  "
            f"Mix:{pt.fmt_stake(bet_record['mixed']['potential_win'])}"
        )

        # Send draw accas message
        await tg.send(build_signal_msg(acca3, acca5, acca10, mixed15, match_date))

        # Send mixed acca as separate message
        mixed_msg = build_mixed_signal_msg(mixed15, match_date)
        if mixed_msg:
            await tg.send(mixed_msg)

        print(
            f"[Signals] Posted — A3:{len(acca3)} A5:{len(acca5)} Mix:{len(mixed15)}"
        )

    except Exception as e:
        print(f"[Signals Error] {e}")
        await tg.send(f"⚠️ Signal build failed for {match_date}: {e}")


async def _grade_loop():
    while True:
        try:
            if not fstate.is_paused():
                now   = datetime.now(timezone.utc)
                today = today_utc()

                # ── 1. Catch up any missed past days (no time gate) ──────────
                for date in fstate.get_ungraded_signal_dates(exclude_today=today):
                    print(f"[GradeLoop] Catching up missed grade for {date}...")
                    grade = await check_results(date)
                    if grade:
                        await tg.send(build_grade_msg(grade))
                        print(f"[GradeLoop] {date} catch-up graded and posted")
                    else:
                        print(f"[GradeLoop] {date} results still unavailable")

                # ── 2. Grade today (only after 17:00 UTC) ────────────────────
                last_grade = fstate.get("last_grade_date", "")
                if (now.hour >= 17
                        and last_grade != today
                        and fstate.get("last_signal_date", "") == today):
                    print(f"[GradeLoop] Attempting to grade {today}...")
                    grade = await check_results(today)
                    if grade:
                        await tg.send(build_grade_msg(grade))
                        print(f"[GradeLoop] {today} graded and posted")
                    else:
                        print(f"[GradeLoop] Not finished yet — retry in 30 min")
        except Exception as e:
            print(f"[GradeLoop Error] {e}")
        await asyncio.sleep(1800)


async def _command_loop():
    while True:
        try:
            await tg.poll_commands()
        except Exception as e:
            print(f"[CommandLoop Error] {e}")
        await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stopped by user]")
