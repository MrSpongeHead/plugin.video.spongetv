# SPDX-License-Identifier: GPL-3.0-or-later
"""Made-up releases. Nothing here contacts the internet, and the hashes don't belong to real files."""

import hashlib

VARIANTS = [
    ("2160p.UHD.BluRay.HDR.HEVC.Atmos", 18400, 140),
    ("2160p.WEB-DL.DV.HDR.HEVC.5.1", 21000, 95),
    ("1080p.BluRay.x264.5.1", 9100, 310),
    ("1080p.WEB-DL.HEVC.5.1", 4600, 220),
    ("1080p.WEBRip.x265", 2900, 60),
    ("720p.WEB-DL.x264", 1400, 80),
    ("480p.DVDRip.x264", 700, 12),
    ("HDCAM.x264", 1500, 5),
    ("1080p.3D.BluRay.x264", 12000, 3),
]


def release(name, variant, size_mb, seeds, provider):
    digest = hashlib.sha1(f"{provider}:{name}:{variant}".encode("utf-8")).hexdigest()
    return {"hash": digest, "magnet": f"magnet:?xt=urn:btih:{digest}&dn={name}.{variant}",
            "release_title": f"{name}.{variant}", "size": size_mb, "seeds": seeds, "package": "single"}


def movie_name(title, year):
    return f"{title.replace(' ', '.')}.{year}"


def episode_name(simple_info):
    return "{}.S{:02d}E{:02d}".format(simple_info["show_title"].replace(" ", "."), int(simple_info["season_number"]),
                                      int(simple_info["episode_number"]))
