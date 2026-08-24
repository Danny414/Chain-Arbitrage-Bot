#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║            SOLANA ARB DETECTOR  (World Class)                   ║
║                                                                  ║
║  Meteora DAMM/DLMM · Raydium · Orca · Jupiter                  ║
║                                                                  ║
║  Features:                                                       ║
║   • Intra-chain arb detection across Solana DEXes              ║
║   • Concurrent async scanning (all tokens in parallel)          ║
║   • Jupiter pre-flight validation before every trade            ║
║   • Confidence scoring per opportunity                          ║
║   • New pool detection alerts                                    ║
║   • Persistent state (survives restarts)                        ║
║   • Full Telegram command suite                                  ║
║   • Live config via /setspread /settrade /setcooldown           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import asyncio
from datetime import datetime, timezone
import time

import bot.state as state
import bot.telegram as tg
import bot.pnl as pnl
from bot.scanner import run_scan
from bot.fetcher import close_session
from bot.alerts import build_startup_msg
from bot.config import (
    TELEGRAM_BOT_TOKEN, SCAN_INTERVAL,
)

HEARTBEAT_INTERVAL = 3600   # 1 hour


async def main():
    print("=" * 62)
    print("  SOLANA ARB DETECTOR")
    print("=" * 62)

    if not TELEGRAM_BOT_TOKEN:
        print("[ERROR] TELEGRAM_BOT_TOKEN not set in Replit Secrets.")
        return

    state.load()

    wl = state.watchlist()
    sol_count = sum(1 for v in wl.values() if v["chain"] == "sol")

    print(f"✅ SOL: {sol_count} tokens")
    live_sz = state.cfg_live_trade_size()
    live_mode = state.get("automode") == "live" and state.get("live_confirmed")
    size_label = f"LIVE ${live_sz:.0f}" if live_mode else f"${state.cfg_trade():,} (model)"
    print(f"✅ Min spread: {state.cfg_spread()}% | Trade size: {size_label} | Scan: {SCAN_INTERVAL}s")
    print(f"✅ Persistent state: bot/state.json")
    print(f"\nListening for Telegram commands...")

    await tg.send(build_startup_msg(
        sol_count=sol_count,
        spread=state.cfg_spread(),
        scan_sec=SCAN_INTERVAL,
    ))

    scan_task      = asyncio.create_task(_scan_loop())
    command_task   = asyncio.create_task(_command_loop())
    report_task    = asyncio.create_task(_report_loop())
    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    try:
        await asyncio.gather(scan_task, command_task, report_task, heartbeat_task)
    except asyncio.CancelledError:
        pass
    finally:
        scan_task.cancel()
        command_task.cancel()
        report_task.cancel()
        heartbeat_task.cancel()
        await close_session()
        await tg.send("🔴 <b>Solana Arb Detector — Offline</b>")
        print("\n[Stopped]")


async def _scan_loop():
    while True:
        try:
            await run_scan()
        except Exception as e:
            print(f"[Scan Error] {e}")
        await asyncio.sleep(SCAN_INTERVAL)


async def _command_loop():
    while True:
        try:
            await tg.poll_commands()
        except Exception as e:
            print(f"[Command Error] {e}")
        await asyncio.sleep(2)


async def _heartbeat_loop():
    """Sends a status ping to Telegram every cfg_heartbeat_interval() seconds.
    Sleeps in 30-second chunks so interval changes take effect promptly."""
    elapsed = 0
    while True:
        interval = state.cfg_heartbeat_interval()
        await asyncio.sleep(30)
        elapsed += 30
        if elapsed >= interval:
            elapsed = 0
            try:
                await _send_heartbeat()
            except Exception as e:
                print(f"[Heartbeat Error] {e}")


async def _send_heartbeat():
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode        = state.get("automode", "off").upper()
    confirmed   = state.get("live_confirmed", False)
    scan_count  = state.get("scan_count", 0)

    # ── Mode label ─────────────────────────────────────────────────────
    if mode == "LIVE" and confirmed:
        mode_line = "💸 LIVE TRADING"
    elif mode == "DRY":
        mode_line = "🧪 DRY-RUN"
    else:
        mode_line = "🔇 ALERTS ONLY"

    # ── Wallet balance (live mode only) ────────────────────────────────
    balance_line = ""
    if mode == "LIVE" and confirmed:
        try:
            import aiohttp as _aiohttp
            from bot.live_executor import get_usdc_balance, get_wallet_pubkey
            async with _aiohttp.ClientSession() as _sess:
                bal = await get_usdc_balance(_sess)
            pubkey = get_wallet_pubkey()
            balance_line = (
                f"💳 Wallet: <code>{pubkey[:6]}…{pubkey[-4:]}</code>  "
                f"USDC: <b>${bal:.4f}</b>\n"
            )
        except Exception as e:
            balance_line = f"💳 Balance check failed: {e}\n"

    # ── Trades in last hour ────────────────────────────────────────────
    cutoff      = time.time() - HEARTBEAT_INTERVAL
    all_trades  = pnl.get_all_trades()
    recent      = [t for t in all_trades if t.get("unix_ts", 0) >= cutoff]
    live_recent = [t for t in recent if t.get("mode") == "live"]
    dry_recent  = [t for t in recent if t.get("mode") == "dry_run"]

    if recent:
        wins  = sum(1 for t in recent if t.get("win"))
        net   = sum(t.get("net_profit", 0) for t in recent)
        from bot.utils import fmt_usd
        trades_line = (
            f"📊 Last hour: <b>{len(recent)} trade(s)</b>  "
            f"({wins}W / {len(recent)-wins}L)  "
            f"Net: <b>{fmt_usd(net)}</b>"
        )
        if live_recent:
            trades_line += f"  · {len(live_recent)} live"
    else:
        trades_line = "📊 Last hour: no trades executed"

    # ── Nearest gap to threshold ────────────────────────────────────────
    opps     = state.get_opportunities()
    min_conf = state.cfg_confidence()
    below    = [o for o in opps if o.get("confidence", 0) < min_conf]
    if below:
        closest = max(below, key=lambda o: o.get("confidence", 0))
        gap_line = (
            f"🔍 Nearest gap: <b>${closest['symbol']}</b>  "
            f"conf {closest['confidence']}/{min_conf}  "
            f"({closest['spread_pct']:.1f}% spread)"
        )
    else:
        gap_line = f"🔍 No suppressed gaps recently"

    # ── All-time stats footer ──────────────────────────────────────────
    stats = pnl.get_stats()
    if stats:
        from bot.utils import fmt_usd
        wr       = stats["win_rate"]
        wr_icon  = "🟢" if wr >= 60 else "🟡" if wr >= 40 else "🔴"
        stats_line = (
            f"All-time: {wr_icon} {wr:.0f}% win rate  |  "
            f"{stats['total']} trades  |  {fmt_usd(stats['total_profit'])} net"
        )
    else:
        stats_line = "All-time: no trades yet"

    msg = (
        f"💓 <b>BOT HEARTBEAT</b>  —  {now_utc_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Mode: <b>{mode_line}</b>  |  Scans: <b>{scan_count}</b>\n"
        f"{balance_line}"
        f"{trades_line}\n"
        f"{gap_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>{stats_line}</i>"
    )
    await tg.send(msg)
    print(f"[Heartbeat] Sent at {now_utc_str}")


async def _report_loop():
    """Fires the daily report at the configured UTC time once per day."""
    while True:
        try:
            now       = datetime.now(timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            hhmm      = now.strftime("%H:%M")
            target    = state.cfg_report_time()        # e.g. "08:00"
            last_sent = state.report_last_sent()       # e.g. "2026-05-03"

            if hhmm == target and last_sent != today_str:
                report = pnl.build_daily_report()
                await tg.send(report)
                state.set_report_last_sent(today_str)
                print(f"[Report] Daily report sent at {hhmm} UTC")
        except Exception as e:
            print(f"[Report Error] {e}")
        await asyncio.sleep(30)   # check every 30 s — plenty fine for minute precision


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Stopped by user]")
