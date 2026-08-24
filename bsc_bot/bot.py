"""
BSC Whale Alert Bot — Telegram Interface

Handles:
  - Sending alerts (rate-limited queue)
  - Long-polling getUpdates for commands
  - /start /help /status /summary /top /pause /resume /config
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from bsc_bot.config import TG_TOKEN, TG_CHAT_ID, THRESHOLD_BTC, THRESHOLD_ETH, THRESHOLD_GOLD, THRESHOLD_BNB, THRESHOLD_ALT
from bsc_bot.monitor import get_hot_tokens, get_coin_summary

logger = logging.getLogger("bsc_bot.bot")

TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

# ── User access control ────────────────────────────────────────────────────────
_USERS_FILE = Path(__file__).parent / "allowed_users.json"

def _load_users() -> dict[str, str | None]:
    """Load {username_lower: chat_id_or_None} from disk. Migrates old list format."""
    try:
        if _USERS_FILE.exists():
            data = json.loads(_USERS_FILE.read_text())
            if isinstance(data, list):
                return {str(u).lower().lstrip("@"): None for u in data}
            if isinstance(data, dict):
                return {k.lower().lstrip("@"): v for k, v in data.items()}
    except Exception:
        pass
    return {}

def _save_users(users: dict[str, str | None]) -> None:
    try:
        _USERS_FILE.write_text(json.dumps(users, indent=2))
    except Exception as exc:
        logger.warning(f"[Users] Save failed: {exc}")


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fmt_usd(v: float) -> str:
    if v == 0:
        return "💲Unknown"
    a = abs(v)
    if a >= 1_000_000_000:
        return f"${v / 1_000_000_000:.2f}B"
    if a >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if a >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.2f}"


def _fmt_amt(amount: float, symbol: str) -> str:
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.2f}B {symbol}"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M {symbol}"
    if amount >= 1_000:
        return f"{amount / 1_000:.2f}K {symbol}"
    if amount >= 1:
        return f"{amount:.4f} {symbol}"
    return f"{amount:.8f} {symbol}"


def _short(addr: str) -> str:
    return f"<code>{addr[:6]}…{addr[-4:]}</code>"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def _parse_window(s: str) -> int | None:
    """Parse a time window token (30m, 1h, 2h, 5h, 12h) → seconds. None if invalid."""
    s = s.strip().lower()
    if s.endswith("m"):
        try:
            return int(s[:-1]) * 60
        except ValueError:
            return None
    if s.endswith("h"):
        try:
            return int(s[:-1]) * 3600
        except ValueError:
            return None
    return None


def _whale_score(usd_value: float, threshold: float) -> str:
    """Visual whale score — how many times above threshold this move is."""
    if threshold == 0 or usd_value == 0:
        return ""
    ratio = usd_value / threshold
    if ratio >= 10:
        return " 🦈🦈🦈 (10x+ threshold)"
    if ratio >= 5:
        return " 🦈🦈 (5x+ threshold)"
    if ratio >= 2:
        return " 🦈 (2x+ threshold)"
    return ""


# ── WhaleBot ─────────────────────────────────────────────────────────────────

class WhaleBot:
    def __init__(self):
        self._queue             = asyncio.Queue(maxsize=500)
        self._sent              = 0
        self._start_time        = time.time()
        self._monitor           = None
        self._update_offset     = 0
        self._allowed_users: dict[str, str | None] = _load_users()

    def set_monitor(self, monitor):
        self._monitor = monitor

    async def run(self):
        if not TG_TOKEN:
            logger.error("BSC_TG_TOKEN not set — Telegram disabled")
            return
        async with aiohttp.ClientSession() as session:
            self._session = session
            await self._send_raw(self._startup_msg())
            logger.info("Telegram bot online")
            await asyncio.gather(
                self._dispatch_loop(),
                self._poll_commands(),
                self._hot_tokens_loop(),
                self._hot_tokens_loop_3h(),
            )

    # ── Alert queue ───────────────────────────────────────────────────────────
    async def _dispatch_loop(self):
        """Rate-limited alert sender — max ~2 messages/sec."""
        while True:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                await self._send_raw(msg)
                self._sent += 1
                await asyncio.sleep(0.5)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error(f"Dispatch error: {exc}")

    async def send_alert(
        self,
        signal: dict,
        symbol: str,
        amount: float,
        usd_value: float,
        total_usd: float,
        count: int,
        price: float,
        market_cap: float = 0.0,
        threshold: float = 0.0,
        link: str = "",
        from_addr: str = "",
        to_addr: str = "",
        block_time: int = 0,
    ):
        """Format and enqueue a whale alert."""
        emoji     = signal["emoji"]
        label     = signal["label"]
        direction = signal["direction"]
        note      = signal["note"]
        impact    = signal["impact"]
        from_tag  = signal["from_tag"]
        to_tag    = signal["to_tag"]

        price_str = f"${price:,.4f}" if price >= 0.0001 else (f"${price:.8f}" if price > 0 else "Unknown")
        mc_str    = f"📊 <b>Mkt Cap:</b> {_fmt_usd(market_cap)}" if market_cap > 0 else ""

        agg_line = (
            f"\n🔁 <b>Tranche #{count}</b> | 24h running total: <b>{_fmt_usd(total_usd)}</b>"
            if count > 1 else ""
        )

        score_str = _whale_score(usd_value, threshold)

        # Block time for age indicator
        age_str = ""
        if block_time:
            age_secs = int(time.time()) - block_time
            if age_secs < 120:
                age_str = f" · {age_secs}s ago"
            elif age_secs < 3600:
                age_str = f" · {age_secs//60}m ago"

        lines = [
            f"{emoji} <b>{label}</b> — <code>{symbol}</code>{score_str}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💰 <b>Amount:</b> {_fmt_amt(amount, symbol)}",
            f"💵 <b>Value:</b> {_fmt_usd(usd_value)}   <i>({price_str}/token)</i>",
            mc_str,
            f"📤 <b>From:</b> {from_tag}",
            f"📥 <b>To:</b> {to_tag}",
            f"🔀 <b>Direction:</b> {direction}",
            f"📌 {note}",
            f"🎯 {impact}",
            agg_line,
            f"🔍 <a href=\"{link}\">Verify on BscScan</a>",
            f"⛓ BNB Smart Chain · <i>{_now_utc()}{age_str}</i>",
        ]

        msg = "\n".join(l for l in lines if l)
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping alert")

    async def send_signal_card(self, card: str):
        """Enqueue a BUY/SELL signal card (onchain flow primary, TA confirms)."""
        try:
            self._queue.put_nowait(card)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping signal card")

    # ── Hot tokens periodic report ────────────────────────────────────────────

    async def _hot_tokens_loop(self):
        """Post 🔥 Hot Tokens (30 min) at every :00 and :30 past the hour."""
        import time as _time
        now = _time.time()
        sph = now % 3600
        wait = (1800 - sph) if sph < 1800 else (3600 - sph)
        if wait < 120:
            wait += 1800
        logger.info(f"[HotTokens] First 30min report in {wait / 60:.1f} min")
        await asyncio.sleep(wait)
        while True:
            try:
                await self._send_raw(self._hot_tokens_msg())
                logger.info("[HotTokens] 30min report posted")
            except Exception as exc:
                logger.error(f"[HotTokens] Error: {exc}")
            await asyncio.sleep(1800)

    async def _hot_tokens_loop_3h(self):
        """Post 🔥 Hot Tokens (3h) at 00:00, 03:00, 06:00 … 21:00 UTC."""
        import time as _time
        now  = _time.time()
        spb  = now % 10800          # seconds past current 3h boundary
        wait = 10800 - spb
        if wait < 120:
            wait += 10800
        logger.info(f"[HotTokens3h] First 3h report in {wait / 60:.1f} min")
        await asyncio.sleep(wait)
        while True:
            try:
                await self._send_raw(self._hot_tokens_msg(10800, "3 Hours"))
                logger.info("[HotTokens3h] 3h report posted")
            except Exception as exc:
                logger.error(f"[HotTokens3h] Error: {exc}")
            await asyncio.sleep(10800)

    def _hot_tokens_msg(self, window_secs: int = 1800, label: str = "30 Min") -> str:
        top_n   = 15 if window_secs >= 10800 else 10
        tokens  = get_hot_tokens(window_secs=window_secs, top_n=top_n)
        now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        title   = f"🔥 <b>Hot Tokens — Last {label} | BSC</b>"

        if not tokens:
            return (
                f"{title}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<i>No qualifying moves recorded yet.</i>\n"
                f"\n⏰ Time: {now_str}"
            )

        lines = [title, "━━━━━━━━━━━━━━━━━━━━"]
        for i, t in enumerate(tokens, 1):
            net_emoji = "🟢" if t["net"] == "buy" else ("🔴" if t["net"] == "sell" else "⚪")
            net_label = "Accum" if t["net"] == "buy" else ("Distrib" if t["net"] == "sell" else "Neutral")
            lines.append(
                f"#{i} <b>{t['symbol']}</b>  {_fmt_usd(t['total_usd'])}  "
                f"({t['moves']} moves) | {net_emoji} {net_label}"
            )
            lines.append(f"   ↗ {_fmt_usd(t['buy_usd'])}  ↘ {_fmt_usd(t['sell_usd'])}")

        lines.append(f"\n⏰ Time: {now_str}")
        return "\n".join(lines)

    # ── Command polling ───────────────────────────────────────────────────────
    async def _poll_commands(self):
        """Long-poll Telegram getUpdates."""
        while True:
            try:
                async with self._session.get(
                    f"{TG_API}/getUpdates",
                    params={"offset": self._update_offset, "timeout": 30},
                    timeout=aiohttp.ClientTimeout(total=40),
                ) as r:
                    if r.status != 200:
                        await asyncio.sleep(5)
                        continue
                    data = await r.json()
                    for update in data.get("result", []):
                        self._update_offset = update["update_id"] + 1
                        await self._handle_update(update)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug(f"Poll error: {exc}")
                await asyncio.sleep(5)

    async def _handle_update(self, update: dict):
        msg     = update.get("message", {})
        text    = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not text.startswith("/"):
            return

        from_user = msg.get("from") or {}
        username  = (from_user.get("username") or "").lower().lstrip("@")
        is_owner  = (chat_id == TG_CHAT_ID)

        parts = text.split()
        cmd   = parts[0].lower().lstrip("/").split("@")[0]

        # ── User management — owner-only, bypasses access gate ────────────────
        if cmd == "enable":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            target = parts[1].lower().lstrip("@") if len(parts) > 1 else ""
            if not target:
                await self._send_to(chat_id, "⚠️ Usage: /enable username")
                return
            self._allowed_users[target] = self._allowed_users.get(target)  # preserve existing chat_id
            _save_users(self._allowed_users)
            await self._send_to(chat_id,
                f"✅ <b>@{target}</b> enabled — unlimited access granted.\n\n"
                "⚠️ They must open a private chat with this bot and send "
                "<code>/start</code> at least once — until then the live feed "
                "cannot reach them.")
            return

        if cmd == "disable":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            target = parts[1].lower().lstrip("@") if len(parts) > 1 else ""
            if not target:
                await self._send_to(chat_id, "⚠️ Usage: /disable username")
                return
            self._allowed_users.pop(target, None)
            _save_users(self._allowed_users)
            await self._send_to(chat_id,
                f"🚫 <b>@{target}</b> removed — access revoked.")
            return

        if cmd == "users":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            if not self._allowed_users:
                await self._send_to(chat_id,
                    "👥 <b>No users enabled yet.</b>\n"
                    "Use /enable username to grant access.")
            else:
                lines = ["👥 <b>Enabled Users — BSC Bot:</b>"]
                for u, cid in sorted(self._allowed_users.items()):
                    status = "✅ live feed active" if cid else "⏳ awaiting /start"
                    lines.append(f"  • @{u} — {status}")
                await self._send_to(chat_id, "\n".join(lines))
            return

        # ── Access gate ────────────────────────────────────────────────────────
        is_allowed = is_owner or (username and username in self._allowed_users)
        if not is_allowed:
            hint = f"<code>/enable {username}</code>" if username else "<code>/enable your_username</code>"
            await self._send_to(chat_id,
                "⛔ <b>Access Denied</b>\n"
                f"Ask the bot owner to grant access: {hint}")
            return

        # ── Admin-only commands — owner alone, never delegated to enabled users ──
        if cmd in ("config", "pause", "resume", "blocktoken", "unblocktoken") and not is_owner:
            await self._send_to(chat_id, "⛔ Owner-only command.")
            return

        # ── Register chat_id so live feed reaches this user ───────────────────
        if username and username in self._allowed_users and self._allowed_users.get(username) != chat_id:
            self._allowed_users[username] = chat_id
            _save_users(self._allowed_users)

        # ── Command dispatch ───────────────────────────────────────────────────
        if cmd == "coininfo":
            symbol     = parts[1].upper() if len(parts) > 1 else ""
            window_str = parts[2]         if len(parts) > 2 else None
            await self._cmd_coininfo(chat_id, symbol, window_str)
            return

        # ── Multi-arg commands ─────────────────────────────────────────────────
        if cmd == "blocktoken":
            sym = parts[1].upper() if len(parts) > 1 else ""
            if not sym:
                await self._send_to(chat_id, "Usage: /blocktoken SYMBOL")
                return
            if self._monitor:
                self._monitor.add_block(sym)
            await self._send_to(chat_id, f"🚫 <b>{sym}</b> blocked — no more alerts for this token.")
            return

        if cmd == "unblocktoken":
            sym = parts[1].upper() if len(parts) > 1 else ""
            if not sym:
                await self._send_to(chat_id, "Usage: /unblocktoken SYMBOL")
                return
            if self._monitor:
                ok = self._monitor.remove_block(sym)
                if ok:
                    await self._send_to(chat_id, f"✅ <b>{sym}</b> unblocked — alerts will resume.")
                else:
                    await self._send_to(chat_id, f"⛔ <b>{sym}</b> is permanently blocked and cannot be unblocked.")
            return

        if cmd == "blocklist":
            bl = self._monitor.get_custom_blocklist() if self._monitor else []
            if bl:
                await self._send_to(chat_id, "🚫 <b>Custom blocked tokens:</b>\n" + "\n".join(f"• {s}" for s in bl))
            else:
                await self._send_to(chat_id, "✅ No custom blocked tokens.")
            return

        if cmd == "addwallet":
            # Usage: /addwallet [cex] NAME 0xADDRESS
            if len(parts) < 3:
                await self._send_to(chat_id, "Usage:\n/addwallet NAME 0xADDRESS\n/addwallet cex NAME 0xADDRESS")
                return
            if parts[1].lower() == "cex":
                if len(parts) < 4:
                    await self._send_to(chat_id, "Usage: /addwallet cex NAME 0xADDRESS")
                    return
                wtype, name, address = "cex", parts[2], parts[3]
            else:
                wtype, name, address = "whale", parts[1], parts[2]
            if not address.startswith("0x") or len(address) != 42:
                await self._send_to(chat_id, "⛔ Invalid address — must be 0x… (42 chars).")
                return
            if self._monitor:
                self._monitor.add_wallet(name, address, wtype)
            type_label = "CEX" if wtype == "cex" else "Whale"
            await self._send_to(chat_id, f"✅ Added <b>{name}</b> ({type_label}) — <code>{address}</code>")
            return

        if cmd == "listwallets":
            wallets = self._monitor.get_wallets() if self._monitor else []
            if not wallets:
                await self._send_to(chat_id, "📭 No tracked wallets added yet.")
                return
            lines = ["👁 <b>Tracked Wallets:</b>"]
            for w in wallets:
                label = "CEX" if w.get("type") == "cex" else "Whale"
                lines.append(f"• <b>{w['name']}</b> [{label}]\n  <code>{w['address']}</code>")
            await self._send_to(chat_id, "\n".join(lines))
            return

        handlers = {
            "start":   self._cmd_start,
            "help":    self._cmd_help,
            "status":  self._cmd_status,
            "summary": self._cmd_summary,
            "top":     self._cmd_top,
            "hot":     self._cmd_hot,
            "hot3h":   self._cmd_hot3h,
            "pause":   self._cmd_pause,
            "resume":  self._cmd_resume,
            "config":  self._cmd_config,
        }
        handler = handlers.get(cmd)
        if handler:
            await handler(chat_id)

    # ── Commands ──────────────────────────────────────────────────────────────
    async def _cmd_start(self, chat_id: str):
        await self._send_to(chat_id, self._startup_msg())

    async def _cmd_help(self, chat_id: str):
        msg = (
            "🐋 <b>BSC WHALE ALERT BOT — SIGNAL GUIDE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Signal Types:</b>\n"
            "🟢 <b>ACCUMULATION</b> — CEX → Private Wallet\n"
            "   Coins withdrawn from exchange. Bullish.\n\n"
            "🔴 <b>DISTRIBUTION</b> — Private Wallet → CEX\n"
            "   Coins deposited to exchange. Bearish.\n\n"
            "🟠 <b>POSSIBLE SELL</b> — CEX → CEX\n"
            "   OTC routing or disguised selling. Watch price.\n\n"
            "🐋 <b>WHALE MOVE</b> — Wallet → Wallet\n"
            "   Cold storage or OTC. No exchange pressure.\n\n"
            "<b>Thresholds:</b>\n"
            f"₿ BTC group: ${THRESHOLD_BTC/1e6:.0f}M minimum\n"
            f"⬡ ETH group: ${THRESHOLD_ETH/1e3:.0f}K minimum\n"
            f"🥇 Gold/Oil: ${THRESHOLD_GOLD/1e3:.0f}K minimum\n"
            f"🟡 BNB-native: ${THRESHOLD_BNB/1e3:.0f}K minimum\n"
            f"🪙 All alts: ${THRESHOLD_ALT/1e3:.0f}K minimum\n"
            "💵 Stablecoins: <b>skipped entirely</b>\n\n"
            "<b>Commands:</b>\n"
            "/status — Bot health\n"
            "/summary — Aggregated 24h positions\n"
            "/top — Biggest moves today\n"
            "/hot — Most bought &amp; sold tokens (last 30 min)\n"
            "/hot3h — Most bought &amp; sold tokens (last 3 hours)\n"
            "/coininfo SYMBOL [WINDOW] — acc &amp; dist for a token\n"
            "   Windows: 30m · 1h · 2h · 5h · 12h · (blank = all-time)\n"
            "   e.g. /coininfo LAB 1h\n"
            "/config — Current thresholds\n"
            "/pause — Pause scanning\n"
            "/resume — Resume scanning\n"
            "/help — This menu\n\n"
            "<b>Token control (owner only):</b>\n"
            "/blocktoken SYMBOL — suppress all alerts for a token\n"
            "/unblocktoken SYMBOL — re-enable a blocked token\n"
            "/blocklist — list custom blocked tokens\n\n"
            "<b>Wallet tracking (all users):</b>\n"
            "/addwallet NAME 0x… — track a whale wallet\n"
            "/addwallet cex NAME 0x… — track a CEX wallet\n"
            "/listwallets — list tracked wallets\n\n"
            "<b>Access management (owner only):</b>\n"
            "/enable username — grant a user full access\n"
            "/disable username — revoke access\n"
            "/users — list all enabled users"
        )
        await self._send_to(chat_id, msg)

    async def _cmd_status(self, chat_id: str):
        from bsc_bot.monitor import AGGREGATOR, SEEN_TXS
        uptime = int(time.time() - self._start_time)
        h, rem = divmod(uptime, 3600)
        m = rem // 60
        stats  = self._monitor.stats if self._monitor else {}
        paused = "⏸ PAUSED" if stats.get("paused") else "✅ Running"
        msg = (
            f"🤖 <b>BSC WHALE BOT STATUS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{paused}\n"
            f"⏱ Uptime: {h}h {m}m\n"
            f"🔔 Alerts sent: {self._sent}\n"
            f"🔍 Scans completed: {stats.get('scans', 0)}\n"
            f"👛 Wallets tracked: {len(AGGREGATOR)}\n"
            f"📝 Txs seen: {len(SEEN_TXS):,}\n"
            f"⛓ Chain: BNB Smart Chain\n"
            f"<i>⏰ {_now_utc()}</i>"
        )
        await self._send_to(chat_id, msg)

    async def _cmd_summary(self, chat_id: str):
        from bsc_bot.monitor import AGGREGATOR
        if not AGGREGATOR:
            await self._send_to(chat_id, "📊 No aggregated positions yet. Check back after some alerts fire.")
            return

        wallet_totals = []
        for (wallet, token), data in AGGREGATOR.items():
            wallet_totals.append((wallet, token, data))
        wallet_totals.sort(key=lambda x: x[2]["total_usd"], reverse=True)

        lines = ["📊 <b>AGGREGATED POSITIONS (Last 24h)</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        seen_wallets: dict[str, list] = {}
        for wallet, token, data in wallet_totals:
            seen_wallets.setdefault(wallet, []).append((token, data))

        # Sort wallets by total volume
        wallet_vol = {w: sum(d["total_usd"] for _, d in items) for w, items in seen_wallets.items()}
        top_wallets = sorted(wallet_vol, key=wallet_vol.get, reverse=True)[:8]

        for wallet in top_wallets:
            items = seen_wallets[wallet]
            total_vol = wallet_vol[wallet]
            lines.append(f"👛 <code>{wallet[:6]}…{wallet[-4:]}</code> · Vol: <b>{_fmt_usd(total_vol)}</b>")
            for token, data in sorted(items, key=lambda x: x[1]["total_usd"], reverse=True)[:4]:
                lines.append(
                    f"   • <b>{token}</b>: {_fmt_amt(data['total_amount'], token)} "
                    f"({_fmt_usd(data['total_usd'])}) · {data['count']} txs"
                )
            lines.append("")

        lines.append(f"<i>Updated: {_now_utc()}</i>")
        await self._send_to(chat_id, "\n".join(lines))

    async def _cmd_top(self, chat_id: str):
        from bsc_bot.monitor import get_top_moves
        moves = get_top_moves(n=10, hours=24)
        if not moves:
            await self._send_to(chat_id, "📈 No moves recorded yet in the last 24h.")
            return

        type_emoji = {
            "ACCUMULATION": "🟢", "DISTRIBUTION": "🔴",
            "CEX_TO_CEX": "🟠", "WHALE_MOVE": "🐋",
        }
        lines = ["🏆 <b>BIGGEST MOVES (Last 24h)</b>", "━━━━━━━━━━━━━━━━━━━━\n"]
        for i, m in enumerate(moves, 1):
            em   = type_emoji.get(m["type"], "•")
            ts   = datetime.fromtimestamp(m["ts"], tz=timezone.utc).strftime("%H:%M")
            lines.append(
                f"{i}. {em} <b>{m['symbol']}</b> — {_fmt_usd(m['usd'])} "
                f"<i>(total: {_fmt_usd(m['total_usd'])})</i> · {ts} UTC"
            )
        lines.append(f"\n<i>Updated: {_now_utc()}</i>")
        await self._send_to(chat_id, "\n".join(lines))

    async def _cmd_hot(self, chat_id: str):
        await self._send_to(chat_id, self._hot_tokens_msg())

    async def _cmd_hot3h(self, chat_id: str):
        await self._send_to(chat_id, self._hot_tokens_msg(10800, "3 Hours"))

    async def _cmd_coininfo(self, chat_id: str, symbol: str, window_str: str | None = None):
        await self._send_to(chat_id, self._coininfo_msg(symbol, window_str))

    def _coininfo_msg(self, symbol: str, window_str: str | None = None) -> str:
        if not symbol:
            return (
                "⚠️ <b>Usage:</b> /coininfo SYMBOL [WINDOW]\n"
                "Windows: 30m · 1h · 2h · 5h · 12h · (blank = all-time)\n\n"
                "Examples:\n"
                "  /coininfo LAB\n"
                "  /coininfo LAB 1h\n"
                "  /coininfo LAB 12h"
            )
        window_secs = _parse_window(window_str) if window_str else None
        if window_str and window_secs is None:
            return (
                f"⚠️ Unknown window <b>{window_str}</b>\n"
                "Valid: 30m · 1h · 2h · 5h · 12h · (blank = all-time)"
            )
        win_label = window_str.lower() if window_str else "All-Time"
        summary   = get_coin_summary(symbol, window_secs)
        if summary is None:
            period = f"the last {win_label}" if window_secs else "the bot uptime window"
            return (
                f"❌ <b>{symbol}</b> — no moves recorded in {period}.\n\n"
                "Try /hot to see currently active tokens."
            )
        net       = summary["net_usd"]
        total     = summary["total_usd"]
        net_emoji = "🟢" if net > 0 else ("🔴" if net < 0 else "⚪")
        net_label = "NET ACCUMULATION" if net > 0 else ("NET DISTRIBUTION" if net < 0 else "NEUTRAL")
        buy_pct   = round(summary["buy_usd"] / total * 10) if total > 0 else 0
        bar       = "🟩" * buy_pct + "🟥" * (10 - buy_pct)
        first_dt  = datetime.fromtimestamp(summary["first_seen"], tz=timezone.utc).strftime("%d %b %H:%M UTC")
        last_dt   = datetime.fromtimestamp(summary["last_seen"],  tz=timezone.utc).strftime("%d %b %H:%M UTC")
        return (
            f"📊 <b>Coin Summary — {symbol} | BSC  [{win_label}]</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>Accumulated:</b>  {_fmt_usd(summary['buy_usd'])}  ({summary['buy_moves']} moves)\n"
            f"🔴 <b>Distributed:</b>   {_fmt_usd(summary['sell_usd'])}  ({summary['sell_moves']} moves)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Total Volume:</b>  {_fmt_usd(total)}\n"
            f"{net_emoji} <b>{net_label}:</b>  {_fmt_usd(abs(net))}\n\n"
            f"{bar}\n\n"
            f"📅 First: {first_dt}\n"
            f"🕐 Last:  {last_dt}\n"
            f"🔢 Moves: {summary['total_moves']}"
        )

    async def _cmd_pause(self, chat_id: str):
        if self._monitor:
            self._monitor.pause()
        await self._send_to(chat_id, "⏸ Scanning paused. Use /resume to continue.")

    async def _cmd_resume(self, chat_id: str):
        if self._monitor:
            self._monitor.resume()
        await self._send_to(chat_id, "▶️ Scanning resumed.")

    async def _cmd_config(self, chat_id: str):
        from bsc_bot.config import POLL_SECONDS, AGG_WINDOW, ALERT_COOLDOWN, DUST_FILTER
        msg = (
            "⚙️ <b>BOT CONFIGURATION</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 Scan interval: {POLL_SECONDS}s\n"
            f"🧹 Dust filter: {_fmt_usd(DUST_FILTER)}\n"
            f"⏱ Alert cooldown: {ALERT_COOLDOWN}s per wallet+token\n"
            f"🕐 Aggregation window: {AGG_WINDOW//3600}h\n\n"
            "<b>Thresholds:</b>\n"
            f"  ₿ BTC group: {_fmt_usd(THRESHOLD_BTC)}\n"
            f"  ⬡ ETH group: {_fmt_usd(THRESHOLD_ETH)}\n"
            f"  🥇 Gold/Oil: {_fmt_usd(THRESHOLD_GOLD)}\n"
            f"  🟡 BNB-native: {_fmt_usd(THRESHOLD_BNB)}\n"
            f"  🪙 Alts: {_fmt_usd(THRESHOLD_ALT)}\n"
            "  💵 Stablecoins: skipped\n\n"
            "<b>Chains monitored:</b> BNB Smart Chain (BSC)\n"
            "<b>Source:</b> BscScan free API + CoinGecko"
        )
        await self._send_to(chat_id, msg)

    # ── Telegram send ─────────────────────────────────────────────────────────
    async def _send_to(self, chat_id: str, text: str):
        try:
            await self._session.post(
                f"{TG_API}/sendMessage",
                json={
                    "chat_id":                  chat_id,
                    "text":                     text,
                    "parse_mode":               "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            logger.error(f"Telegram send error: {exc}")

    async def _send_raw(self, text: str):
        if not TG_CHAT_ID:
            return
        targets: set[str] = {TG_CHAT_ID}
        for cid in self._allowed_users.values():
            if cid:
                targets.add(cid)
        for cid in targets:
            await self._send_to(cid, text)

    async def send_cluster_alert(
        self,
        symbol: str,
        direction: str,
        unique_wallets: int,
        total_amount: float,
        total_usd: float,
    ):
        """
        Fire a concentration cluster alert when multiple unique wallets
        move the same token in the same direction within the cluster window.

        direction: "ACC" = multiple wallets withdrew from CEX (bullish cluster)
                   "DIS" = multiple wallets deposited to CEX   (bearish cluster)
        """
        if direction == "ACC":
            emoji     = "🚨🟢"
            title     = f"ENTRY CONCENTRATION — {symbol}"
            move_desc = (
                f"<b>{unique_wallets} unique wallets</b> withdrew "
                f"<b>{symbol}</b> from CEX within the last 60 minutes"
            )
            signal    = "📈 <b>Potential coordinated accumulation / smart money entry</b>"
            dir_str   = "CEX → Wallets"
        else:
            emoji     = "🚨🔴"
            title     = f"EXIT CONCENTRATION — {symbol}"
            move_desc = (
                f"<b>{unique_wallets} unique wallets</b> moved "
                f"<b>{symbol} → CEX</b> within the last 60 minutes"
            )
            signal    = "📉 <b>Potential coordinated exit / smart money distribution</b>"
            dir_str   = "Wallets → CEX"

        lines = [
            f"{emoji} <b>{title}</b> | Chain: BSC",
            "━━━━━━━━━━━━━━━━━━━━",
            move_desc,
            "",
            f"💰 <b>Total amount:</b> {_fmt_amt(total_amount, symbol)}",
            f"💵 <b>Total value:</b>  {_fmt_usd(total_usd)}",
            f"🔀 <b>Direction:</b>    {dir_str}",
            "",
            f"Signal: {signal}",
            f"⏰ <b>Time:</b> {_now_utc()}",
        ]
        msg = "\n".join(lines)
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping cluster alert")

    def _startup_msg(self) -> str:
        return (
            "🐋 <b>BSC WHALE ALERT BOT ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⛓ Chain: BNB Smart Chain\n\n"
            "<b>Watching for:</b>\n"
            "🟢 Accumulation — CEX → Wallet (Bullish)\n"
            "🔴 Distribution — Wallet → CEX (Bearish)\n"
            "🟠 Possible Sell — CEX → CEX (Watch)\n"
            "🐋 Whale Move — Wallet → Wallet (Neutral)\n\n"
            f"<b>Minimum thresholds:</b>\n"
            f"₿ BTC group: {_fmt_usd(THRESHOLD_BTC)} | ⬡ ETH: {_fmt_usd(THRESHOLD_ETH)}\n"
            f"🥇 Gold: {_fmt_usd(THRESHOLD_GOLD)} | 🟡 BNB: {_fmt_usd(THRESHOLD_BNB)} | 🪙 Alts: {_fmt_usd(THRESHOLD_ALT)}\n"
            "💵 Stablecoins: skipped entirely\n\n"
            "🔥 Hot Tokens: auto-report every 30 min &amp; every 3 hours.\n\n"
            "Use /help for the full signal guide."
        )
