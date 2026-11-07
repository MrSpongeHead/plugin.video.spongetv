# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""SpongeTV menu and action entry point."""

import sys

from resources.lib.router import dispatch

if __name__ == "__main__":
    dispatch(sys.argv)
