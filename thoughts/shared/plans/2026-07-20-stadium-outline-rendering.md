# Stadium Outline Rendering Implementation Plan

## Overview

Replace the hand-drawn ASCII/emoji diamond on the game detail page with an inline SVG rendering of the home team's actual ballpark outline (filled: green grass, tan dirt, white lines), sourced from a data file vendored (once, offline) from `pybaseball`'s `mlbstadiums.csv`. Runner-on-base markers are geometrically derived per team from that same data rather than hardcoded or parsed from the noisy dirt-cutout curve.

## Current State Analysis

- The "field" today is not an image or vector asset — it's built at runtime by `updateDiamond()` in `baseball/static/baseball/js/game.js:40-51`, which writes a `<pre>` block of Unicode box characters (`🟡`/`⬜`) into `<div id="diamond">` (`baseball/templates/baseball/game_detail.html:57-63`).
- `updateDiamond` is invoked from `updateScoreboard` (`game.js:21-38`), which every play-handling path (`handlePlay`, `game.js:179-193`) calls after each roll, plus once on initial page load (`game.js:274-282`) by reading the `#diamond` element's `data-bases` attribute.
- No SVG/image/canvas assets exist anywhere under `baseball/static/` today — this is new territory for the app.
- `Game.home_team` is a nullable FK to `Team` (`baseball/models.py:260-263`), always populated by the time `GameDetailView` renders (every mode sets both teams before flipping a game to `active`/`waiting`→`active`; `GameDetailView.get()` redirects away from the template entirely while a multiplayer game is still `waiting`).
- `Team.stadium` FK → `Stadium` (`baseball/models.py:10-24, 27-47`) exists but `Stadium` only carries descriptive fields (name/city/capacity) — no shape data. Both are unmanaged models seeded via `baseball/migrations/0006_seed_stadiums_teams.py`.
- No test suite exists for the `baseball` app (`baseball/tests.py` doesn't exist; `accounts/tests.py` and `todo_app/tests.py` do, unrelated). No `Makefile`. Verification in this repo is done via `python manage.py check` and targeted `python manage.py shell -c "..."` snippets (see `baseball/migrations/0009...`'s companion plan for precedent).
- Full research on the CSV's structure and licensing is in `thoughts/shared/research/2026-07-20-pybaseball-stadium-rendering.md`.

### Key Discoveries (from live inspection of the CSV, this session)

- The CSV (`https://raw.githubusercontent.com/jldbc/pybaseball/master/pybaseball/data/mlbstadiums.csv`, MIT licensed) has columns `index, team, x, y, segment, name, location`, 15,630 rows, 31 team slugs (30 MLB teams + `generic` fallback), 6 segments per team: `foul_lines`, `home_plate`, `infield_inner`, `infield_outer`, `outfield_inner`, `outfield_outer`.
- **Every team's `home_plate` centroid is the identical point `(125.189, 201.534)`** (confirmed by averaging `home_plate` rows across all 30 teams directly from the downloaded CSV — 29 of 30 match exactly, Yankees differs by ~1 unit, negligible). This proves the CSV uses one shared, home-plate-anchored, canonical coordinate frame (the MLBAM/Statcast hit-coordinate convention `pybaseball` calibrates against) — **not** per-park pixel coordinates at arbitrary rotation. Practical consequence: there is no need to parse each park's `foul_lines` rays to figure out orientation; the "toward center field" axis and home-plate anchor are already normalized across every team.
- `infield_inner` (the rounded dirt-cutout curve, ~38–63 points depending on team) does **not** have clean 4-corner points — it's a smooth rounded shape, not a simple square. Deriving base positions by corner-detection on this curve (the originally-considered approach) would be fragile. Instead, the plan derives base positions from the **direction and distance to `infield_inner`'s single farthest point from the home-plate centroid** (the mound-side apex of the skinned-dirt cutout, a real-world ~95 ft radius in every modern park) — this gives both the correct per-park "toward center field" direction *and* a distance to calibrate real basepath geometry (90 ft to 1B/3B, 127.28 ft to 2B) against, using nothing fragile like ray-splitting or curvature analysis.
- Since raw CSV `y` already increases toward home plate and decreases toward center field (confirmed: `outfield_outer` min y ≈ 34, home plate y ≈ 201), and SVG's `y` axis also increases downward, **no coordinate sign-flip or Statcast-alignment transform is needed** — raw CSV `(x, y)` pairs can be plotted directly into an SVG `viewBox` computed per-team from that team's own point bounding box. (`pybaseball`'s own `STADIUM_SCALE`/center transform exists only to align with Statcast's `hc_x`/`hc_y` fields for overlaying batted-ball data, which this app has no use for.)
- This app's `Team.name` values map to the CSV's `team` slug via an explicit lookup table (not a string transform) for all 30 teams; the one non-obvious mapping is `"Guardians" → "indians"` (the CSV predates Cleveland's 2021 rename and hasn't been updated).

## Desired End State

- `GameDetailView` (any mode, any active/finished game) renders an inline SVG of the home team's real ballpark outline in place of the old ASCII diamond, filled green (grass) / tan (dirt) / white (lines), sized in its own larger area on the page.
- Three base-occupancy markers (1st/2nd/3rd) sit inside that outline at geometrically-derived positions, and toggle on/off exactly as the old 🟡/⬜ indicators did — same call sites, same trigger points (initial load + after every roll in every mode).
- Works for all 30 MLB teams the app already seeds, including the Guardians→`indians` slug mismatch, plus a `generic` fallback outline for the (currently theoretical) case of a game whose `home_team` is null.
- No new runtime dependency: the stadium data is vendored into the repo once via an offline generation script; nothing in the running app fetches from GitHub or parses the raw CSV at request time.

### Verify by:
- Loading a finished or active game's detail page for several different home teams (including one requiring the Guardians override) and visually confirming a recognizable, correctly-colored park outline with base markers positioned inside the infield.
- Rolling through at-bats and confirming the base markers update at the same moments the old diamond used to (immediately after each roll's response, and correctly on page reload).
- Confirming all 4 existing modes (`cpu_auto`, `click_all`, `auto_play`, `multiplayer`) still play through correctly with the new field in place — this is a display-only change, no game-state/engine changes.

## What We're NOT Doing

- Not touching `Team`/`Stadium` DB models, migrations, or the existing `stadium` FK — the CSV data is a separate, purely presentational data source joined by team identity, not routed through that FK/table.
- Not overlaying real batted-ball/Statcast hit data (`pybaseball`'s `spraychart`) — this is a static park outline only.
- Not adding stadium metadata display (capacity, city, opening year, etc.) beyond what's needed to pick the right outline.
- Not making the park shape interactive/animated beyond the existing base-occupancy toggle.
- Not changing `engine.py` or any game-state logic — purely a rendering change.
- Not fetching `mlbstadiums.csv` at app runtime — it's vendored once via an offline script; the running app never makes an outbound network call for this feature.
- Not attempting exact real-world compass-accurate 1st-base-vs-3rd-base side labeling — base markers form a geometrically correct, symmetric diamond relative to each park's own home-plate/center-field axis, which is sufficient for a base-occupancy display.
- Not adding a UI setting to preview a stadium during game setup — this only affects the in-game (`game_detail.html`) view, matching where the old diamond lived.

## Implementation Approach

Five phases: an offline one-time data-generation script producing a vendored JSON file, a small Python loader module exposing that data to Django views, the template swap from ASCII div to server-rendered inline SVG, the JS rework of `updateDiamond()` to toggle SVG circles instead of rebuilding text, and a layout pass to give the park adequate visual room.

---

## Phase 1: Vendor + Derive Stadium Data

### Overview
A standalone, stdlib-only Python script (not part of the running app, not added to `requirements.txt`) downloads `mlbstadiums.csv`, groups points by team and segment, derives base-marker positions, computes a per-team SVG viewBox, and writes one JSON file checked into the repo.

### Changes Required

#### 1. `hack/generate_stadium_data.py` — new file

```python
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


def derive_bases(segments):
    """Home-plate-anchored, geometrically-derived 1st/2nd/3rd positions.

    Direction: unit vector from home-plate centroid toward infield_inner's
    farthest point (the mound-side cutout apex — always points toward
    center field in this shared coordinate frame).
    Distance: that same home-to-apex distance, scaled by real basepath
    ratios (90ft/95ft for 1st & 3rd, 127.28ft/95ft for 2nd), placing 1st
    and 3rd at +/-45 degrees from the center-field axis.
    """
    home = centroid(segments["home_plate"])
    apex = farthest_point(segments["infield_inner"], home)
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
    xs = [x for seg in SEGMENTS for x, y in segments[seg]]
    ys = [y for seg in SEGMENTS for x, y in segments[seg]]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w, h = maxx - minx, maxy - miny
    pad_x, pad_y = w * padding_ratio, h * padding_ratio
    return [minx - pad_x, miny - pad_y, w + 2 * pad_x, h + 2 * pad_y]


def build_entry(segments):
    seg_points = {seg: segments[seg] for seg in SEGMENTS}
    viewbox = bounding_viewbox(seg_points)
    entry = {
        "name": segments["_name"],
        "location": segments["_location"],
        "viewbox": viewbox,
        "marker_radius": viewbox[2] * 0.018,
        "segments": seg_points,
        "bases": derive_bases(seg_points),
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
```

Run once by hand: `python hack/generate_stadium_data.py`. This produces `baseball/data/stadiums.json`, which gets committed to the repo like any other seed data.

**Deviation found during implementation**: the CSV's `generic` entry only has `outfield_outer`/`infield_outer` data — no `home_plate`/`infield_inner`/`foul_lines`/`outfield_inner` — so `derive_bases`'s original home-plate-anchored approach divides by zero on it. Fixed by giving `derive_bases` a fixed-diamond fallback (centered on the park's own bounding box, "up" = toward center field) used whenever `home_plate`/`infield_inner` data is missing — this is the same "fixed overlay fallback" approach already approved for any team where derivation isn't viable, just triggered by `generic` specifically rather than a real team. `bounding_viewbox`/`build_entry` also switched to `.get(seg, [])` so missing segments don't KeyError. The script committed to the repo reflects this fix.

### Success Criteria

#### Automated Verification:
- [x] Script runs to completion: `python hack/generate_stadium_data.py` exits 0 and reports "wrote 31 stadiums"
- [x] Output is valid and complete: `python -c "import json; d=json.load(open('baseball/data/stadiums.json')); assert len(d)==31; assert 'angels' in d and 'indians' in d and 'generic' in d; assert set(d['angels']['segments'])=={'outfield_outer','outfield_inner','infield_outer','infield_inner','foul_lines','home_plate'}; assert set(d['angels']['bases'])=={'home_plate','first_base','second_base','third_base'}; print('ok')"`

#### Manual Verification:
- [ ] None yet — no UI change in this phase; visual confirmation happens in Phase 3

**Implementation Note**: Pause here for manual confirmation before Phase 2.

---

## Phase 2: Backend Wiring

### Overview
A small loader module exposes the vendored data to Django, plus the explicit `Team.name → CSV slug` mapping (with the Guardians override), plumbed into `GameDetailView`'s context in template-ready form.

### Changes Required

#### 1. `baseball/data/stadiums.json` — vendored output of Phase 1 (already created)

#### 2. `baseball/stadiums.py` — new file

```python
import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "data" / "stadiums.json"
_STADIUMS = json.loads(_DATA_PATH.read_text())

TEAM_SLUGS = {
    "Angels": "angels", "Astros": "astros", "Athletics": "athletics",
    "Blue Jays": "blue_jays", "Braves": "braves", "Brewers": "brewers",
    "Cardinals": "cardinals", "Cubs": "cubs", "Diamondbacks": "diamondbacks",
    "Dodgers": "dodgers", "Giants": "giants", "Guardians": "indians",
    "Mariners": "mariners", "Marlins": "marlins", "Mets": "mets",
    "Nationals": "nationals", "Orioles": "orioles", "Padres": "padres",
    "Phillies": "phillies", "Pirates": "pirates", "Rangers": "rangers",
    "Rays": "rays", "Red Sox": "red_sox", "Reds": "reds",
    "Rockies": "rockies", "Royals": "royals", "Tigers": "tigers",
    "Twins": "twins", "White Sox": "white_sox", "Yankees": "yankees",
}


def stadium_context(team):
    """Return template-ready stadium data for the given Team (or None)."""
    slug = TEAM_SLUGS.get(team.name) if team else None
    data = _STADIUMS.get(slug) or _STADIUMS["generic"]
    minx, miny, w, h = data["viewbox"]
    return {
        "name": data["name"] or "Generic Ballpark",
        "viewbox": f"{minx} {miny} {w} {h}",
        "marker_radius": data["marker_radius"],
        "segments": {
            seg: " ".join(f"{x},{y}" for x, y in points)
            for seg, points in data["segments"].items()
        },
        "bases": data["bases"],
    }
```

#### 3. `baseball/views.py` — `GameDetailView.get_context_data`

Add alongside the existing multiplayer `my_side`/`opponent_username` block:

```python
from .stadiums import stadium_context
```

```python
        ctx["stadium"] = stadium_context(self.object.home_team)
```

(One import line near the top with the other local imports, one context assignment inside `get_context_data`, right after `ctx["winner"]`/before the multiplayer block — order doesn't matter functionally.)

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from baseball.stadiums import stadium_context, TEAM_SLUGS; from baseball.models import Team; assert TEAM_SLUGS['Guardians'] == 'indians'; t = Team.objects.get(name='Guardians'); ctx = stadium_context(t); assert ctx['name']; assert 'first_base' in ctx['bases']; assert ',' in ctx['segments']['outfield_outer']; print('ok')"`
- [x] Fallback works for a null team: `python manage.py shell -c "from baseball.stadiums import stadium_context; ctx = stadium_context(None); assert ctx['name'] == 'Generic Ballpark'; print('ok')"`

#### Manual Verification:
- [ ] None yet — not rendered in any template until Phase 3

**Implementation Note**: Pause here for manual confirmation before Phase 3.

---

## Phase 3: Template — Replace `#diamond` with Inline SVG

### Overview
`game_detail.html`'s ASCII diamond container becomes a server-rendered SVG built from `ctx["stadium"]`, filled green/tan/white, with 3 base-marker circles.

### Changes Required

#### 1. `baseball/templates/baseball/game_detail.html` — replace the diamond block

Replace:
```html
        <div id="diamond"
             data-half="{{ game.state.half }}"
             data-bases="{{ game.state.bases|join:',' }}"
             class="my-2"
             style="font-family:monospace;line-height:1.6">
        </div>
```

With:
```html
        <div id="diamond"
             data-half="{{ game.state.half }}"
             data-bases="{{ game.state.bases|join:',' }}"
             class="my-2">
          <svg viewBox="{{ stadium.viewbox }}" preserveAspectRatio="xMidYMid meet"
               style="width:100%;height:auto;display:block">
            <polygon class="field-outfield-outer" points="{{ stadium.segments.outfield_outer }}" />
            <polygon class="field-outfield-inner" points="{{ stadium.segments.outfield_inner }}" />
            <polygon class="field-infield-dirt"   points="{{ stadium.segments.infield_outer }}" />
            <polygon class="field-infield-grass"  points="{{ stadium.segments.infield_inner }}" />
            <polyline class="field-foul-lines"    points="{{ stadium.segments.foul_lines }}" />
            <polygon class="field-home-plate"     points="{{ stadium.segments.home_plate }}" />
            <circle id="base-marker-1" class="base-marker"
                    cx="{{ stadium.bases.first_base.x }}" cy="{{ stadium.bases.first_base.y }}"
                    r="{{ stadium.marker_radius }}" />
            <circle id="base-marker-2" class="base-marker"
                    cx="{{ stadium.bases.second_base.x }}" cy="{{ stadium.bases.second_base.y }}"
                    r="{{ stadium.marker_radius }}" />
            <circle id="base-marker-3" class="base-marker"
                    cx="{{ stadium.bases.third_base.x }}" cy="{{ stadium.bases.third_base.y }}"
                    r="{{ stadium.marker_radius }}" />
          </svg>
        </div>
```

#### 2. `baseball/templates/baseball/game_detail.html` — add styling

Add near the top of the file (mirroring the existing convention of inline `<style>`/`style=` attributes rather than a separate CSS file — no CSS file exists anywhere in this project):

```html
<style>
  .field-outfield-outer, .field-outfield-inner { fill: #4a8f3c; stroke: none; }
  .field-infield-dirt   { fill: #c8a165; stroke: none; }
  .field-infield-grass  { fill: #4a8f3c; stroke: none; }
  .field-foul-lines     { fill: none; stroke: #fff; stroke-width: 1; }
  .field-home-plate     { fill: #fff; stroke: none; }
  .base-marker          { fill: #e8e8e8; stroke: #333; stroke-width: 1; }
  .base-marker.occupied { fill: #ffd400; }
</style>
```

`.field-outfield-inner` intentionally matches `.field-outfield-outer`'s color (both grass) — the two segments are nested grass boundaries, not different surfaces; verify this visually in the manual check below and adjust if a specific park's data reveals otherwise (e.g. if `outfield_inner` turns out to trace a warning track, differentiate its color then).

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] Template loads: `python manage.py shell -c "from django.template.loader import get_template; get_template('baseball/game_detail.html'); print('ok')"`
- [x] Full render with a real game's context succeeds and contains the SVG + base markers (verified beyond the plan's listed check, to catch runtime template errors `get_template` alone wouldn't)

#### Manual Verification:
- [ ] Loading `/baseball/<pk>/` for games with different home teams (e.g. Angels, Red Sox, Guardians) shows visually distinct, recognizable park outlines — green outfield/infield grass, tan infield dirt, white foul lines and home plate
- [ ] The 3 base markers render inside the infield area, not overlapping the outfield or off the edge of the SVG, for several different teams
- [ ] A game whose `home_team` somehow ends up null renders the `generic` fallback outline without error

**Implementation Note**: Pause here for manual confirmation before Phase 4.

---

## Phase 4: JS — `updateDiamond()` Rework

### Overview
Instead of rebuilding ASCII text, `updateDiamond()` toggles the 3 SVG circles' `occupied` class. Same call sites as today — no changes to `handlePlay`, `updateScoreboard`'s call to it, or the initial-load block.

### Changes Required

#### 1. `baseball/static/baseball/js/game.js` — replace `updateDiamond`

Replace:
```javascript
function updateDiamond(bases) {
    const on = '🟡', off = '⬜';
    const b1 = bases[0], b2 = bases[1], b3 = bases[2];
    document.getElementById('diamond').innerHTML =
        `<pre style="line-height:1.4;margin:0">` +
        `         ${b2 ? on : off}\n` +
        `        /   \\\n` +
        `    ${b3 ? on : off}       ${b1 ? on : off}\n` +
        `        \\   /\n` +
        `         (H)\n` +
        `</pre>`;
}
```

With:
```javascript
function updateDiamond(bases) {
    document.getElementById('base-marker-1').classList.toggle('occupied', !!bases[0]);
    document.getElementById('base-marker-2').classList.toggle('occupied', !!bases[1]);
    document.getElementById('base-marker-3').classList.toggle('occupied', !!bases[2]);
}
```

Everything else in `game.js` — `updateScoreboard`'s call to `updateDiamond(state.bases)` (`game.js:37`), `handlePlay`'s indirect call via `updateScoreboard` (`game.js:182`), and the initial-load block reading `#diamond`'s `data-bases` attribute (`game.js:274-282`) — is unchanged; they already pass/parse the same 3-element boolean array this function now consumes.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0 (no Python changes in this phase, but keeps the phase-gate consistent with the rest of the plan)

#### Manual Verification:
- [ ] Loading a game detail page shows base markers correctly reflecting the current (possibly mid-game) base state on first paint, with no flash of incorrect state
- [ ] Rolling through at-bats in `cpu_auto` mode toggles markers on/off at the same moments the old diamond used to (immediately after each roll's dice/message display)
- [ ] Same check in `click_all`, `auto_play`, and `multiplayer` modes — no mode-specific regressions
- [ ] No JS console errors on any game page

**Implementation Note**: Pause here for manual confirmation before Phase 5.

---

## Phase 5: Layout

### Overview
Give the park outline its own larger, legible area instead of the old diamond's small footprint inside the scoreboard card.

### Changes Required

#### 1. `baseball/templates/baseball/game_detail.html` — restructure the layout

Move the `#diamond` block (now the SVG) out of the scoreboard card's `card-body` and into its own full-width card placed above the existing two-column `row g-4` (scoreboard + play-by-play), constrained to a reasonable max width so it doesn't dominate on wide screens:

```html
<div class="card mb-3" style="max-width:600px;margin-left:auto;margin-right:auto">
  <div class="card-header fw-bold text-center">{{ stadium.name }}</div>
  <div class="card-body">
    <!-- SVG block from Phase 3 goes here -->
  </div>
</div>

<div class="row g-4">
  <!-- existing scoreboard card (minus the old diamond block) + play-by-play columns, unchanged -->
</div>
```

The scoreboard card's `card-body` keeps everything it had except the removed diamond block (outs counter, batter line) — no other content moves.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] Template loads: `python manage.py shell -c "from django.template.loader import get_template; get_template('baseball/game_detail.html'); print('ok')"`
- [x] Full render confirms the stadium card now precedes the scoreboard card in output order

#### Manual Verification:
- [ ] Park outline renders at a clearly legible size on a typical desktop browser width
- [ ] Layout doesn't overlap or break the scoreboard, play-by-play, or lineup cards below it
- [ ] Layout remains usable (no horizontal overflow/clipping) at a narrow/mobile browser width

---

## Testing Strategy

### Manual Testing Steps (end-to-end):
1. Start a `cpu_auto` game as several different home teams in turn (e.g. Angels, Red Sox, Guardians — the mapping-override case) and confirm each shows a distinct, correctly-colored, recognizable park outline on `/baseball/<pk>/`.
2. Roll through at-bats; confirm base markers turn on/off at the correct moments and end up correctly cleared after each half-inning/run.
3. Reload the page mid-game; confirm the markers show the correct current state on first paint (not blank/stale).
4. Repeat a quick playthrough in `click_all`, `auto_play`, and `multiplayer` modes to confirm no mode-specific regression.
5. Confirm a finished game's detail page still renders the park outline correctly (post-game state).
6. Resize the browser to a narrow width and confirm the layout holds up.

## Performance Considerations

All stadium data is precomputed once offline and loaded as a single small JSON file at Django process startup (`baseball/stadiums.py` module import) — no per-request file I/O, CSV parsing, or network calls. The SVG itself is plain server-rendered markup (a few hundred points per park at most), well within the size of the existing full-page-reload HTML responses this app already sends after every roll.

## Migration Notes

No database schema changes. `baseball/data/stadiums.json` is committed like any other seed/static data; `hack/generate_stadium_data.py` is a one-time developer tool, not run automatically by the app or any deploy step.

## References

- Research: `thoughts/shared/research/2026-07-20-pybaseball-stadium-rendering.md`
- `baseball/static/baseball/js/game.js:40-51` — current `updateDiamond()` (being replaced)
- `baseball/static/baseball/js/game.js:21-38` — `updateScoreboard()`, calls `updateDiamond`
- `baseball/static/baseball/js/game.js:179-193` — `handlePlay()`, drives the update pipeline after every roll
- `baseball/static/baseball/js/game.js:274-282` — initial-load diamond render
- `baseball/templates/baseball/game_detail.html:57-63` — current `<div id="diamond">` markup
- `baseball/models.py:10-24, 27-47, 260-263` — `Stadium`, `Team`, `Game.home_team`
- `baseball/views.py` — `GameDetailView.get_context_data`
