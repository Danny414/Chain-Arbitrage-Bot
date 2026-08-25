"""
BSC Whale Alert Bot — Configuration
All constants, token groups, stablecoins, and API settings.
"""
import os

# ── Telegram ─────────────────────────────────────────────────────────────────
TG_TOKEN   = os.getenv("BSC_TG_TOKEN",   "")
TG_CHAT_ID = os.getenv("BSC_TG_CHAT_ID", "")

# ── BSC RPC endpoints (no API key needed, free tier) ─────────────────────────
# Strategy: single eth_getLogs per cycle (just Transfer topic, no address filter).
# Client-side CEX filtering — works on any standard node, no topic-array limits.
# Updated endpoints (2026-08-25) — removed dead nodes, added fresh working RPCs
BSC_RPC_URLS: list[str] = [
    "https://bsc-rpc.publicnode.com",              # PublicNode - reliable, fast
    "https://bsc.meowrpc.com",                     # MeowRPC - BSC specialist
    "https://bsc-pokt.nodies.app",                 # Pocket Network - free tier
    "https://1rpc.io/bnb",                         # 1RPC - free public endpoint
    "https://rpc-bsc.48.club",                     # 48 Club RPC - free public
    "https://bsc-dataseed.binance.org",            # Binance official seed node
    "https://bsc-dataseed1.defibit.io",            # DeFiBit seed node
    "https://bsc-dataseed1.ninicoin.io",           # Ninicoin seed node
    "https://bsc-dataseed2.defibit.io",            # DeFiBit secondary
    "https://bsc-dataseed3.defibit.io",            # DeFiBit tertiary
    "https://bsc-dataseed4.defibit.io",            # DeFiBit quaternary
]

# ERC-20 Transfer(address,address,uint256) event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# BSC explorer links (for alert URLs)
BSCSCAN_TX_URL  = "https://bscscan.com/tx/"
BSCSCAN_ADR_URL = "https://bscscan.com/address/"

# ── CoinGecko (free, no key) ─────────────────────────────────────────────────
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_COIN_URL  = "https://api.coingecko.com/api/v3/coins/list"

# ── Timing ────────────────────────────────────────────────────────────────────
POLL_SECONDS        = 30    # main scan loop interval (seconds)
BLOCKS_PER_SCAN     = 60    # blocks per startup catch-up (BSC ~0.5s/block → ~30s)
MAX_BLOCKS_PER_SCAN = 300   # hard cap per cycle to keep response size bounded
BSC_BLOCK_SECONDS   = 0.5   # current BSC block time (~0.5s after fast-finality upgrade)
PRICE_TTL         = 120   # seconds before refreshing known-token prices
UNKNOWN_PRICE_TTL = 300   # seconds before retrying unknown token price lookup
ALERT_COOLDOWN    = 300   # 5 min — don't re-alert same wallet+token within window
AGG_WINDOW        = 86_400  # 24-hour aggregation window

# ── Concentration cluster detection ──────────────────────────────────────────
CLUSTER_WINDOW       = 3600   # rolling window in seconds (60 min)
CLUSTER_MIN_WALLETS  = 3      # minimum unique wallets to fire a cluster alert
CLUSTER_COOLDOWN     = 3600   # seconds before re-firing same token+direction cluster
CLUSTER_TRACK_MIN    = 1_000  # minimum USD per tx to count toward a cluster

# ── Concentration signal card USD thresholds ──────────────────────────────────
# LONG/SHORT signal cards only fire when the cluster total meets these bars.
# Lower-cap (alts, BNB ecosystem):  $150K minimum,  $300K+ = high confidence
# Large-cap (BNB group bluechips):  $500K minimum, $1M+ = high confidence
# Activity must also span at least 30 minutes (not a flash pump).
CLUSTER_LOWER_MIN   = 150_000    # lower-cap alts: minimum total USD to fire
CLUSTER_LOWER_HIGH  = 300_000    # lower-cap alts: high-confidence tier
CLUSTER_LARGE_MIN   = 500_000    # large-cap (BNB group): minimum total USD
CLUSTER_LARGE_HIGH  = 1_000_000  # large-cap: high-confidence tier
CLUSTER_MIN_SPREAD  = 1_800      # cluster must span >= 30 min (seconds)

# ── USD Thresholds ─────────────────────────────────────────────────────────────
THRESHOLD_BTC    = 2_000_000   # BTC and BTC-pegged
THRESHOLD_ETH    =   500_000   # ETH and ETH-pegged
THRESHOLD_GOLD   =   500_000   # Gold/commodity tokens
THRESHOLD_BNB    =    50_000   # BNB-native ecosystem (WBNB, CAKE, etc.)
THRESHOLD_ALT    =    30_000   # All other alts
THRESHOLD_STABLE = 10_000_000  # Stablecoins — skipped entirely anyway

DUST_FILTER      =    30_000   # Hard min — nothing below $30K ever fires on BSC

# ── Stablecoins (skip all alerts) ────────────────────────────────────────────
STABLECOINS: set[str] = {
    # ── USD-pegged (explicit) ─────────────────────────────────────────────────
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "USDD", "FDUSD",
    "GUSD", "HUSD", "USDJ", "VAI", "CUSD", "SUSD", "LUSD", "FRAX",
    "MIM", "RSV", "USDX", "UST", "USTC", "USBN", "HAY", "USDV",
    "LISUD", "PUSD", "DOLA", "USDE", "PYUSD", "EUSD", "GHO",
    "CRVUSD", "MKUSD", "BEAN", "FLEX", "IDRT", "BIDR",
    # Newer / chain-specific USD pegs
    "USD1",   # World Liberty Financial
    "USD0",   # Usual Protocol
    "USDB",   # Blast USD
    "USDT0",  # Omni-chain USDT
    "USDBC",  # Base-bridged USDC
    "USDPLUS", "STUSD", "RUSD", "BBUSD",
    "JUSD", "MONEY", "ZUSD", "USDR", "USDK",
    "AUSD", "OUSD", "NUSD", "USDLR", "USDTB", "USDM",
    "LISUSD", "CLPD",
    # ── EUR-pegged ───────────────────────────────────────────────────────────
    "EURS", "EURT", "AGEUR", "CEUR", "JEUR", "EUROC", "EURC",
    # ── Other fiat pegs ──────────────────────────────────────────────────────
    "XSGD", "XAUD", "CADC", "TRYB", "BRLC", "NZDS",
    # ── Algo / depegged (no signal value) ────────────────────────────────────
    "IRON", "USN", "DJED", "FEI",
}

# ── Token groups for threshold selection ─────────────────────────────────────
BTC_GROUP: set[str] = {
    "BTC", "BTCB", "WBTC", "RENBTC", "HBTC", "ANYBTC",
    "BBTC", "SBTC", "TBTC", "LBTC", "CBBTC",
}
ETH_GROUP: set[str] = {
    "ETH", "WETH", "BETH", "STETH", "WSTETH", "CBETH",
    "RETH", "FRXETH", "SFRXETH", "WEETH", "RSETH",
}
GOLD_GROUP: set[str] = {
    "PAXG", "XAUT", "DGX", "PMGT", "CACHE",
    "OIL", "CRUDE", "OILT", "BCO",
}
BNB_GROUP: set[str] = {
    "BNB", "WBNB", "CAKE", "XVS", "ALPACA", "BIFI",
    "AUTO", "BELT", "BUNNY", "BSW", "BANANA",
}


# Pattern-based detection — catches future USD* coins without list updates
_STABLE_CONTAINS = ("STABLE", "STBL")


def is_stablecoin(symbol: str) -> bool:
    s = symbol.upper()
    if s in STABLECOINS:
        return True
    # Any symbol starting with USD (USD1, USD0, USDB, USDX …)
    if s.startswith("USD"):
        return True
    # Wrapped/yield variants: aUSDT, cUSDC, xUSDC …
    if len(s) > 4 and s[1:].startswith("USD"):
        return True
    # *USD suffix on short tickers
    if s.endswith("USD") and len(s) <= 8:
        return True
    # Anything with STABLE or STBL in the ticker
    for kw in _STABLE_CONTAINS:
        if kw in s:
            return True
    return False


def get_threshold(symbol: str) -> float:
    s = symbol.upper()
    if s in STABLECOINS: return THRESHOLD_STABLE
    if s in BTC_GROUP:   return THRESHOLD_BTC
    if s in ETH_GROUP:   return THRESHOLD_ETH
    if s in GOLD_GROUP:  return THRESHOLD_GOLD
    if s in BNB_GROUP:   return THRESHOLD_BNB
    return THRESHOLD_ALT


def threshold_label(symbol: str) -> str:
    s = symbol.upper()
    if s in BTC_GROUP:   return "₿ BTC-group"
    if s in ETH_GROUP:   return "⬡ ETH-group"
    if s in GOLD_GROUP:  return "🥇 Gold/Oil"
    if s in BNB_GROUP:   return "🟡 BNB-native"
    return "🪙 Altcoin"


def get_cluster_thresholds(symbol: str) -> tuple[float, float]:
    """Return (min_signal_usd, high_confidence_usd) for concentration signal cards."""
    s = symbol.upper()
    if s in BNB_GROUP:
        return CLUSTER_LARGE_MIN, CLUSTER_LARGE_HIGH
    return CLUSTER_LOWER_MIN, CLUSTER_LOWER_HIGH


# ── Tokenized stocks (blocked — crypto only) ──────────────────────────────────
# These BEP-20 tokens represent equity positions, not crypto assets.
# No price impact logic applies; suppress entirely on both bots.
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
    # Synthetix synths (sXXX / iXXX equities)
    "STSLA", "SAAPL", "SAMZN", "SNFLX",
})


# ── CoinGecko ID map for common tokens ───────────────────────────────────────
COINGECKO_IDS: dict[str, str] = {
    # BTC group
    "BTC":      "bitcoin",
    "BTCB":     "bitcoin",
    "WBTC":     "wrapped-bitcoin",
    "RENBTC":   "renbtc",
    "HBTC":     "huobi-btc",
    "CBBTC":    "coinbase-wrapped-btc",
    # ETH group
    "ETH":      "ethereum",
    "WETH":     "ethereum",
    "BETH":     "binance-eth",
    "STETH":    "staked-ether",
    "WSTETH":   "wrapped-steth",
    "RETH":     "rocket-pool-eth",
    "WEETH":    "wrapped-eeth",
    # BNB
    "BNB":      "binancecoin",
    "WBNB":     "binancecoin",
    # Gold
    "PAXG":     "pax-gold",
    "XAUT":     "tether-gold",
    "DGX":      "digix-gold",
    # Stables (prices only, no alerts)
    "USDT":     "tether",
    "USDC":     "usd-coin",
    "BUSD":     "binance-usd",
    "DAI":      "dai",
    "TUSD":     "true-usd",
    "FRAX":     "frax",
    # Major alts
    "SOL":      "solana",
    "ADA":      "cardano",
    "DOGE":     "dogecoin",
    "XRP":      "ripple",
    "DOT":      "polkadot",
    "AVAX":     "avalanche-2",
    "MATIC":    "matic-network",
    "POL":      "matic-network",
    "LINK":     "chainlink",
    "UNI":      "uniswap",
    "AAVE":     "aave",
    "CRV":      "curve-dao-token",
    "CAKE":     "pancakeswap-token",
    "INJ":      "injective-protocol",
    "TIA":      "celestia",
    "SUI":      "sui",
    "APT":      "aptos",
    "ARB":      "arbitrum",
    "OP":       "optimism",
    "PEPE":     "pepe",
    "SHIB":     "shiba-inu",
    "WIF":      "dogwifcoin",
    "BONK":     "bonk",
    "FLOKI":    "floki",
    "BABYDOGE": "baby-doge-coin",
    "SAND":     "the-sandbox",
    "MANA":     "decentraland",
    "AXS":      "axie-infinity",
    "GALA":     "gala",
    "GMT":      "stepn",
    "APE":      "apecoin",
    "LTC":      "litecoin",
    "BCH":      "bitcoin-cash",
    "FIL":      "filecoin",
    "ATOM":     "cosmos",
    "NEAR":     "near",
    "ICP":      "internet-computer",
    "VET":      "vechain",
    "ALGO":     "algorand",
    "XLM":      "stellar",
    "TRX":      "tron",
    "ETC":      "ethereum-classic",
    "HBAR":     "hedera-hashgraph",
    "XMR":      "monero",
    "THETA":    "theta-token",
    "FTM":      "fantom",
    "GRT":      "the-graph",
    "COMP":     "compound-governance-token",
    "SNX":      "synthetix-network-token",
    "YFI":      "yearn-finance",
    "SUSHI":    "sushi",
    "1INCH":    "1inch",
    "ENJ":      "enjincoin",
    "CHZ":      "chiliz",
    "BAT":      "basic-attention-token",
    "ZEC":      "zcash",
    "DASH":     "dash",
    "WAVES":    "waves",
    "EOS":      "eos",
    "ZIL":      "zilliqa",
    "XTZ":      "tezos",
    "OMG":      "omisego",
    "ZRX":      "0x",
    "BAL":      "balancer",
    "ALPHA":    "alpha-finance",
    "XVS":      "venus",
    "LDO":      "lido-dao",
    "MKR":      "maker",
    "LIDO":     "lido-dao",
    "RPL":      "rocket-pool",
    "SSV":      "ssv-network",
    "PENDLE":   "pendle",
    "EIGEN":    "eigenlayer",
    "JUP":      "jupiter-exchange-solana",
    "RAY":      "raydium",
    "WLD":      "worldcoin-wld",
    "PYTH":     "pyth-network",
    "JTO":      "jito-governance-token",
    "ORCA":     "orca",
    "BOME":     "book-of-meme",
    "POPCAT":   "popcat",
    "TON":      "the-open-network",
    "NOT":      "notcoin",
    "DOGS":     "dogs-",
    "HMSTR":    "hamster-kombat",
    "PIXEL":    "pixels",
    "PIXEL":    "pixels",
    "DYDX":     "dydx",
    "LPT":      "livepeer",
    "ANKR":     "ankr",
    "OCEAN":    "ocean-protocol",
    "BAND":     "band-protocol",
    "REN":      "ren",
}
