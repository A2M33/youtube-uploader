"""Publish-slot planning in the channel's audience time zone."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .library import now_utc, parse_iso

MIN_LEAD = timedelta(minutes=30)


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def next_slots(count: int, tz_name: str, slot_times: list[str],
               taken: list[str] | None = None, start: datetime | None = None) -> list[str]:
    """Return `count` future UTC ISO slots, one per configured slot time per day,
    skipping slots already used by scheduled videos (compared to the minute)."""
    tz = ZoneInfo(tz_name)
    times = sorted(_parse_hhmm(t) for t in slot_times) or [time(15, 0)]
    used = {d.strftime("%Y-%m-%dT%H:%M") for d in (parse_iso(t) for t in taken or []) if d}
    earliest = (start or now_utc()) + MIN_LEAD
    day = earliest.astimezone(tz).date()
    out = []
    while len(out) < count:
        for t in times:
            local = datetime.combine(day, t, tzinfo=tz)
            utc = local.astimezone(timezone.utc)
            key = utc.strftime("%Y-%m-%dT%H:%M")
            if utc >= earliest and key not in used:
                out.append(utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
                used.add(key)
                if len(out) == count:
                    break
        day += timedelta(days=1)
    return out
