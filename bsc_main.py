"""
BSC Whale Alert Bot — top-level entry point.
Runs from workspace root so bsc_bot/ is importable as a package.
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

from bsc_bot.bot import WhaleBot
from bsc_bot.monitor import BSCMonitor

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
