from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Korea Standard Time (UTC+9)
KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """Return current time as a timezone-aware datetime in KST."""
    return datetime.now(KST)


def now_utc() -> datetime:
    """Return current time as a timezone-aware datetime in UTC."""
    return datetime.now(timezone.utc)


def today_kst_str() -> str:
    """Return today's date string in KST (YYYY-MM-DD)."""
    return now_kst().date().isoformat()


def to_kst(dt: datetime) -> datetime:
    """Convert a datetime to KST, assuming naive values are UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)
