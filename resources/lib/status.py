# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Is a show still being made, and when is it back? One line for the top of its plot, from TMDB.

Works on a show's full TMDB details or on the small summary tmdb.tv_facts keeps (the same keys).
TMDB's dates are the show's own country's, so a UK broadcast can differ by a day or more.
"""

import datetime

from resources.lib import kodi

STILL_GOING = {"Returning Series": "status_no_date", "In Production": "status_in_production",
               "Planned": "status_planned", "Pilot": "status_planned"}
FINISHED = {"Ended": "status_ended", "Canceled": "status_cancelled", "Cancelled": "status_cancelled"}


def _today():
    return datetime.date.today().isoformat()


def is_finished(show):
    return show.get("status") in FINISHED


def is_still_going(show):
    return show.get("status") in STILL_GOING


def next_due(show, today=None):
    """(season, episode, "YYYY-MM-DD") of the next episode with a date from today on, or None. A season
    TMDB lists with a future start date counts as its episode 1."""
    today = today or _today()
    upcoming = show.get("next_episode_to_air") or {}
    date = (upcoming.get("air_date") or "")[:10]
    if date >= today:
        return int(upcoming.get("season_number") or 0), int(upcoming.get("episode_number") or 0), date
    later = sorted(((s.get("air_date") or "")[:10], int(s.get("season_number") or 0))
                   for s in show.get("seasons") or [] if int(s.get("season_number") or 0) > 0
                   and (s.get("air_date") or "")[:10] >= today)
    if later:
        date, season = later[0]
        return season, 1, date
    return None


def nice_date(date):
    """ "2027-03-03" -> "3 March 2027" (month names from SpongeTV's strings, so they can be translated)."""
    try:
        day = datetime.date.fromisoformat(date[:10])
    except (TypeError, ValueError):
        return ""
    months = kodi.text("month_names").split()
    month = months[day.month - 1] if len(months) == 12 else str(day.month)
    return f"{day.day} {month} {day.year}"


def line(show, today=None):
    """"Returning: season 6 starts 3 March 2027", "Ended" and so on; "" when TMDB doesn't say."""
    status = show.get("status") or ""
    if status in FINISHED:
        return kodi.text(FINISHED[status])
    if status not in STILL_GOING:
        return ""
    due = next_due(show, today)
    date = nice_date(due[2]) if due else ""
    if not date:
        return kodi.text(STILL_GOING[status])
    season, episode, _ = due
    if episode <= 1 and season <= 1:
        return kodi.text("status_starts", date=date)
    if episode <= 1:
        return kodi.text("status_returning", season=season, date=date)
    return kodi.text("status_next_episode", date=date)


def with_line(plot, show, today=None):
    """The plot with the status line on top, in bold."""
    text = line(show, today)
    if not text:
        return plot or ""
    return f"[B]{text}[/B]\n{plot}" if plot else f"[B]{text}[/B]"
