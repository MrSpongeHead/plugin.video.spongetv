# SPDX-License-Identifier: GPL-3.0-or-later
"""Air dates and release dates, worked out from the time zone."""

import datetime as dt

from resources.lib import airtime

UK_WINTER = 0
UK_SUMMER = 3600


def test_us_daylight_saving_dates():
    # 2026: DST from Sunday 8 March to Sunday 1 November.
    assert airtime.us_eastern_offset_hours(dt.datetime(2026, 3, 8, 6, 59)) == -5
    assert airtime.us_eastern_offset_hours(dt.datetime(2026, 3, 8, 7, 0)) == -4
    assert airtime.us_eastern_offset_hours(dt.datetime(2026, 11, 1, 5, 59)) == -4
    assert airtime.us_eastern_offset_hours(dt.datetime(2026, 11, 1, 6, 0)) == -5


def test_us_episode_is_watchable_the_next_morning_in_the_uk():
    # Airs Thursday 15 January 2026, 20:00 EST = 01:00 UTC Friday.
    thursday_evening_uk = dt.datetime(2026, 1, 15, 22, 0)
    friday_early_uk = dt.datetime(2026, 1, 16, 1, 30)
    assert not airtime.has_aired("2026-01-15", ["US"], now=thursday_evening_uk, offset=UK_WINTER)
    assert airtime.has_aired("2026-01-15", ["US"], now=friday_early_uk, offset=UK_WINTER)


def test_us_episode_in_summer_uses_daylight_saving():
    # 20:00 EDT on 15 July = 00:00 UTC on 16 July.
    assert not airtime.has_aired("2026-07-15", ["US"], now=dt.datetime(2026, 7, 15, 23, 59))
    assert airtime.has_aired("2026-07-15", ["US"], now=dt.datetime(2026, 7, 16, 0, 0))


def test_other_shows_are_watchable_from_local_midnight():
    # UK summer (UTC+1): local midnight on 15 July is 23:00 UTC on 14 July.
    assert not airtime.has_aired("2026-07-15", ["GB"], now=dt.datetime(2026, 7, 14, 22, 59), offset=UK_SUMMER)
    assert airtime.has_aired("2026-07-15", ["GB"], now=dt.datetime(2026, 7, 14, 23, 0), offset=UK_SUMMER)


def test_no_date_means_not_aired():
    assert not airtime.has_aired("", ["GB"])
    assert not airtime.has_aired(None)
    assert not airtime.is_released("")


def test_film_release_uses_local_date():
    assert airtime.is_released("2026-07-15", now=dt.datetime(2026, 7, 14, 23, 30), offset=UK_SUMMER)
    assert not airtime.is_released("2026-07-15", now=dt.datetime(2026, 7, 14, 22, 30), offset=UK_SUMMER)


def test_local_release_date_prefers_your_region():
    details = {"release_date": "2026-05-01", "release_dates": {"results": [
        {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2026-05-01T00:00:00.000Z"}]},
        {"iso_3166_1": "GB", "release_dates": [{"type": 1, "release_date": "2026-04-01T00:00:00.000Z"},
                                              {"type": 4, "release_date": "2026-06-20T00:00:00.000Z"},
                                              {"type": 3, "release_date": "2026-05-08T00:00:00.000Z"}]},
    ]}}
    assert airtime.local_release_date(details, "GB") == "2026-05-08"  # premieres (type 1) don't count
    assert airtime.local_release_date(details, "FR") == "2026-05-01"


WORDS = {"today": "Today", "tomorrow": "Tomorrow", "yesterday": "Yesterday"}


def test_when_label_in_your_time_zone():
    now = dt.datetime(2026, 11, 7, 18, 0)      # Saturday evening, UK winter
    assert airtime.when_label("2026-11-07T21:00:00.000Z", WORDS, now, UK_WINTER) == "Today 21:00"
    assert airtime.when_label("2026-11-08T02:00:00.000Z", WORDS, now, UK_WINTER) == "Tomorrow 02:00"
    assert airtime.when_label("2026-11-06T20:00:00.000Z", WORDS, now, UK_WINTER) == "Yesterday 20:00"
    assert airtime.when_label("2026-11-14T20:00:00.000Z", WORDS, now, UK_WINTER) == "Sat 14 Nov 20:00"
    assert airtime.when_label("2026-11-03T20:00:00.000Z", WORDS, now, UK_WINTER) == "Tue 3 Nov 20:00"


def test_when_label_crosses_midnight_with_the_offset():
    # 23:30 UTC in UK summer (UTC+1) is 00:30 the next day locally.
    now = dt.datetime(2026, 7, 14, 12, 0)
    assert airtime.when_label("2026-07-14T23:30:00.000Z", WORDS, now, UK_SUMMER) == "Tomorrow 00:30"


def test_when_label_date_only_and_missing():
    now = dt.datetime(2026, 11, 7, 18, 0)
    assert airtime.when_label("2026-11-14", WORDS, now, UK_WINTER) == "Sat 14 Nov"
    assert airtime.when_label("", WORDS, now, UK_WINTER) == ""
    assert airtime.when_label("not a date", WORDS, now, UK_WINTER) == ""
