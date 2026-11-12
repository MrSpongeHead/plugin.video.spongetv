# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""Where the time goes while one list is built, for the debug log.

step("name") notes the time since the previous step; tally("name", seconds) adds up work done many
times over, possibly on several threads at once (so tallies can add up to more than the clock time).
main.py writes both to Kodi's log, at debug level, when the list or action has finished.
"""

import threading
import time

_lock = threading.Lock()
_steps = []
_tallies = {}
_last = time.perf_counter()


def step(name):
    global _last
    now = time.perf_counter()
    with _lock:
        _steps.append((name, now - _last))
        _last = now


def tally(name, seconds=0.0):
    with _lock:
        count, total = _tallies.get(name, (0, 0.0))
        _tallies[name] = (count + 1, total + seconds)


def timed(name, call, *args, **kwargs):
    """Run call(*args, **kwargs), adding its time to the tally; a failure is tallied under "<name>, failed"."""
    started = time.perf_counter()
    try:
        result = call(*args, **kwargs)
    except Exception:
        tally(f"{name}, failed", time.perf_counter() - started)
        raise
    tally(name, time.perf_counter() - started)
    return result


def summary():
    """Lines for the log, or [] when nothing was noted."""
    with _lock:
        lines = []
        if _steps:
            lines.append("Steps: " + ", ".join(f"{name} {seconds * 1000:.0f} ms" for name, seconds in _steps))
        if _tallies:
            lines.append("Counts: " + ", ".join(f"{name} x{count} ({total * 1000:.0f} ms added up)"
                                                for name, (count, total) in sorted(_tallies.items())))
        return lines


def reset():
    global _last
    with _lock:
        _steps.clear()
        _tallies.clear()
        _last = time.perf_counter()
