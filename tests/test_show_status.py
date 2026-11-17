# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""1.0.9: whether a show is still airing and when it's back; the lists of your shows by status; removing a search."""

from conftest import Directory, FakeAddon
from resources.lib import status
from test_menus import call
from test_mine import world  # noqa: F401  (fixture)

TODAY = "2026-11-17"


def show(**fields):
    base = {"id": 1, "name": "A Show", "status": "Returning Series", "next_episode_to_air": None,
            "seasons": [{"season_number": 0, "air_date": "2027-01-01"}, {"season_number": 1, "air_date": "2020-01-01"},
                        {"season_number": 2, "air_date": "2023-05-01"}]}
    base.update(fields)
    return base


def test_the_line():
    assert status.line(show(status="Ended")) == "Ended"
    assert status.line(show(status="Canceled")) == "Cancelled"
    assert status.line(show(status="")) == ""
    assert status.line(show(), TODAY) == "Returning series: no date yet"      # specials' dates don't count
    assert status.line(show(status="In Production"), TODAY) == "In production: no date yet"
    assert status.line(show(status="Planned"), TODAY) == "Planned: no date yet"
    nxt = {"season_number": 3, "episode_number": 1, "air_date": "2027-03-03"}
    assert status.line(show(next_episode_to_air=nxt), TODAY) == "Returning: season 3 starts 3 March 2027"
    nxt = {"season_number": 2, "episode_number": 5, "air_date": "2026-11-21"}
    assert status.line(show(next_episode_to_air=nxt), TODAY) == "Still airing: next episode 21 November 2026"
    assert status.line(show(next_episode_to_air=nxt), "2026-11-21") == "Still airing: next episode 21 November 2026"
    # a next episode TMDB hasn't moved on from yet is ignored
    assert status.line(show(next_episode_to_air=nxt), "2026-11-22") == "Returning series: no date yet"
    # a new season TMDB lists with a start date, but no episode yet
    seasons = show()["seasons"] + [{"season_number": 3, "air_date": "2027-02-14"}]
    assert status.line(show(seasons=seasons), TODAY) == "Returning: season 3 starts 14 February 2027"
    new = {"season_number": 1, "episode_number": 1, "air_date": "2027-01-09"}
    assert status.line(show(status="Planned", next_episode_to_air=new), TODAY) == "New: starts 9 January 2027"
    assert status.line(show(next_episode_to_air={"season_number": 3, "episode_number": 1, "air_date": "soon"}),
                       TODAY) == "Returning series: no date yet"


def test_on_top_of_the_plot():
    assert status.with_line("The plot.", show(status="Ended")) == "[B]Ended[/B]\nThe plot."
    assert status.with_line("", show(status="Ended")) == "[B]Ended[/B]"
    assert status.with_line("The plot.", show(status="")) == "The plot."


def _plots():
    return [li.tag.calls["setPlot"][-1][0] for _, li, _ in Directory.items if "setPlot" in li.tag.calls]


def test_the_line_shows_on_show_lists_and_seasons_and_can_be_switched_off(world):
    tmdb, _ = world
    for show_id in (51, 52, 53, 54):
        tmdb.shows[show_id]["status"] = "Ended"
    FakeAddon.settings["display.status_line"] = True
    call("?action=library_titles&media=tv&part=watched")
    assert _plots() and all(p.startswith("[B]Ended[/B]") for p in _plots())
    call("?action=seasons&tmdb_id=51")
    assert _plots() and all(p.startswith("[B]Ended[/B]") for p in _plots())
    FakeAddon.settings["display.status_line"] = False
    call("?action=library_titles&media=tv&part=watched")
    assert not any("Ended" in p for p in _plots())
    call("?action=seasons&tmdb_id=51")
    assert not any("Ended" in p for p in _plots())


def _ids():
    return [li.tag.calls["setUniqueIDs"][0][0]["tmdb"] for _, li, _ in Directory.items if "setUniqueIDs" in li.tag.calls]


def test_still_airing_and_ended_lists_of_your_shows(world):
    tmdb, _ = world
    tmdb.shows[51].update(status="Returning Series", name="Zed",
                          next_episode_to_air={"season_number": 3, "episode_number": 1, "air_date": "2099-03-01"})
    tmdb.shows[52].update(status="Returning Series", name="Alpha", next_episode_to_air=None)
    tmdb.shows[53].update(status="Canceled", last_air_date="2024-01-01")
    tmdb.shows[54].update(status="Returning Series")       # dropped on Trakt: left out like Next up
    call("?action=still_airing")
    assert _ids() == ["51", "52"]                             # a date first, then no date yet
    call("?action=ended_shows")
    assert _ids() == ["53"]
    call("?action=my_tv")
    labels = [li.getLabel() for _, li, _ in Directory.items]
    assert "Still airing" in labels and "Ended or cancelled" in labels


def test_remove_one_search(world):
    from resources.lib import context
    app = context.App()
    for query in ("first", "second", "third"):
        app.store.add_search("all", query)
    call("?action=search_menu")
    item = [li for _, li, _ in Directory.items if li.getLabel() == "second"][0]
    label, command = item.context_menu[0]
    assert label == "Remove from search history" and "remove_search" in command
    call("?action=remove_search&query=second")
    assert context.App().store.searches("all") == ["third", "first"]
