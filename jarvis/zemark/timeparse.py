"""A small, dependency-free Portuguese time parser for reminders.

Turns natural spoken phrases into an absolute epoch timestamp:

    "em 10 minutos"        -> now + 10 min
    "daqui a 2 horas"      -> now + 2 h
    "em 1h30"              -> now + 90 min
    "às 15h"  / "as 15:30" -> today at that time (tomorrow if already past)
    "amanhã às 9h"         -> tomorrow at 09:00
    "hoje às 22h"          -> today at 22:00

Returns ``None`` when nothing time-like is found, so callers can ask the user
to rephrase. Pure and fully unit-tested — no external libraries.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta


def _strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


_REL_UNIT_MIN = {
    "min": 1, "minuto": 1, "minutos": 1, "minutos.": 1,
    "h": 60, "hora": 60, "horas": 60,
    "seg": 1 / 60, "segundo": 1 / 60, "segundos": 1 / 60,
    "dia": 1440, "dias": 1440,
}


def parse_when(text: str, now: datetime | None = None) -> float | None:
    """Parse a Portuguese time expression into an epoch timestamp (seconds)."""
    if now is None:
        now = datetime.now().astimezone()
    norm = _strip_accents(text)

    dt = _parse_relative(norm, now)
    if dt is None:
        dt = _parse_absolute(norm, now)
    return dt.timestamp() if dt is not None else None


def _parse_relative(norm: str, now: datetime) -> datetime | None:
    # "em 1h30" / "1h30" combined hours+minutes
    m = re.search(r"\b(\d{1,2})\s*h\s*(\d{1,2})\b", norm)
    if m and ("em " in norm or "daqui" in norm):
        return now + timedelta(hours=int(m.group(1)), minutes=int(m.group(2)))

    # "em N <unit>" / "daqui a N <unit>"
    m = re.search(r"\b(?:em|daqui a|daqui|apos|depois de)\s+(\d+)\s*([a-z.]+)", norm)
    if m:
        qty = int(m.group(1))
        unit = m.group(2).rstrip(".")
        mult = _REL_UNIT_MIN.get(unit)
        if mult is None:
            # tolerate abbreviations like "10min" already split, or unknown -> minutes
            mult = _REL_UNIT_MIN.get(unit[:3])
        if mult is not None:
            return now + timedelta(minutes=qty * mult)

    # "em 90 min" style already covered; "em meia hora"
    if re.search(r"\b(em|daqui)\b.*\bmeia hora\b", norm):
        return now + timedelta(minutes=30)
    return None


def _parse_absolute(norm: str, now: datetime) -> datetime | None:
    tomorrow = "amanha" in norm
    today = "hoje" in norm

    # "as 15:30" / "as 15h30" / "as 15h" / "15:30" / "9 horas"
    m = re.search(r"\b(?:as|às)?\s*(\d{1,2})(?:[:h](\d{1,2}))?\s*(?:h|hs|horas)?\b", norm)
    if not m:
        return None
    # require an explicit time cue so we don't grab stray numbers
    if not re.search(r"\b(as|às|hora|horas|h|:)\b|\dh|\d:", norm):
        return None

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if hour > 23 or minute > 59:
        return None

    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if tomorrow:
        target += timedelta(days=1)
    elif not today and target <= now:
        # a bare "às 9h" that already passed today means tomorrow
        target += timedelta(days=1)
    return target
