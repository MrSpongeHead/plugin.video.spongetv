# SPDX-License-Identifier: GPL-3.0-or-later
"""Returns a spread of made-up releases straight away."""

from providerModules.SpongeTVTest import fake


class sources:
    def movie(self, title, year, imdb=None, **kwargs):
        name = fake.movie_name(title, year)
        return [fake.release(name, v, size, seeds, "sample") for v, size, seeds in fake.VARIANTS]

    def episode(self, simple_info, all_info, **kwargs):
        name = fake.episode_name(simple_info)
        return [fake.release(name, v, max(size // 8, 200), seeds, "sample") for v, size, seeds in fake.VARIANTS]
