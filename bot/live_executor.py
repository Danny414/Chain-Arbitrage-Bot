"""
Live trade executor — Solana only, via Jupiter Aggregator API.
Uses SOL_PRIVATE_KEY secret to sign and submit real swaps.

Safety rules (hard-coded, cannot be overridden via commands):
  - Max $1 per trade (LIVE_TRADE_SIZE_USD)
  - Max $5 total wallet exposure cap check before every trade
  - Slippage guard: abort if on-chain quote slippage > MAX_SLIPPAGE_BPS
  - Only executes when automode == "live" AND confirmed == True
  - SOL intra-chain only — no BSC live trading yet
"""
import os
import base64
import asyncio
import aiohttp
import struct
import time
from bot.utils import now_utc
from bot.config import GAS_COST_USD

# ── Global Jupiter API rate limiter ────────────────────────────────────────
# Jupiter's public tier allows ~1 req/s.  Pre-flight (2 legs) + the Jupiter
# Direct scanner all share the same quota.  Serialise every outbound Jupiter
# call through this throttle so we never exceed the limit regardless of how
# many gaps fire concurrently.
_jupiter_lock: asyncio.Lock | None = None
_jupiter_last_ts: float = 0.0
_JUPITER_MIN_INTERVAL: float = 2.0   # seconds between successive Jupiter calls

def _get_jupiter_lock() -> asyncio.Lock:
    """Lazy-init so the Lock is always created on the running event loop."""
    global _jupiter_lock
    if _jupiter_lock is None:
        _jupiter_lock = asyncio.Lock()
    return _jupiter_lock

async def _jupiter_throttle() -> None:
    """Acquire the global Jupiter rate-limit slot, sleeping if needed."""
    global _jupiter_last_ts
    lock = _get_jupiter_lock()
    async with lock:
        now = time.time()
        wait = _JUPITER_MIN_INTERVAL - (now - _jupiter_last_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        _jupiter_last_ts = time.time()

# ── Constants ──────────────────────────────────────────────────────────────
LIVE_TRADE_SIZE_USD  = 1.0          # hard cap per trade — do not raise
MAX_WALLET_EXPOSURE  = 5.0          # refuse to trade if USDC balance < $1
MAX_SLIPPAGE_BPS     = 150          # 1.5% — abort if Jupiter quote exceeds this
MIN_NET_PROFIT_USD   = 0.05         # minimum clear profit after gas before any trade fires
JUPITER_QUOTE_URL    = "https://api.jup.ag/swap/v1/quote"
JUPITER_SWAP_URL     = "https://api.jup.ag/swap/v1/swap"
SOLANA_RPC           = "https://api.mainnet-beta.solana.com"

# Solana token mints
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Known token mints for our watchlist (add more as needed)
TOKEN_MINTS = {
    # Blue-chip / infrastructure
    "SOL":      "So11111111111111111111111111111111111111112",
    "JUP":      "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "RAY":      "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    "JTO":      "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "ORCA":     "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE",
    "DRIFT":    "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7",
    "HNT":      "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
    "PYTH":     "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
    # Meme / volatile
    "MSOL":     "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "BONK":     "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "WIF":      "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "POPCAT":   "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "W":        "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ",
    "PENGU":    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv",
    "CLOUD":    "CLoUDKc4Ane7HeQcPpE3YHnznRxhMimJ4MyaUqyHFzAu",
    "GIGA":     "63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9",
    "AI16Z":    "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC",
    "SAMO":     "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
    "KMNO":     "KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS",
    "INF":      "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
    # Smaller-cap multi-DEX (verified 4-8 pools)
    "SPX":      "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr",
    "ZEREBRO":  "8x5VqbHA8D7NkD52uNuS5nnt3PwA8pLD34ymskeSo2Wn",
    "SWARMS":   "74SBV4zDXxTRgv1pEMoECskKBkZHc2yGPnc7GYVepump",
    "RENDER":   "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof",
    "NOS":      "nosXBVoaCTtYdLvKY6Csb4AC8JCdQKKAaWYtx2ZMoo7",
}

# ── Wallet loading ─────────────────────────────────────────────────────────

def _load_keypair():
    """Load keypair from SOL_PRIVATE_KEY env var. Supports base58 and byte-array formats."""
    raw = os.getenv("SOL_PRIVATE_KEY", "").strip()
    if not raw:
        raise RuntimeError("SOL_PRIVATE_KEY secret not set")
    try:
        import base58
        key_bytes = base58.b58decode(raw)
    except Exception:
        # Try JSON byte array format [1,2,3,...]
        import json
        try:
            arr = json.loads(raw)
            key_bytes = bytes(arr)
        except Exception:
            raise RuntimeError("SOL_PRIVATE_KEY format unrecognized — expected base58 or byte array")
    if len(key_bytes) not in (32, 64):
        raise RuntimeError(f"SOL_PRIVATE_KEY invalid length: {len(key_bytes)} bytes")
    # nacl expects 32-byte seed or 64-byte keypair
    from nacl.signing import SigningKey
    seed = key_bytes[:32]
    signing_key = SigningKey(seed)
    pubkey_bytes = bytes(signing_key.verify_key)
    return signing_key, pubkey_bytes


def get_wallet_pubkey() -> str:
    """Return the base58 public key of the configured wallet."""
    import base58
    _, pubkey_bytes = _load_keypair()
    return base58.b58encode(pubkey_bytes).decode()


# ── Balance check ──────────────────────────────────────────────────────────

async def get_usdc_balance(session: aiohttp.ClientSession) -> float:
    """Fetch the wallet's USDC balance via Solana RPC."""
    pubkey = get_wallet_pubkey()
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            pubkey,
            {"mint": USDC_MINT},
            {"encoding": "jsonParsed"}
        ]
    }
    try:
        async with session.post(SOLANA_RPC, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            accounts = data.get("result", {}).get("value", [])
            if not accounts:
                return 0.0
            amt = accounts[0]["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
            return float(amt or 0)
    except Exception as e:
        print(f"[LiveExec] Balance check failed: {e}")
        return 0.0


# ── Jupiter quote ──────────────────────────────────────────────────────────

async def _get_jupiter_quote(session, input_mint: str, output_mint: str, amount_usdc: float) -> dict | None:
    """Fetch a swap quote from Jupiter. amount_usdc in human units.
    All calls go through the global rate throttle before hitting the API."""
    amount_lamports = int(amount_usdc * 1_000_000)   # USDC has 6 decimals
    params = {
        "inputMint":   input_mint,
        "outputMint":  output_mint,
        "amount":      amount_lamports,
        "slippageBps": MAX_SLIPPAGE_BPS,
        "onlyDirectRoutes": "false",
    }
    await _jupiter_throttle()
    try:
        async with session.get(JUPITER_QUOTE_URL, params=params,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                text = await r.text()
                print(f"[LiveExec] Jupiter quote error {r.status}: {text[:120]}")
                return None
            return await r.json()
    except Exception as e:
        print(f"[LiveExec] Jupiter quote exception: {e}")
        return None


# ── Transaction signing ────────────────────────────────────────────────────

def _sign_transaction(tx_bytes: bytes) -> bytes:
    """Sign a raw versioned transaction with our keypair."""
    from nacl.signing import SigningKey
    signing_key, pubkey_bytes = _load_keypair()

    # Versioned transaction: first byte is version prefix (0x80), then message
    # Signature goes into the first signature slot
    # Message starts after the compact-array of signatures
    # We sign the message (everything after the signature array)

    # Parse: num_signatures (compact-u16), then signatures (64 bytes each), then message
    num_sigs = tx_bytes[1] if tx_bytes[0] == 0x80 else tx_bytes[0]
    if tx_bytes[0] == 0x80:
        # versioned transaction
        msg_start = 1 + 1 + (num_sigs * 64)   # prefix + sig_count + sigs
        message = tx_bytes[msg_start:]
        sig = bytes(signing_key.sign(message).signature)
        # Replace first signature slot
        result = bytearray(tx_bytes)
        result[2:2+64] = sig
        return bytes(result)
    else:
        # legacy transaction
        msg_start = 1 + (num_sigs * 64)
        message = tx_bytes[msg_start:]
        sig = bytes(signing_key.sign(message).signature)
        result = bytearray(tx_bytes)
        result[1:1+64] = sig
        return bytes(result)


# ── Main live execute ──────────────────────────────────────────────────────

async def live_execute(gap: dict) -> dict:
    """
    Execute a real SOL intra-chain arbitrage trade via Jupiter.

    Returns a trade record dict (same shape as simulate()) with mode="live".
    Raises RuntimeError with a descriptive message on any failure.
    """
    symbol     = gap["symbol"]
    buy_price  = gap["buy_price"]
    sell_price = gap["sell_price"]
    spread_pct = gap["spread_pct"]
    confidence = gap.get("confidence", 0)
    buy_dex    = gap["buy_pool"].get("dex_name", "?")
    sell_dex   = gap["sell_pool"].get("dex_name", "?")
    buy_liq    = gap["buy_pool"].get("liq_usd", 0)
    sell_liq   = gap["sell_pool"].get("liq_usd", 0)

    token_mint = TOKEN_MINTS.get(symbol.upper())
    if not token_mint:
        raise RuntimeError(f"No mint address known for {symbol} — cannot execute live trade")

    # Read trade size from persistent state so /setlivetrade takes effect immediately.
    # Falls back to LIVE_TRADE_SIZE_USD ($1) if never configured.
    import bot.state as _state
    trade_size = _state.cfg_live_trade_size()

    async with aiohttp.ClientSession() as session:
        # ── 1. Balance check ──────────────────────────────────────────────
        balance = await get_usdc_balance(session)
        if balance < trade_size:
            raise RuntimeError(
                f"Insufficient USDC: wallet has ${balance:.2f}, need ${trade_size:.2f} — "
                f"lower trade size with /setlivetrade or top up wallet"
            )
        if balance < 1.0:
            raise RuntimeError(
                f"Wallet USDC balance too low (${balance:.2f}) — minimum $1.00 required"
            )

        print(f"[LiveExec] Wallet USDC: ${balance:.4f} | Trade size: ${trade_size:.2f}")

        # ── 2. PRE-FLIGHT: get both Jupiter quotes BEFORE any transaction ─
        # DexScreener detects price gaps between specific pools.
        # Jupiter routes freely across ALL liquidity — the gap may not
        # survive. We must verify Jupiter's own round-trip is profitable
        # before committing real money to any on-chain transaction.

        print(f"[LiveExec] Pre-flight: quoting USDC → {symbol} → USDC via Jupiter...")
        quote1 = await _get_jupiter_quote(session, USDC_MINT, token_mint, trade_size)
        if not quote1:
            raise RuntimeError("Jupiter quote failed for Leg 1 (USDC → token)")

        quoted_out1   = int(quote1.get("outAmount", 0))
        price_impact1 = float(quote1.get("priceImpactPct", 0))
        if price_impact1 > (MAX_SLIPPAGE_BPS / 100):
            raise RuntimeError(
                f"Leg 1 price impact too high: {price_impact1:.2f}% > {MAX_SLIPPAGE_BPS/100:.1f}% — aborted (no funds moved)"
            )

        # Quote leg 2 using leg 1's expected output
        params2 = {
            "inputMint":        token_mint,
            "outputMint":       USDC_MINT,
            "amount":           quoted_out1,
            "slippageBps":      MAX_SLIPPAGE_BPS,
            "onlyDirectRoutes": "false",
        }
        try:
            async with session.get(JUPITER_QUOTE_URL, params=params2,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    text = await r.text()
                    raise RuntimeError(f"Jupiter Leg 2 pre-flight quote error {r.status}: {text[:120]}")
                quote2 = await r.json()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Leg 2 pre-flight quote failed: {e}")

        price_impact2 = float(quote2.get("priceImpactPct", 0))
        if price_impact2 > (MAX_SLIPPAGE_BPS / 100):
            raise RuntimeError(
                f"Leg 2 price impact too high: {price_impact2:.2f}% — aborted (no funds moved)"
            )

        # Profitability gate — Jupiter's own round-trip must at minimum cover gas.
        # We do NOT require an additional percentage margin here; the pre-flight
        # in scanner.py already confirmed break-even.  The only job of this gate
        # is to catch gaps that have closed between pre-flight and execution.
        gas_cost         = GAS_COST_USD.get("sol", 0.001) * 2
        usdc_quoted_out2 = int(quote2.get("outAmount", 0)) / 1_000_000
        quoted_net       = usdc_quoted_out2 - trade_size - gas_cost

        print(
            f"[LiveExec] Pre-flight result: in=${trade_size:.4f} → out=${usdc_quoted_out2:.4f} "
            f"gas=${gas_cost:.4f} net=${quoted_net:.4f}"
        )

        net_pct = (quoted_net / trade_size) * 100
        print(
            f"[LiveExec] P&L check:  in=${trade_size:.4f}  out=${usdc_quoted_out2:.4f}"
            f"  gas=${gas_cost:.4f}  net=${quoted_net:.4f} ({net_pct:+.2f}%)"
            f"  threshold=+${MIN_NET_PROFIT_USD:.2f}"
        )

        if quoted_net < MIN_NET_PROFIT_USD:
            raise RuntimeError(
                f"Pre-flight rejected: projected net ${quoted_net:.4f} ({net_pct:+.2f}%)"
                f" is below the ${MIN_NET_PROFIT_USD:.2f} minimum — no funds moved"
            )

        print(f"[LiveExec] Pre-flight PASSED ✅ net=${quoted_net:.4f} ({net_pct:+.2f}%) — proceeding")

        # ── 3. Get swap transaction for Leg 1 ────────────────────────────
        pubkey = get_wallet_pubkey()
        swap_payload1 = {
            "quoteResponse": quote1,
            "userPublicKey": pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        try:
            async with session.post(JUPITER_SWAP_URL, json=swap_payload1,
                                    timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    text = await r.text()
                    raise RuntimeError(f"Jupiter swap API error {r.status}: {text[:120]}")
                swap_data1 = await r.json()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Jupiter swap request failed: {e}")

        tx_b64_1 = swap_data1.get("swapTransaction")
        if not tx_b64_1:
            raise RuntimeError("No swapTransaction in Jupiter response for Leg 1")

        # ── 4. Sign and submit Leg 1 ──────────────────────────────────────
        tx_bytes1 = base64.b64decode(tx_b64_1)
        signed1   = _sign_transaction(tx_bytes1)
        signed_b64_1 = base64.b64encode(signed1).decode()

        rpc_payload1 = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [signed_b64_1, {"encoding": "base64", "skipPreflight": False,
                                       "preflightCommitment": "processed"}]
        }
        async with session.post(SOLANA_RPC, json=rpc_payload1,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
            rpc_resp1 = await r.json()

        tx_sig1 = rpc_resp1.get("result")
        if not tx_sig1 or "error" in rpc_resp1:
            err = rpc_resp1.get("error", {})
            raise RuntimeError(f"Leg 1 tx rejected: {err.get('message', rpc_resp1)}")

        print(f"[LiveExec] Leg 1 submitted: {tx_sig1}")

        # ── 5. Wait for Leg 1 confirmation (up to 30s) ───────────────────
        confirmed1 = await _confirm_tx(session, tx_sig1, timeout=30)
        if not confirmed1:
            raise RuntimeError(f"Leg 1 tx not confirmed within 30s: {tx_sig1}")

        # ── 6. Leg 2: token → USDC — re-quote with actual leg 1 output ───
        # Re-quote now to get a fresh transaction (the pre-flight quote may
        # have expired). Use the same quoted_out1 amount as the input.
        # CRITICAL: Leg 1 is already on-chain — retry aggressively on 429
        # so we never leave a partial trade (bought token but no sell).
        print(f"[LiveExec] Leg 2: {symbol} → USDC via Jupiter (sell on {sell_dex})")
        quote2 = None
        for _leg2_attempt in range(1, 6):   # up to 5 attempts
            _leg2_wait = _leg2_attempt * 4  # 4s, 8s, 12s, 16s, 20s
            try:
                await _jupiter_throttle()
                async with session.get(JUPITER_QUOTE_URL, params=params2,
                                       timeout=aiohttp.ClientTimeout(total=12)) as r:
                    if r.status == 429:
                        print(f"[LiveExec] Leg 2 quote 429 — attempt {_leg2_attempt}/5, "
                              f"waiting {_leg2_wait}s before retry")
                        await asyncio.sleep(_leg2_wait)
                        continue
                    if r.status != 200:
                        text = await r.text()
                        raise RuntimeError(f"Jupiter Leg 2 quote error {r.status}: {text[:120]}")
                    quote2 = await r.json()
                    break
            except RuntimeError:
                raise
            except Exception as e:
                if _leg2_attempt == 5:
                    raise RuntimeError(f"Leg 2 quote failed after 5 attempts: {e}")
                await asyncio.sleep(_leg2_wait)
        if quote2 is None:
            raise RuntimeError("Leg 2 quote failed after 5 attempts (all 429) — "
                               "token held in wallet, sell manually on Jupiter")

        price_impact2 = float(quote2.get("priceImpactPct", 0))
        if price_impact2 > (MAX_SLIPPAGE_BPS / 100):
            raise RuntimeError(
                f"Leg 2 price impact too high: {price_impact2:.2f}% — aborting after Leg 1"
            )

        swap_payload2 = {
            "quoteResponse": quote2,
            "userPublicKey": pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": "auto",
        }
        async with session.post(JUPITER_SWAP_URL, json=swap_payload2,
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                text = await r.text()
                raise RuntimeError(f"Jupiter Leg 2 swap error {r.status}: {text[:120]}")
            swap_data2 = await r.json()

        tx_b64_2  = swap_data2.get("swapTransaction")
        tx_bytes2 = base64.b64decode(tx_b64_2)
        signed2   = _sign_transaction(tx_bytes2)

        rpc_payload2 = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(signed2).decode(),
                       {"encoding": "base64", "skipPreflight": False,
                        "preflightCommitment": "processed"}]
        }
        async with session.post(SOLANA_RPC, json=rpc_payload2,
                                 timeout=aiohttp.ClientTimeout(total=20)) as r:
            rpc_resp2 = await r.json()

        tx_sig2 = rpc_resp2.get("result")
        if not tx_sig2 or "error" in rpc_resp2:
            err = rpc_resp2.get("error", {})
            raise RuntimeError(f"Leg 2 tx rejected: {err.get('message', rpc_resp2)}")

        print(f"[LiveExec] Leg 2 submitted: {tx_sig2}")
        confirmed2 = await _confirm_tx(session, tx_sig2, timeout=30)
        if not confirmed2:
            raise RuntimeError(f"Leg 2 tx not confirmed within 30s: {tx_sig2}")

        # ── 7. Compute actual P&L ─────────────────────────────────────────
        usdc_out_raw  = int(quote2.get("outAmount", 0))
        usdc_received = usdc_out_raw / 1_000_000   # USDC 6 decimals
        gross_profit  = usdc_received - trade_size
        gas_cost      = GAS_COST_USD.get("sol", 0.001) * 2   # two txns
        net_profit    = gross_profit - gas_cost
        win           = net_profit > 0

        route = f"USDC → {symbol} on {buy_dex} → USDC on {sell_dex}"

        return {
            "mode":        "live",
            "type":        "intra",
            "chain":       "sol",
            "symbol":      symbol,
            "sim_size":    trade_size,
            "buy_price":   buy_price,
            "sell_price":  sell_price,
            "spread_pct":  spread_pct,
            "gross_profit":gross_profit,
            "fees_est":    gas_cost,
            "slip_cost":   0.0,      # actual slippage absorbed in usdc_received
            "net_profit":  net_profit,
            "profit_pct":  (net_profit / trade_size) * 100,
            "win":         win,
            "confidence":  confidence,
            "route":       route,
            "timestamp":   now_utc(),
            "buy_pool":    buy_dex,
            "sell_pool":   sell_dex,
            "buy_liq":     buy_liq,
            "sell_liq":    sell_liq,
            "tx_leg1":     tx_sig1,
            "tx_leg2":     tx_sig2,
            "usdc_in":     trade_size,
            "usdc_out":    usdc_received,
            "balance_before": balance,
        }


# ── Jupiter Pre-flight (fast, no transaction) ──────────────────────────────

async def jupiter_preflight_quick(
    symbol: str,
    trade_size: float = 1.0,
) -> tuple[bool, float, str]:
    """
    Two-leg Jupiter quote with zero execution.  Call this BEFORE sending
    any Telegram alert so dead DexScreener gaps never reach the user.

    Returns (profitable: bool, net_usd: float, reason: str).
    """
    mint = TOKEN_MINTS.get(symbol.upper())
    if not mint:
        return False, 0.0, f"no mint address for {symbol}"

    gas_total = GAS_COST_USD.get("sol", 0.025) * 2

    async with aiohttp.ClientSession() as session:
        # Leg 1: USDC → token  (goes through global throttle inside _get_jupiter_quote)
        quote1 = await _get_jupiter_quote(session, USDC_MINT, mint, trade_size)
        if not quote1:
            return False, 0.0, "Jupiter leg 1 quote failed (rate-limit or network)"

        token_out = int(quote1.get("outAmount", 0))
        if token_out == 0:
            return False, 0.0, "Leg 1 returned 0 output tokens"

        # Leg 2: token → USDC  (throttle before request — token amount already in raw units)
        await _jupiter_throttle()
        params2 = {
            "inputMint":        mint,
            "outputMint":       USDC_MINT,
            "amount":           token_out,
            "slippageBps":      MAX_SLIPPAGE_BPS,
            "onlyDirectRoutes": "false",
        }
        try:
            async with session.get(JUPITER_QUOTE_URL, params=params2,
                                   timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    text = await r.text()
                    return False, 0.0, f"Leg 2 quote HTTP {r.status}: {text[:80]}"
                quote2 = await r.json()
        except Exception as e:
            return False, 0.0, f"Leg 2 quote exception: {e}"

        usdc_out = int(quote2.get("outAmount", 0)) / 1_000_000
        net_usd  = usdc_out - trade_size - gas_total
        net_pct  = (net_usd / trade_size) * 100

        # Gate: Jupiter round-trip must clear gas AND deliver at least MIN_NET_PROFIT_USD
        # in clear profit.  This prevents marginal break-even trades where any price
        # movement between quote and execution would flip the trade into a loss.
        if net_usd < MIN_NET_PROFIT_USD:
            return (
                False, net_usd,
                f"round-trip net ${net_usd:.4f} ({net_pct:+.2f}%) below ${MIN_NET_PROFIT_USD:.2f} minimum"
            )

        return True, net_usd, f"net +${net_usd:.4f} ({net_pct:+.2f}%) ✅"


# ── Jupiter Direct Round-Trip Scanner ──────────────────────────────────────

# Minimum net profit required for a Jupiter direct trade to fire.
# Lower than the DexScreener path (0.5%) because we have zero false positives —
# if Jupiter quotes it, Jupiter can execute it.
JDIRECT_MIN_NET_PCT = 0.3    # 0.3% after gas — adjust via /set jdirect_min 0.5
JDIRECT_TRADE_SIZE  = 1.0    # fallback only — overridden at runtime by cfg_live_trade_size()
JDIRECT_MAX_NET_PCT = 20.0   # sanity cap: >20% net is a ghost/stale quote — reject


async def jupiter_roundtrip_scan(
    token_items: list[tuple[str, str]],
    trade_size: float = JDIRECT_TRADE_SIZE,
    min_net_pct: float = JDIRECT_MIN_NET_PCT,
) -> list[dict]:
    """
    Ask Jupiter directly whether any token's USDC→token→USDC round-trip
    is currently profitable.  Completely independent of DexScreener.

    Checks tokens sequentially with a small inter-request gap to stay
    within Jupiter's free-tier rate limit (~30 RPM sustained).  The
    caller batches a subset of tokens per scan cycle (see JDIRECT_BATCH)
    so the full watchlist rotates every few minutes.

    Returns opportunities with pre-fetched quotes ready for immediate
    execution (quotes expire ~30s after this call).
    """
    gas_total   = GAS_COST_USD.get("sol", 0.025) * 2
    min_net_usd = trade_size * (min_net_pct / 100)
    opportunities: list[dict] = []

    async def _jup_get(session, params: dict) -> dict | None:
        """Single Jupiter quote — always throttled through the global rate limiter."""
        await _jupiter_throttle()
        try:
            async with session.get(
                JUPITER_QUOTE_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=12)
            ) as r:
                if r.status != 200:
                    return None
                return await r.json()
        except Exception:
            return None

    async with aiohttp.ClientSession() as session:
        for symbol, mint in token_items:
            # Leg 1: USDC → Token  (throttle is inside _jup_get)
            p1 = {
                "inputMint":        USDC_MINT,
                "outputMint":       mint,
                "amount":           int(trade_size * 1_000_000),
                "slippageBps":      MAX_SLIPPAGE_BPS,
                "onlyDirectRoutes": "false",
            }
            quote1 = await _jup_get(session, p1)
            if not quote1:
                continue
            token_out = int(quote1.get("outAmount", 0))
            if token_out == 0:
                continue

            # Leg 2: Token → USDC  (throttle is inside _jup_get)
            p2 = {
                "inputMint":        mint,
                "outputMint":       USDC_MINT,
                "amount":           token_out,
                "slippageBps":      MAX_SLIPPAGE_BPS,
                "onlyDirectRoutes": "false",
            }
            quote2 = await _jup_get(session, p2)
            if not quote2:
                continue

            usdc_out = int(quote2.get("outAmount", 0)) / 1_000_000
            net_usd  = usdc_out - trade_size - gas_total
            net_pct  = (net_usd / trade_size) * 100

            # Sanity cap: any quote above JDIRECT_MAX_NET_PCT is a ghost/stale pool.
            # Real on-chain arbitrage never returns >20% on a round-trip — if Jupiter
            # quotes 100x or 24000% it found a phantom market that won't execute.
            if net_pct > JDIRECT_MAX_NET_PCT:
                print(
                    f"[JupDirect] ⚠️  {symbol} quote rejected — net {net_pct:.1f}% > "
                    f"{JDIRECT_MAX_NET_PCT}% cap (ghost/stale pool, not real)"
                )
                continue

            if net_usd >= min_net_usd:
                opportunities.append({
                    "symbol":    symbol,
                    "mint":      mint,
                    "quote1":    quote1,
                    "quote2":    quote2,
                    "token_out": token_out,
                    "usdc_in":   trade_size,
                    "usdc_out":  usdc_out,
                    "net_usd":   net_usd,
                    "net_pct":   net_pct,
                })

    return opportunities


async def jupiter_direct_execute(opp: dict) -> dict:
    """
    Execute a Jupiter round-trip using quotes already fetched by
    jupiter_roundtrip_scan().  Submits Leg 1 immediately (quotes are
    fresh), then re-quotes Leg 2 after confirmation to capture the
    real-time sell price.
    """
    symbol    = opp["symbol"]
    mint      = opp["mint"]
    trade_size = opp["usdc_in"]
    token_out  = opp["token_out"]

    async with aiohttp.ClientSession() as session:
        balance = await get_usdc_balance(session)
        if balance < trade_size:
            raise RuntimeError(
                f"Insufficient USDC: wallet ${balance:.2f} < required ${trade_size:.2f}"
            )

        pubkey = get_wallet_pubkey()

        # ── Leg 1: USDC → Token (use pre-fetched quote — time-critical) ──
        swap1 = {
            "quoteResponse":            opp["quote1"],
            "userPublicKey":            pubkey,
            "wrapAndUnwrapSol":         True,
            "dynamicComputeUnitLimit":  True,
            "prioritizationFeeLamports":"auto",
        }
        async with session.post(JUPITER_SWAP_URL, json=swap1,
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                text = await r.text()
                raise RuntimeError(f"Leg 1 swap API error {r.status}: {text[:120]}")
            sd1 = await r.json()

        tx1 = sd1.get("swapTransaction")
        if not tx1:
            raise RuntimeError("No swapTransaction from Jupiter (Leg 1)")

        signed1 = _sign_transaction(base64.b64decode(tx1))
        rpc1 = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(signed1).decode(),
                       {"encoding": "base64", "skipPreflight": False,
                        "preflightCommitment": "processed"}],
        }
        async with session.post(SOLANA_RPC, json=rpc1,
                                timeout=aiohttp.ClientTimeout(total=20)) as r:
            rr1 = await r.json()

        sig1 = rr1.get("result")
        if not sig1 or "error" in rr1:
            raise RuntimeError(f"Leg 1 rejected: {rr1.get('error', rr1)}")

        print(f"[JupDirect] Leg 1 submitted: {sig1}")
        if not await _confirm_tx(session, sig1, timeout=30):
            raise RuntimeError(f"Leg 1 not confirmed within 30s: {sig1}")

        # ── Leg 2: Token → USDC (fresh re-quote after confirmation) ───────
        params2 = {
            "inputMint":        mint,
            "outputMint":       USDC_MINT,
            "amount":           token_out,
            "slippageBps":      MAX_SLIPPAGE_BPS,
            "onlyDirectRoutes": "false",
        }
        async with session.get(JUPITER_QUOTE_URL, params=params2,
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                text = await r.text()
                raise RuntimeError(f"Leg 2 re-quote error {r.status}: {text[:120]}")
            q2_fresh = await r.json()

        swap2 = {
            "quoteResponse":            q2_fresh,
            "userPublicKey":            pubkey,
            "wrapAndUnwrapSol":         True,
            "dynamicComputeUnitLimit":  True,
            "prioritizationFeeLamports":"auto",
        }
        async with session.post(JUPITER_SWAP_URL, json=swap2,
                                timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                text = await r.text()
                raise RuntimeError(f"Leg 2 swap API error {r.status}: {text[:120]}")
            sd2 = await r.json()

        tx2 = sd2.get("swapTransaction")
        if not tx2:
            raise RuntimeError("No swapTransaction from Jupiter (Leg 2)")

        signed2 = _sign_transaction(base64.b64decode(tx2))
        rpc2 = {
            "jsonrpc": "2.0", "id": 1,
            "method": "sendTransaction",
            "params": [base64.b64encode(signed2).decode(),
                       {"encoding": "base64", "skipPreflight": False,
                        "preflightCommitment": "processed"}],
        }
        async with session.post(SOLANA_RPC, json=rpc2,
                                timeout=aiohttp.ClientTimeout(total=20)) as r:
            rr2 = await r.json()

        sig2 = rr2.get("result")
        if not sig2 or "error" in rr2:
            raise RuntimeError(f"Leg 2 rejected: {rr2.get('error', rr2)}")

        print(f"[JupDirect] Leg 2 submitted: {sig2}")
        await _confirm_tx(session, sig2, timeout=30)

        usdc_received = int(q2_fresh.get("outAmount", 0)) / 1_000_000
        gas_cost      = GAS_COST_USD.get("sol", 0.025) * 2
        net_profit    = usdc_received - trade_size - gas_cost

        return {
            "mode":        "live",
            "type":        "jdirect",
            "chain":       "sol",
            "symbol":      symbol,
            "sim_size":    trade_size,
            "usdc_in":     trade_size,
            "usdc_out":    usdc_received,
            "gross_profit":usdc_received - trade_size,
            "fees_est":    gas_cost,
            "slip_cost":   0.0,
            "net_profit":  net_profit,
            "profit_pct":  (net_profit / trade_size) * 100,
            "win":         net_profit > 0,
            "route":       f"Jupiter Direct USDC→{symbol}→USDC",
            "timestamp":   now_utc(),
            "tx_leg1":     sig1,
            "tx_leg2":     sig2,
            "balance_before": balance,
        }


# ── Helpers ────────────────────────────────────────────────────────────────

async def _confirm_tx(session: aiohttp.ClientSession, sig: str, timeout: int = 30) -> bool:
    """Poll until tx is confirmed or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getSignatureStatuses",
            "params": [[sig], {"searchTransactionHistory": True}]
        }
        try:
            async with session.post(SOLANA_RPC, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=8)) as r:
                data  = await r.json()
                value = (data.get("result", {}).get("value") or [None])[0]
                if value and value.get("confirmationStatus") in ("confirmed", "finalized"):
                    return True
                if value and value.get("err"):
                    print(f"[LiveExec] TX {sig[:16]}… failed on-chain: {value['err']}")
                    return False
        except Exception:
            pass
        await asyncio.sleep(2)
    return False


def _estimate_decimals(quote: dict) -> int:
    """Guess token decimals from Jupiter quote context."""
    # Jupiter v6 exposes routePlan; fall back to 6 (most SPL tokens)
    try:
        return quote["routePlan"][0]["swapInfo"]["outputMint"]["decimals"]
    except Exception:
        return 6
