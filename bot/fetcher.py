"""
Async data fetcher — DexScreener + Jupiter Price API.
Concurrency is capped via semaphore to avoid rate limits at larger watchlist sizes.
"""
import asyncio
import aiohttp
from bot.config import CHAIN_IDS, MAX_POOLS_PER_TOKEN, MAX_FETCH_CONCURRENT
from bot.utils import clean_dex
import bot.state as state

DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex/tokens"
JUPITER_PRICE    = "https://price.jup.ag/v6/price"

_session:   aiohttp.ClientSession | None = None
_semaphore: asyncio.Semaphore | None     = None


async def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        timeout  = aiohttp.ClientTimeout(total=16)
        conn     = aiohttp.TCPConnector(limit=30, limit_per_host=10)
        _session = aiohttp.ClientSession(timeout=timeout, connector=conn)
    return _session


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_FETCH_CONCURRENT)
    return _semaphore


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


async def fetch_pools(chain: str, address: str, symbol: str) -> list[dict]:
    dex_chain = CHAIN_IDS.get(chain, chain)
    min_liq   = state.cfg_liquidity()
    session   = await get_session()
    sem       = get_semaphore()

    async with sem:
        try:
            async with session.get(f"{DEXSCREENER_BASE}/{address}") as r:
                if r.status == 429:
                    print(f"[Fetcher] Rate limited — {symbol}({chain}), backing off")
                    await asyncio.sleep(2)
                    return []
                if r.status != 200:
                    return []
                data  = await r.json(content_type=None)
                pairs = data.get("pairs") or []
        except asyncio.TimeoutError:
            print(f"[Fetcher] Timeout — {symbol}({chain})")
            return []
        except Exception as e:
            print(f"[Fetcher] {symbol}({chain}): {e}")
            return []

    pools = []
    for p in pairs:
        if p.get("chainId", "") != dex_chain:
            continue
        dex_id    = (p.get("dexId") or "").lower()
        price_str = p.get("priceUsd")
        liq_usd   = (p.get("liquidity") or {}).get("usd", 0) or 0
        vol_24h   = (p.get("volume") or {}).get("h24", 0) or 0

        # Only include pools where our token is the BASE token.
        # If our token is the QUOTE, priceUsd is the OTHER token's price — not ours.
        # This eliminates fake mega-gaps (e.g. MOBILE/HNT appearing as a HNT pool).
        #
        # DexScreener quirks handled here:
        #   "$WIF" → tracked as "WIF"  (dollar-sign prefix on meme tokens)
        raw_sym  = (p.get("baseToken") or {}).get("symbol", "")
        norm_sym = raw_sym.upper().lstrip("$")
        if norm_sym != symbol.upper():
            continue

        if not price_str:
            continue
        try:
            price_usd = float(price_str)
        except Exception:
            continue
        if price_usd <= 0 or liq_usd < min_liq:
            continue

        pools.append({
            "chain":             chain,
            "dex":               dex_id,
            "dex_name":          clean_dex(dex_id),
            "pool_addr":         p.get("pairAddress", ""),
            "price_usd":         price_usd,
            "liq_usd":           liq_usd,
            "vol_24h":           vol_24h,
            "base":              (p.get("baseToken") or {}).get("symbol", "?"),
            "quote":             (p.get("quoteToken") or {}).get("symbol", "?"),
            "url":               p.get("url", ""),
            "fdv":               p.get("fdv", 0) or 0,
            "price_change_h1":   (p.get("priceChange") or {}).get("h1", 0) or 0,
            "price_change_h24":  (p.get("priceChange") or {}).get("h24", 0) or 0,
            "txns_h24_buys":     (p.get("txns") or {}).get("h24", {}).get("buys", 0) or 0,
            "txns_h24_sells":    (p.get("txns") or {}).get("h24", {}).get("sells", 0) or 0,
        })

    pools.sort(key=lambda x: x["liq_usd"], reverse=True)
    return pools[:MAX_POOLS_PER_TOKEN]


async def fetch_jupiter_price(address: str) -> float | None:
    """Fetch aggregated Jupiter price for a Solana token."""
    session = await get_session()
    sem     = get_semaphore()
    async with sem:
        try:
            async with session.get(f"{JUPITER_PRICE}?ids={address}") as r:
                if r.status != 200:
                    return None
                data  = await r.json(content_type=None)
                price = data.get("data", {}).get(address, {}).get("price")
                return float(price) if price else None
        except Exception:
            return None


async def fetch_all_pools(watchlist: dict) -> dict[str, list[dict]]:
    """
    Fetch all tokens concurrently, capped by MAX_FETCH_CONCURRENT semaphore.
    Returns {key: pools}.
    """
    keys    = list(watchlist.keys())
    coros   = [
        fetch_pools(watchlist[k]["chain"], watchlist[k]["address"], watchlist[k]["symbol"])
        for k in keys
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    out = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            print(f"[Fetcher] {key} exception: {result}")
            out[key] = []
        else:
            out[key] = result
    return out
