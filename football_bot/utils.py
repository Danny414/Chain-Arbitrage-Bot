from datetime import datetime, timezone


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def fmt_kickoff(utc_iso: str) -> str:
    """Convert ISO kickoff to HH:MM UTC."""
    try:
        dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except Exception:
        return "?"
