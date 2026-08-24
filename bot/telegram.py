"""
Telegram send + async polling with full command handling.
"""
import asyncio
import aiohttp
from collections import defaultdict
from bot.config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    CHAIN_IDS, CHAIN_EMOJIS, CHAIN_LABELS, SCAN_INTERVAL
)
from bot.utils import fmt_usd, now_utc
import bot.state as state
import bot.pnl as pnl

TG_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
_offset = 0
_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout = aiohttp.ClientTimeout(total=12)
        _session = aiohttp.ClientSession(timeout=timeout)
    return _session


async def send(msg: str, chat_id: str | None = None, parse_mode: str = "HTML"):
    cid = str(chat_id or TELEGRAM_CHAT_ID)
    if not TELEGRAM_BOT_TOKEN:
        print(f"[TG MOCK] {msg[:120]}")
        return
    session = await _get_session()
    payload = {
        "chat_id": cid,
        "text": msg,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(f"{TG_BASE}/sendMessage", json=payload) as r:
            if r.status == 400:
                # Retry without parse_mode on HTML errors
                payload["parse_mode"] = ""
                async with session.post(f"{TG_BASE}/sendMessage", json=payload):
                    pass
            elif not r.ok:
                text = await r.text()
                print(f"[TG] {r.status}: {text[:80]}")
    except Exception as e:
        print(f"[TG Error] {e}")


async def poll_commands():
    global _offset
    session = await _get_session()
    try:
        async with session.get(
            f"{TG_BASE}/getUpdates",
            params={"offset": _offset, "timeout": 3, "limit": 20}
        ) as r:
            data = await r.json(content_type=None)
            updates = data.get("result", [])
    except Exception as e:
        print(f"[TG Poll] {e}")
        return

    for u in updates:
        _offset = u["update_id"] + 1
        msg  = u.get("message", {})
        text = (msg.get("text") or "").strip()
        cid  = str(msg.get("chat", {}).get("id", ""))
        if text:
            await _handle(text, cid)


async def _handle(text: str, cid: str):
    low = text.lower()

    # ── /add sol BONK address ────────────────────────────────────
    if low.startswith("/add "):
        parts = text.split()
        if len(parts) == 4:
            chain, sym, addr = parts[1].lower(), parts[2].upper(), parts[3]
            if chain not in CHAIN_IDS:
                await send(f"❌ Unknown chain '{chain}'. Only 'sol' is supported.", chat_id=cid)
            else:
                key = state.add_token(chain, sym, addr)
                ce  = CHAIN_EMOJIS.get(chain, "")
                await send(f"✅ Added <b>{ce} {sym}</b> (SOL) to watchlist.\n"
                           f"Address: <code>{addr}</code>", chat_id=cid)
        else:
            await send("Usage: /add sol SYMBOL ADDRESS\nExample: /add sol BONK DezXAZ...", chat_id=cid)

    # ── /remove sol BONK ─────────────────────────────────────────
    elif low.startswith("/remove "):
        parts = text.split()
        if len(parts) == 3:
            removed, key = state.remove_token(parts[1].lower(), parts[2].upper())
            if removed:
                await send(f"✅ Removed <b>{key}</b> from watchlist.", chat_id=cid)
            else:
                await send(f"❌ Not found: <b>{parts[1].lower()}:{parts[2].upper()}</b>", chat_id=cid)
        else:
            await send("Usage: /remove CHAIN SYMBOL\nExample: /remove sol BONK", chat_id=cid)

    # ── /watchlist ───────────────────────────────────────────────
    elif low == "/watchlist":
        wl = state.watchlist()
        by_chain = defaultdict(list)
        for k, v in wl.items():
            by_chain[v["chain"]].append(v["symbol"])
        lines = [f"📋 <b>Watching {len(wl)} tokens:</b>"]
        syms = by_chain.get("sol", [])
        if syms:
            lines.append(f"\n🟣 <b>SOL</b>: {', '.join(sorted(syms))}")
        await send("\n".join(lines), chat_id=cid)

    # ── /opportunities ───────────────────────────────────────────
    elif low == "/opportunities":
        log = state.get_opportunities()
        if not log:
            await send("No opportunities detected yet.", chat_id=cid)
        else:
            recent = log[-10:]
            lines  = [f"📊 <b>Last {len(recent)} Opportunities:</b>"]
            for o in reversed(recent):
                if o.get("type") == "cross":
                    bce = CHAIN_EMOJIS.get(o.get("buy_chain",""), "")
                    sce = CHAIN_EMOJIS.get(o.get("sell_chain",""), "")
                    lines.append(
                        f"🌐 ${o['symbol']} {bce}→{sce} "
                        f"<b>{o['spread_pct']:.1f}%</b> | "
                        f"Net: {fmt_usd(o['net_profit'])} | "
                        f"{o['detected_at'][11:16]} UTC"
                    )
                else:
                    ce = CHAIN_EMOJIS.get(o.get("chain",""), "")
                    lines.append(
                        f"{ce} ${o['symbol']} — "
                        f"<b>{o['spread_pct']:.1f}%</b> | "
                        f"Net: {fmt_usd(o['net_profit'])} | "
                        f"{o['detected_at'][11:16]} UTC"
                    )
            await send("\n".join(lines), chat_id=cid)

    # ── /topgaps ─────────────────────────────────────────────────
    elif low == "/topgaps":
        log = state.get_opportunities()
        if not log:
            await send("No opportunities logged yet.", chat_id=cid)
        else:
            top = sorted(log, key=lambda x: x["spread_pct"], reverse=True)[:5]
            lines = ["🏆 <b>Top 5 Gaps (all time):</b>"]
            for i, o in enumerate(top, 1):
                sym  = o["symbol"]
                ce   = CHAIN_EMOJIS.get(o.get("chain", o.get("buy_chain","")), "🌐")
                lines.append(
                    f"{i}. {ce} <b>${sym}</b> {o['spread_pct']:.2f}% | "
                    f"Net {fmt_usd(o['net_profit'])} | {o['detected_at'][5:16]} UTC"
                )
            await send("\n".join(lines), chat_id=cid)

    # ── /stats ───────────────────────────────────────────────────
    elif low == "/stats":
        log   = state.get_opportunities()
        intra = [o for o in log if o.get("type") == "intra"]
        cross = [o for o in log if o.get("type") == "cross"]
        pos   = [o for o in log if o.get("net_profit", 0) > 0]
        avg_spread = (sum(o["spread_pct"] for o in log) / len(log)) if log else 0

        # ── Actual dry-run trade stats ────────────────────────────
        dr_stats = pnl.get_stats()
        if dr_stats:
            wr      = dr_stats["win_rate"]
            wr_icon = "🟢" if wr >= 60 else "🟡" if wr >= 40 else "🔴"
            dr_lines = (
                f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧪 <b>Dry-Run Trades</b>\n"
                f"Executed: <b>{dr_stats['total']}</b>  "
                f"({dr_stats['wins']}W / {dr_stats['losses']}L)\n"
                f"Win rate: <b>{wr_icon} {wr:.1f}%</b>\n"
                f"Net P&amp;L: <b>{fmt_usd(dr_stats['total_profit'])}</b>  "
                f"(avg {fmt_usd(dr_stats['avg_net'])} / trade)\n"
                f"<i>Use /pnl for full breakdown · /trades for trade list</i>"
            )
        else:
            dr_lines = (
                f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧪 <b>Dry-Run Trades</b>\n"
                f"No trades recorded yet — use /automode dry"
            )

        await send(
            f"📈 <b>Session Statistics</b>\n"
            f"Scans completed: <b>{state.get('scan_count', 0)}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 <b>Opportunities Detected</b>\n"
            f"Total: <b>{len(log)}</b>  ({len(intra)} intra · {len(cross)} cross)\n"
            f"Net-positive gaps: <b>{len(pos)}</b>\n"
            f"Avg spread: <b>{avg_spread:.2f}%</b>"
            f"{dr_lines}\n"
            f"⏰ {now_utc()}", chat_id=cid
        )

    # ── /status ──────────────────────────────────────────────────
    elif low == "/status":
        wl     = state.watchlist()
        by_chain = defaultdict(int)
        for v in wl.values():
            by_chain[v["chain"]] += 1
        paused = "⏸ PAUSED" if state.is_paused() else "▶️ RUNNING"
        live_sz = state.cfg_live_trade_size()
        await send(
            f"✅ <b>Arb Detector — {paused}</b>\n"
            f"🟣 SOL: {by_chain['sol']} tokens\n"
            f"Scans: <b>{state.get('scan_count', 0)}</b> | "
            f"Opportunities: <b>{len(state.get_opportunities())}</b>\n"
            f"Min spread: <b>{state.cfg_spread()}%</b> | "
            f"Live trade size: <b>${live_sz:.2f}</b>  → /setlivetrade VALUE\n"
            f"Cooldown: <b>{state.cfg_cooldown()}s</b> | "
            f"Min liq: <b>{fmt_usd(state.cfg_liquidity())}</b>\n"
            f"⏰ {now_utc()}", chat_id=cid
        )

    # ── /config ──────────────────────────────────────────────────
    elif low == "/config":
        conf_val = state.cfg_confidence()
        conf_label = "🟢" if conf_val >= 70 else "🟡" if conf_val >= 40 else "🔴"
        await send(
            f"⚙️ <b>Current Config:</b>\n"
            f"Min spread:     <b>{state.cfg_spread()}%</b>  → /setspread VALUE\n"
            f"Trade size:     <b>${state.cfg_trade():,}</b>  → /settrade VALUE\n"
            f"Cooldown:       <b>{state.cfg_cooldown()}s</b>  → /setcooldown VALUE\n"
            f"Min liquidity:  <b>{fmt_usd(state.cfg_liquidity())}</b>  → /setliquidity VALUE\n"
            f"Min confidence: <b>{conf_label} {conf_val}/100</b>  → /setconfidence VALUE\n"
            f"Scan interval:  <b>{SCAN_INTERVAL}s</b>  (fixed)\n"
            f"Paused:         <b>{state.is_paused()}</b>", chat_id=cid
        )

    # ── /setspread VALUE ─────────────────────────────────────────
    elif low.startswith("/setspread "):
        try:
            val = float(text.split()[1])
            if val < 0.1 or val > 99:
                raise ValueError
            state.set("min_spread_pct", val)
            await send(f"✅ Min spread set to <b>{val}%</b>", chat_id=cid)
        except Exception:
            await send("Usage: /setspread VALUE (e.g. /setspread 2.5)", chat_id=cid)

    # ── /settrade VALUE ──────────────────────────────────────────
    elif low.startswith("/settrade "):
        try:
            val = float(text.split()[1])
            if val < 1:
                raise ValueError
            state.set("trade_size_usdc", val)
            await send(f"✅ Trade size set to <b>${val:,.0f} USDC</b>", chat_id=cid)
        except Exception:
            await send("Usage: /settrade VALUE (e.g. /settrade 5000)", chat_id=cid)

    # ── /setcooldown VALUE ───────────────────────────────────────
    elif low.startswith("/setcooldown "):
        try:
            val = int(text.split()[1])
            if val < 0:
                raise ValueError
            state.set("alert_cooldown", val)
            await send(f"✅ Alert cooldown set to <b>{val}s</b>", chat_id=cid)
        except Exception:
            await send("Usage: /setcooldown SECONDS (e.g. /setcooldown 120)", chat_id=cid)

    # ── /setconfidence VALUE ─────────────────────────────────────
    elif low.startswith("/setconfidence "):
        try:
            val = int(text.split()[1])
            if val < 0 or val > 100:
                raise ValueError
            state.set("min_confidence", val)
            label = "🔇 Noise suppressed" if val >= 50 else "⚠️ Most gaps will alert"
            await send(
                f"✅ Min confidence set to <b>{val}/100</b>\n"
                f"{label}\n"
                f"<i>Gaps below {val} are logged silently — use /opportunities to review them.</i>",
                chat_id=cid
            )
        except Exception:
            await send(
                "Usage: /setconfidence VALUE (0–100)\n"
                "Example: /setconfidence 40\n\n"
                "Score guide:\n"
                "  70+ 🟢 High confidence — liquid, active pools\n"
                "  40–69 🟡 Medium — worth watching\n"
                "  0–39 🔴 Low — likely stale or thin pools",
                chat_id=cid
            )

    # ── /setliquidity VALUE ──────────────────────────────────────
    elif low.startswith("/setliquidity "):
        try:
            val = float(text.split()[1])
            if val < 0:
                raise ValueError
            state.set("min_liquidity_usd", val)
            await send(f"✅ Min liquidity set to <b>{fmt_usd(val)}</b>", chat_id=cid)
        except Exception:
            await send("Usage: /setliquidity VALUE (e.g. /setliquidity 5000)", chat_id=cid)

    # ── /report ──────────────────────────────────────────────────
    elif low == "/report":
        await send(pnl.build_daily_report(), chat_id=cid)

    # ── /setreporttime HH:MM ─────────────────────────────────────
    elif low.startswith("/setreporttime "):
        try:
            val = text.split()[1].strip()
            h, m = val.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                raise ValueError
            val = f"{int(h):02d}:{int(m):02d}"
            state.set("report_time", val)
            await send(
                f"✅ Daily report scheduled for <b>{val} UTC</b> every day.\n"
                f"Use /report any time for an immediate report.",
                chat_id=cid
            )
        except Exception:
            await send(
                "Usage: /setreporttime HH:MM  (24-hour UTC)\n"
                "Example: /setreporttime 08:00\n"
                "         /setreporttime 20:30",
                chat_id=cid
            )

    # ── /automode dry|live|off ───────────────────────────────────
    elif low.startswith("/automode"):
        parts = low.split()
        mode  = parts[1] if len(parts) > 1 else ""
        if mode == "dry":
            state.set("automode", "dry")
            state.set("live_confirmed", False)
            await send(
                "🧪 <b>Dry-run mode ON</b>\n"
                "The bot will now simulate every high-confidence trade automatically.\n"
                "No real money moves. Results tracked via /pnl and /trades.\n\n"
                f"Sim size per trade: <b>${state.cfg_max_sim_size():.0f}</b>  → /setmaxsize VALUE",
                chat_id=cid
            )
        elif mode == "live":
            state.set("automode", "live")
            state.set("live_confirmed", False)
            live_sz = state.cfg_live_trade_size()
            await send(
                "⚠️ <b>LIVE MODE ARMED — NOT YET ACTIVE</b>\n\n"
                f"Trade size: <b>${live_sz:.2f} per trade</b>  → /setlivetrade VALUE (max $50)\n"
                "Slippage guard: <b>1.5%</b> — trades abort if on-chain impact exceeds this.\n"
                "SOL intra-chain only.\n\n"
                "💡 <b>Recommended:</b> set size to $10–$20 before confirming.\n"
                "   At $1 gas eats 5% of every trade. At $10 gas is just 0.5%.\n"
                "   Use /balance to check available USDC first.\n\n"
                "⚡ Send /confirmgo to activate live trading.\n"
                "🔴 Send /automode off or /automode dry to cancel.",
                chat_id=cid
            )
        elif mode == "off":
            state.set("automode", "off")
            state.set("live_confirmed", False)
            await send("🔴 <b>Auto-execution OFF.</b> Bot is in alert-only mode.", chat_id=cid)
        else:
            current = state.get("automode", "off")
            confirmed = state.get("live_confirmed", False)
            status = f"{current.upper()}"
            if current == "live":
                status += " ✅ ACTIVE" if confirmed else " ⏳ AWAITING /confirmgo"
            await send(
                f"Current mode: <b>{status}</b>\n\n"
                "Usage: /automode dry  — simulate trades (no real money)\n"
                "       /automode live — arm live trading (requires /confirmgo)\n"
                "       /automode off  — alert-only mode",
                chat_id=cid
            )

    # ── /confirmgo ───────────────────────────────────────────────
    elif low == "/confirmgo":
        if state.get("automode") != "live":
            await send(
                "⚠️ Not in live mode. Send /automode live first, then /confirmgo.",
                chat_id=cid
            )
        elif state.get("live_confirmed"):
            await send("💸 Live trading is already active.", chat_id=cid)
        else:
            state.set("live_confirmed", True)
            from bot.live_executor import get_wallet_pubkey, get_usdc_balance
            import aiohttp as _aiohttp
            live_sz = state.cfg_live_trade_size()
            try:
                pubkey = get_wallet_pubkey()
                async with _aiohttp.ClientSession() as _sess:
                    bal = await get_usdc_balance(_sess)
                wallet_info = (
                    f"Wallet: <code>{pubkey[:6]}…{pubkey[-4:]}</code>\n"
                    f"USDC balance: <b>${bal:.4f}</b>"
                )
            except Exception as e:
                wallet_info = f"(Balance check failed: {e})"
            await send(
                "💸 <b>LIVE TRADING ACTIVATED</b>\n\n"
                f"{wallet_info}\n"
                f"Trade size: <b>${live_sz:.2f}</b> per trade  → /setlivetrade VALUE\n"
                "Slippage guard: <b>1.5%</b>\n\n"
                "The bot will now execute real SOL swaps via Jupiter on every "
                "high-confidence intra-chain gap that Jupiter confirms is profitable.\n"
                "Results posted here with Solscan links.\n\n"
                "Send /automode dry or /automode off to stop live trading.",
                chat_id=cid
            )

    # ── /balance ─────────────────────────────────────────────────
    elif low == "/balance":
        from bot.live_executor import get_wallet_pubkey, get_usdc_balance
        import aiohttp as _aiohttp
        try:
            pubkey = get_wallet_pubkey()
            async with _aiohttp.ClientSession() as _sess:
                bal = await get_usdc_balance(_sess)
            mode = state.get("automode", "off")
            await send(
                f"💳 <b>Wallet Balance</b>\n"
                f"Address: <code>{pubkey[:6]}…{pubkey[-4:]}</code>\n"
                f"USDC: <b>${bal:.4f}</b>\n"
                f"Mode: <b>{mode.upper()}</b>",
                chat_id=cid
            )
        except Exception as e:
            await send(f"⚠️ Balance check failed: {e}", chat_id=cid)

    # ── /setlivetrade VALUE ──────────────────────────────────────
    elif low.startswith("/setlivetrade "):
        try:
            val = float(text.split()[1])
            if val < 1 or val > 50:
                raise ValueError
            state.set("live_trade_size_usdc", val)
            gas  = 0.05
            pct  = (gas / val) * 100
            await send(
                f"✅ Live trade size set to <b>${val:.2f} USDC</b>\n\n"
                f"Gas cost as % of trade: <b>{pct:.1f}%</b>\n"
                f"A 4% Jupiter round-trip at this size → net <b>{fmt_usd(val * 0.04 - gas)}</b>\n\n"
                f"<i>Make sure your wallet holds at least ${val + 0.10:.2f} USDC "
                f"(trade + SOL for priority fees).\n"
                f"Max allowed: $50. Use /balance to check wallet.</i>",
                chat_id=cid
            )
        except Exception:
            await send(
                "Usage: /setlivetrade AMOUNT  (range $1 – $50)\n\n"
                "Example: /setlivetrade 10\n\n"
                "Why this matters:\n"
                "  At $1  → gas is 5% of trade, nearly impossible to profit\n"
                "  At $10 → gas is 0.5%, a 1% gap earns ~$0.05 net\n"
                "  At $20 → gas is 0.25%, same 1% gap earns ~$0.15 net\n\n"
                "Use /balance to check available USDC before raising size.",
                chat_id=cid
            )

    # ── /setmaxsize VALUE ────────────────────────────────────────
    elif low.startswith("/setmaxsize "):
        try:
            val = float(text.split()[1])
            if val < 1 or val > 100_000:
                raise ValueError
            state.set("max_sim_size", val)
            await send(f"✅ Max sim size set to <b>${val:,.0f}</b> per dry-run trade.", chat_id=cid)
        except Exception:
            await send("Usage: /setmaxsize VALUE (e.g. /setmaxsize 100)\nRange: $1 – $100,000", chat_id=cid)

    # ── /pnl ─────────────────────────────────────────────────────
    elif low == "/pnl":
        stats = pnl.get_stats()
        await send(pnl.fmt_pnl_summary(stats), chat_id=cid)

    # ── /trades ──────────────────────────────────────────────────
    elif low == "/trades":
        trades = pnl.get_trades(limit=10)
        if not trades:
            await send(
                "📋 No dry-run trades yet.\n"
                "Use /automode dry to start simulating trades automatically.",
                chat_id=cid
            )
        else:
            lines = [f"📋 <b>Last {len(trades)} Dry-Run Trades:</b>\n"]
            for i, t in enumerate(reversed(trades), 1):
                lines.append(pnl.fmt_trade(t, idx=i))
                lines.append("")
            stats = pnl.get_stats()
            wr    = stats.get("win_rate", 0)
            lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"Win rate: <b>{'🟢' if wr>=60 else '🟡' if wr>=40 else '🔴'} {wr:.1f}%</b>  |  "
                         f"Total P&L: <b>{fmt_usd(stats.get('total_profit', 0))}</b>  |  "
                         f"Use /pnl for full breakdown")
            await send("\n".join(lines), chat_id=cid)

    # ── /sethb VALUE ─────────────────────────────────────────────
    elif low.startswith("/sethb"):
        parts = low.split()
        if len(parts) < 2:
            current = state.cfg_heartbeat_interval()
            mins    = current // 60
            await send(
                f"💓 Heartbeat interval: <b>{mins} min</b>\n\n"
                "Usage: /sethb MINUTES  (e.g. /sethb 30 or /sethb 60)\n"
                "Range: 5 – 1440 minutes",
                chat_id=cid
            )
        else:
            try:
                mins = int(parts[1])
                if not (5 <= mins <= 1440):
                    raise ValueError
                secs = mins * 60
                state.set("heartbeat_interval", secs)
                await send(
                    f"✅ Heartbeat set to every <b>{mins} minute{'s' if mins != 1 else ''}</b>.\n"
                    f"Next ping within {mins} min.",
                    chat_id=cid
                )
            except (ValueError, IndexError):
                await send(
                    "Usage: /sethb MINUTES  (e.g. /sethb 30)\nRange: 5 – 1440 minutes",
                    chat_id=cid
                )

    # ── /pause ───────────────────────────────────────────────────
    elif low == "/pause":
        state.set_paused(True)
        await send("⏸ <b>Scanner paused.</b> Use /resume to restart.", chat_id=cid)

    # ── /resume ──────────────────────────────────────────────────
    elif low == "/resume":
        state.set_paused(False)
        await send("▶️ <b>Scanner resumed.</b>", chat_id=cid)

    # ── /help ────────────────────────────────────────────────────
    elif low == "/help":
        await send(
            "🤖 <b>Solana Arb Bot — Commands</b>\n\n"
            "<b>Watchlist:</b>\n"
            "/add sol SYMBOL ADDRESS — add token\n"
            "/remove CHAIN SYMBOL — remove token\n"
            "/watchlist — view all tokens\n\n"
            "<b>Opportunities:</b>\n"
            "/opportunities — last 10 detected gaps\n"
            "/topgaps — top 5 gaps by spread size\n"
            "/stats — session statistics\n\n"
            "<b>Control:</b>\n"
            "/pause — pause scanning\n"
            "/resume — resume scanning\n"
            "/status — bot health & config\n"
            "/config — view all settings\n\n"
            "<b>Dry-Run / Auto:</b>\n"
            "/automode dry — simulate trades (no real money)\n"
            "/automode live — arm live trading\n"
            "/confirmgo — activate live trading (after /automode live)\n"
            "/automode off — alert-only mode\n"
            "/balance — check wallet USDC balance\n"
            "/pnl — full win/loss P&amp;L breakdown\n"
            "/trades — last 10 trades (dry-run + live)\n"
            "/setmaxsize VALUE — sim position size ($)\n\n"
            "<b>Reports:</b>\n"
            "/report — send daily summary now\n"
            "/setreporttime HH:MM — schedule daily report (UTC)\n\n"
            "<b>Config:</b>\n"
            "/setspread VALUE — min spread % (e.g. 2.5)\n"
            "/settrade VALUE — signal trade size in USDC\n"
            "/setcooldown SECS — re-alert cooldown\n"
            "/setliquidity VALUE — min pool liquidity\n"
            "/setconfidence VALUE — min confidence 0–100\n"
            "  (gaps below threshold are logged, not alerted)\n\n"
            "<b>Chains:</b> sol · bsc  |  Live trading: SOL only\n"
            "<i>Detects intra-chain and cross-chain arb.</i>",
            chat_id=cid
        )
