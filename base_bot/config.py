"""
Base Chain Whale Alert Bot — Configuration
All constants, token groups, stablecoins, RPC endpoints and API settings.
"""
import os

# ── Telegram ──────────────────────────────────────────────────────────────────
TG_TOKEN   = os.getenv("BASE_TG_TOKEN",   "")
TG_CHAT_ID = os.getenv("BASE_TG_CHAT_ID", "")

# ── Base RPC endpoints (no API key, free tier) ────────────────────────────────
# Single eth_getLogs call per cycle (Transfer topic only), client-side filtering.
BASE_RPC_URLS: list[str] = [
    "https://mainnet.base.org",
    "https://base.drpc.org",
    "https://base.meowrpc.com",
    "https://base-rpc.publicnode.com",
    "https://1rpc.io/base",
    "https://base.llamarpc.com",
    "https://base-pokt.nodies.app",
]

# ERC-20 Transfer(address,address,uint256) event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Base explorer
BASESCAN_TX_URL  = "https://basescan.org/tx/"
BASESCAN_ADR_URL = "https://basescan.org/address/"

# ── CoinGecko (free, no key) ──────────────────────────────────────────────────
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_COIN_URL  = "https://api.coingecko.com/api/v3/coins/list"

# ── Timing ────────────────────────────────────────────────────────────────────
POLL_SECONDS        = 15     # Base blocks ~2s — scan every 15s
BLOCKS_PER_SCAN     = 7      # startup catch-up (~14s of blocks)
MAX_BLOCKS_PER_SCAN = 150    # hard cap per cycle to keep response size bounded
BASE_BLOCK_SECONDS  = 2      # Base L2 block time
PRICE_TTL           = 120    # seconds before refreshing known-token prices
UNKNOWN_PRICE_TTL   = 300    # seconds before retrying unknown token price
ALERT_COOLDOWN      = 300    # 5-min cooldown per wallet+token
AGG_WINDOW          = 86_400 # 24-hour aggregation window

# ── Concentration cluster detection ───────────────────────────────────────────
CLUSTER_WINDOW      = 3600   # rolling window (60 min)
CLUSTER_MIN_WALLETS = 3      # unique wallets to fire cluster alert
CLUSTER_COOLDOWN    = 3600   # cooldown after firing same cluster
CLUSTER_TRACK_MIN   =   200  # min USD per tx to count toward cluster (Base-tuned)

# ── Concentration signal card USD thresholds ───────────────────────────────────
# LONG/SHORT signal cards only fire when the cluster total meets these bars.
# Lower-cap (alts, AERO, Base-native):  $100K minimum,  $200K+ = high confidence
# Large-cap (cbBTC, commodity tokens):  $300K minimum,  $600K+ = high confidence
# Activity must also span at least 30 minutes (not a flash event).
CLUSTER_LOWER_MIN   = 100_000   # lower-cap alts: minimum total USD to fire
CLUSTER_LOWER_HIGH  = 200_000   # lower-cap alts: high-confidence tier
CLUSTER_LARGE_MIN   = 300_000   # large-cap (BTC/Gold group): minimum total USD
CLUSTER_LARGE_HIGH  = 600_000   # large-cap: high-confidence tier
CLUSTER_MIN_SPREAD  = 1_800     # cluster must span >= 30 min (seconds)

# ── Smart money rotation (BRETT / TOSHI top-holder tracking) ──────────────────
# When a wallet sells BRETT or TOSHI then buys something else → rotation signal
ROTATION_WINDOW   = 4 * 3600  # 4-hour window to detect rotation
ROTATION_MIN_USD  = 10_000    # min $10K move to qualify as smart money

# ── Key Base token contracts (lowercase) ─────────────────────────────────────
BRETT_ADDRESS   = "0x532f27101965dd16442e59d40670faf5ebb142e4"
TOSHI_ADDRESS   = "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4"
DEGEN_ADDRESS   = "0x4ed4e862860bed51a9570b96d89af5e1b0efefed"
VIRTUAL_ADDRESS = "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b"
AERO_ADDRESS    = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
CBBTC_ADDRESS   = "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"
WETH_ADDRESS    = "0x4200000000000000000000000000000000000006"

# Tokens whose large moves trigger rotation tracking
ROTATION_TRIGGER_TOKENS: frozenset[str] = frozenset({
    BRETT_ADDRESS,
    TOSHI_ADDRESS,
})

# ── CoinGecko IDs for price fetching ─────────────────────────────────────────
COINGECKO_IDS: dict[str, str] = {
    "ETH":     "ethereum",
    "WETH":    "ethereum",
    "CBETH":   "coinbase-wrapped-staked-eth",
    "STETH":   "staked-ether",
    "WSTETH":  "wrapped-steth",
    "RETH":    "rocket-pool-eth",
    "WEETH":   "wrapped-eeth",
    "CBBTC":   "coinbase-wrapped-btc",
    "WBTC":    "wrapped-bitcoin",
    "USDC":    "usd-coin",
    "USDT":    "tether",
    "DAI":     "dai",
    "AERO":    "aerodrome-finance",
    "BRETT":   "brett",
    "TOSHI":   "toshi",
    "DEGEN":   "degen-base",
    "VIRTUAL": "virtual-protocol",
    "HIGHER":  "higher",
    "BALD":    "bald",
    "SNX":     "havven",
    "UNI":     "uniswap",
    "LINK":    "chainlink",
    "COMP":    "compound-governance-token",
    "CRV":     "curve-dao-token",
    "BAL":     "balancer",
    "MKR":     "maker",
    "AAVE":    "aave",
    "OP":      "optimism",
    "ARB":     "arbitrum",
    "SKI":     "ski",
    "TBTC":    "tbtc",
    "OPG":     "opengradient",
    "MORPHO":  "morpho",
    "WELL":    "moonwell-artemis",
    "PRIME":   "echelon-prime",
    "MOCHI":   "mochi",
    "ONCHAIN": "onchain",
}

# ── USD Thresholds ────────────────────────────────────────────────────────────
# Base is a Coinbase L2 — institutional flows are smaller than BSC/ETH mainnet.
# These are tuned for Base's actual activity levels.
THRESHOLD_BTC    =   500_000   # cbBTC / WBTC — large but Base volume is lower
THRESHOLD_ETH    =   100_000   # ETH / WETH / liquid-staked — Base L2 scale
THRESHOLD_GOLD   =   200_000   # tokenised commodities
THRESHOLD_AERO   =     5_000   # AERO — Base-native ecosystem token
THRESHOLD_ALT    =     5_000   # all other alts (BRETT, TOSHI, DEGEN, VIRTUAL…)
THRESHOLD_STABLE =         0   # stablecoins: always suppressed
DUST_FILTER      =     5_000   # absolute floor — nothing below $5K ever fires on Base

# Minimum token amount (no price) to still alert — catches large unknown tokens
UNKNOWN_AMOUNT_MIN = 100_000   # tokens (no USD value known)

# ── Token groups ──────────────────────────────────────────────────────────────
BTC_GROUP: set[str] = {
    "BTC", "WBTC", "CBBTC", "RENBTC", "HBTC", "TBTC", "LBTC",
}
ETH_GROUP: set[str] = {
    "ETH", "WETH", "CBETH", "STETH", "WSTETH", "RETH",
    "FRXETH", "SFRXETH", "WEETH", "RSETH",
}
GOLD_GROUP: set[str] = {"PAXG", "XAUT", "DGX"}
AERO_GROUP: set[str] = {"AERO"}

# ── Stablecoins ───────────────────────────────────────────────────────────────
STABLECOINS: set[str] = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD", "FDUSD",
    "GUSD", "HUSD", "USDJ", "VAI", "CUSD", "SUSD", "LUSD", "FRAX",
    "MIM", "RSV", "USDX", "UST", "USTC", "USBN", "HAY", "USDV",
    "LISUD", "PUSD", "DOLA", "USDE", "PYUSD", "EUSD", "GHO",
    "CRVUSD", "MKUSD", "BEAN", "FLEX", "IDRT", "BIDR",
    "USD1", "USD0", "USDB", "USDT0", "USDBC", "USDPLUS", "STUSD", "RUSD",
    "BBUSD", "JUSD", "MONEY", "ZUSD", "USDR", "USDK",
    "AUSD", "OUSD", "NUSD", "USDLR", "USDTB", "USDM", "LISUSD", "CLPD",
    "EURS", "EURT", "AGEUR", "CEUR", "JEUR", "EUROC", "EURC",
    "XSGD", "XAUD", "CADC", "TRYB", "BRLC", "NZDS",
    "IRON", "USN", "DJED", "FEI",
}

_STABLE_CONTAINS = ("STABLE", "STBL")


def is_stablecoin(symbol: str) -> bool:
    s = symbol.upper()
    if s in STABLECOINS:
        return True
    if s.startswith("USD"):
        return True
    if len(s) > 4 and s[1:].startswith("USD"):
        return True
    if s.endswith("USD") and len(s) <= 8:
        return True
    for kw in _STABLE_CONTAINS:
        if kw in s:
            return True
    return False


def get_threshold(symbol: str) -> float:
    s = symbol.upper()
    if is_stablecoin(s):  return THRESHOLD_STABLE
    if s in BTC_GROUP:    return THRESHOLD_BTC
    if s in ETH_GROUP:    return THRESHOLD_ETH
    if s in GOLD_GROUP:   return THRESHOLD_GOLD
    if s in AERO_GROUP:   return THRESHOLD_AERO
    return THRESHOLD_ALT


def get_cluster_thresholds(symbol: str) -> tuple[float, float]:
    """Return (min_signal_usd, high_confidence_usd) for concentration signal cards."""
    s = symbol.upper()
    if s in BTC_GROUP or s in GOLD_GROUP:
        return CLUSTER_LARGE_MIN, CLUSTER_LARGE_HIGH
    return CLUSTER_LOWER_MIN, CLUSTER_LOWER_HIGH


# ── Tokenized stocks (blocked — crypto only) ──────────────────────────────────
# These tokens represent equity positions, not crypto assets. Suppress entirely.
TOKENIZED_STOCKS: frozenset[str] = frozenset({
    # US large-caps (Mirror Protocol, Synthetix, Backed, etc.)
    "TSLA", "AAPL", "AMZN", "GOOGL", "GOOG", "MSFT", "META", "NVDA",
    "NFLX", "AMD", "INTC", "BABA", "BIDU", "JD", "PDD", "PYPL",
    "SBUX", "DIS", "V", "MA", "JPM", "BAC", "GS", "MS",
    "UBER", "LYFT", "TWTR", "SNAP", "SPOT", "ROKU",
    # Meme / retail stocks
    "GME", "AMC", "BB", "NOK", "BBBY",
    # Crypto-adjacent equities
    "COIN", "HOOD", "MSTR", "RIOT", "MARA", "HUT",
    # ETFs (tokenized index / commodity)
    "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "USO", "TLT",
    # Mirror Protocol prefix (mXXX)
    "MTSLA", "MAAPL", "MAMZN", "MGOOGL", "MMSFT", "MNVDA",
    "MNFLX", "MMETA", "MAMD", "MCOIN", "MSPY", "MQQQ",
    # Synthetix synths (sXXX equities)
    "STSLA", "SAAPL", "SAMZN", "SNFLX",
})
