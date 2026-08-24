"""
Base Chain Whale Alert Bot — Block Scanner & Signal Engine

Features:
  1. Transfer event monitoring — scans all ERC-20 transfers, filters for
     CEX wallets, Aerodrome/Uniswap routers, and Base Bridge client-side.
  2. Smart Money Rotation — tracks wallets that sell BRETT/TOSHI, then
     alerts when they rotate into another Base-native token within 4 hours.
  3. Concentration cluster alerts — 3+ unique wallets, same token, same
     direction within 60 minutes.
  4. 24h aggregation & alert cooldown per wallet+token.
"""

import asyncio
import json
import logging
import os
import time
import aiohttp

from base_bot.config import (
    BASE_RPC_URLS, TRANSFER_TOPIC, BASESCAN_TX_URL,
    COINGECKO_PRICE_URL, COINGECKO_COIN_URL,
    COINGECKO_IDS, POLL_SECONDS, BLOCKS_PER_SCAN, MAX_BLOCKS_PER_SCAN,
    BASE_BLOCK_SECONDS, PRICE_TTL, UNKNOWN_PRICE_TTL, ALERT_COOLDOWN, AGG_WINDOW,
    DUST_FILTER, UNKNOWN_AMOUNT_MIN, is_stablecoin, get_threshold,
    CLUSTER_WINDOW, CLUSTER_MIN_WALLETS, CLUSTER_COOLDOWN, CLUSTER_TRACK_MIN,
    CLUSTER_MIN_SPREAD, get_cluster_thresholds,
    ROTATION_TRIGGER_TOKENS, ROTATION_WINDOW, ROTATION_MIN_USD,
    BTC_GROUP, ETH_GROUP,
    TOKENIZED_STOCKS,
)
import base_bot.cex_labels as _cex_mod
from base_bot.cex_labels import CEX_SET, classify, is_cex
from base_bot.signals import build_signal_card

logger = logging.getLogger("base_bot.monitor")

# ── Symbol blacklist ──────────────────────────────────────────────────────────
# BTC/ETH groups permanently blocked. Users extend via /blocktoken.
_PERMANENTLY_BLOCKED: frozenset[str] = frozenset(BTC_GROUP | ETH_GROUP)
SYMBOL_BLACKLIST: set[str] = set(_PERMANENTLY_BLOCKED)

_BLOCKLIST_FILE = "base_bot/blocked_tokens.json"
_WALLETS_FILE   = "base_bot/tracked_wallets.json"


def _load_blocklist() -> None:
    try:
        if os.path.exists(_BLOCKLIST_FILE):
            data = json.loads(open(_BLOCKLIST_FILE).read())
            SYMBOL_BLACKLIST.update(s.upper() for s in data if isinstance(s, str))
            logger.info(f"[Blocklist] Loaded {len(data)} custom blocked tokens")
    except Exception as exc:
        logger.warning(f"[Blocklist] Load failed: {exc}")


def _load_tracked_wallets() -> dict:
    try:
        if os.path.exists(_WALLETS_FILE):
            data = json.loads(open(_WALLETS_FILE).read())
            return {e["address"].lower(): e for e in data if "address" in e}
    except Exception as exc:
        logger.warning(f"[Wallets] Load failed: {exc}")
    return {}


TRACKED_WALLETS: dict[str, dict] = _load_tracked_wallets()
EXTRA_WALLETS:   set[str]        = set()
_EXTRA_CEX:      dict[str, str]  = {}

for _tw in TRACKED_WALLETS.values():
    _addr = _tw["address"].lower()
    EXTRA_WALLETS.add(_addr)
    if _tw.get("type") == "cex":
        _EXTRA_CEX[_addr] = _tw["name"]


def _is_any_cex(addr: str) -> bool:
    return is_cex(addr) or addr in _EXTRA_CEX


def _any_cex_label(addr: str) -> str:
    entry = _cex_mod._CEX_DB.get(addr)
    if entry:
        return entry[0]
    return _EXTRA_CEX.get(addr, "Exchange")


_load_blocklist()

# ── Module-level state ────────────────────────────────────────────────────────

# (wallet, token) → aggregation entry
AGGREGATOR: dict[tuple[str, str], dict] = {}

# dedup: tx_hash:log_index → bool
SEEN_TXS: set[str] = set()
MAX_SEEN = 50_000

# (wallet, token) → last alert timestamp
LAST_ALERT: dict[tuple[str, str], float] = {}

# symbol → (usd_price, fetched_at)
PRICE_CACHE: dict[str, tuple[float, float]] = {}

# symbol → market_cap_usd  (refreshed every PRICE_TTL with the price batch)
MARKET_CAP_CACHE: dict[str, float] = {}

# contract_address → {symbol, decimals}  (permanent — never changes)
TOKEN_INFO_CACHE: dict[str, dict] = {}

# Move log for /top command
MOVE_LOG: list[dict] = []
MAX_MOVE_LOG = 500

# Hot tokens rolling log — populated by every qualified alert
# Each entry: {symbol, side, usd, ts}  side ∈ "buy" | "sell" | "neutral"
HOT_TOKENS_LOG: list[dict] = []
MAX_HOT_LOG = 20_000
HOT_LOG_FILE = "base_bot/hot_log.jsonl"    # persisted across restarts


def _load_hot_log():
    """Load persisted hot-token entries from disk on startup (keeps last 7 days)."""
    if not os.path.exists(HOT_LOG_FILE):
        return
    cutoff = time.time() - 7 * 86400
    loaded = 0
    try:
        with open(HOT_LOG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    if e.get("ts", 0) >= cutoff:
                        HOT_TOKENS_LOG.append(e)
                        loaded += 1
                except Exception:
                    pass
        if loaded:
            _rewrite_hot_log()
        logger.info(f"[HotLog] Loaded {loaded} entries from disk")
    except Exception as exc:
        logger.warning(f"[HotLog] Could not load {HOT_LOG_FILE}: {exc}")


def _rewrite_hot_log():
    """Overwrite the log file with current in-memory entries (used after pruning)."""
    try:
        with open(HOT_LOG_FILE, "w") as f:
            for e in HOT_TOKENS_LOG:
                f.write(json.dumps(e) + "\n")
    except Exception as exc:
        logger.warning(f"[HotLog] Rewrite failed: {exc}")


# ─ side lookup by signal type ────────────────────────────────────────────────
_HOT_SIDE: dict[str, str] = {
    "ACC":        "buy",
    "BRIDGE_IN":  "buy",
    "DIS":        "sell",
    "BRIDGE_OUT": "sell",
}

# Load any persisted entries now (runs once at import time)
_load_hot_log()

# Concentration cluster tracking: (token, direction) → [{wallet, amount, usd_value, ts}]
CLUSTER_DATA:       dict[tuple[str, str], list[dict]] = {}
CLUSTER_LAST_ALERT: dict[tuple[str, str], float]      = {}

# Smart money rotation: wallet → [{token, contract, usd, ts}]
ROTATION_SELLS: dict[str, list[dict]] = {}
# Rotation alert cooldown: (wallet, new_token) → last alert ts
ROTATION_LAST_ALERT: dict[tuple[str, str], float] = {}


# ── ABI helpers ───────────────────────────────────────────────────────────────

def _log_hot_token(symbol: str, side: str, usd: float):
    """Append one data point to the rolling hot-tokens log and persist to disk."""
    entry = {"symbol": symbol, "side": side, "usd": usd, "ts": time.time()}
    HOT_TOKENS_LOG.append(entry)
    if len(HOT_TOKENS_LOG) > MAX_HOT_LOG:
        del HOT_TOKENS_LOG[:MAX_HOT_LOG // 2]
    try:
        with open(HOT_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def get_hot_tokens(window_secs: int = 1800, top_n: int = 10) -> list[dict]:
    """
    Aggregate HOT_TOKENS_LOG over the last `window_secs` seconds.
    Returns a list (sorted by total_usd desc) of dicts:
      {symbol, buy_usd, sell_usd, total_usd, moves, net}
    where net is "buy" if buy_usd > sell_usd, else "sell", else "neutral".
    """
    cutoff = time.time() - window_secs
    agg: dict[str, dict] = {}
    for entry in HOT_TOKENS_LOG:
        if entry["ts"] < cutoff:
            continue
        sym = entry["symbol"]
        if sym not in agg:
            agg[sym] = {"buy_usd": 0.0, "sell_usd": 0.0, "moves": 0}
        agg[sym]["moves"] += 1
        if entry["side"] == "buy":
            agg[sym]["buy_usd"] += entry["usd"]
        elif entry["side"] == "sell":
            agg[sym]["sell_usd"] += entry["usd"]

    results = []
    for sym, d in agg.items():
        total = d["buy_usd"] + d["sell_usd"]
        if total == 0 and d["moves"] == 0:
            continue
        if d["buy_usd"] > d["sell_usd"]:
            net = "buy"
        elif d["sell_usd"] > d["buy_usd"]:
            net = "sell"
        else:
            net = "neutral"
        results.append({
            "symbol":   sym,
            "buy_usd":  d["buy_usd"],
            "sell_usd": d["sell_usd"],
            "total_usd": total,
            "moves":    d["moves"],
            "net":      net,
        })

    results.sort(key=lambda x: x["total_usd"], reverse=True)
    return results[:top_n]


def _decode_abi_string(hex_data: str) -> str:
    if not hex_data or hex_data in ("0x", ""):
        return ""
    data = hex_data[2:]
    if not data:
        return ""
    try:
        if len(data) >= 128:
            offset = int(data[:64], 16)
            if offset == 32:
                length = int(data[64:128], 16)
                if 0 < length <= 64 and len(data) >= 128 + length * 2:
                    raw = bytes.fromhex(data[128: 128 + length * 2])
                    decoded = raw.decode("utf-8", errors="ignore").strip("\x00").strip()
                    if decoded:
                        return decoded
        padded  = data.ljust(64, "0")[:64]
        raw     = bytes.fromhex(padded).rstrip(b"\x00")
        decoded = raw.decode("utf-8", errors="ignore").strip()
        if decoded and all(c.isprintable() for c in decoded):
            return decoded
    except Exception:
        pass
    return ""


class BaseMonitor:
    def __init__(self, bot):
        self.bot                = bot
        self._session: aiohttp.ClientSession | None = None
        self._last_price_fetch  = 0.0
        self._coin_list: list[dict] | None = None
        self._coin_list_fetched = 0.0
        self._paused            = False
        self._scan_count        = 0
        self._alert_count       = 0
        self._last_block        = 0
        self._rpc_idx           = 0

    def pause(self):  self._paused = True
    def resume(self): self._paused = False

    # ── Blocklist management ───────────────────────────────────────────────────
    def add_block(self, symbol: str) -> None:
        SYMBOL_BLACKLIST.add(symbol.upper())
        self._save_blocklist()

    def remove_block(self, symbol: str) -> bool:
        s = symbol.upper()
        if s in _PERMANENTLY_BLOCKED:
            return False
        SYMBOL_BLACKLIST.discard(s)
        self._save_blocklist()
        return True

    def get_custom_blocklist(self) -> list[str]:
        return sorted(SYMBOL_BLACKLIST - _PERMANENTLY_BLOCKED)

    def _save_blocklist(self) -> None:
        try:
            with open(_BLOCKLIST_FILE, "w") as f:
                json.dump(self.get_custom_blocklist(), f, indent=2)
        except Exception as exc:
            logger.warning(f"[Blocklist] Save failed: {exc}")

    # ── Wallet management ──────────────────────────────────────────────────────
    def add_wallet(self, name: str, address: str, wallet_type: str = "whale") -> None:
        addr = address.lower()
        entry = {"name": name, "address": addr, "type": wallet_type}
        TRACKED_WALLETS[addr] = entry
        EXTRA_WALLETS.add(addr)
        if wallet_type == "cex":
            _EXTRA_CEX[addr] = name
        self._save_wallets()

    def remove_wallet(self, address: str) -> bool:
        addr = address.lower()
        if addr not in TRACKED_WALLETS:
            return False
        TRACKED_WALLETS.pop(addr, None)
        EXTRA_WALLETS.discard(addr)
        _EXTRA_CEX.pop(addr, None)
        self._save_wallets()
        return True

    def get_wallets(self) -> list[dict]:
        return list(TRACKED_WALLETS.values())

    def _save_wallets(self) -> None:
        try:
            with open(_WALLETS_FILE, "w") as f:
                json.dump(list(TRACKED_WALLETS.values()), f, indent=2)
        except Exception as exc:
            logger.warning(f"[Wallets] Save failed: {exc}")

    @property
    def stats(self) -> dict:
        return {
            "scans":            self._scan_count,
            "alerts":           self._alert_count,
            "wallets":          len(AGGREGATOR),
            "seen_txs":         len(SEEN_TXS),
            "last_block":       self._last_block,
            "paused":           self._paused,
            "rotation_watches": sum(1 for v in ROTATION_SELLS.values() if v),
        }

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        logger.info("Base Monitor starting…")
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=False),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as session:
            self._session = session
            while True:
                try:
                    if not self._paused:
                        await self._refresh_prices()
                        await self._scan_blocks()
                        self._expire_aggregator()
                        self._scan_count += 1
                except Exception as exc:
                    logger.error(f"Monitor loop error: {exc}", exc_info=True)
                await asyncio.sleep(POLL_SECONDS)

    # ── RPC layer ─────────────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: list):
        for attempt in range(len(BASE_RPC_URLS)):
            url = BASE_RPC_URLS[self._rpc_idx % len(BASE_RPC_URLS)]
            self._rpc_idx += 1
            try:
                async with self._session.post(
                    url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        if "result" in data:
                            return data["result"]
                        if "error" in data:
                            logger.debug(f"RPC {method} error from {url}: {data['error']}")
                    else:
                        logger.debug(f"RPC {method} HTTP {r.status} from {url}")
            except asyncio.TimeoutError:
                logger.debug(f"RPC {method} timeout from {url}")
            except Exception as exc:
                logger.debug(f"RPC {method} exception: {exc}")
        logger.warning(f"[RPC] All nodes failed for {method}")
        return None

    # ── Token info ────────────────────────────────────────────────────────────

    async def _get_token_info(self, contract: str) -> dict:
        cached = TOKEN_INFO_CACHE.get(contract)
        if cached:
            return cached

        sym_call = {
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": contract, "data": "0x95d89b41"}, "latest"],
        }
        dec_call = {
            "jsonrpc": "2.0", "id": 2, "method": "eth_call",
            "params": [{"to": contract, "data": "0x313ce567"}, "latest"],
        }

        symbol   = "UNKNOWN"
        decimals = 18

        try:
            async with self._session.post(
                BASE_RPC_URLS[0],
                json=[sym_call, dec_call],
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    results = await r.json(content_type=None)
                    for res in results:
                        if res.get("id") == 1:
                            s = _decode_abi_string(res.get("result", ""))
                            if s:
                                symbol = s.upper()
                        elif res.get("id") == 2:
                            raw = res.get("result", "0x")
                            if raw and raw != "0x":
                                decimals = int(raw, 16) & 0xFF
        except Exception as exc:
            logger.debug(f"Token info fetch error for {contract}: {exc}")

        info = {"symbol": symbol, "decimals": decimals}
        TOKEN_INFO_CACHE[contract] = info
        return info

    # ── Price fetching ────────────────────────────────────────────────────────

    async def _refresh_prices(self):
        now = time.time()
        if now - self._last_price_fetch < PRICE_TTL:
            return
        self._last_price_fetch = now

        ids = ",".join(set(COINGECKO_IDS.values()))
        try:
            async with self._session.get(
                COINGECKO_PRICE_URL,
                params={"ids": ids, "vs_currencies": "usd", "include_market_cap": "true"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    updated = 0
                    for sym, cg_id in COINGECKO_IDS.items():
                        entry = data.get(cg_id, {})
                        price = entry.get("usd", 0)
                        if price:
                            PRICE_CACHE[sym.upper()] = (float(price), now)
                            updated += 1
                        mc = entry.get("usd_market_cap", 0)
                        if mc:
                            MARKET_CAP_CACHE[sym.upper()] = float(mc)
                    logger.info(f"[Price] Refreshed {updated} tokens")
        except Exception as exc:
            logger.warning(f"[Price] Refresh failed: {exc}")

    async def _lookup_unknown_price(self, symbol: str) -> float:
        cached = PRICE_CACHE.get(symbol.upper())
        if cached:
            price, ts = cached
            if time.time() - ts < UNKNOWN_PRICE_TTL:
                return price

        now = time.time()
        if self._coin_list is None or now - self._coin_list_fetched > 3600:
            try:
                async with self._session.get(
                    COINGECKO_COIN_URL,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as r:
                    if r.status == 200:
                        self._coin_list = await r.json()
                        self._coin_list_fetched = now
            except Exception:
                return 0.0

        if not self._coin_list:
            return 0.0

        sym_lower = symbol.lower()
        matches   = [c["id"] for c in self._coin_list if c.get("symbol", "").lower() == sym_lower]
        if not matches:
            PRICE_CACHE[symbol.upper()] = (0.0, now)
            return 0.0

        try:
            async with self._session.get(
                COINGECKO_PRICE_URL,
                params={"ids": ",".join(matches[:3]), "vs_currencies": "usd"},
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    for cg_id in matches[:3]:
                        price = data.get(cg_id, {}).get("usd", 0)
                        if price:
                            PRICE_CACHE[symbol.upper()] = (float(price), now)
                            return float(price)
        except Exception:
            pass

        PRICE_CACHE[symbol.upper()] = (0.0, now)
        return 0.0

    def _price(self, symbol: str) -> float:
        cached = PRICE_CACHE.get(symbol.upper())
        return cached[0] if cached else 0.0

    def _market_cap(self, symbol: str) -> float:
        return MARKET_CAP_CACHE.get(symbol.upper(), 0.0)

    # ── Block scanning ────────────────────────────────────────────────────────

    async def _scan_blocks(self):
        """
        Single eth_getLogs call for all Transfer events — client-side CEX filter.
        Works on any standard free Base RPC node without topic-array limits.
        """
        cur_hex = await self._rpc("eth_blockNumber", [])
        if not cur_hex:
            logger.warning("[Scan] Could not fetch block number — skipping")
            return

        cur_block = int(cur_hex, 16)

        if self._last_block == 0:
            self._last_block = cur_block - BLOCKS_PER_SCAN

        from_block = self._last_block + 1
        to_block   = min(cur_block, self._last_block + MAX_BLOCKS_PER_SCAN)

        if from_block > to_block:
            return

        raw_logs = await self._rpc("eth_getLogs", [{
            "fromBlock": hex(from_block),
            "toBlock":   hex(to_block),
            "topics":    [TRANSFER_TOPIC],
        }])

        if raw_logs is None:
            logger.warning("[Scan] eth_getLogs returned None — all nodes failed")
            return

        # Client-side filter: keep only logs where from OR to is a known address
        cex_logs = []
        for log in raw_logs:
            topics = log.get("topics", [])
            if len(topics) < 3:
                continue
            from_a = ("0x" + topics[1][-40:]).lower()
            to_a   = ("0x" + topics[2][-40:]).lower()
            if from_a in CEX_SET or to_a in CEX_SET or from_a in EXTRA_WALLETS or to_a in EXTRA_WALLETS:
                cex_logs.append(log)

        logger.info(
            f"[Scan] Blocks {from_block}–{to_block} "
            f"({to_block - from_block + 1} blocks), "
            f"{len(raw_logs)} transfers → {len(cex_logs)} CEX/DEX/Bridge-related"
        )

        self._last_block = to_block

        for log in cex_logs:
            try:
                await self._process_log(log, cur_block)
            except Exception as exc:
                logger.debug(f"[Log] Process error: {exc}")

    # ── Log processor ─────────────────────────────────────────────────────────

    async def _process_log(self, log: dict, cur_block: int):
        """Parse one Transfer event and fire an alert if it qualifies."""
        topics = log.get("topics", [])
        if len(topics) < 3:
            return

        contract  = (log.get("address") or "").lower()
        from_addr = ("0x" + topics[1][-40:]).lower()
        to_addr   = ("0x" + topics[2][-40:]).lower()
        raw_data  = log.get("data", "0x") or "0x"
        tx_hash   = log.get("transactionHash", "")
        log_index = log.get("logIndex", "0x0")
        log_block = int(log.get("blockNumber", hex(cur_block)), 16)

        if not tx_hash or not contract or not from_addr or not to_addr:
            return

        # ── Dedup ─────────────────────────────────────────────────────────────
        dedup_key = f"{tx_hash}:{log_index}"
        if dedup_key in SEEN_TXS:
            return
        SEEN_TXS.add(dedup_key)
        if len(SEEN_TXS) > MAX_SEEN:
            pruned = list(SEEN_TXS)
            SEEN_TXS.clear()
            SEEN_TXS.update(pruned[MAX_SEEN // 2:])

        # ── Parse value ───────────────────────────────────────────────────────
        try:
            raw_value = int(raw_data, 16) if raw_data not in ("0x", "") else 0
        except (ValueError, TypeError):
            return
        if raw_value == 0:
            return

        # ── Token info ────────────────────────────────────────────────────────
        token_info = await self._get_token_info(contract)
        symbol     = token_info["symbol"]
        decimals   = token_info["decimals"]
        amount     = raw_value / (10 ** decimals)

        if amount <= 0:
            return

        # ── Skip stablecoins ──────────────────────────────────────────────────
        if is_stablecoin(symbol):
            return

        # ── Skip blacklisted symbols (BTC/ETH groups + user-added) ────────────
        if symbol.upper() in SYMBOL_BLACKLIST:
            return

        # ── Skip tokenized stocks — crypto only ───────────────────────────────
        if symbol.upper() in TOKENIZED_STOCKS:
            return

        # ── USD valuation ─────────────────────────────────────────────────────
        price = self._price(symbol)
        if price == 0:
            price = await self._lookup_unknown_price(symbol)

        if price == 0:
            return  # can't value this token — skip silently

        usd_value = amount * price

        # ── Dust filter ───────────────────────────────────────────────────────
        if usd_value > 0 and usd_value < DUST_FILTER:
            return

        # ── Smart money rotation tracking ─────────────────────────────────────
        # Runs before the individual threshold check — catches rotations even
        # when the destination token doesn't hit the normal alert bar.
        now = time.time()
        if usd_value >= ROTATION_MIN_USD:
            await self._track_rotation(
                contract, from_addr, to_addr, symbol, usd_value, tx_hash
            )

        # ── Concentration cluster tracking (before individual threshold) ───────
        _from_cex = is_cex(from_addr)
        _to_cex   = is_cex(to_addr)
        if usd_value >= CLUSTER_TRACK_MIN:
            if _from_cex and not _to_cex:
                await self._track_cluster(symbol, "ACC", to_addr,   amount, usd_value, contract, from_addr)
            elif _to_cex and not _from_cex:
                await self._track_cluster(symbol, "DIS", from_addr, amount, usd_value, contract, to_addr)

        # ── Individual threshold check ─────────────────────────────────────────
        threshold = get_threshold(symbol)
        if usd_value > 0 and usd_value < threshold:
            return

        # ── Aggregation ───────────────────────────────────────────────────────
        wallet_key = to_addr if _from_cex else from_addr
        agg = self._aggregate(wallet_key, symbol, amount, usd_value)

        # ── Alert cooldown ────────────────────────────────────────────────────
        cool_key = (wallet_key, symbol)
        if now - LAST_ALERT.get(cool_key, 0) < ALERT_COOLDOWN:
            return
        LAST_ALERT[cool_key] = now

        # ── Classify and fire ─────────────────────────────────────────────────
        signal = classify(from_addr, to_addr)

        age_secs   = (cur_block - log_block) * BASE_BLOCK_SECONDS
        block_time = int(time.time()) - age_secs

        self._alert_count += 1
        _log_move(signal["type"], symbol, usd_value or 0, agg["total_usd"])

        logger.info(
            f"[Alert] {signal['emoji']} {signal['label']} | "
            f"{symbol} ${usd_value:,.0f} | "
            f"{from_addr[:10]}..→{to_addr[:10]}.."
        )

        # ── Hot tokens log ────────────────────────────────────────────────────
        hot_side = _HOT_SIDE.get(signal["type"], "neutral")
        _log_hot_token(symbol, hot_side, usd_value or 0)

        await self.bot.send_alert(
            signal     = signal,
            symbol     = symbol,
            amount     = amount,
            usd_value  = usd_value,
            total_usd  = agg["total_usd"],
            count      = agg["count"],
            price      = price,
            market_cap = self._market_cap(symbol),
            threshold  = threshold,
            link       = BASESCAN_TX_URL + tx_hash,
            from_addr  = from_addr,
            to_addr    = to_addr,
            block_time = block_time,
        )


    # ── Smart money rotation ───────────────────────────────────────────────────

    async def _track_rotation(
        self,
        contract: str,
        from_addr: str,
        to_addr: str,
        symbol: str,
        usd_value: float,
        tx_hash: str,
    ):
        """
        Track when a wallet sells BRETT/TOSHI (rotation trigger) and then
        buys something else within ROTATION_WINDOW — fire a rotation alert.
        """
        now = time.time()

        # Step 1: if this is a SELL of BRETT/TOSHI, mark the from_addr
        if contract in ROTATION_TRIGGER_TOKENS and not is_cex(from_addr):
            if from_addr not in ROTATION_SELLS:
                ROTATION_SELLS[from_addr] = []
            ROTATION_SELLS[from_addr].append({
                "token":    symbol,
                "contract": contract,
                "usd":      usd_value,
                "ts":       now,
            })
            logger.info(
                f"[Rotation] Watching {from_addr[:10]}… — sold {symbol} ${usd_value:,.0f}"
            )

        # Step 2: if to_addr is a wallet we're watching and this is NOT
        # a trigger token, it's a rotation buy
        if to_addr in ROTATION_SELLS and contract not in ROTATION_TRIGGER_TOKENS:
            cutoff = now - ROTATION_WINDOW
            recent = [e for e in ROTATION_SELLS[to_addr] if e["ts"] >= cutoff]
            if recent and not is_stablecoin(symbol):
                # Cooldown per (wallet, new_token) pair
                cool_key = (to_addr, symbol)
                if now - ROTATION_LAST_ALERT.get(cool_key, 0) < ROTATION_WINDOW:
                    return
                ROTATION_LAST_ALERT[cool_key] = now

                sell_entry = recent[-1]  # most recent sell
                logger.info(
                    f"[Rotation] 🔄 {to_addr[:10]}… rotated "
                    f"{sell_entry['token']} → {symbol} ${usd_value:,.0f}"
                )

                # Prune consumed entry
                ROTATION_SELLS[to_addr] = [
                    e for e in ROTATION_SELLS[to_addr]
                    if e["ts"] < cutoff or e is not sell_entry
                ]

                await self.bot.send_rotation_alert(
                    wallet       = to_addr,
                    sold_token   = sell_entry["token"],
                    sold_usd     = sell_entry["usd"],
                    bought_token = symbol,
                    bought_usd   = usd_value,
                    link         = BASESCAN_TX_URL + tx_hash,
                )

    # ── Concentration cluster tracker ─────────────────────────────────────────

    async def _track_cluster(
        self,
        symbol:    str,
        direction: str,  # "ACC" = CEX→wallet (bullish), "DIS" = wallet→CEX (bearish)
        wallet:    str,
        amount:    float,
        usd_value: float,
        contract:  str = "",
        cex_addr:  str = "",
    ):
        now = time.time()
        key = (symbol, direction)

        if key not in CLUSTER_DATA:
            CLUSTER_DATA[key] = []

        cex_name = _any_cex_label(cex_addr) if cex_addr else "Exchange"

        CLUSTER_DATA[key].append({
            "wallet":    wallet,
            "amount":    amount,
            "usd_value": usd_value,
            "contract":  contract,
            "cex_name":  cex_name,
            "ts":        now,
        })

        cutoff = now - CLUSTER_WINDOW
        CLUSTER_DATA[key] = [e for e in CLUSTER_DATA[key] if e["ts"] >= cutoff]

        unique_wallets = len({e["wallet"] for e in CLUSTER_DATA[key]})

        if unique_wallets < CLUSTER_MIN_WALLETS:
            return

        if now - CLUSTER_LAST_ALERT.get(key, 0) < CLUSTER_COOLDOWN:
            return

        CLUSTER_LAST_ALERT[key] = now

        entries      = CLUSTER_DATA[key]
        total_amount = sum(e["amount"]    for e in entries)
        total_usd    = sum(e["usd_value"] for e in entries)
        cex_names    = list({e["cex_name"] for e in entries if e.get("cex_name")})
        use_contract = next((e["contract"] for e in entries if e.get("contract")), "")
        oldest_ts    = min(e["ts"] for e in entries)
        window_mins  = max(1, int((now - oldest_ts) / 60))

        CLUSTER_DATA[key] = []

        # ── Statistical significance gate ─────────────────────────────────────
        # Reject clusters that don't meet USD thresholds or minimum time-spread.
        # Lower-cap (alts, AERO, Base-native): min $100K total.
        # Large-cap (cbBTC, Gold): min $300K total.
        # Activity must span at least 30 minutes — not a flash event.
        if window_mins * 60 < CLUSTER_MIN_SPREAD:
            logger.info(
                f"[Cluster] Skipped {symbol} — spread {window_mins}m < 30m minimum"
            )
            return

        min_usd, high_usd = get_cluster_thresholds(symbol)
        if total_usd < min_usd:
            logger.info(
                f"[Cluster] Skipped {symbol} — ${total_usd:,.0f} below ${min_usd:,.0f} minimum"
            )
            return

        logger.info(
            f"[Cluster] {'🟢' if direction == 'ACC' else '🔴'} "
            f"{direction} concentration | {symbol} | "
            f"{unique_wallets} wallets | ${total_usd:,.0f}"
        )

        await self.bot.send_cluster_alert(
            symbol         = symbol,
            direction      = direction,
            unique_wallets = unique_wallets,
            total_amount   = total_amount,
            total_usd      = total_usd,
        )

        # ── Signal card — ONLY fires on statistically significant clusters ─────
        price = self._price(symbol)
        if price > 0 and use_contract:
            try:
                card = await build_signal_card(
                    session        = self._session,
                    symbol         = symbol,
                    direction      = direction,
                    price          = price,
                    contract       = use_contract,
                    unique_wallets = unique_wallets,
                    total_usd      = total_usd,
                    total_amount   = total_amount,
                    cex_names      = cex_names,
                    window_mins    = window_mins,
                )
                if card:
                    await self.bot.send_signal_card(card)
            except Exception as exc:
                logger.debug(f"[Signal] Card failed for {symbol}: {exc}")

    # ── Aggregator ────────────────────────────────────────────────────────────

    def _aggregate(
        self,
        wallet: str, token: str,
        amount: float, usd_value: float,
    ) -> dict:
        now = time.time()
        key = (wallet, token)

        if key not in AGGREGATOR:
            AGGREGATOR[key] = {
                "total_amount": 0.0,
                "total_usd":    0.0,
                "count":        0,
                "first_seen":   now,
                "last_seen":    now,
            }

        entry = AGGREGATOR[key]
        entry["total_amount"] += amount
        entry["total_usd"]    += usd_value
        entry["count"]        += 1
        entry["last_seen"]     = now
        return entry

    def _expire_aggregator(self):
        cutoff  = time.time() - AGG_WINDOW
        expired = [k for k, v in AGGREGATOR.items() if v["last_seen"] < cutoff]
        for k in expired:
            del AGGREGATOR[k]
        if expired:
            logger.debug(f"Aggregator: expired {len(expired)} entries")


# ── Move log for /top command ──────────────────────────────────────────────────

def _log_move(signal_type: str, symbol: str, usd: float, total_usd: float):
    MOVE_LOG.append({
        "type":      signal_type,
        "symbol":    symbol,
        "usd":       usd,
        "total_usd": total_usd,
        "ts":        time.time(),
    })
    if len(MOVE_LOG) > MAX_MOVE_LOG:
        MOVE_LOG.pop(0)


def get_coin_summary(symbol: str, window_secs: int | None = None) -> dict | None:
    """
    Aggregate HOT_TOKENS_LOG entries for the given symbol (case-insensitive).
    window_secs — look back this many seconds; None = all available history.
    Returns None if no matching entries are found.
    Returns dict:
      {symbol, buy_usd, sell_usd, net_usd, total_usd,
       buy_moves, sell_moves, total_moves, first_seen, last_seen}
    """
    sym    = symbol.upper()
    cutoff = time.time() - window_secs if window_secs is not None else 0.0
    entries = [e for e in HOT_TOKENS_LOG
               if e["symbol"].upper() == sym and e["ts"] >= cutoff]
    if not entries:
        return None
    buy_entries  = [e for e in entries if e["side"] == "buy"]
    sell_entries = [e for e in entries if e["side"] == "sell"]
    buy_usd      = sum(e["usd"] for e in buy_entries)
    sell_usd     = sum(e["usd"] for e in sell_entries)
    return {
        "symbol":      sym,
        "buy_usd":     buy_usd,
        "sell_usd":    sell_usd,
        "net_usd":     buy_usd - sell_usd,
        "total_usd":   buy_usd + sell_usd,
        "buy_moves":   len(buy_entries),
        "sell_moves":  len(sell_entries),
        "total_moves": len(entries),
        "first_seen":  min(e["ts"] for e in entries),
        "last_seen":   max(e["ts"] for e in entries),
    }
