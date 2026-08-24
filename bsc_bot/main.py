"""
================================================================
BSC WHALE ALERT BOT
================================================================
Chain:    BNB Smart Chain (BSC)
Detects:  ALL large token movements (no stablecoin alerts)
Signals:  Accumulation / Distribution / Possible Sell / Whale Move
Alerts:   Telegram with verifiable BscScan links

Data source: direct BSC RPC via eth_getLogs (no API key needed)

Required env vars:
  BSC_TG_TOKEN    — Telegram bot token (from @BotFather)
  BSC_TG_CHAT_ID  — Telegram chat/channel ID
================================================================
"""

import asyncio
import logging
import sys

from bsc_bot.bot import WhaleBot
from bsc_bot.monitor import BSCMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("bsc_bot.main")


async def main():
    print("=" * 60)
    print("  BSC WHALE ALERT BOT")
    print("=" * 60)

    from bsc_bot.config import TG_TOKEN, TG_CHAT_ID, BSC_RPC_URLS
    if not TG_TOKEN:
        logger.error("BSC_TG_TOKEN not set — set it in Secrets and restart")
    if not TG_CHAT_ID:
        logger.error("BSC_TG_CHAT_ID not set — set it in Secrets and restart")
    logger.info(f"Using {len(BSC_RPC_URLS)} BSC RPC endpoints (no API key required)")

    from bsc_bot.cex_labels import CEX_SET
    logger.info(f"Monitoring {len(CEX_SET)} CEX addresses across 14 exchanges")

    bot     = WhaleBot()
    monitor = BSCMonitor(bot)
    bot.set_monitor(monitor)

    await asyncio.gather(
        bot.run(),
        monitor.run(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
