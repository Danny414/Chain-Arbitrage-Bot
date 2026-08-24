"""
Alert message builders for Telegram.
Structure: Header → Spread/Profit → Prices → Slippage → Pool Details → All Pools → Route → Timestamp
"""
from bot.utils import fmt_usd, urgency_label, confidence_bar, explorer_url, now_utc
from bot.config import CHAIN_EMOJIS, CHAIN_LABELS

S = "━" * 30


def _price(p: float) -> str:
    """Format a price with the right number of significant digits."""
    if p >= 10_000: return f"${p:,.2f}"
    if p >= 100:    return f"${p:,.4f}"
    if p >= 1:      return f"${p:.6f}"
    if p >= 0.0001: return f"${p:.8f}"
    return f"${p:.10f}"


def _slip_icon(pct: float) -> str:
    if pct < 0.1:  return "🟢"
    if pct < 0.5:  return "🟡"
    if pct < 2.0:  return "🟠"
    return "🔴"


def build_intra_alert(gap: dict) -> str:
    chain  = gap["chain"]
    sym    = gap["symbol"]
    bp     = gap["buy_pool"]
    sp     = gap["sell_pool"]
    spread = gap["spread_pct"]
    net_p  = gap["net_profit"]
    gross  = gap["gross_profit"]
    ce     = CHAIN_EMOJIS.get(chain, "")
    cl     = CHAIN_LABELS.get(chain, chain.upper())
    urg    = urgency_label(spread)
    conf   = gap.get("confidence", 0)
    pe     = "🟢" if net_p > 0 else "🔴"

    buy_slip  = gap.get("slip_buy_pct", 0)
    sell_slip = gap.get("slip_sell_pct", 0)
    slip_cost = gap.get("slip_cost", 0)
    fees      = gap.get("fees_est", 0)
    trade     = gap.get("trade_size", 1000)

    price_gap = gap["sell_price"] - gap["buy_price"]

    # Section 6 — all pools table
    pool_rows = []
    for i, p in enumerate(sorted(gap["all_pools"], key=lambda x: x["price_usd"]), 1):
        tag = ""
        if p["pool_addr"] == bp["pool_addr"]: tag = "  ← BUY"
        if p["pool_addr"] == sp["pool_addr"]: tag = "  ← SELL"
        pool_rows.append(
            f"  {i}. {p['dex_name']:<18} {_price(p['price_usd']):<14}"
            f"💧{fmt_usd(p['liq_usd'])}{tag}"
        )

    lines = [
        # ── 1. HEADER ─────────────────────────────────────────────
        f"{urg}",
        f"{ce} <b>${sym}</b>  •  {cl}",
        S,

        # ── 2. SPREAD & PROFIT ────────────────────────────────────
        f"📊 <b>SPREAD &amp; PROFIT</b>",
        f"  Spread:         <b>+{spread:.2f}%</b>",
        f"  Gross profit:   <b>{fmt_usd(gross)}</b>",
        f"  DEX fees + gas: <b>-{fmt_usd(fees)}</b>",
        f"  Slippage cost:  <b>-{fmt_usd(slip_cost)}</b>",
        f"  {pe} Net profit: <b>{fmt_usd(net_p)}</b>  ({gap['profit_pct']:+.2f}%)",
        S,

        # ── 3. CURRENT PRICES ─────────────────────────────────────
        f"💱 <b>CURRENT PRICES</b>",
        f"  BUY   <b>{_price(gap['buy_price'])}</b>  ({bp['dex_name']})",
        f"  SELL  <b>{_price(gap['sell_price'])}</b>  ({sp['dex_name']})",
        f"  Gap   <b>+{_price(price_gap)}</b>  per token",
        S,

        # ── 4. SLIPPAGE WARNING ───────────────────────────────────
        f"⚠️ <b>SLIPPAGE WARNING</b>  (${trade:,} trade)",
        f"  Buy  pool: {_slip_icon(buy_slip)} <b>{buy_slip:.3f}%</b>  "
        f"(${trade:,} into {fmt_usd(bp['liq_usd'])} liq)",
        f"  Sell pool: {_slip_icon(sell_slip)} <b>{sell_slip:.3f}%</b>  "
        f"(${trade:,} into {fmt_usd(sp['liq_usd'])} liq)",
        f"  Total slippage cost: <b>~{fmt_usd(slip_cost)}</b>",
        S,

        # ── 5. POOL DETAILS ───────────────────────────────────────
        f"🟢 <b>BUY POOL</b>",
        f"  DEX:       <b>{bp['dex_name']}</b>",
        f"  Liquidity: <b>{fmt_usd(bp['liq_usd'])}</b>",
        f"  Vol 24h:   <b>{fmt_usd(bp['vol_24h'])}</b>",
        f"  Address:   <code>{bp['pool_addr']}</code>",
        f"",
        f"🔴 <b>SELL POOL</b>",
        f"  DEX:       <b>{sp['dex_name']}</b>",
        f"  Liquidity: <b>{fmt_usd(sp['liq_usd'])}</b>",
        f"  Vol 24h:   <b>{fmt_usd(sp['vol_24h'])}</b>",
        f"  Address:   <code>{sp['pool_addr']}</code>",
        S,

        # ── 6. ALL POOLS TABLE ────────────────────────────────────
        f"📋 <b>ALL {sym} POOLS</b>  ({len(gap['all_pools'])} found, cheapest → priciest)",
        *pool_rows,
        S,

        # ── 7. ROUTE ──────────────────────────────────────────────
        f"🔗 <b>ROUTE</b>",
        f"  USDC → {sym} → USDC",
        f"  Buy:  <a href='{explorer_url(chain, bp['pool_addr'])}'>Open on explorer ↗</a>",
        f"  Sell: <a href='{explorer_url(chain, sp['pool_addr'])}'>Open on explorer ↗</a>",
        f"  Confidence: {confidence_bar(conf)}",
        S,

        # ── 8. TIMESTAMP + WARNING ────────────────────────────────
        f"⏰ {gap['detected_at']}",
        f"⚡ <i>Act fast — gaps close within seconds.</i>",
    ]

    return "\n".join(lines)


def build_cross_alert(gap: dict) -> str:
    sym       = gap["symbol"]
    bc        = gap["buy_chain"]
    sc        = gap["sell_chain"]
    bce       = CHAIN_EMOJIS.get(bc, "")
    sce       = CHAIN_EMOJIS.get(sc, "")
    bcl       = CHAIN_LABELS.get(bc, bc.upper())
    scl       = CHAIN_LABELS.get(sc, sc.upper())
    spread    = gap["spread_pct"]
    net_p     = gap["net_profit"]
    gross     = gap["gross_profit"]
    urg       = urgency_label(spread)
    conf      = gap.get("confidence", 0)
    pe        = "🟢" if net_p > 0 else "🔴"
    buy_slip  = gap.get("slip_buy_pct", 0)
    sell_slip = gap.get("slip_sell_pct", 0)
    slip_cost = gap.get("slip_cost", 0)
    fees      = gap.get("fees_est", 0)
    trade     = gap.get("trade_size", 1000)
    bp        = gap["buy_pool"]
    sp        = gap["sell_pool"]
    price_gap = gap["sell_price"] - gap["buy_price"]

    chain_rows = []
    for entry in sorted(gap["all_chain_prices"], key=lambda x: x["price_usd"]):
        ec = CHAIN_EMOJIS.get(entry["chain"], "")
        cl = CHAIN_LABELS.get(entry["chain"], entry["chain"].upper())
        chain_rows.append(
            f"  {ec} {cl:<8}  {_price(entry['price_usd']):<14}💧{fmt_usd(entry['liq_usd'])}"
        )

    lines = [
        # ── 1. HEADER ─────────────────────────────────────────────
        f"{urg}  [CROSS-CHAIN]",
        f"{bce} {bcl} → {sce} {scl}  •  <b>${sym}</b>",
        S,

        # ── 2. SPREAD & PROFIT ────────────────────────────────────
        f"📊 <b>SPREAD &amp; PROFIT</b>",
        f"  Spread:              <b>+{spread:.2f}%</b>",
        f"  Gross profit:        <b>{fmt_usd(gross)}</b>",
        f"  Fees + gas + bridge: <b>-{fmt_usd(fees)}</b>",
        f"  Slippage cost:       <b>-{fmt_usd(slip_cost)}</b>",
        f"  {pe} Net profit:     <b>{fmt_usd(net_p)}</b>  ({gap['profit_pct']:+.2f}%)",
        S,

        # ── 3. CURRENT PRICES ─────────────────────────────────────
        f"💱 <b>CURRENT PRICES</b>",
        f"  BUY   <b>{_price(gap['buy_price'])}</b>  on {bce} {bcl}  ({bp['dex_name']})",
        f"  SELL  <b>{_price(gap['sell_price'])}</b>  on {sce} {scl}  ({sp['dex_name']})",
        f"  Gap   <b>+{_price(price_gap)}</b>  per token",
        S,

        # ── 4. SLIPPAGE WARNING ───────────────────────────────────
        f"⚠️ <b>SLIPPAGE WARNING</b>  (${trade:,} trade)",
        f"  Buy  ({bcl}): {_slip_icon(buy_slip)} <b>{buy_slip:.3f}%</b>  "
        f"(${trade:,} into {fmt_usd(bp['liq_usd'])} liq)",
        f"  Sell ({scl}): {_slip_icon(sell_slip)} <b>{sell_slip:.3f}%</b>  "
        f"(${trade:,} into {fmt_usd(sp['liq_usd'])} liq)",
        f"  Total slippage cost: <b>~{fmt_usd(slip_cost)}</b>",
        S,

        # ── 5. POOL DETAILS ───────────────────────────────────────
        f"🟢 <b>BUY POOL</b>  —  {bce} {bcl}",
        f"  DEX:       <b>{bp['dex_name']}</b>",
        f"  Liquidity: <b>{fmt_usd(bp['liq_usd'])}</b>",
        f"  Address:   <code>{bp['pool_addr']}</code>",
        f"",
        f"🔴 <b>SELL POOL</b>  —  {sce} {scl}",
        f"  DEX:       <b>{sp['dex_name']}</b>",
        f"  Liquidity: <b>{fmt_usd(sp['liq_usd'])}</b>",
        f"  Address:   <code>{sp['pool_addr']}</code>",
        S,

        # ── 6. ALL POOLS TABLE (by chain) ─────────────────────────
        f"📋 <b>PRICE ACROSS CHAINS</b>",
        *chain_rows,
        S,

        # ── 7. ROUTE ──────────────────────────────────────────────
        f"🔗 <b>ROUTE</b>",
        f"  USDC → {sym} → USDC  (via bridge)",
        f"  Buy:  <a href='{explorer_url(bc, bp['pool_addr'])}'>Open on {bcl} explorer ↗</a>",
        f"  Sell: <a href='{explorer_url(sc, sp['pool_addr'])}'>Open on {scl} explorer ↗</a>",
        f"  Confidence: {confidence_bar(conf)}",
        S,

        # ── 8. TIMESTAMP + WARNING ────────────────────────────────
        f"⏰ {gap['detected_at']}",
        f"⚡ <i>Cross-chain: factor in bridge time and extra slippage.</i>",
    ]

    return "\n".join(lines)


def build_new_pool_alert(chain: str, symbol: str, pool: dict) -> str:
    ce      = CHAIN_EMOJIS.get(chain, "")
    cl      = CHAIN_LABELS.get(chain, chain.upper())
    liq     = pool["liq_usd"]
    slip_1k = (1000 / (liq + 1000)) * 100 if liq > 0 else 99.0
    return "\n".join([
        f"🆕 <b>NEW POOL DETECTED</b>",
        f"{ce} {cl}  •  <b>${symbol}</b>",
        S,
        f"  DEX:       <b>{pool['dex_name']}</b>",
        f"  Price:     <b>{_price(pool['price_usd'])}</b>",
        f"  Liquidity: <b>{fmt_usd(liq)}</b>",
        f"  Slippage:  ~{slip_1k:.2f}% on $1K trade",
        f"  Vol 24h:   {fmt_usd(pool['vol_24h'])}",
        f"  Address:   <code>{pool['pool_addr']}</code>",
        f"  <a href='{explorer_url(chain, pool['pool_addr'])}'>View on explorer ↗</a>",
        S,
        f"⚠️ New pools often have mispriced tokens — check for arb.",
        f"⏰ {now_utc()}",
    ])


def build_startup_msg(sol_count: int, spread: float, scan_sec: int) -> str:
    return "\n".join([
        f"🤖 <b>Solana Arb Detector — Online</b>",
        S,
        f"  🟣 Solana:  <b>{sol_count}</b> tokens",
        S,
        f"  Min spread: <b>{spread}%</b>  |  Scan every: <b>{scan_sec}s</b>",
        f"  Jupiter pre-flight: ✅ enabled",
        S,
        f"📌 <b>Commands:</b>",
        f"  /watchlist · /opportunities · /topgaps",
        f"  /stats · /status · /config · /help",
        f"  /pause · /resume",
        f"  /add sol SYMBOL ADDRESS",
        f"  /setspread · /settrade · /setcooldown",
    ])
