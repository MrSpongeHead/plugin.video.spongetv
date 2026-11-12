# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""SpongeTV menu and action entry point."""

import sys
import time

_started = time.perf_counter()
from resources.lib import kodi  # noqa: E402
from resources.lib.router import dispatch  # noqa: E402

_code_loaded = time.perf_counter()

if __name__ == "__main__":
    try:
        dispatch(sys.argv)
    finally:
        # Only in Kodi's log with debug logging on: where the time goes each time a list or action runs
        done = time.perf_counter()
        kodi.log_debug(f"Timing {(sys.argv[2] if len(sys.argv) > 2 else '')[:90] or '(main menu)'}: "
                       f"{(done - _started) * 1000:.0f} ms in all, {(_code_loaded - _started) * 1000:.0f} ms of it "
                       f"starting up{' (used the network)' if 'requests' in sys.modules else ''}")
