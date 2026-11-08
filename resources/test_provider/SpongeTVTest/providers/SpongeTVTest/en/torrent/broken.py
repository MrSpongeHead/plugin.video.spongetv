# SPDX-License-Identifier: GPL-3.0-or-later
"""Always fails, to show one failing provider can't stop the search."""


class sources:
    def movie(self, title, year, imdb=None, **kwargs):
        raise RuntimeError("the broken test provider failed, as it always does")

    def episode(self, simple_info, all_info, **kwargs):
        raise RuntimeError("the broken test provider failed, as it always does")
