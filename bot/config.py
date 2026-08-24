import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

SCAN_INTERVAL        = 60          # slightly longer scan to handle bigger watchlist
MIN_SPREAD_PCT       = 3.0
TRADE_SIZE_USDC      = 1            # model size — profit shown as multiple of $1 input
ALERT_COOLDOWN       = 3600         # 1 hour — prevents same-gap re-alerts within a session
MIN_LIQUIDITY_USD    = 10_000
MAX_POOLS_PER_TOKEN  = 10
MAX_FETCH_CONCURRENT = 15          # semaphore cap — avoids DexScreener rate limits
MIN_CONFIDENCE       = 40          # Jupiter pre-flight is the real quality gate; keep heuristic loose
STATE_FILE           = "bot/state.json"

CHAIN_IDS    = {"sol": "solana"}
CHAIN_LABELS = {"sol": "Solana"}
CHAIN_EMOJIS = {"sol": "🟣"}

DEX_FEE_PCT  = {"sol": 0.003}
GAS_COST_USD = {"sol": 0.025}  # ~0.0003 SOL/tx priority fee at $84/SOL, ×2 legs

DEX_NAMES = {
    "meteora":        "Meteora DAMM",
    "meteoradlmm":    "Meteora DLMM",
    "raydium":        "Raydium AMM",
    "raydiumclmm":    "Raydium CLMM",
    "orca":           "Orca",
    "whirlpool":      "Orca Whirlpool",
    "jupiter":        "Jupiter",
    "lifinity":       "Lifinity",
    "saber":          "Saber",
    "openbook":       "OpenBook",
    "phoenix":        "Phoenix",
    "fluxbeam":       "FluxBeam",
}

DEFAULT_WATCHLIST = {
    # ════════════════════════════════════════════
    #  SOLANA — 25 tokens
    #  Curated for multi-pool fragmentation (4+ active pools each)
    # ════════════════════════════════════════════

    # Blue-chip / infrastructure (deeply liquid, many pools)
    "sol:SOL":     {"chain": "sol", "symbol": "SOL",     "address": "So11111111111111111111111111111111111111112"},
    "sol:JUP":     {"chain": "sol", "symbol": "JUP",     "address": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"},
    "sol:RAY":     {"chain": "sol", "symbol": "RAY",     "address": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"},
    "sol:JTO":     {"chain": "sol", "symbol": "JTO",     "address": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"},
    "sol:ORCA":    {"chain": "sol", "symbol": "ORCA",    "address": "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE"},
    "sol:DRIFT":   {"chain": "sol", "symbol": "DRIFT",   "address": "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7"},
    "sol:HNT":     {"chain": "sol", "symbol": "HNT",     "address": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux"},
    "sol:PYTH":    {"chain": "sol", "symbol": "PYTH",    "address": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"},

    # Meme coins — high volatility, many competing pools
    "sol:BONK":    {"chain": "sol", "symbol": "BONK",    "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"},
    "sol:WIF":     {"chain": "sol", "symbol": "WIF",     "address": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"},
    "sol:POPCAT":  {"chain": "sol", "symbol": "POPCAT",  "address": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"},
    "sol:MSOL":    {"chain": "sol", "symbol": "MSOL",    "address": "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So"},
    "sol:W":       {"chain": "sol", "symbol": "W",       "address": "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ"},
    "sol:PENGU":   {"chain": "sol", "symbol": "PENGU",   "address": "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv"},
    "sol:CLOUD":   {"chain": "sol", "symbol": "CLOUD",   "address": "CLoUDKc4Ane7HeQcPpE3YHnznRxhMimJ4MyaUqyHFzAu"},
    "sol:GIGA":    {"chain": "sol", "symbol": "GIGA",    "address": "63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9"},
    "sol:AI16Z":   {"chain": "sol", "symbol": "AI16Z",   "address": "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC"},
    "sol:SAMO":    {"chain": "sol", "symbol": "SAMO",    "address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"},
    "sol:KMNO":    {"chain": "sol", "symbol": "KMNO",    "address": "KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS"},
    "sol:INF":     {"chain": "sol", "symbol": "INF",     "address": "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"},

    # Smaller-cap multi-DEX tokens — verified 4–8 pools, higher spread fragmentation
    "sol:SPX":     {"chain": "sol", "symbol": "SPX",     "address": "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr"},
    "sol:ZEREBRO": {"chain": "sol", "symbol": "ZEREBRO", "address": "8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn"},
    "sol:SWARMS":  {"chain": "sol", "symbol": "SWARMS",  "address": "74SBV4zDXxTRgv1pEMoECskKBkZHc2yGPnc7GYVepump"},
    "sol:RENDER":  {"chain": "sol", "symbol": "RENDER",  "address": "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof"},
    "sol:NOS":     {"chain": "sol", "symbol": "NOS",     "address": "nosXBVoaCTtYdLvKY6Csb4AC8JCdQKKAaWYtx2ZMoo7"},
}
