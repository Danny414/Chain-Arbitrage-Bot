"""
Base Chain Whale Alert Bot — top-level entry point.
Runs from workspace root so base_bot/ is importable as a package.
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from base_bot.config import TG_TOKEN, TG_CHAT_ID, BASE_RPC_URLS
from base_bot.bot     import WhaleBot
from base_bot.monitor import BaseMonitor

logger = logging.getLogger("base_bot.main")


async def main():
    print("=" * 60)
    print("  BASE CHAIN WHALE ALERT BOT")
    print("=" * 60)

    if not TG_TOKEN:
        logger.error("BASE_TG_TOKEN not set — set it in Secrets and restart")
    if not TG_CHAT_ID:
        logger.error("BASE_TG_CHAT_ID not set — set it in Secrets and restart")

    from base_bot.cex_labels import CEX_SET
    logger.info(f"Using {len(BASE_RPC_URLS)} Base RPC endpoints (no API key required)")
    logger.info(f"Monitoring {len(CEX_SET)} CEX/DEX/Bridge addresses across 11 entities")
    logger.info("Smart money rotation tracking: BRETT + TOSHI top holders")

    bot     = WhaleBot()
    monitor = BaseMonitor(bot)
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
