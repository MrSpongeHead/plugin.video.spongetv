# SPDX-License-Identifier: GPL-3.0-or-later
"""A public test video (Big Buck Bunny, Blender Foundation, CC BY 3.0) as a direct link, so playback,
resume and Playing Next can be tried without Premiumize. Off until you turn it on in Manage packages.

It plays the test video whatever you chose, so stop it before the end if you're signed in to Trakt:
watching most of it would mark the film or episode you chose as watched there."""

VIDEO = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4"


def _release(name):
    return {"url": VIDEO, "release_title": f"{name} SpongeTV TEST VIDEO not the real thing 720p", "quality": "720p",
            "size": 150, "debrid": ""}


class sources:
    def movie(self, title, year, imdb=None, **kwargs):
        return [_release(f"{title} {year}")]

    def episode(self, simple_info, all_info, **kwargs):
        return [_release(f"{simple_info.get('show_title')} S{int(simple_info.get('season_number') or 0):02d}"
                         f"E{int(simple_info.get('episode_number') or 0):02d}")]
