# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""The step-by-step timing lines for the debug log."""

import pytest

from resources.lib import timing


def test_steps_and_tallies_are_summarised():
    timing.reset()
    assert timing.summary() == []
    timing.step("loading")
    timing.tally("read from the cache", 0.002)
    timing.tally("read from the cache", 0.003)
    assert timing.timed("network requests", lambda value: value * 2, 4) == 8
    with pytest.raises(ValueError):
        timing.timed("network requests", int, "x")
    steps, counts = timing.summary()
    assert steps.startswith("Steps: loading ") and steps.endswith(" ms")
    assert "read from the cache x2 (5 ms added up)" in counts
    assert "network requests x1" in counts and "network requests, failed x1" in counts
    timing.reset()
    assert timing.summary() == []


def test_next_up_notes_its_steps(monkeypatch):
    from test_smartplay import show  # noqa: F401
    from resources.lib import mine
    timing.reset()

    class Library:
        def skipped_shows(self):
            return set()

        def watched_shows(self):
            return []

    class App:
        library = Library()
    assert mine.next_up_entries(App()) == []
    assert "listing 0 watched shows" in timing.summary()[0] and "working out next episodes" in timing.summary()[0]
