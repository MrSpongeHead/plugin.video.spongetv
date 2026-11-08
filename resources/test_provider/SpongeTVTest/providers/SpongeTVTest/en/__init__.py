# SPDX-License-Identifier: GPL-3.0-or-later
"""SpongeTV's test provider: made-up results, for trying the source search without real sources."""

from . import torrent


def get_torrent():
    return torrent.__all__


def get_hosters():
    return []
