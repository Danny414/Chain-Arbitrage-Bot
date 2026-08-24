from datetime import datetime, timezone
from bot.config import DEX_NAMES, CHAIN_IDS

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def now_ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%S")

def fmt_usd(v):
    try:
        v = float(v)
        if abs(v) >= 1e6: return f"${v/1e6:.2f}M"
        if abs(v) >= 1e3: return f"${v/1e3:.2f}K"
        return f"${v:.4f}"
    except Exception:
        return "$?"

def fmt_pct(v):
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "?%"

def clean_dex(dex_id: str) -> str:
    return DEX_NAMES.get(dex_id.lower(), dex_id.replace("-", " ").title())

def explorer_url(chain: str, addr: str) -> str:
    urls = {
        "sol": f"https://solscan.io/account/{addr}",
        "eth": f"https://etherscan.io/address/{addr}",
        "bsc": f"https://bscscan.com/address/{addr}",
    }
    return urls.get(chain, "https://dexscreener.com")

def dexscreener_token_url(chain: str, address: str) -> str:
    chain_id = CHAIN_IDS.get(chain, chain)
    return f"https://dexscreener.com/{chain_id}/{address}"

def confidence_score(gap: dict) -> int:
    """
    Score 0–100 based on liquidity, volume, spread size, and number of pools.
    Higher = more trustworthy opportunity.
    """
    score = 0
    liq = gap["buy_pool"].get("liq_usd", 0) + gap["sell_pool"].get("liq_usd", 0)
    vol = gap["buy_pool"].get("vol_24h", 0) + gap["sell_pool"].get("vol_24h", 0)
    spread = gap["spread_pct"]
    n_pools = len(gap.get("all_pools", []))

    # Liquidity component (0–40)
    if liq >= 1_000_000:  score += 40
    elif liq >= 500_000:  score += 30
    elif liq >= 100_000:  score += 20
    elif liq >= 50_000:   score += 10

    # Volume component (0–30)
    if vol >= 5_000_000:  score += 30
    elif vol >= 1_000_000:score += 22
    elif vol >= 500_000:  score += 15
    elif vol >= 100_000:  score += 8

    # Spread plausibility (0–20) — very large spreads are suspicious
    if 3 <= spread < 8:   score += 20
    elif 8 <= spread < 15:score += 14
    elif 15 <= spread < 30:score += 7
    else:                 score += 2

    # Pool count (0–10)
    if n_pools >= 5:      score += 10
    elif n_pools >= 3:    score += 6
    else:                 score += 3

    return min(score, 100)

def confidence_bar(score: int) -> str:
    filled = score // 10
    bar = "█" * filled + "░" * (10 - filled)
    if score >= 70:   emoji = "🟢"
    elif score >= 40: emoji = "🟡"
    else:             emoji = "🔴"
    return f"{emoji} [{bar}] {score}/100"

def urgency_label(spread_pct: float) -> str:
    if spread_pct >= 20: return "🚨🚨🚨 EXTREME"
    if spread_pct >= 10: return "🚨🚨 HIGH"
    if spread_pct >= 5:  return "🚨 MODERATE"
    return "⚡ LOW"
