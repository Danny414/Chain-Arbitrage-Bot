"""
Price gap analyser — intra-chain and cross-chain detection.
Includes slippage estimation using AMM price impact model.
"""
import statistics
from bot.utils import now_utc, confidence_score
from bot.config import DEX_FEE_PCT, GAS_COST_USD
import bot.state as state


def estimate_slippage(trade_size_usd: float, liquidity_usd: float) -> float:
    """
    Estimate price impact / slippage for a given trade size and pool liquidity.
    Uses the constant-product AMM formula:
        price_impact = trade_size / (liquidity + trade_size)
    Returns slippage as a percentage (e.g. 0.47 means 0.47%).
    Conservative for CL pools (V3/CLMM), accurate for V2-style pools.
    """
    if liquidity_usd <= 0:
        return 99.0
    return (trade_size_usd / (liquidity_usd + trade_size_usd)) * 100


MIN_POOL_VOL_24H      = 1_000   # $1,000/day — pools below this are stale
MAX_MEDIAN_DEVIATION  = 0.08   # reject pools priced >8% from median cluster


def find_intra_gap(chain: str, symbol: str, address: str, pools: list[dict]) -> dict | None:
    """Find best arb within the same chain across different DEXes."""
    if len(pools) < 2:
        return None

    # Step 1 — drop zero-volume (dead) pools
    active = [p for p in pools if (p.get("vol_24h") or 0) >= MIN_POOL_VOL_24H]
    if len(active) < 2:
        return None

    # Step 2 — outlier price rejection.
    # Jupiter routes across ALL pools and averages toward the cluster price,
    # so a single pool priced 13% away from nine others cannot be captured
    # by Jupiter routing — it always sees the cluster. Reject any pool whose
    # price deviates >8% from the median of active pools before gap detection.
    prices = [p["price_usd"] for p in active]
    median = statistics.median(prices)
    if median <= 0:
        return None
    cluster = [
        p for p in active
        if abs(p["price_usd"] - median) / median <= MAX_MEDIAN_DEVIATION
    ]
    if len(cluster) < 2:
        return None

    cheapest   = min(cluster, key=lambda x: x["price_usd"])
    most_exp   = max(cluster, key=lambda x: x["price_usd"])
    buy_price  = cheapest["price_usd"]
    sell_price = most_exp["price_usd"]

    if buy_price <= 0:
        return None

    spread_pct = ((sell_price - buy_price) / buy_price) * 100
    if spread_pct < state.cfg_spread():
        return None

    trade_size    = state.cfg_live_trade_size()
    tokens_bought = trade_size / buy_price
    proceeds      = tokens_bought * sell_price
    gross_profit  = proceeds - trade_size

    fee_pct   = DEX_FEE_PCT.get(chain, 0.003)
    gas_cost  = GAS_COST_USD.get(chain, 1.0)
    fees_est  = (trade_size * fee_pct * 2) + gas_cost

    # Slippage estimates
    buy_slip  = estimate_slippage(trade_size, cheapest["liq_usd"])
    sell_slip = estimate_slippage(trade_size, most_exp["liq_usd"])
    slip_cost = (trade_size * (buy_slip + sell_slip)) / 100
    total_cost = fees_est + slip_cost

    net_profit = gross_profit - total_cost
    profit_pct = (net_profit / trade_size) * 100

    gap = {
        "type":         "intra",
        "chain":        chain,
        "symbol":       symbol,
        "address":      address,
        "buy_pool":     cheapest,
        "sell_pool":    most_exp,
        "buy_price":    buy_price,
        "sell_price":   sell_price,
        "spread_pct":   spread_pct,
        "gross_profit": gross_profit,
        "net_profit":   net_profit,
        "profit_pct":   profit_pct,
        "fees_est":     fees_est,
        "slip_buy_pct": buy_slip,
        "slip_sell_pct":sell_slip,
        "slip_cost":    slip_cost,
        "total_cost":   total_cost,
        "trade_size":   trade_size,
        "all_pools":    pools,
        "detected_at":  now_utc(),
    }
    gap["confidence"] = confidence_score(gap)
    return gap



def detect_new_pools(key: str, pools: list[dict], known: dict) -> list[dict]:
    """Return newly seen pools not in the persisted known set."""
    known_set = set(known.get(key, []))
    new_found = []
    for p in pools:
        addr = p["pool_addr"]
        if addr and addr not in known_set:
            if known_set:   # only alert after first observation
                new_found.append(p)
            known_set.add(addr)
    known[key] = list(known_set)
    return new_found
