# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""When has something aired or been released *here*? Works the offset out from the time zone.

TMDB gives air dates only (no times). US shows mostly air in the evening, US Eastern time,
which is already the next morning in Europe, so a fixed "date <= today" check shows them a
day early or late depending on where you are. Instead:

- US shows: assumed watchable from 20:00 US Eastern on the air date, converted to UTC.
- Everything else: watchable from local midnight on the air date.

"Local" is the time zone Kodi runs in (Kodi applies its own time-zone setting to itself on
platforms where it has one; elsewhere it follows the device), read through Python's clock.
"""

import datetime
import time

US_EVENING_HOUR = 20


def _nth_sunday(year, month, n):
    first = datetime.date(year, month, 1)
    first_sunday = first + datetime.timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + datetime.timedelta(weeks=n - 1)


def us_eastern_offset_hours(utc_moment):
    """-4 during US daylight saving (2nd Sunday in March to 1st Sunday in November), else -5."""
    year = utc_moment.year
    starts = datetime.datetime.combine(_nth_sunday(year, 3, 2), datetime.time(7))   # 02:00 EST
    ends = datetime.datetime.combine(_nth_sunday(year, 11, 1), datetime.time(6))    # 02:00 EDT
    return -4 if starts <= utc_moment < ends else -5


def local_offset_seconds():
    return time.localtime().tm_gmtoff or 0


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _parse(date_text):
    try:
        return datetime.date.fromisoformat((date_text or "")[:10])
    except ValueError:
        return None


def local_today(now=None, offset=None):
    now = now or utc_now()
    offset = local_offset_seconds() if offset is None else offset
    return (now + datetime.timedelta(seconds=offset)).date()


def available_from(date_text, origin_countries=None, offset=None):
    """UTC moment an episode or show becomes watchable here, or None without a date."""
    day = _parse(date_text)
    if day is None:
        return None
    if "US" in (origin_countries or []):
        evening_local = datetime.datetime.combine(day, datetime.time(US_EVENING_HOUR))
        hours = us_eastern_offset_hours(evening_local + datetime.timedelta(hours=5))
        return evening_local - datetime.timedelta(hours=hours)
    offset = local_offset_seconds() if offset is None else offset
    return datetime.datetime.combine(day, datetime.time(0)) - datetime.timedelta(seconds=offset)


def has_aired(date_text, origin_countries=None, now=None, offset=None):
    moment = available_from(date_text, origin_countries, offset)
    return moment is not None and (now or utc_now()) >= moment


def is_released(date_text, now=None, offset=None):
    """Films: released once the local date reaches the (already local) release date."""
    day = _parse(date_text)
    return day is not None and local_today(now, offset) >= day


def local_release_date(details, region):
    """Earliest cinema, digital, disc or TV release in your region; else TMDB's main date."""
    for country in (details.get("release_dates") or {}).get("results", []):
        if country.get("iso_3166_1") == region:
            dates = [r.get("release_date", "")[:10] for r in country.get("release_dates", [])
                     if r.get("type") in (2, 3, 4, 5, 6) and r.get("release_date")]
            if dates:
                return min(dates)
    return details.get("release_date", "") or ""


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def when_label(first_aired, words, now=None, offset=None):
    """"Today 21:00", "Tomorrow 02:00", "Yesterday 20:00" or "Sat 14 Nov 20:00", in your time zone.

    first_aired: Trakt's UTC time ("2026-11-14T01:00:00.000Z"). A plain date ("2026-11-14") has
    no time to convert, so it's shown as a date only. words: {"today", "tomorrow", "yesterday"}."""
    text = (first_aired or "").strip()
    if not text:
        return ""
    offset = local_offset_seconds() if offset is None else offset
    if "T" in text:
        try:
            moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return ""
        local = moment + datetime.timedelta(seconds=offset)
        day, clock = local.date(), local.strftime("%H:%M")
    else:
        day, clock = _parse(text), ""
        if day is None:
            return ""
    today = local_today(now, offset)
    names = {today: words["today"], today + datetime.timedelta(days=1): words["tomorrow"],
             today - datetime.timedelta(days=1): words["yesterday"]}
    label = names.get(day) or f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
    return f"{label} {clock}".strip()
