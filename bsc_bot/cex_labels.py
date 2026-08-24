"""
BSC Whale Alert Bot — CEX Wallet Database & Signal Classification

Signal logic:
  CEX  → Wallet  = 🟢 ACCUMULATION   (coins leaving exchange → bullish)
  Wallet → CEX   = 🔴 DISTRIBUTION   (coins entering exchange → bearish)
  CEX  → CEX     = 🟠 POSSIBLE SELL  (OTC routing or disguised selling)
  Wallet → Wallet = 🐋 WHALE MOVE    (OTC / cold storage, neutral)

All addresses stored lowercase for fast O(1) lookup.
"""

# ── CEX Hot & Cold Wallet Database ───────────────────────────────────────────
CEX_WALLETS: dict[str, str] = {

    # ── BINANCE (largest BSC presence — BSC is their chain) ──────────────────
    "0x8894e0a0c962cb723c1976a4421c95949be2d4e3": "Binance Hot 1",
    "0xe2fc31f816a9b3aa888729e996f3a2e8d40f3f47": "Binance Hot 2",
    "0x3c783c21a0383057d128bae431894a5c19f9cf06": "Binance Hot 3",
    "0xf977814e90da44bfa03b6295a0616a897441acec": "Binance Cold 1",
    "0x28c6c06298d514db089934071355e5743bf21d60": "Binance Hot 4",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "Binance Hot 5",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "Binance Hot 6",
    "0x56eddb7aa87536c09ccc2793473599fd21a8b17f": "Binance Hot 7",
    "0x9696f59e4d72e237be84ffd425dcad154bf96976": "Binance Deployer",
    "0x4b16c5de96eb2117bbe5fd171e4d203624b014aa": "Binance Hot 8",
    "0x5a52e96bacdabb82fd05763e25335261b270efcb": "Binance Hot 9",
    "0xbe0eb53f46cd790cd13851d5eff43d12404d33e8": "Binance Cold 2",
    "0xa344c7ada83113b3b56941f6e85bf2eb425949f3": "Binance Hot 10",
    "0x0681d8db095565fe8a346fa0277bffde9c0edbbf": "Binance Hot 11",

    # ── OKX ──────────────────────────────────────────────────────────────────
    "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "OKX Hot 1",
    "0x98ec059dc3adfbdd63429454aeb0c990fba4a128": "OKX Hot 2",
    "0x5041ed759dd4afc3a72b8192c143f72f4724081a": "OKX Hot 3",
    "0xa7efae728d2936e78bda97dc267687568dd593f3": "OKX Cold",
    "0x236f9f97e0e62388479bf9e5ba4889e46b0273c3": "OKX Hot 4",
    "0x461249076b88189f8ac9418de28b365859e46bfd": "OKX Hot 5",

    # ── BYBIT ────────────────────────────────────────────────────────────────
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "Bybit Hot 1",
    "0x1db92e2eebc8e0c075a02bea49a2935bcd2dfcf4": "Bybit Hot 2",
    "0x6ebaf477f83e055589c1188bcc6ddccd8c9b131a": "Bybit Hot 3",
    "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b": "Bybit Cold",
    "0x2d4c407bbe49438ed859fe965b140dcf1aab71a9": "Bybit Hot 4",

    # ── KUCOIN ───────────────────────────────────────────────────────────────
    "0x2b5634c42055806a59e9107ed44d43c426e58258": "KuCoin Hot 1",
    "0xa1d8d972560c2f8144af871db508f0b0b10a3fbf": "KuCoin Hot 2",
    "0x689c56aef474df92d44a1b70850f808488f9769c": "KuCoin Cold",
    "0x3052f1e0a5c01bda4c3a0f4d6e6bd04b90d5a8d5": "KuCoin Hot 3",

    # ── GATE.IO ──────────────────────────────────────────────────────────────
    "0x0d0707963952f2fba59dd06f2b425ace40b492fe": "Gate.io Hot 1",
    "0x7c5d9305a6df2e38c2c41b3e8bcf51a00b35e73f": "Gate.io Hot 2",

    # ── HUOBI / HTX ──────────────────────────────────────────────────────────
    "0xab5c66752a9e8167967685f1450532fb96d5d24f": "HTX Hot 1",
    "0x6748f50f686bfbca6fe8ad62b22228b87f31ff2b": "HTX Hot 2",
    "0xeee28d484628d41a82d01e21d12e2e78d69920da": "HTX Hot 3",
    "0x1062a747393198f70f71ec65a582423dba7e5ab3": "HTX Cold",

    # ── MEXC ─────────────────────────────────────────────────────────────────
    "0x0211f3cedbef3143223d3acf0e589747933e8527": "MEXC Hot 1",
    "0x75e89d5979e4f6fba9f97c104c2f0afb3f1dcb88": "MEXC Hot 2",

    # ── CRYPTO.COM ───────────────────────────────────────────────────────────
    "0x6262998ced04146fa42253a5c0af90ca02dfd2a3": "Crypto.com Hot 1",
    "0xcffad3200574698b78f32232aa9d63eabd290703": "Crypto.com Hot 2",

    # ── BITGET ───────────────────────────────────────────────────────────────
    "0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23": "Bitget Hot 1",
    "0x0639556f03714a74a5feeaf5736a4a64ff70d206": "Bitget Hot 2",

    # ── BINGX ────────────────────────────────────────────────────────────────
    "0x0d0d65e7a7db277d3e0f5e1676325e75f3340455": "BingX Hot",

    # ── BITMART ──────────────────────────────────────────────────────────────
    "0xe79eef9b9388a4ff70ed7ec5bccd5b928ebb8bd1": "BitMart Hot",

    # ── COINBASE ─────────────────────────────────────────────────────────────
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "Coinbase Hot",
    "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": "Coinbase Prime",

    # ── KRAKEN ───────────────────────────────────────────────────────────────
    "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "Kraken Hot",

    # ── PHEMEX ───────────────────────────────────────────────────────────────
    "0xab5801a7d398351b8be11c439e05c5b3259aec9b": "Phemex Hot",

    # ── BITFINEX ─────────────────────────────────────────────────────────────
    "0x77134cbc06cb00b66f4c7e623d5fdbf6777635ec": "Bitfinex Hot",

    # ── POLONIEX ─────────────────────────────────────────────────────────────
    "0x32be343b94f860124dc4fee278fdcbd38c102d88": "Poloniex Hot",

    # ── FALCONX (institutional OTC desk) ─────────────────────────────────────
    "0x1151cb3d861920e07a38e03eead12c32178567f6": "FalconX Hot Wallet",
    "0x4585fe77225b41b697c938b018e2ac67ac5a20c0": "FalconX Deposit",
    "0x7b7b57b31fa0c1e5cda2a9f0b583e7d2b0cd985a": "FalconX Hot 2",

    # ── WINTERMUTE (market maker) ─────────────────────────────────────────────
    "0x4f3a120e72c76c22ae802d129f599bfdbc31cb81": "Wintermute Hot 1",
    "0x00000000ae347930bd1e7b0f35588b92280f9e75": "Wintermute Hot 2",

    # ── CUMBERLAND DRW ────────────────────────────────────────────────────────
    "0xdc76cd25977e0a5ae17155770273ad58648900d3": "Cumberland Hot 1",
    "0x08a3c2a819e3de7aca384c798269b3ce1cd0e437": "Cumberland Hot 2",

    # ── JUMP TRADING ──────────────────────────────────────────────────────────
    "0x46a3a41bd932244dd08186e4c19f1a7e48cbcdf4": "Jump Trading Hot 1",

    # ── B2C2 ─────────────────────────────────────────────────────────────────
    "0x01e2919679362dfbc9ee1644ba9c6da6d6245bb1": "B2C2 Hot 1",
}

CEX_SET = set(CEX_WALLETS.keys())


def is_cex(address: str) -> bool:
    return address.lower() in CEX_SET


def get_cex_name(address: str) -> str:
    return CEX_WALLETS.get(address.lower(), "Unknown Exchange")


def _short(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}"


def classify(from_addr: str, to_addr: str) -> dict:
    """
    Core signal classification.  Direction matters — not just participation.
    Returns a signal dict with type, emoji, label, direction, note, impact.
    """
    f = from_addr.lower()
    t = to_addr.lower()

    from_cex = is_cex(f)
    to_cex   = is_cex(t)

    from_tag = get_cex_name(f) if from_cex else _short(f)
    to_tag   = get_cex_name(t) if to_cex   else _short(t)

    # ── CEX → Wallet — ACCUMULATION (bullish) ────────────────────────────────
    if from_cex and not to_cex:
        return {
            "type":      "ACCUMULATION",
            "emoji":     "🟢",
            "label":     "ACCUMULATION",
            "direction": "BUY / HOLD",
            "note":      f"Withdrawn from <b>{from_tag}</b> to private wallet",
            "from_tag":  from_tag,
            "to_tag":    to_tag,
            "impact":    "📈 <b>Bullish</b> — supply leaving exchange",
        }

    # ── Wallet → CEX — DISTRIBUTION (bearish) ────────────────────────────────
    if to_cex and not from_cex:
        return {
            "type":      "DISTRIBUTION",
            "emoji":     "🔴",
            "label":     "DISTRIBUTION",
            "direction": "SELL",
            "note":      f"Deposited to <b>{to_tag}</b> from private wallet",
            "from_tag":  from_tag,
            "to_tag":    to_tag,
            "impact":    "📉 <b>Bearish</b> — supply entering exchange",
        }

    # ── CEX → CEX — POSSIBLE DISGUISED SELL ──────────────────────────────────
    if from_cex and to_cex:
        return {
            "type":      "CEX_TO_CEX",
            "emoji":     "🟠",
            "label":     "POSSIBLE SELL",
            "direction": "WATCH",
            "note":      f"<b>{from_tag}</b> → <b>{to_tag}</b>. OTC routing or rebalancing.",
            "from_tag":  from_tag,
            "to_tag":    to_tag,
            "impact":    "⚠️ Ambiguous — monitor price action",
        }

    # ── Wallet → Wallet — WHALE MOVE (neutral) ───────────────────────────────
    return {
        "type":      "WHALE_MOVE",
        "emoji":     "🐋",
        "label":     "WHALE MOVE",
        "direction": "NEUTRAL",
        "note":      "Large wallet-to-wallet transfer. OTC or cold storage move.",
        "from_tag":  from_tag,
        "to_tag":    to_tag,
        "impact":    "⚪ Neutral — no immediate exchange pressure",
    }
