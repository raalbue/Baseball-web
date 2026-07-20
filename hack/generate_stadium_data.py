"""One-time generator for baseball/data/stadiums.json.

Run manually with: python hack/generate_stadium_data.py
Requires only the standard library (csv, urllib, json, math) — not part of
the app's runtime dependencies.
"""
import csv
import json
import math
import urllib.request
from collections import defaultdict
from pathlib import Path

CSV_URL = "https://raw.githubusercontent.com/jldbc/pybaseball/master/pybaseball/data/mlbstadiums.csv"
OUT_PATH = Path(__file__).resolve().parent.parent / "baseball" / "data" / "stadiums.json"

SEGMENTS = [
    "outfield_outer", "outfield_inner",
    "infield_outer", "infield_inner",
    "foul_lines", "home_plate",
]

# Real-world basepath distances (feet), used to scale marker positions
# against each park's own derived home-to-mound-cutout distance.
FT_HOME_TO_MOUND_CUTOUT = 95.0
FT_HOME_TO_FIRST_THIRD  = 90.0
FT_HOME_TO_SECOND       = 127.28


def fetch_rows():
    with urllib.request.urlopen(CSV_URL) as resp:
        text = resp.read().decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def group_by_team_segment(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        team = row["team"]
        seg = row["segment"]
        x, y = float(row["x"]), float(row["y"])
        grouped[team][seg].append((x, y))
        grouped[team]["_name"] = row["name"]
        grouped[team]["_location"] = row["location"]
    return grouped


def centroid(points):
    n = len(points)
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def farthest_point(points, from_point):
    fx, fy = from_point
    return max(points, key=lambda p: (p[0] - fx) ** 2 + (p[1] - fy) ** 2)


def derive_bases(segments, fallback_center, fallback_scale):
    """Home-plate-anchored, geometrically-derived 1st/2nd/3rd positions.

    Direction: unit vector from home-plate centroid toward infield_inner's
    farthest point (the mound-side cutout apex — always points toward
    center field in this shared coordinate frame).
    Distance: that same home-to-apex distance, scaled by real basepath
    ratios (90ft/95ft for 1st & 3rd, 127.28ft/95ft for 2nd), placing 1st
    and 3rd at +/-45 degrees from the center-field axis.

    Falls back to a fixed diamond (centered on the park's own bounding box,
    "up" = toward center field) when a park has no home_plate/infield_inner
    data at all — true for the `generic` entry, which the CSV only supplies
    outfield_outer/infield_outer for.
    """
    home_pts, inner_pts = segments.get("home_plate"), segments.get("infield_inner")
    if not home_pts or not inner_pts:
        home = fallback_center
        ux, uy = 0.0, -1.0
        dist = fallback_scale
    else:
        home = centroid(home_pts)
        apex = farthest_point(inner_pts, home)
        dx, dy = apex[0] - home[0], apex[1] - home[1]
        dist = math.hypot(dx, dy)
        ux, uy = dx / dist, dy / dist

    def offset(distance_ft, angle_deg):
        angle = math.radians(angle_deg)
        # rotate (ux, uy) by angle
        rx = ux * math.cos(angle) - uy * math.sin(angle)
        ry = ux * math.sin(angle) + uy * math.cos(angle)
        scale = dist * (distance_ft / FT_HOME_TO_MOUND_CUTOUT)
        return (home[0] + rx * scale, home[1] + ry * scale)

    return {
        "home_plate":  {"x": home[0], "y": home[1]},
        "first_base":  dict(zip(("x", "y"), offset(FT_HOME_TO_FIRST_THIRD, -45))),
        "second_base": dict(zip(("x", "y"), offset(FT_HOME_TO_SECOND, 0))),
        "third_base":  dict(zip(("x", "y"), offset(FT_HOME_TO_FIRST_THIRD, 45))),
    }


def bounding_viewbox(segments, padding_ratio=0.08):
    xs = [x for seg in SEGMENTS for x, y in segments.get(seg, [])]
    ys = [y for seg in SEGMENTS for x, y in segments.get(seg, [])]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    pad_x, pad_y = w * padding_ratio, h * padding_ratio
    return [minx - pad_x, miny - pad_y, w + 2 * pad_x, h + 2 * pad_y]


def build_entry(segments):
    seg_points = {seg: segments.get(seg, []) for seg in SEGMENTS}
    viewbox = bounding_viewbox(seg_points)
    minx, miny, w, h = viewbox
    fallback_center = (minx + w / 2, miny + h / 2)
    fallback_scale = w * 0.25
    entry = {
        "name": segments["_name"],
        "location": segments["_location"],
        "viewbox": viewbox,
        "marker_radius": viewbox[2] * 0.018,
        "segments": seg_points,
        "bases": derive_bases(seg_points, fallback_center, fallback_scale),
    }
    return entry


def main():
    grouped = group_by_team_segment(fetch_rows())
    out = {}
    for team, segments in grouped.items():
        out[team] = build_entry(segments)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=None, separators=(",", ":")))
    print(f"wrote {len(out)} stadiums to {OUT_PATH}")


if __name__ == "__main__":
    main()
