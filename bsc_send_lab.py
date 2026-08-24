"""
Standalone script — reads bsc_bot/hot_log.jsonl and sends a LAB today summary
to the BSC Telegram channel as a bot alert.

Usage:
    python3 bsc_send_lab.py [SYMBOL]

Default symbol is LAB. Run any time after the BSC Whale Bot has been running
with file persistence enabled (bsc_bot/hot_log.jsonl must exist).
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone

TOKEN   = os.environ.get("BSC_TG_TOKEN", "")
CHAT_ID = os.environ.get("BSC_TG_CHAT_ID", "")
HOT_LOG = "bsc_bot/hot_log.jsonl"

SYMBOL = sys.argv[1].upper() if len(sys.argv) > 1 else "LAB"


def _fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def today_start_ts() -> float:
    dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp()


def read_summary(symbol: str, since_ts: float) -> dict | None:
    if not os.path.exists(HOT_LOG):
        return None
    entries = []
    try:
        with open(HOT_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if e.get("symbol", "").upper() == symbol and e.get("ts", 0) >= since_ts:
                        entries.append(e)
                except Exception:
                    pass
    except Exception:
        return None
    if not entries:
        return None
    buy  = [e for e in entries if e["side"] == "buy"]
    sell = [e for e in entries if e["side"] == "sell"]
    return {
        "buy_usd":     sum(e["usd"] for e in buy),
        "sell_usd":    sum(e["usd"] for e in sell),
        "buy_moves":   len(buy),
        "sell_moves":  len(sell),
        "total_moves": len(entries),
        "first_seen":  min(e["ts"] for e in entries),
        "last_seen":   max(e["ts"] for e in entries),
    }


def build_message(symbol: str, data: dict | None, since_ts: float) -> str:
    now_str   = datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    since_str = datetime.fromtimestamp(since_ts, tz=timezone.utc).strftime("%d %b %H:%M UTC")

    if data is None:
        return (
            f"📊 <b>{symbol} Today — BSC</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>No {symbol} moves captured since {since_str}.\n"
            "The file log starts from when the bot last restarted.</i>\n"
            f"\n⏰ {now_str}"
        )

    net       = data["buy_usd"] - data["sell_usd"]
    total     = data["buy_usd"] + data["sell_usd"]
    net_emoji = "🟢" if net > 0 else ("🔴" if net < 0 else "⚪")
    net_label = "NET ACCUMULATION" if net > 0 else ("NET DISTRIBUTION" if net < 0 else "NEUTRAL")
    buy_pct   = round(data["buy_usd"] / total * 10) if total > 0 else 0
    bar       = "🟩" * buy_pct + "🟥" * (10 - buy_pct)
    first_str = datetime.fromtimestamp(data["first_seen"], tz=timezone.utc).strftime("%d %b %H:%M UTC")
    last_str  = datetime.fromtimestamp(data["last_seen"],  tz=timezone.utc).strftime("%d %b %H:%M UTC")

    return (
        f"📊 <b>{symbol} Today — BSC</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>Accumulated:</b>  {_fmt_usd(data['buy_usd'])}  ({data['buy_moves']} moves)\n"
        f"🔴 <b>Distributed:</b>   {_fmt_usd(data['sell_usd'])}  ({data['sell_moves']} moves)\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Total Volume:</b>  {_fmt_usd(total)}\n"
        f"{net_emoji} <b>{net_label}:</b>  {_fmt_usd(abs(net))}\n\n"
        f"{bar}\n\n"
        f"📅 First: {first_str}  →  🕐 Last: {last_str}\n"
        f"🔢 Total moves today: {data['total_moves']}\n"
        f"⏰ {now_str}"
    )


async def send(msg: str) -> None:
    import aiohttp
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as s:
        resp = await s.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       msg,
            "parse_mode": "HTML",
        })
        body = await resp.json()
        if not body.get("ok"):
            print(f"Telegram error: {body}")
        else:
            print(f"Sent successfully to chat {CHAT_ID}")


async def main() -> None:
    if not TOKEN or not CHAT_ID:
        print("BSC_TG_TOKEN / BSC_TG_CHAT_ID not set in environment")
        return
    since  = today_start_ts()
    data   = read_summary(SYMBOL, since)
    msg    = build_message(SYMBOL, data, since)
    print("Message preview:\n", msg)
    await send(msg)


asyncio.run(main())
