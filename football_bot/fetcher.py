"""
Football data fetcher — ESPN public API (no API key required).
Replaces football-data.org which may be geo-blocked in some regions.

All public functions return data in the same format the analyzer expects:
  match dict: {status, homeTeam: {id}, awayTeam: {id}, score: {fullTime: {home, away}}}
"""
import asyncio
import aiohttp
from datetime import date
from football_bot.config import LEAGUES

# ── ESPN league codes → our internal codes ─────────────────────────────────
ESPN_LEAGUES: dict[str, str] = {
    # ── Existing leagues ────────────────────────────────────────────────────
    "eng.1": "PL",    # Premier League
    "eng.2": "ELC",   # Championship
    "ger.1": "BL1",   # Bundesliga
    "ger.2": "BL2",   # 2. Bundesliga
    "ita.1": "SA",    # Serie A
    "fra.1": "FL1",   # Ligue 1
    "esp.1": "PD",    # La Liga
    "ned.1": "DED",   # Eredivisie
    "por.1": "PPL",   # Primeira Liga
    "bra.1": "BSA",   # Brasileirao
    # ── High-draw additions ──────────────────────────────────────────────────
    "sco.1": "SCO",   # Scottish Premiership
    "bel.1": "BEL",   # Belgian Pro League
    "ita.2": "SB",    # Serie B
    "esp.2": "SD",    # Segunda División
    "fra.2": "FL2",   # Ligue 2
    "eng.3": "EL1",   # League One
    "tur.1": "TSL",   # Süper Lig
    "gre.1": "GSL",   # Super League Greece
}
_OUR_TO_ESPN = {v: k for k, v in ESPN_LEAGUES.items()}

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

# ── In-memory caches (rebuilt each bot session) ────────────────────────────
_session: aiohttp.ClientSession | None = None
_team_league_map: dict[str, str] = {}   # str(team_id) → espn_league_code
_match_meta: dict[int, dict]     = {}   # match_id → {espn_league, home_id, away_id}
_team_form_cache: dict[str, list] = {}  # str(team_id) → list[match_dict]


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; FootballBot/1.0)"}
        _session = aiohttp.ClientSession(
            headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        )
    return _session


async def close_session():
    global _session
    if _session and not _session.closed:
        await _session.close()


async def _get(url: str, params: dict | None = None) -> dict | None:
    session = await _get_session()
    try:
        async with session.get(url, params=params) as r:
            if not r.ok:
                text = await r.text()
                print(f"[ESPNFetcher] {r.status} {url}: {text[:120]}")
                return None
            return await r.json(content_type=None)
    except Exception as e:
        print(f"[ESPNFetcher] Error {url}: {e}")
        return None


# ── Score extraction ────────────────────────────────────────────────────────

def _to_int_score(raw) -> int | None:
    """Handle ESPN score fields which can be str, int, float, or dict."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        try:
            return int(float(raw))
        except (ValueError, TypeError):
            return None
    if isinstance(raw, dict):
        v = raw.get("displayValue") or raw.get("value")
        if v is not None:
            try:
                return int(float(str(v)))
            except (ValueError, TypeError):
                return None
    return None


def _competition_to_match(comp: dict, espn_league: str, event_id: int) -> dict | None:
    """Convert an ESPN competition block to our internal match format."""
    status_obj  = comp.get("status", {}).get("type", {})
    completed   = status_obj.get("completed", False)
    status      = "FINISHED" if completed else "SCHEDULED"

    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    home_team = home.get("team", {})
    away_team = away.get("team", {})
    home_id   = int(home_team.get("id", 0))
    away_id   = int(away_team.get("id", 0))
    if not home_id or not away_id:
        return None

    return {
        "status":   status,
        "homeTeam": {"id": home_id, "name": home_team.get("displayName", "")},
        "awayTeam": {"id": away_id, "name": away_team.get("displayName", "")},
        "score": {
            "fullTime": {
                "home": _to_int_score(home.get("score")),
                "away": _to_int_score(away.get("score")),
            }
        },
        "_event_id":    event_id,
        "_espn_league": espn_league,
    }


# ── Public API (same signatures as old football-data.org fetcher) ───────────

async def validate_api_key() -> tuple[bool, str]:
    """ESPN needs no API key — validate reachability instead."""
    data = await _get(f"{ESPN_BASE}/eng.1/scoreboard")
    if data is not None:
        return True, "ESPN API — no key required ✅"
    return False, "ESPN API unreachable — check internet connection"


async def fetch_todays_fixtures() -> list[dict]:
    """Return today's scheduled fixtures across all covered leagues."""
    global _team_league_map, _match_meta

    today_str = date.today().strftime("%Y%m%d")
    espn_codes = list(ESPN_LEAGUES.keys())

    # Fetch all leagues in parallel
    responses = await asyncio.gather(
        *[_get(f"{ESPN_BASE}/{code}/scoreboard", {"dates": today_str})
          for code in espn_codes],
        return_exceptions=True,
    )

    result = []
    for espn_code, data in zip(espn_codes, responses):
        if not isinstance(data, dict):
            continue
        our_code    = ESPN_LEAGUES[espn_code]
        league_meta = LEAGUES.get(our_code, {})

        for ev in data.get("events", []):
            event_id = int(ev.get("id", 0))
            comps    = ev.get("competitions", [{}])
            if not comps or not event_id:
                continue
            comp       = comps[0]
            status_obj = comp.get("status", {}).get("type", {})

            # Only upcoming fixtures (not already finished)
            if status_obj.get("completed", False):
                continue

            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            home_team = home.get("team", {})
            away_team = away.get("team", {})
            home_id   = int(home_team.get("id", 0))
            away_id   = int(away_team.get("id", 0))
            if not home_id or not away_id:
                continue

            # Populate caches so form/h2h lookups are fast
            _team_league_map[str(home_id)] = espn_code
            _team_league_map[str(away_id)] = espn_code
            _match_meta[event_id] = {
                "espn_league": espn_code,
                "home_id":     home_id,
                "away_id":     away_id,
            }

            result.append({
                "id":               event_id,
                "league_code":      our_code,
                "league_name":      league_meta.get("name", our_code),
                "league_country":   league_meta.get("country", ""),
                "league_draw_rate": league_meta.get("draw_rate", 0.25),
                "home_id":          home_id,
                "home_name":        home_team.get("displayName", ""),
                "home_short":       home_team.get("shortDisplayName",
                                    home_team.get("displayName", "")),
                "away_id":          away_id,
                "away_name":        away_team.get("displayName", ""),
                "away_short":       away_team.get("shortDisplayName",
                                    away_team.get("displayName", "")),
                "kickoff":          ev.get("date", ""),
                "status":           "SCHEDULED",
                "_espn_league":     espn_code,
            })

    # Persist match meta so grading survives restarts
    try:
        from football_bot import state as fstate
        fstate.save_match_meta({str(k): v for k, v in _match_meta.items()})
    except Exception:
        pass

    print(f"[ESPNFetcher] Today's fixtures in covered leagues: {len(result)}")
    return result


async def fetch_team_form(team_id: int, limit: int = 20) -> list[dict]:
    """Return last N finished matches for a team."""
    tid = str(team_id)

    if tid in _team_form_cache:
        return _team_form_cache[tid]

    # Determine ESPN league for this team
    espn_league = _team_league_map.get(tid)
    if not espn_league:
        # Search across leagues until found (rare — only if cache miss)
        for code in ESPN_LEAGUES:
            data = await _get(f"{ESPN_BASE}/{code}/teams/{team_id}/schedule")
            if data and data.get("events"):
                espn_league = code
                _team_league_map[tid] = code
                break
        if not espn_league:
            return []

    data = await _get(f"{ESPN_BASE}/{espn_league}/teams/{team_id}/schedule")
    if not data:
        return []

    matches = []
    for ev in data.get("events", []):
        event_id = int(ev.get("id", 0))
        comps    = ev.get("competitions", [{}])
        if not comps:
            continue
        m = _competition_to_match(comps[0], espn_league, event_id)
        if m and m["status"] == "FINISHED":
            matches.append(m)

    # Most recent first, cap at limit
    matches.sort(key=lambda x: x["_event_id"], reverse=True)
    result = matches[:limit]

    _team_form_cache[tid] = result
    return result


async def fetch_h2h(match_id: int) -> list[dict]:
    """Return head-to-head finished matches for a fixture."""
    meta    = _match_meta.get(match_id, {})
    home_id = meta.get("home_id")
    away_id = meta.get("away_id")
    if not home_id or not away_id:
        return []

    # Fetch both schedules (cache is shared — no duplicate calls)
    home_matches, away_matches = await asyncio.gather(
        fetch_team_form(home_id, limit=60),
        fetch_team_form(away_id, limit=60),
    )

    seen: set[int] = set()
    h2h: list[dict] = []
    pair = {home_id, away_id}

    for m in home_matches + away_matches:
        mid = m.get("_event_id", 0)
        if mid in seen:
            continue
        ht = m.get("homeTeam", {}).get("id")
        at = m.get("awayTeam", {}).get("id")
        if {ht, at} == pair:
            h2h.append(m)
            seen.add(mid)

    return h2h


async def fetch_match_result(match_id: int) -> dict | None:
    """Return a single match result (for grading)."""
    meta = _match_meta.get(match_id)

    # If not in memory cache, try to reload from persisted state
    if not meta:
        try:
            from football_bot import state as fstate
            persisted = fstate.get_match_meta()
            meta = persisted.get(str(match_id))
            if meta:
                _match_meta[match_id] = meta
        except Exception:
            pass

    # If still unknown, probe each ESPN league until we find it
    if not meta:
        for code in ESPN_LEAGUES:
            data = await _get(
                f"{ESPN_BASE}/{code}/summary", {"event": match_id}
            )
            if data and data.get("header", {}).get("competitions"):
                comp  = data["header"]["competitions"][0]
                teams = comp.get("competitors", [])
                home  = next((t for t in teams if t.get("homeAway") == "home"), {})
                away  = next((t for t in teams if t.get("homeAway") == "away"), {})
                meta  = {
                    "espn_league": code,
                    "home_id":     int(home.get("team", {}).get("id", 0)),
                    "away_id":     int(away.get("team", {}).get("id", 0)),
                }
                _match_meta[match_id] = meta
                break
        if not meta:
            return None

    espn_league = meta["espn_league"]
    data = await _get(f"{ESPN_BASE}/{espn_league}/summary", {"event": match_id})
    if not data:
        return None

    header = data.get("header", {})
    comps  = header.get("competitions", [{}])
    if not comps:
        return None
    comp       = comps[0]
    status_obj = comp.get("status", {}).get("type", {})
    completed  = status_obj.get("completed", False)
    status     = "FINISHED" if completed else "SCHEDULED"

    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        return None

    return {
        "status": status,
        "score": {
            "fullTime": {
                "home": _to_int_score(home.get("score")),
                "away": _to_int_score(away.get("score")),
            }
        },
    }


async def fetch_fixtures_for_date(target_date: str) -> list[dict]:
    """Fetch all fixtures for a specific date (used for result checking)."""
    date_str = target_date.replace("-", "")
    all_fixtures: list[dict] = []

    for espn_code in ESPN_LEAGUES:
        data = await _get(
            f"{ESPN_BASE}/{espn_code}/scoreboard", {"dates": date_str}
        )
        if not data:
            continue
        for ev in data.get("events", []):
            event_id = int(ev.get("id", 0))
            comps    = ev.get("competitions", [{}])
            if not comps or not event_id:
                continue
            m = _competition_to_match(comps[0], espn_code, event_id)
            if m:
                all_fixtures.append(m)
                _match_meta[event_id] = {
                    "espn_league": espn_code,
                    "home_id":     m["homeTeam"]["id"],
                    "away_id":     m["awayTeam"]["id"],
                }

    return all_fixtures
