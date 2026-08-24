"""
Persistent state manager — survives restarts via JSON on disk.
On load, any eth: tokens are automatically stripped from watchlist and known_pools.
"""
import json, os, time, copy
from bot.config import STATE_FILE, DEFAULT_WATCHLIST

_defaults = {
    "watchlist":       copy.deepcopy(DEFAULT_WATCHLIST),
    "last_alert_time": {},
    "opportunity_log": [],
    "scan_count":      0,
    "paused":          False,
    "min_spread_pct":  None,
    "trade_size_usdc": None,
    "alert_cooldown":  None,
    "min_liquidity_usd": None,
    "known_pools":     {},
    "min_confidence":  None,
    "automode":        "off",
    "max_sim_size":    None,
    "trade_log":       [],
    "report_time":      "00:00",
    "report_last_sent": "",
    "alerted_today":    {},         # {"YYYY-MM-DD": ["sol:GIGA", "cross:WIF:sol:bsc", ...]}
    "live_confirmed":   False,      # requires /confirmgo after /automode live
    "heartbeat_interval": 3600,    # seconds between heartbeat pings (default 1 hour)
    "live_trade_size_usdc": 9.0,   # persisted live trade size — set via /setlivetrade
}

_state = {}


def load():
    global _state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            _state = {**copy.deepcopy(_defaults), **saved}

            # Merge watchlist: new default tokens are added, user tokens preserved.
            # {**DEFAULT, **saved} means saved keys win (user edits kept),
            # but any new default tokens not in saved get added.
            merged_wl = {**copy.deepcopy(DEFAULT_WATCHLIST), **saved.get("watchlist", {})}
            _state["watchlist"] = merged_wl

            # Strip non-SOL chain entries everywhere (eth:, bsc:, etc.)
            for store in ("watchlist", "known_pools"):
                d = _state.get(store, {})
                for k in [k for k in list(d) if not k.startswith("sol:")]:
                    d.pop(k)

            lat = _state.get("last_alert_time", {})
            for k in [k for k in list(lat) if not k.startswith("sol:")]:
                lat.pop(k)

            # For keys that have a real default, a stored null should not override it.
            # This handles the case where a key was added to _defaults after the file
            # was first written — the file has the key as null but the default is meaningful.
            _numeric_keys_with_defaults = {"live_trade_size_usdc"}
            for k in _numeric_keys_with_defaults:
                if _state.get(k) is None and _defaults.get(k) is not None:
                    _state[k] = _defaults[k]

            added = [k for k in DEFAULT_WATCHLIST if k not in saved.get("watchlist", {})]
            _clean_alerted_today()   # drop stale date buckets from previous days
            print(f"[State] Loaded from {STATE_FILE}")
            if added:
                print(f"[State] Added {len(added)} new default tokens: {', '.join(added)}")
            save()   # persist the merged state immediately
            return
        except Exception as e:
            print(f"[State] Load error: {e} — using defaults")
    _state = copy.deepcopy(_defaults)


def save():
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f, indent=2)
    except Exception as e:
        print(f"[State] Save error: {e}")


def get(key, default=None):
    return _state.get(key, default)


def set(key, value):
    _state[key] = value
    save()


def watchlist():
    return _state.setdefault("watchlist", {})


def add_token(chain, symbol, address):
    key = f"{chain}:{symbol}"
    _state["watchlist"][key] = {"chain": chain, "symbol": symbol, "address": address}
    save()
    return key


def remove_token(chain, symbol):
    key = f"{chain}:{symbol}"
    removed = key in _state["watchlist"]
    if removed:
        _state["watchlist"].pop(key, None)
        save()
    return removed, key


def log_opportunity(gap):
    slim = {k: v for k, v in gap.items() if k != "all_pools"}
    log  = _state.setdefault("opportunity_log", [])
    log.append(slim)
    if len(log) > 200:
        _state["opportunity_log"] = log[-200:]
    save()


def get_opportunities():
    return _state.get("opportunity_log", [])


def cooldown_ok(key, cooldown_secs):
    last = _state.get("last_alert_time", {}).get(key, 0)
    return time.time() - last >= cooldown_secs


def set_alerted(key):
    _state.setdefault("last_alert_time", {})[key] = time.time()
    save()


def cooldown_remaining(key, cooldown_secs):
    last = _state.get("last_alert_time", {}).get(key, 0)
    rem  = cooldown_secs - (time.time() - last)
    return max(0, int(rem))


def inc_scan():
    _state["scan_count"] = _state.get("scan_count", 0) + 1
    return _state["scan_count"]


def is_paused():
    return _state.get("paused", False)


def set_paused(v: bool):
    _state["paused"] = v
    save()


# ── Persistent known pools ─────────────────────────────────────────

def get_known_pools() -> dict:
    return _state.setdefault("known_pools", {})


def update_known_pools(key: str, pool_addrs: list[str]):
    _state.setdefault("known_pools", {})[key] = pool_addrs


def save_known_pools():
    save()


# ── Live config helpers ────────────────────────────────────────────

def cfg_spread():
    return _state.get("min_spread_pct") or __import__("bot.config", fromlist=["MIN_SPREAD_PCT"]).MIN_SPREAD_PCT


def cfg_trade():
    return _state.get("trade_size_usdc") or __import__("bot.config", fromlist=["TRADE_SIZE_USDC"]).TRADE_SIZE_USDC


def cfg_cooldown():
    return _state.get("alert_cooldown") or __import__("bot.config", fromlist=["ALERT_COOLDOWN"]).ALERT_COOLDOWN


def cfg_liquidity():
    return _state.get("min_liquidity_usd") or __import__("bot.config", fromlist=["MIN_LIQUIDITY_USD"]).MIN_LIQUIDITY_USD

def cfg_confidence():
    v = _state.get("min_confidence")
    return v if v is not None else __import__("bot.config", fromlist=["MIN_CONFIDENCE"]).MIN_CONFIDENCE

def cfg_max_sim_size():
    v = _state.get("max_sim_size")
    return v if v is not None else 1.0


def cfg_live_trade_size() -> float:
    """Live trade size in USDC. Configurable via /setlivetrade. Hard max $50."""
    v = _state.get("live_trade_size_usdc")
    if v is not None:
        return float(min(v, 50.0))
    return 1.0

# ── Per-day alert deduplication ───────────────────────────────────────

def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _clean_alerted_today():
    """Remove stale dates (anything before today) from alerted_today."""
    today = _today()
    store = _state.setdefault("alerted_today", {})
    stale = [d for d in list(store) if d != today]
    for d in stale:
        store.pop(d)


def already_alerted_today(key: str) -> bool:
    today = _today()
    return key in _state.get("alerted_today", {}).get(today, [])


def mark_alerted_today(key: str):
    today = _today()
    store = _state.setdefault("alerted_today", {})
    store.setdefault(today, [])
    if key not in store[today]:
        store[today].append(key)
    save()


def cfg_heartbeat_interval() -> int:
    v = _state.get("heartbeat_interval")
    return int(v) if v is not None else 3600


def cfg_report_time() -> str:
    return _state.get("report_time") or "00:00"

def report_last_sent() -> str:
    return _state.get("report_last_sent", "")

def set_report_last_sent(date_str: str):
    _state["report_last_sent"] = date_str
    save()
