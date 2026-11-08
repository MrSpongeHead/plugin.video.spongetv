# SPDX-License-Identifier: GPL-3.0-or-later
"""SpongeTV's test provider: made-up results, for trying the source search without real sources."""

from . import direct, torrent


def get_torrent():
    return torrent.__all__


def get_hosters():
    return []


def get_direct():
    return direct.__all__
