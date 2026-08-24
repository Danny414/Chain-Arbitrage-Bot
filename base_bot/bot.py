"""
Base Chain Whale Alert Bot — Telegram Interface

Handles:
  - Sending alerts via a rate-limited async queue
  - Long-polling getUpdates for commands
  - /start /help /status /top /rotation /pause /resume /config
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from base_bot.config import (
    TG_TOKEN, TG_CHAT_ID,
    THRESHOLD_BTC, THRESHOLD_ETH, THRESHOLD_GOLD, THRESHOLD_AERO, THRESHOLD_ALT,
    CLUSTER_MIN_WALLETS, CLUSTER_WINDOW,
)
from base_bot.monitor import get_hot_tokens, get_coin_summary

logger = logging.getLogger("base_bot.bot")

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

TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"


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
    if threshold == 0 or usd_value == 0:
        return ""
    r = usd_value / threshold
    if r >= 10: return " 🦈🦈🦈 (10x+ threshold)"
    if r >= 5:  return " 🦈🦈 (5x+ threshold)"
    if r >= 2:  return " 🦈 (2x+ threshold)"
    return ""


# ── WhaleBot ──────────────────────────────────────────────────────────────────

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
            logger.error("BASE_TG_TOKEN not set — Telegram disabled")
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

    # ── Queue dispatch ────────────────────────────────────────────────────────

    async def _dispatch_loop(self):
        while True:
            msg = await self._queue.get()
            await self._send_raw(msg)
            self._sent += 1
            await asyncio.sleep(1.2)   # ~50 msg/min — well within TG limits

    async def _send_raw(self, text: str):
        if not TG_TOKEN or not TG_CHAT_ID:
            return
        targets: set[str] = {TG_CHAT_ID}
        for cid in self._allowed_users.values():
            if cid:
                targets.add(cid)
        for cid in targets:
            await self._send_to(cid, text)

    async def _send_to(self, chat_id: str, text: str):
        try:
            async with self._session.post(
                f"{TG_API}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status not in (200, 429):
                    body = await r.text()
                    logger.warning(f"TG send failed {r.status}: {body[:120]}")
        except Exception as exc:
            logger.warning(f"TG send exception: {exc}")

    # ── Alert builders ────────────────────────────────────────────────────────

    async def send_alert(
        self, *,
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
        sig_type = signal["type"]
        emoji    = signal["emoji"]
        label    = signal["label"]
        detail   = signal["detail"]
        from_lbl = signal["from_label"]
        to_lbl   = signal["to_label"]

        age_secs = int(time.time()) - block_time
        age_str  = f"{age_secs}s ago" if age_secs < 120 else f"{age_secs // 60}m ago"

        score     = _whale_score(usd_value, threshold)
        price_str = f"(${price:.4g}/token)" if price > 0 else ""
        mc_str    = f"📊 <b>Mkt Cap:</b> {_fmt_usd(market_cap)}" if market_cap > 0 else ""

        agg_line = ""
        if count >= 2:
            agg_line = f"\n📊 <b>24h total:</b> {_fmt_usd(total_usd)} ({count} txs)"

        from_part = _short(from_addr) if from_lbl.startswith("?") or from_lbl[0] == "0" else f"<b>{from_lbl}</b>"
        to_part   = _short(to_addr)   if to_lbl.startswith("?")   or to_lbl[0] == "0"   else f"<b>{to_lbl}</b>"

        lines = [
            f"{emoji} <b>{label} — {symbol}</b>{score}",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💰 <b>Amount:</b> {_fmt_amt(amount, symbol)}",
            f"💵 <b>Value:</b>  {_fmt_usd(usd_value)}  {price_str}",
            mc_str,
            f"📤 <b>From:</b>   {from_part}",
            f"📥 <b>To:</b>     {to_part}",
            f"🔀 <b>Direction:</b> {signal['direction']}",
        ]

        if sig_type in ("ACC", "DIS", "DEX_BUY", "DEX_SELL", "BRIDGE_IN", "BRIDGE_OUT"):
            bull = "📈 Bullish" if sig_type in ("ACC", "DEX_BUY", "BRIDGE_IN") else "📉 Bearish"
            lines.append(f"🎯 {bull} — {detail}")

        if agg_line:
            lines.append(agg_line)

        lines += [
            f"🔍 <a href='{link}'>View on BaseScan</a>",
            f"⛓ Base Network · {_now_utc()} · {age_str}",
        ]

        msg = "\n".join(lines)
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

    async def send_cluster_alert(
        self, *,
        symbol: str,
        direction: str,
        unique_wallets: int,
        total_amount: float,
        total_usd: float,
    ):
        if direction == "ACC":
            emoji     = "🚨🟢"
            title     = f"ENTRY CONCENTRATION — {symbol}"
            move_desc = (
                f"<b>{unique_wallets} unique wallets</b> withdrew "
                f"<b>{symbol}</b> from CEX within the last 60 minutes"
            )
            signal = "📈 <b>Potential coordinated accumulation / smart money entry</b>"
            dir_str = "CEX → Wallets"
        else:
            emoji     = "🚨🔴"
            title     = f"EXIT CONCENTRATION — {symbol}"
            move_desc = (
                f"<b>{unique_wallets} unique wallets</b> moved "
                f"<b>{symbol} → CEX</b> within the last 60 minutes"
            )
            signal = "📉 <b>Potential coordinated exit / smart money distribution</b>"
            dir_str = "Wallets → CEX"

        lines = [
            f"{emoji} <b>{title}</b> | Chain: Base",
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

    async def send_rotation_alert(
        self, *,
        wallet: str,
        sold_token: str,
        sold_usd: float,
        bought_token: str,
        bought_usd: float,
        link: str,
    ):
        """
        🔄 Smart Money Rotation — BRETT/TOSHI top holder rotated into a new token.
        Historically a high-probability 2-5x signal within 24h on Base.
        """
        lines = [
            "🔄🚨 <b>SMART MONEY ROTATION</b> | Chain: Base",
            "━━━━━━━━━━━━━━━━━━━━",
            f"Wallet {_short(wallet)} sold <b>{sold_token}</b> and rotated into <b>{bought_token}</b>",
            "",
            f"💸 <b>Sold:</b>    {_fmt_usd(sold_usd)} of {sold_token}",
            f"💰 <b>Bought:</b>  {_fmt_usd(bought_usd)} of {bought_token}",
            "",
            "🎯 <b>BRETT/TOSHI top holders rotating into a Base-native token",
            "is historically a high-probability 2–5x signal within 24h.</b>",
            "",
            f"🔍 <a href='{link}'>View on BaseScan</a>",
            f"⏰ <b>Time:</b> {_now_utc()}",
        ]
        msg = "\n".join(lines)
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping rotation alert")

    async def send_bridge_alert(
        self, *,
        direction: str,
        symbol: str,
        amount: float,
        usd_value: float,
        link: str,
    ):
        """Bridge inflow / outflow — institutional on/off-ramping signal."""
        if direction == "IN":
            emoji  = "🌉🟢"
            title  = "BRIDGE INFLOW"
            detail = "Capital arriving on Base — institutional buying signal"
        else:
            emoji  = "🌉🔴"
            title  = "BRIDGE OUTFLOW"
            detail = "Capital leaving Base — possible exit / sell pressure"

        lines = [
            f"{emoji} <b>{title} — {symbol}</b> | Chain: Base",
            "━━━━━━━━━━━━━━━━━━━━",
            f"💰 <b>Amount:</b> {_fmt_amt(amount, symbol)}",
            f"💵 <b>Value:</b>  {_fmt_usd(usd_value)}",
            f"🏦 <b>Via:</b>    Base L2 Standard Bridge",
            f"📢 {detail}",
            f"🔍 <a href='{link}'>View on BaseScan</a>",
            f"⏰ <b>Time:</b> {_now_utc()}",
        ]
        msg = "\n".join(lines)
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping bridge alert")

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
        spb  = now % 10800
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
        title   = f"🔥 <b>Hot Tokens — Last {label} | Base</b>"

        if not tokens:
            return (
                f"{title}\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "<i>No qualifying moves recorded yet.</i>\n"
                f"\n⏰ Time: {now_str}"
            )

        lines = [title, "━━━━━━━━━━━━━━━━━━━━"]
        for i, t in enumerate(tokens, 1):
            net_emoji = "🟢" if t["net"] == "buy"  else ("🔴" if t["net"] == "sell" else "⚪")
            net_label = "Accum" if t["net"] == "buy" else ("Distrib" if t["net"] == "sell" else "Neutral")
            lines.append(
                f"#{i} <b>{t['symbol']}</b>  {_fmt_usd(t['total_usd'])}  "
                f"({t['moves']} moves) | {net_emoji} {net_label}"
            )
            lines.append(f"   ↗ {_fmt_usd(t['buy_usd'])}  ↘ {_fmt_usd(t['sell_usd'])}")

        lines.append(f"\n⏰ Time: {now_str}")
        return "\n".join(lines)

    def _coininfo_msg(self, symbol: str, window_str: str | None = None) -> str:
        if not symbol:
            return (
                "⚠️ <b>Usage:</b> /coininfo SYMBOL [WINDOW]\n"
                "Windows: 30m · 1h · 2h · 5h · 12h · (blank = all-time)\n\n"
                "Examples:\n"
                "  /coininfo BRETT\n"
                "  /coininfo BRETT 1h\n"
                "  /coininfo BRETT 12h"
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
            f"📊 <b>Coin Summary — {symbol} | Base  [{win_label}]</b>\n"
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

    # ── Command polling ───────────────────────────────────────────────────────

    async def _poll_commands(self):
        while True:
            try:
                async with self._session.get(
                    f"{TG_API}/getUpdates",
                    params={"offset": self._update_offset, "timeout": 20, "limit": 10},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as r:
                    if r.status == 200:
                        data = await r.json()
                        for upd in data.get("result", []):
                            self._update_offset = upd["update_id"] + 1
                            msg = upd.get("message") or upd.get("channel_post") or {}
                            text = (msg.get("text") or "").strip()
                            if text.startswith("/"):
                                await self._handle_cmd(text.split()[0].lower(), msg)
            except asyncio.TimeoutError:
                pass
            except Exception as exc:
                logger.debug(f"Poll error: {exc}")
            await asyncio.sleep(1)

    async def _handle_cmd(self, cmd: str, msg: dict):
        chat_id   = str(msg.get("chat", {}).get("id", TG_CHAT_ID))
        from_user = msg.get("from") or {}
        username  = (from_user.get("username") or "").lower().lstrip("@")
        is_owner  = (chat_id == TG_CHAT_ID)

        # ── User management — owner-only, bypasses access gate ────────────────
        if cmd == "/enable":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            parts  = (msg.get("text") or "").strip().split()
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

        if cmd == "/disable":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            parts  = (msg.get("text") or "").strip().split()
            target = parts[1].lower().lstrip("@") if len(parts) > 1 else ""
            if not target:
                await self._send_to(chat_id, "⚠️ Usage: /disable username")
                return
            self._allowed_users.pop(target, None)
            _save_users(self._allowed_users)
            await self._send_to(chat_id,
                f"🚫 <b>@{target}</b> removed — access revoked.")
            return

        if cmd == "/users":
            if not is_owner:
                await self._send_to(chat_id, "⛔ Owner-only command.")
                return
            if not self._allowed_users:
                await self._send_to(chat_id,
                    "👥 <b>No users enabled yet.</b>\n"
                    "Use /enable username to grant access.")
            else:
                lines = ["👥 <b>Enabled Users — Base Bot:</b>"]
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
        if cmd in ("/config", "/pause", "/resume", "/blocktoken", "/unblocktoken") and not is_owner:
            await self._send_to(chat_id, "⛔ Owner-only command.")
            return

        # ── Register chat_id so live feed reaches this user ───────────────────
        if username and username in self._allowed_users and self._allowed_users.get(username) != chat_id:
            self._allowed_users[username] = chat_id
            _save_users(self._allowed_users)

        # ── Command dispatch ───────────────────────────────────────────────────
        parts = (msg.get("text") or "").strip().split()

        if cmd in ("/start", "/help"):
            await self._send_to(chat_id, self._help_msg())
        elif cmd == "/status":
            await self._send_to(chat_id, self._status_msg())
        elif cmd == "/top":
            await self._send_to(chat_id, self._top_msg())
        elif cmd == "/rotation":
            await self._send_to(chat_id, self._rotation_msg())
        elif cmd == "/config":
            await self._send_to(chat_id, self._config_msg())
        elif cmd == "/hot":
            await self._send_to(chat_id, self._hot_tokens_msg())
        elif cmd == "/hot3h":
            await self._send_to(chat_id, self._hot_tokens_msg(10800, "3 Hours"))
        elif cmd == "/coininfo":
            symbol     = parts[1].upper() if len(parts) > 1 else ""
            window_str = parts[2]         if len(parts) > 2 else None
            await self._send_to(chat_id, self._coininfo_msg(symbol, window_str))
        elif cmd == "/test":
            await self._send_to(chat_id, (
                "✅ <b>Base Whale Bot — Telegram connection OK</b>\n"
                f"Bot is alive · {_now_utc()}\n"
                f"Alerts sent so far: {self._sent}"
            ))
        elif cmd == "/pause":
            if self._monitor:
                self._monitor.pause()
            await self._send_to(chat_id, "⏸ Bot paused — no new alerts.")
        elif cmd == "/resume":
            if self._monitor:
                self._monitor.resume()
            await self._send_to(chat_id, "▶️ Bot resumed.")

        elif cmd == "/blocktoken":
            sym = parts[1].upper() if len(parts) > 1 else ""
            if not sym:
                await self._send_to(chat_id, "Usage: /blocktoken SYMBOL")
                return
            if self._monitor:
                self._monitor.add_block(sym)
            await self._send_to(chat_id, f"🚫 <b>{sym}</b> blocked — no more alerts for this token.")

        elif cmd == "/unblocktoken":
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

        elif cmd == "/blocklist":
            bl = self._monitor.get_custom_blocklist() if self._monitor else []
            if bl:
                await self._send_to(chat_id, "🚫 <b>Custom blocked tokens:</b>\n" + "\n".join(f"• {s}" for s in bl))
            else:
                await self._send_to(chat_id, "✅ No custom blocked tokens.")

        elif cmd == "/addwallet":
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

        elif cmd == "/listwallets":
            wallets = self._monitor.get_wallets() if self._monitor else []
            if not wallets:
                await self._send_to(chat_id, "📭 No tracked wallets added yet.")
                return
            lines = ["👁 <b>Tracked Wallets:</b>"]
            for w in wallets:
                label = "CEX" if w.get("type") == "cex" else "Whale"
                lines.append(f"• <b>{w['name']}</b> [{label}]\n  <code>{w['address']}</code>")
            await self._send_to(chat_id, "\n".join(lines))

    # ── Status / info messages ────────────────────────────────────────────────

    def _startup_msg(self) -> str:
        return (
            "🌊 <b>BASE CHAIN WHALE ALERT BOT ONLINE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⛓ Chain: Base (Coinbase L2)\n\n"
            "<b>Monitoring:</b>\n"
            "• CEX inflows / outflows (ACCUMULATION / DISTRIBUTION)\n"
            "• Base Bridge inflow / outflow (institutional signal)\n"
            "• Concentration clusters (3+ wallets, same direction, 60 min)\n"
            "• 🔄 Smart Money Rotation — BRETT/TOSHI whale tracker\n"
            "• 🔥 Hot Tokens: auto-report every 30 min &amp; every 3 hours\n\n"
            "<b>Commands:</b> /status /top /hot /hot3h /rotation /config /test /pause /resume /help"
        )

    def _help_msg(self) -> str:
        return (
            "🌊 <b>BASE CHAIN WHALE ALERT BOT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "<b>Alert types:</b>\n"
            "🟢 ACCUMULATION — tokens leaving CEX (bullish)\n"
            "🔴 DISTRIBUTION — tokens entering CEX (bearish)\n"
            "🟠 POSSIBLE SELL — CEX→CEX transfer\n"
            "🐋 WHALE MOVE — large wallet-to-wallet\n"
            "🟢 DEX BUY — large Aerodrome/Uniswap purchase\n"
            "🔴 DEX SELL — large Aerodrome/Uniswap sale\n"
            "🌉🟢 BRIDGE INFLOW — capital arriving on Base\n"
            "🌉🔴 BRIDGE OUTFLOW — capital leaving Base\n"
            "🚨 CONCENTRATION — 3+ wallets coordinated move\n"
            "🔄 ROTATION — BRETT/TOSHI whale buying new token\n\n"
            "<b>Commands:</b>\n"
            "/status — bot health + scan stats\n"
            "/top — biggest moves in last 24h\n"
            "/rotation — recent smart money rotations\n"
            "/config — current thresholds\n"
            "/hot — most bought &amp; sold tokens (last 30 min)\n"
            "/hot3h — most bought &amp; sold tokens (last 3 hours)\n"
            "/coininfo SYMBOL [WINDOW] — acc &amp; dist for a token\n"
            "   Windows: 30m · 1h · 2h · 5h · 12h · (blank = all-time)\n"
            "   e.g. /coininfo BRETT 1h\n"
            "/pause — pause all alerts\n"
            "/resume — resume alerts\n"
            "/test — verify Telegram connection is working\n"
            "/help — this message\n\n"
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

    def _status_msg(self) -> str:
        if not self._monitor:
            return "⚠️ Monitor not initialised."
        s = self._monitor.stats
        uptime = int(time.time() - self._start_time)
        h, m = divmod(uptime // 60, 60)
        return (
            f"📊 <b>Base Whale Bot Status</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{'⏸ PAUSED' if s['paused'] else '✅ Running'}\n"
            f"⏱ Uptime: {h}h {m}m\n"
            f"🔍 Scans: {s['scans']:,}\n"
            f"🚨 Alerts sent: {self._sent:,}\n"
            f"📦 Last block: {s['last_block']:,}\n"
            f"🔄 Rotation watches: {s['rotation_watches']:,}\n"
            f"💾 Tracked wallets: {s['wallets']:,}\n"
            f"🕐 {_now_utc()}"
        )

    def _top_msg(self) -> str:
        from base_bot.monitor import MOVE_LOG
        if not MOVE_LOG:
            return "📊 No moves logged yet — check back after a scan cycle."
        cutoff = time.time() - 86_400
        recent = [m for m in MOVE_LOG if m["ts"] >= cutoff]
        if not recent:
            return "📊 No moves in the last 24 hours."
        by_type: dict[str, float] = {}
        for m in recent:
            by_type[m["type"]] = by_type.get(m["type"], 0) + m["usd"]
        top5 = sorted(recent, key=lambda x: x["usd"], reverse=True)[:5]
        lines = [f"📊 <b>Top moves (last 24h)</b> — {len(recent)} total\n"]
        for m in top5:
            lines.append(f"• <b>{m['symbol']}</b> {_fmt_usd(m['usd'])} [{m['type']}]")
        lines.append("\n<b>By type:</b>")
        for t, v in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {t}: {_fmt_usd(v)}")
        return "\n".join(lines)

    def _rotation_msg(self) -> str:
        from base_bot.monitor import ROTATION_SELLS
        if not ROTATION_SELLS:
            return "🔄 No smart money rotation watches active."
        now    = time.time()
        cutoff = now - 4 * 3600
        active = {
            w: [e for e in entries if e["ts"] >= cutoff]
            for w, entries in ROTATION_SELLS.items()
        }
        active = {w: e for w, e in active.items() if e}
        if not active:
            return "🔄 No active rotation watches (all expired)."
        lines = [f"🔄 <b>Active rotation watches</b> — {len(active)} wallets\n"]
        for wallet, entries in list(active.items())[:10]:
            sold = entries[-1]
            age  = int((now - sold["ts"]) / 60)
            lines.append(
                f"• {_short(wallet)} sold <b>{sold['token']}</b> "
                f"{_fmt_usd(sold['usd'])} — {age}m ago"
            )
        return "\n".join(lines)

    def _config_msg(self) -> str:
        return (
            "⚙️ <b>Base Whale Bot Config</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🔸 cbBTC/WBTC threshold: ${THRESHOLD_BTC:,}\n"
            f"🔸 ETH/WETH threshold:   ${THRESHOLD_ETH:,}\n"
            f"🔸 Commodities:          ${THRESHOLD_GOLD:,}\n"
            f"🔸 AERO ecosystem:       ${THRESHOLD_AERO:,}\n"
            f"🔸 All other alts:       ${THRESHOLD_ALT:,}\n"
            f"🔸 Stablecoins:          🚫 always suppressed\n\n"
            "📝 <i>Thresholds are tuned for Base L2 activity levels</i>\n\n"
            "🔄 <b>Smart Money Rotation</b>\n"
            "  Tracks BRETT/TOSHI top holders for 4h after a large sell\n"
            "  Min move: $10,000\n\n"
            f"🚨 <b>Concentration clusters</b>\n"
            f"  Fires when {CLUSTER_MIN_WALLETS}+ unique wallets move the same token\n"
            f"  in the same direction within {CLUSTER_WINDOW // 60} minutes\n\n"
            "💡 <b>Commands:</b> /test — verify Telegram connection"
        )
