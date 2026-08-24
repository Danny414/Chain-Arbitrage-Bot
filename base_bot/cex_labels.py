"""
Base Chain — CEX Wallet & Key Contract Database

Covers: Coinbase, Binance, OKX, Bybit, Kraken, Gate.io, KuCoin,
        Bitfinex, HTX, Crypto.com, Robinhood, FalconX, Wintermute,
        Cumberland, Jump Trading, Amber Group, B2C2 + Base Bridge.

Note: DEX addresses (Aerodrome, Uniswap) are intentionally excluded —
      DEX swap events are noise and are fully suppressed.

classify() maps a (from_addr, to_addr) pair to a typed signal dict.
"""

_CEX_DB: dict[str, tuple[str, str, str]] = {
    # (exchange, human_label, wallet_type)
    # wallet_type: "hot" | "cold" | "dex" | "bridge"

    # ── Coinbase ──────────────────────────────────────────────────────────────
    "0x503828976d22510aad0201ac7ec88293211d23da": ("Coinbase",    "Coinbase Hot 1",        "hot"),
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": ("Coinbase",    "Coinbase Hot 2",        "hot"),
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": ("Coinbase",    "Coinbase Hot 3",        "hot"),
    "0x77696bb39917c91a0c3908d577d5e322095425ca": ("Coinbase",    "Coinbase Hot 4",        "hot"),
    "0x8eb8a3b98659cce290402893d0123abb75e3ab28": ("Coinbase",    "Coinbase Hot 5",        "hot"),
    "0x4d9339dd97db55e3b9bcbe65de39ff9c04d1c2cd": ("Coinbase",    "Coinbase Cold 1",       "cold"),
    "0x6dca56c95d6e8c5cf4e3f2dd2a47e2b69afe3de8": ("Coinbase",    "Coinbase Prime",        "cold"),

    # ── Binance ───────────────────────────────────────────────────────────────
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": ("Binance",     "Binance Hot 1",         "hot"),
    "0xf977814e90da44bfa03b6295a0616a897441acec": ("Binance",     "Binance Hot 2",         "hot"),
    "0x28c6c06298d514db089934071355e5743bf21d60": ("Binance",     "Binance Hot 3",         "hot"),
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": ("Binance",     "Binance Hot 4",         "hot"),
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": ("Binance",     "Binance Hot 5",         "hot"),

    # ── OKX ───────────────────────────────────────────────────────────────────
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": ("OKX",         "OKX Hot 1",             "hot"),
    "0x236f233dbba689bd5f1f4dba3bf7ae18a24d1f3f": ("OKX",         "OKX Hot 2",             "hot"),
    "0x461249076b88189f8ac9418de28b365859e46bfd": ("OKX",         "OKX Hot 3",             "hot"),

    # ── Bybit ─────────────────────────────────────────────────────────────────
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": ("Bybit",       "Bybit Hot 1",           "hot"),
    "0x1db92e2eebc8e0c075a02bea49a2935bcd2dfcf4": ("Bybit",       "Bybit Deposit",         "hot"),
    "0x0639556f03714a74a5feeaf5736a4a64ff70d206": ("Bybit",       "Bybit Hot 3",           "hot"),

    # ── Kraken ────────────────────────────────────────────────────────────────
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": ("Kraken",      "Kraken Hot 1",          "hot"),
    "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13": ("Kraken",      "Kraken Hot 2",          "hot"),
    "0xe853c56864a2ebe4576a807d26fdc4a0ada51919": ("Kraken",      "Kraken Hot 3",          "hot"),

    # ── Gate.io ───────────────────────────────────────────────────────────────
    "0x0d0707963952f2fba59dd06f2b425ace40b492fe": ("Gate.io",     "Gate.io Hot 1",         "hot"),
    "0x1c4b0d50f6c547d4af83a81b94f76cb32b265bd": ("Gate.io",     "Gate.io Hot 2",         "hot"),

    # ── KuCoin ────────────────────────────────────────────────────────────────
    "0x2b5634c42055806a59e9107ed44d43c426e58258": ("KuCoin",      "KuCoin Hot 1",          "hot"),
    "0x689c56aef474df92d44a1b70850f808488f9769c": ("KuCoin",      "KuCoin Hot 2",          "hot"),

    # ── Bitfinex ──────────────────────────────────────────────────────────────
    "0x742d35cc6634c0532925a3b844bc454e4438f44e": ("Bitfinex",    "Bitfinex Hot 1",        "hot"),
    "0x876eabf441b2ee5b5b0554fd502a8e0600950cfa": ("Bitfinex",    "Bitfinex Hot 2",        "hot"),

    # ── HTX / Huobi ───────────────────────────────────────────────────────────
    "0xab5c66752a9e8167967685f1450532fb96d5d24f": ("HTX",         "HTX Hot 1",             "hot"),
    "0x6748f50f686bfbca6fe8ad62b22228b87f31ff2b": ("HTX",         "HTX Hot 2",             "hot"),
    "0xfdb16996831753d5331ff813c29a93c76834a0ad": ("HTX",         "HTX Cold",              "cold"),

    # ── Crypto.com ────────────────────────────────────────────────────────────
    "0x6262998ced04146fa42253a5c0af90ca02dfd2a3": ("Crypto.com",  "Crypto.com Hot 1",      "hot"),
    "0x46340b20830761efd29832f407f23e6b4e4ab57e": ("Crypto.com",  "Crypto.com Hot 2",      "hot"),

    # ── Robinhood ─────────────────────────────────────────────────────────────
    "0x0000000000c2d145a2526bd8c716263bfebe1a72": ("Robinhood",   "Robinhood Hot 1",       "hot"),

    # ── FalconX (institutional OTC desk, active on Base) ─────────────────────
    "0x1151cb3d861920e07a38e03eead12c32178567f6": ("FalconX",     "FalconX Hot Wallet",    "hot"),
    "0x4585fe77225b41b697c938b018e2ac67ac5a20c0": ("FalconX",     "FalconX Deposit",       "hot"),
    "0x7b7b57b31fa0c1e5cda2a9f0b583e7d2b0cd985a": ("FalconX",     "FalconX Hot 2",         "hot"),

    # ── Wintermute (market maker, large Base presence) ────────────────────────
    "0x4f3a120e72c76c22ae802d129f599bfdbc31cb81": ("Wintermute",  "Wintermute Hot 1",      "hot"),
    "0x00000000ae347930bd1e7b0f35588b92280f9e75": ("Wintermute",  "Wintermute Hot 2",      "hot"),
    "0x0000000000bc60df61d04571bc3d5e18c7f0b4a3": ("Wintermute",  "Wintermute Hot 3",      "hot"),

    # ── Cumberland DRW (institutional trading desk) ───────────────────────────
    "0xdc76cd25977e0a5ae17155770273ad58648900d3": ("Cumberland",  "Cumberland Hot 1",      "hot"),
    "0x08a3c2a819e3de7aca384c798269b3ce1cd0e437": ("Cumberland",  "Cumberland Hot 2",      "hot"),

    # ── Jump Trading ──────────────────────────────────────────────────────────
    "0x46a3a41bd932244dd08186e4c19f1a7e48cbcdf4": ("Jump Trading","Jump Hot 1",            "hot"),
    "0x792dc691160d9e8d1e68ad62f6a4d76b32ee4d5f": ("Jump Trading","Jump Hot 2",            "hot"),

    # ── Amber Group ───────────────────────────────────────────────────────────
    "0x0bcb7e6a1c6a33a02dccd24e72f6a98f1d96671e": ("Amber Group", "Amber Hot 1",           "hot"),

    # ── B2C2 (institutional liquidity) ───────────────────────────────────────
    "0x01e2919679362dfbc9ee1644ba9c6da6d6245bb1": ("B2C2",        "B2C2 Hot 1",            "hot"),

    # ── Base L2 Bridge ────────────────────────────────────────────────────────
    "0x4200000000000000000000000000000000000010": ("Base Bridge",  "L2 Standard Bridge",   "bridge"),
    "0x420000000000000000000000000000000000000f": ("Base Bridge",  "L1 Fee Vault",         "bridge"),
}

CEX_SET: frozenset[str] = frozenset(_CEX_DB)


def is_cex(addr: str) -> bool:
    return addr.lower() in CEX_SET


def get_label(addr: str) -> tuple[str, str, str]:
    """Return (exchange, label, type). Falls back to short-form address."""
    info = _CEX_DB.get(addr.lower())
    return info if info else ("Unknown", f"{addr[:6]}…{addr[-4:]}", "unknown")


def classify(from_addr: str, to_addr: str) -> dict:
    """
    Classify a transfer into a typed signal dict:
      type, emoji, label, direction, detail, from_label, to_label
    """
    f  = from_addr.lower()
    t  = to_addr.lower()
    fi = _CEX_DB.get(f, ("?", f"{from_addr[:6]}…{from_addr[-4:]}", "unknown"))
    ti = _CEX_DB.get(t, ("?", f"{to_addr[:6]}…{to_addr[-4:]}", "unknown"))
    f_type = fi[2]
    t_type = ti[2]

    # ── Bridge flows ─────────────────────────────────────────────────────────
    if f_type == "bridge" or t_type == "bridge":
        if t_type == "bridge":
            return {
                "type":       "BRIDGE_OUT",
                "emoji":      "🌉🔴",
                "label":      "BRIDGE OUT",
                "direction":  f"Wallet → {ti[1]}",
                "detail":     "Tokens leaving Base — possible sell / exit signal",
                "from_label": fi[1],
                "to_label":   ti[1],
            }
        return {
            "type":       "BRIDGE_IN",
            "emoji":      "🌉🟢",
            "label":      "BRIDGE INFLOW",
            "direction":  f"{fi[1]} → Wallet",
            "detail":     "Capital arriving on Base — bullish institutional flow",
            "from_label": fi[1],
            "to_label":   ti[1],
        }

    # ── CEX flows ─────────────────────────────────────────────────────────────
    f_cex = f in CEX_SET
    t_cex = t in CEX_SET

    if f_cex and not t_cex:
        return {
            "type":       "ACC",
            "emoji":      "🟢",
            "label":      "ACCUMULATION",
            "direction":  f"{fi[1]} → Private wallet",
            "detail":     f"Withdrawn from {fi[1]} — BUY / HOLD",
            "from_label": fi[1],
            "to_label":   ti[1],
        }
    if t_cex and not f_cex:
        return {
            "type":       "DIS",
            "emoji":      "🔴",
            "label":      "DISTRIBUTION",
            "direction":  f"Private wallet → {ti[1]}",
            "detail":     f"Deposited to {ti[1]} — SELL pressure",
            "from_label": fi[1],
            "to_label":   ti[1],
        }
    if f_cex and t_cex:
        return {
            "type":       "CEX_CEX",
            "emoji":      "🟠",
            "label":      "POSSIBLE SELL",
            "direction":  f"{fi[1]} → {ti[1]}",
            "detail":     "CEX-to-CEX transfer (OTC routing / internal)",
            "from_label": fi[1],
            "to_label":   ti[1],
        }

    return {
        "type":       "WHALE",
        "emoji":      "🐋",
        "label":      "WHALE MOVE",
        "direction":  "Wallet → Wallet (OTC / cold storage)",
        "detail":     "Large peer-to-peer transfer",
        "from_label": fi[1],
        "to_label":   ti[1],
    }
