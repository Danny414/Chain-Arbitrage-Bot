"""
Dry-run trade executor.
Simulates Jupiter (SOL) and PancakeSwap (BSC) execution without submitting any transaction.
When live mode is added later, this module gains a live_execute() path alongside simulate().
"""
import time
from bot.utils import now_utc
from bot.config import DEX_FEE_PCT, GAS_COST_USD, CHAIN_LABELS, CHAIN_EMOJIS


def simulate(gap: dict, max_trade_usd: float = 100.0) -> dict:
    """
    Simulate executing an arbitrage gap.
    Returns a trade record that is passed to pnl.record_trade().

    Parameters
    ----------
    gap          : opportunity dict from analyzer (intra or cross)
    max_trade_usd: hard cap on simulated position size
    """
    chain      = gap.get("chain") or gap.get("buy_chain", "sol")
    symbol     = gap["symbol"]
    buy_price  = gap["buy_price"]
    sell_price = gap["sell_price"]
    spread_pct = gap["spread_pct"]
    confidence = gap.get("confidence", 0)
    gap_type   = gap.get("type", "intra")

    # ── Determine simulated size ──────────────────────────────────────────
    # Default $1 — matches the signal model. Raise via /setmaxsize VALUE.
    sim_size = max_trade_usd

    # ── Re-derive costs at sim_size ───────────────────────────────────────
    tokens_bought = sim_size / buy_price
    proceeds      = tokens_bought * sell_price
    gross_profit  = proceeds - sim_size

    if gap_type == "cross":
        buy_chain  = gap.get("buy_chain", chain)
        sell_chain = gap.get("sell_chain", chain)
        fee_pct    = max(DEX_FEE_PCT.get(buy_chain, 0.003), DEX_FEE_PCT.get(sell_chain, 0.003))
        gas_cost   = GAS_COST_USD.get(buy_chain, 1.0) + GAS_COST_USD.get(sell_chain, 1.0) + 2.0
    else:
        fee_pct  = DEX_FEE_PCT.get(chain, 0.003)
        gas_cost = GAS_COST_USD.get(chain, 1.0)

    fees_est = (sim_size * fee_pct * 2) + gas_cost

    # Slippage at sim_size (recompute — gap was calculated at $1)
    buy_liq   = gap["buy_pool"].get("liq_usd", 0)
    sell_liq  = gap["sell_pool"].get("liq_usd", 0)
    buy_slip  = (sim_size / (buy_liq  + sim_size)) * 100 if buy_liq  > 0 else 99.0
    sell_slip = (sim_size / (sell_liq + sim_size)) * 100 if sell_liq > 0 else 99.0
    slip_cost = (sim_size * (buy_slip + sell_slip)) / 100

    total_cost  = fees_est + slip_cost
    net_profit  = gross_profit - total_cost
    profit_pct  = (net_profit / sim_size) * 100
    win         = net_profit > 0

    # ── Simulate DEX routing label ────────────────────────────────────────
    if gap_type == "cross":
        route = (
            f"USDC → {symbol} on "
            f"{CHAIN_LABELS.get(gap.get('buy_chain','?'), '?')} → "
            f"bridge → USDC on "
            f"{CHAIN_LABELS.get(gap.get('sell_chain','?'), '?')}"
        )
    else:
        bp_dex = gap["buy_pool"].get("dex_name", "DEX A")
        sp_dex = gap["sell_pool"].get("dex_name", "DEX B")
        route  = f"USDC → {symbol} on {bp_dex} → USDC on {sp_dex}"

    return {
        "mode":        "dry_run",
        "type":        gap_type,
        "chain":       chain,
        "symbol":      symbol,
        "sim_size":    sim_size,
        "buy_price":   buy_price,
        "sell_price":  sell_price,
        "spread_pct":  spread_pct,
        "gross_profit":gross_profit,
        "fees_est":    fees_est,
        "slip_cost":   slip_cost,
        "net_profit":  net_profit,
        "profit_pct":  profit_pct,
        "win":         win,
        "confidence":  confidence,
        "route":       route,
        "timestamp":   now_utc(),
        "unix_ts":     time.time(),
        "buy_pool":    gap["buy_pool"].get("dex_name", "?"),
        "sell_pool":   gap["sell_pool"].get("dex_name", "?"),
        "buy_liq":     buy_liq,
        "sell_liq":    sell_liq,
    }
