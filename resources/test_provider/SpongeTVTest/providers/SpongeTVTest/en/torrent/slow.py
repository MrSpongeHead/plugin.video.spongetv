# SPDX-License-Identifier: GPL-3.0-or-later
"""Answers after a few seconds, so you can watch the progress window and early stop."""

import time

from providerModules.SpongeTVTest import fake

DELAY = 6


class sources:
    def movie(self, title, year, imdb=None, **kwargs):
        time.sleep(DELAY)
        name = fake.movie_name(title, year)
        return [fake.release(name, v, size, seeds, "slow") for v, size, seeds in fake.VARIANTS[1:4]]

    def episode(self, simple_info, all_info, **kwargs):
        time.sleep(DELAY)
        name = fake.episode_name(simple_info)
        return [fake.release(name, v, max(size // 8, 200), seeds, "slow") for v, size, seeds in fake.VARIANTS[2:5]]
