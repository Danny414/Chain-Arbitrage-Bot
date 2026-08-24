"""
Base Chain Whale Bot — Concentrated-flow signal cards.

Signal cards ONLY fire on cluster events (3+ unique wallets, same direction,
within the rolling window). Onchain flow is the primary signal; RSI/VWAP from
GeckoTerminal confirms and shapes confidence + TP/SL sizing.
No MACD, no Bollinger Bands.
"""

import time
import logging
import aiohttp

logger = logging.getLogger("base_bot.signals")

GECKO_BASE = "https://api.geckoterminal.com/api/v2"
NETWORK    = "base"

RSI_PERIOD     = 14
VOL_AVG_WINDOW = 20
VWAP_WINDOW    = 24

_NO_MARKET_CACHE: dict[str, float] = {}
_NO_MARKET_TTL = 3600

_POOL_CACHE:    dict[str, str]   = {}
_POOL_CACHE_TS: dict[str, float] = {}
_POOL_CACHE_TTL = 3600


def _fmt_price(p: float) -> str:
    if p <= 0:
        return "N/A"
    if p < 0.000001:
        return f"${p:.10f}"
    if p < 0.001:
        return f"${p:.8f}"
    if p < 1:
        return f"${p:.6f}"
    return f"${p:,.4f}"


def _rsi(closes: list[float], period: int = RSI_PERIOD) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _vwap(candles: list) -> float | None:
    if not candles:
        return None
    num = den = 0.0
    for c in candles:
        high, low, close, vol = float(c[2]), float(c[3]), float(c[4]), float(c[5])
        typical = (high + low + close) / 3
        num += typical * vol
        den += vol
    return (num / den) if den > 0 else None


def _volume_ratio(volumes: list[float]) -> float | None:
    if len(volumes) < 2:
        return None
    latest = volumes[-1]
    prior  = volumes[:-1][-VOL_AVG_WINDOW:]
    avg    = sum(prior) / len(prior) if prior else 0
    return (latest / avg) if avg > 0 else None


async def _get_pool(session, contract: str) -> str | None:
    now = time.time()
    if contract in _NO_MARKET_CACHE and now - _NO_MARKET_CACHE[contract] < _NO_MARKET_TTL:
        return None
    if contract in _POOL_CACHE and now - _POOL_CACHE_TS.get(contract, 0) < _POOL_CACHE_TTL:
        return _POOL_CACHE[contract]
    try:
        async with session.get(
            f"{GECKO_BASE}/networks/{NETWORK}/tokens/{contract}/pools",
            params={"page": 1},
            headers={"Accept": "application/json;version=20230302"},
            timeout=aiohttp.ClientTimeout(total=12),
        ) as r:
            if r.status != 200:
                logger.debug(f"[Signal] GeckoTerminal pools HTTP {r.status} for {contract[:10]}… — will retry")
                return None
            data  = await r.json()
            pools = data.get("data", [])
            if not pools:
                _NO_MARKET_CACHE[contract] = now
                return None
            addr = pools[0].get("attributes", {}).get("address")
            if not addr:
                _NO_MARKET_CACHE[contract] = now
                return None
            _POOL_CACHE[contract]    = addr
            _POOL_CACHE_TS[contract] = now
            return addr
    except Exception as exc:
        logger.debug(f"[Signal] Pool lookup failed for {contract[:10]}…: {exc}")
        return None


async def _fetch_ohlcv(session, pool: str, aggregate: int, limit: int) -> list | None:
    try:
        async with session.get(
            f"{GECKO_BASE}/networks/{NETWORK}/pools/{pool}/ohlcv/hour",
            params={"aggregate": aggregate, "limit": limit, "currency": "usd"},
            headers={"Accept": "application/json;version=20230302"},
            timeout=aiohttp.ClientTimeout(total=12),
        ) as r:
            if r.status != 200:
                logger.debug(f"[Signal] GeckoTerminal OHLCV HTTP {r.status} for pool {pool[:10]}…")
                return None
            data  = await r.json()
            ohlcv = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            if not ohlcv or len(ohlcv) < 20:
                return None
            return list(reversed(ohlcv))
    except Exception as exc:
        logger.debug(f"[Signal] OHLCV fetch failed for pool {pool[:10]}…: {exc}")
        return None


def _confidence_and_sizing(direction: str, rsi_4h, rsi_1h, vol_ratio, vwap_above) -> tuple[str, float, float, float]:
    score = 1  # cluster is always the base signal
    if rsi_4h is not None:
        if direction == "DIS" and rsi_4h > 70:   score += 1
        elif direction == "ACC" and rsi_4h < 30:  score += 1
    if rsi_1h is not None:
        if direction == "DIS" and rsi_1h > 70:    score += 1
        elif direction == "ACC" and rsi_1h < 30:  score += 1
    if vol_ratio is not None and vol_ratio >= 2.0:
        score += 1
    if vwap_above is not None:
        if direction == "DIS" and vwap_above:       score += 1
        elif direction == "ACC" and not vwap_above: score += 1

    if score >= 4:
        return "HIGH 🔥",    3.0, 6.0, 10.5
    if score >= 2:
        return "MEDIUM ✅",   2.5, 5.0, 8.5
    return "LOW ⚠️",          2.0, 4.0, 7.0


async def build_signal_card(
    session,
    symbol:         str,
    direction:      str,       # "ACC" or "DIS"
    price:          float,
    contract:       str,
    unique_wallets: int,
    total_usd:      float,
    total_amount:   float,
    cex_names:      list[str],
    window_mins:    int,
) -> str | None:
    """
    Build a concentrated-flow signal card. Always returns a card if price > 0.
    TA indicators are marked N/A when no DEX pool is found on GeckoTerminal.
    """
    if price <= 0:
        return None

    is_sell = (direction == "DIS")

    rsi_4h = rsi_1h = vol_ratio = vwap = None
    pool = await _get_pool(session, contract.lower())
    if pool:
        c4h = await _fetch_ohlcv(session, pool, 4, 60)
        c1h = await _fetch_ohlcv(session, pool, 1, 60)
        if c4h and c1h:
            rsi_4h    = _rsi([float(c[4]) for c in c4h])
            rsi_1h    = _rsi([float(c[4]) for c in c1h])
            vol_ratio = _volume_ratio([float(c[5]) for c in c1h])
            vwap      = _vwap(c1h[-VWAP_WINDOW:])

    vwap_above = (vwap > price) if vwap else None

    confidence, sl_pct, tp1_pct, tp2_pct = _confidence_and_sizing(
        direction, rsi_4h, rsi_1h, vol_ratio, vwap_above
    )

    entry = price
    if is_sell:
        sl   = entry * (1 + sl_pct / 100)
        tp1  = entry * (1 - tp1_pct / 100)
        tp2  = entry * (1 - tp2_pct / 100)
    else:
        sl   = entry * (1 - sl_pct / 100)
        tp1  = entry * (1 + tp1_pct / 100)
        tp2  = entry * (1 + tp2_pct / 100)

    sl_sign  = f"+{sl_pct}%"  if is_sell else f"-{sl_pct}%"
    tp1_sign = f"-{tp1_pct}%" if is_sell else f"+{tp1_pct}%"
    tp2_sign = f"-{tp2_pct}%" if is_sell else f"+{tp2_pct}%"

    def _fmt_flow(v: float) -> str:
        if v >= 1_000_000: return f"${v/1_000_000:.2f}M"
        if v >= 1_000:     return f"${v/1_000:.1f}K"
        return f"${v:.0f}"

    def _fmt_tokens(n: float) -> str:
        if n >= 1_000_000_000: return f"{n/1_000_000_000:.1f}B"
        if n >= 1_000_000:     return f"{n/1_000_000:.1f}M"
        if n >= 1_000:         return f"{n/1_000:.0f}K"
        return f"{n:.0f}"

    cex_str    = " & ".join(sorted(set(cex_names))[:3]) if cex_names else "Exchange"
    window_str = f"{window_mins} min" if window_mins < 60 else f"{window_mins // 60}h {window_mins % 60}m"

    if is_sell:
        flow_line     = (
            f"<b>{unique_wallets} wallets</b> moved {_fmt_tokens(total_amount)} {symbol} "
            f"({_fmt_flow(total_usd)}) → {cex_str} in {window_str}"
        )
        flow_sentiment = "Bearish Flow — Coordinated Distribution"
        title_label    = "SHORT SIGNAL"
        header_emoji   = "🔴🔴"
    else:
        flow_line     = (
            f"<b>{unique_wallets} wallets</b> withdrew {_fmt_tokens(total_amount)} {symbol} "
            f"({_fmt_flow(total_usd)}) from {cex_str} in {window_str}"
        )
        flow_sentiment = "Bullish Flow — Coordinated Accumulation"
        title_label    = "LONG SIGNAL"
        header_emoji   = "🟢🟢"

    rsi4_str  = f"{rsi_4h:.1f}" if rsi_4h is not None else "N/A"
    rsi1_str  = f"{rsi_1h:.1f}" if rsi_1h is not None else "N/A"
    vwap_str  = ("Above price 📉" if vwap_above else "Below price 📈") if vwap_above is not None else "N/A"

    rsi4_tag = ""
    if rsi_4h is not None:
        if rsi_4h > 70:   rsi4_tag = " (Overbought)"
        elif rsi_4h < 30: rsi4_tag = " (Oversold)"

    lines = [
        f"{header_emoji} <b>{title_label} — {symbol}</b> | Base",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 Entry: ~{_fmt_price(entry)}",
        f"🔴 SL: {_fmt_price(sl)} ({sl_sign})",
        f"🎯 TP1: {_fmt_price(tp1)} ({tp1_sign})",
        f"🎯 TP2: {_fmt_price(tp2)} ({tp2_sign})",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💸 Flow: {flow_line}",
        f"{'📉' if is_sell else '📈'} {flow_sentiment}",
        f"📊 RSI 4H: {rsi4_str}{rsi4_tag}  |  RSI 1H: {rsi1_str}  |  VWAP: {vwap_str}",
        f"📈 Confidence: {confidence}",
        "━━━━━━━━━━━━━━━━━━━━",
        f"⚠️ SL {sl_pct}% | TP1 {tp1_pct}% | TP2 {tp2_pct}%",
    ]

    logger.info(
        f"[Signal] Card built: {symbol} {direction} "
        f"wallets={unique_wallets} flow={_fmt_flow(total_usd)} "
        f"RSI4H={rsi4_str} RSI1H={rsi1_str} → {confidence}"
    )
    return "\n".join(lines)
