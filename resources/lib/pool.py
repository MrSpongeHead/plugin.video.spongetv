# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 MrSpongeHead
"""A pool of worker threads, with Python's concurrent.futures loaded only when a pool is first made:
plain menus never need one, and loading it takes a noticeable moment on slower boxes."""


def ThreadPoolExecutor(*args, **kwargs):
    from concurrent.futures import ThreadPoolExecutor as Pool
    return Pool(*args, **kwargs)
