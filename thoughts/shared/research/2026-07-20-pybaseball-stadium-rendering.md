---
date: 2026-07-20T18:07:54-04:00
researcher: Raalbue
git_commit: 26a60c0856b0d9ceff5ccd9703af9dbec82c8421
branch: main
repository: baseball-web
topic: "Replacing the barebones diamond with a real stadium outline from pybaseball's mlbstadiums.csv"
tags: [research, codebase, pybaseball, stadium, svg, game.js, game_detail.html, Stadium, Team]
status: complete
last_updated: 2026-07-20
last_updated_by: Raalbue
---

# Research: Replacing the barebones diamond with a real stadium outline from pybaseball's mlbstadiums.csv

**Date**: 2026-07-20T18:07:54-04:00
**Researcher**: Raalbue
**Git Commit**: 26a60c0856b0d9ceff5ccd9703af9dbec82c8421
**Branch**: main
**Repository**: baseball-web

## Research Question

Is `pybaseball`'s `mlbstadiums.csv` (linked by the user: https://github.com/jldbc/pybaseball/blob/master/pybaseball/data/mlbstadiums.csv) usable data for rendering the home team's actual stadium shape, in place of this app's current barebones diamond? Specifically: is the data usable, and can it be displayed on a webpage (not just a terminal/matplotlib figure)?

## Summary

The CSV is coordinate data, not ASCII art — it's directly usable for web rendering. It contains, for 30 MLB teams (plus a `generic` fallback), a set of (x, y) polyline points grouped into 6 named field segments (`foul_lines`, `home_plate`, `infield_inner`, `infield_outer`, `outfield_inner`, `outfield_outer`). `pybaseball`'s own plotting code (`pybaseball/plotting.py`, function `plot_stadium`) draws these with matplotlib by looping over segments and building one path per segment — but the underlying operation (group rows by `segment`, connect the (x,y) points into a closed/open path) has no dependency on matplotlib and maps 1:1 onto an SVG `<polygon>`/`<path>` per segment. The data is MIT-licensed.

The current in-app field ([baseball/static/baseball/js/game.js:40-51](../../../baseball/static/baseball/js/game.js#L40-L51)) is a hand-drawn ASCII/emoji diamond built in JS, not an image or SVG asset — there is no existing stadium-graphics pipeline in this codebase to build on; this would be new. The app's `Team` model already carries a `stadium` FK ([baseball/models.py:35-38](../../../baseball/models.py#L35-L38)) to a `Stadium` row with `name`/`city`/`state`/`country`/`capacity` — no shape/dimension data, so the CSV would be a wholly separate data source keyed by team, not wired through the existing `Stadium` table. Team-name mapping from this app's `Team.name` to the CSV's `team` slug is a simple `lower().replace(' ', '_')` for 29 of 30 teams; the one exception is Cleveland, stored here as `"Guardians"` while the (evidently pre-2021-rename) CSV still uses the old slug `indians`.

## Detailed Findings

### The CSV's actual structure (not ASCII/terminal art)

Fetched directly from `https://raw.githubusercontent.com/jldbc/pybaseball/master/pybaseball/data/mlbstadiums.csv` (15,630 data rows total):

Columns: `index, team, x, y, segment, name, location`

Example rows:
```
0,angels,147.568125776129,179.161874223871,infield_inner,Angel Stadium of Anaheim,"Anaheim, CA"
316,blue_jays,164.0,164.63,infield_outer,Rogers Centre,"Toronto, ONT"
```

- `team` — lowercase, underscore-separated team slug (e.g. `angels`, `blue_jays`, `white_sox`). 31 distinct values: the 30 MLB teams plus a `generic` fallback stadium (whose rows have blank `name`/`location`).
- `x`, `y` — decimal plot coordinates, not lat/long or physical distances; they're pre-scaled to a shared coordinate space (see below).
- `segment` — 6 distinct values across the whole file: `foul_lines`, `home_plate`, `infield_inner`, `infield_outer`, `outfield_inner`, `outfield_outer`. Each team has ~500 rows split across these 6 segments, each segment being an ordered list of points tracing a piece of the park outline (e.g. `angels` alone has 501 rows).
- `name` / `location` — stadium display name and city/region, repeated on every row for that team (only present for real teams, blank for `generic`).

This confirms it's structured path/polyline data, directly plottable — not pre-rendered text or images.

### How pybaseball itself turns this into a picture

`pybaseball/plotting.py` (fetched from GitHub, MIT license per `pybaseball` repo's `LICENSE` file):

```python
STADIUM_SCALE = 2.495 / 2.33
STADIUM_COORDS = transform_coordinates(
    pd.read_csv(Path(CUR_PATH, 'data', 'mlbstadiums.csv'), index_col=0), scale=STADIUM_SCALE
)

def plot_stadium(team, title=None, width=None, height=None, axis=None):
    coords = STADIUM_COORDS[STADIUM_COORDS['team'] == team.lower()]
    ...
    axis.set_xlim(0, 250)
    axis.set_ylim(-250, 0)
    segments = set(coords['segment'])
    for segment in segments:
        segment_verts = coords[coords['segment'] == segment][['x', 'y']]
        path = matplotlib.path.Path(segment_verts)
        patch = patches.PathPatch(path, facecolor='None', edgecolor='grey', lw=2)
        axis.add_patch(patch)
```

And the coordinate transform applied before plotting:

```python
def _transform_coordinate(coord, center, scale, sign):
    return sign * ((coord - center) * scale + center)

def transform_coordinates(coords, scale, x_center=125, y_center=199):
    x_transform = partial(_transform_coordinate, center=x_center, scale=scale, sign=+1)
    y_transform = partial(_transform_coordinate, center=y_center, scale=scale, sign=-1)
    return coords.assign(x=coords.x.apply(x_transform), y=coords.y.apply(y_transform))
```

Per the code comment, `STADIUM_SCALE = 2.495 / 2.33` and the center `(125, 199)` were picked heuristically so the outline aligns with MLBAM Statcast hit-coordinate fields (`hc_x`/`hc_y`) — i.e. this transform exists to overlay batted-ball data on the park, not because the raw CSV values are unusable on their own. After the transform, the plot area is fixed at `x ∈ [0, 250]`, `y ∈ [-250, 0]` with a 1:1 aspect ratio and the y-axis inverted (so home plate sits near the bottom of the frame). The function loops per unique `segment` value and draws each as its own path — it does not distinguish or hide any segment, so both infield and outfield/foul-line boundaries are drawn.

Mechanically, this is: group CSV rows by (`team`, `segment`) → order by original row index → connect points into a line/polygon. That grouping-and-connecting logic is what an SVG-based renderer would replicate — matplotlib is only the rendering backend `pybaseball` happens to use, not something the data depends on.

### Is it usable on a webpage instead of a terminal?

Yes, mechanically — nothing in the CSV or the transform ties it to matplotlib/terminal output. The same `(x, y)` points per segment can be fed into:
- An SVG `<polygon points="...">` or `<path d="M x,y L x,y ...">` per segment, with the same coordinate transform (or a simplified equivalent — the exact `STADIUM_SCALE`/center values only matter if trying to match real-world Statcast coordinates; for a purely visual outline any consistent scale/offset that fits the target viewBox works)
- An HTML5 `<canvas>` line-path draw, one path per segment
- Any JS charting/plotting library that accepts point arrays

No terminal-only serialization (ASCII art, curses, etc.) is involved anywhere in the CSV or in `pybaseball`'s plotting code — the "terminal vs. webpage" distinction doesn't actually apply here; the output is always a 2D vector picture, and matplotlib's figure is just one of several possible renderers for the same point data.

### Current field rendering in this codebase

The existing "field" is not an image or vector asset — it's assembled at runtime in JS from Unicode characters:

```javascript
// baseball/static/baseball/js/game.js:40-51
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

It's driven by a `<div id="diamond">` in the template that carries the base-occupancy/half-inning state as data attributes, and is re-rendered both on initial page load and after every roll:

```html
<!-- baseball/templates/baseball/game_detail.html:57-63 -->
<div id="diamond"
     data-half="{{ game.state.half }}"
     data-bases="{{ game.state.bases|join:',' }}"
     class="my-2"
     style="font-family:monospace;line-height:1.6">
</div>
```

```javascript
// baseball/static/baseball/js/game.js:274-282
const diamondEl = document.getElementById('diamond');
if (diamondEl) {
    const rawBases = diamondEl.dataset.bases;
    if (rawBases) {
        const bases = rawBases.split(',').map(v => v === 'True' || v === '1' || v === 'true');
        updateDiamond(bases);
    }
}
```

`updateDiamond` is also called from `updateScoreboard` ([baseball/static/baseball/js/game.js:21-38](../../../baseball/static/baseball/js/game.js#L21-L38)), which every play-handling path (`handlePlay`, [baseball/static/baseball/js/game.js:179-193](../../../baseball/static/baseball/js/game.js#L179-L193)) invokes with the freshly-returned `play.state` after each `RollView`/`SimulateView` response. So any replacement of the diamond graphic needs a JS-side update path in addition to the initial server-rendered state, mirroring this existing call pattern.

There are no SVG, image, or canvas assets anywhere under `baseball/static/`:

```
baseball/static/baseball/js/game.js
baseball/static/baseball/sounds/1.wav
baseball/static/baseball/sounds/10.wav
baseball/static/baseball/sounds/5.wav
```

— confirming there's no existing stadium-graphics pipeline to extend; this would be new territory for the app.

### `Team`/`Stadium` models and how a stadium would be selected

`Game.home_team` is a nullable FK to `Team` ([baseball/models.py:260-263](../../../baseball/models.py#L260-L263)), set once a side's team is chosen during setup (`Page1View`/`Page2View`/`Player2JoinView` in `baseball/views.py`). `Team` in turn has a `stadium` FK:

```python
# baseball/models.py:27-47
class Team(models.Model):
    team_id      = models.AutoField(primary_key=True)
    name         = models.CharField(max_length=100)
    city         = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=5, blank=True, null=True)
    ...
    stadium      = models.ForeignKey(
        Stadium, db_column='stadium_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )
    ...
```

```python
# baseball/models.py:10-24
class Stadium(models.Model):
    stadium_id = models.AutoField(primary_key=True)
    name       = models.CharField(max_length=100)
    city       = models.CharField(max_length=50)
    state      = models.CharField(max_length=50, blank=True, null=True)
    country    = models.CharField(max_length=50, default='USA')
    capacity   = models.IntegerField(null=True, blank=True)

    class Meta:
        managed  = False
        db_table = 'stadium'
        ordering = ['name']
```

Both `Team` and `Stadium` are `managed = False` — unmanaged models backed by raw Postgres tables seeded outside Django migrations (see `baseball/migrations/0006_seed_stadiums_teams.py`). Neither carries any shape, dimension, wall-distance, or coordinate data — `Stadium` is purely descriptive (name/city/capacity). So the pybaseball CSV's per-team outline points would be an entirely separate data source, joined at the application layer by team identity rather than through the existing `Stadium` FK/table.

### Team-name mapping between this app and the CSV

Querying this app's `Team` table (`python manage.py shell`) gives all 30 current MLB team `name` values, e.g. `'Angels'`, `'Blue Jays'`, `'White Sox'`, `'Guardians'`, `'Diamondbacks'`, etc. Comparing against the CSV's 30 real-team slugs (`angels`, `blue_jays`, `white_sox`, `indians`, `diamondbacks`, ...): a straightforward `name.lower().replace(' ', '_')` transform matches the CSV slug for every team except one — Cleveland is stored here as `'Guardians'` (the 2021-adopted name) while the CSV's slug is the older `indians`, indicating the CSV predates that rename and has not been updated to match.

## Code References
- `baseball/static/baseball/js/game.js:40-51` — `updateDiamond()`, current ASCII/emoji diamond renderer
- `baseball/static/baseball/js/game.js:179-193` — `handlePlay()`, calls `updateScoreboard` (and thus `updateDiamond`) after every roll
- `baseball/static/baseball/js/game.js:274-282` — initial diamond render from the `#diamond` element's `data-bases` attribute on page load
- `baseball/templates/baseball/game_detail.html:57-63` — `<div id="diamond">` markup and its `data-half`/`data-bases` attributes
- `baseball/models.py:10-24` — `Stadium` model (unmanaged, descriptive fields only, no shape data)
- `baseball/models.py:27-47` — `Team` model, `stadium` FK
- `baseball/models.py:260-263` — `Game.home_team` FK to `Team`
- `baseball/migrations/0006_seed_stadiums_teams.py` — where `Team`/`Stadium` rows are seeded

## Architecture Documentation

Field/diamond rendering today is a single client-side JS function operating on small pieces of server-rendered state (which bases are occupied), re-invoked after every play via the same `handlePlay`/`updateScoreboard` pipeline used for score, outs, and batter updates — there is no server-side image generation or static per-team graphics anywhere in the app. All static assets currently shipped are JS and audio; there is no image/SVG directory convention established yet in `baseball/static/baseball/`.

## Related Research
None found in `thoughts/shared/research/` — the two existing docs (`2026-06-16-todo-app-architecture-map.md`, `2026-06-25-baseball-web-route.md`) don't cover field rendering or the `Team`/`Stadium` models.

## Open Questions
- The CSV's coordinate transform (`STADIUM_SCALE`, center `(125, 199)`) is calibrated to match MLBAM Statcast hit coordinates for overlaying batted-ball data — whether that exact transform is needed for a pure outline display (vs. any transform that fits the target SVG viewBox) wasn't tested here, only read from source.
- Only `plot_stadium` was inspected in `pybaseball/plotting.py`; other functions in that file (`spraychart`, `plot_strike_zone`) weren't examined for anything relevant beyond confirming they build on `plot_stadium`.
