---
date: 2026-07-23T10:11:01-04:00
researcher: Claude
git_commit: 67153d711d743e4175e9744f18444e8265c12e79
branch: main
repository: baseball-web
topic: "Per-inning scoreboard, visual effects, sounds, animated runners, crowd imagery, and streaky-player mechanics"
tags: [research, codebase, engine, models, views, templates, game.js, stadiums, multiplayer]
status: complete
last_updated: 2026-07-23
last_updated_by: Claude
---

# Research: Per-inning scoreboard, visual effects, sounds, animated runners, crowd imagery, and streaky-player mechanics

**Date**: 2026-07-23T10:11:01-04:00
**Researcher**: Claude
**Git Commit**: 67153d711d743e4175e9744f18444e8265c12e79
**Branch**: main
**Repository**: baseball-web

## Research Question
Map the current codebase state relevant to six planned additions: (1) a per-inning scoreboard, (2) visual effects, (3) sounds, (4) animating runners, (5) crowd imagery around the field, (6) a "streaky player" whose chance of a positive outcome improves substantially. Document what exists today for each area.

## Summary
This is a Django app (`baseball/`) that simulates a baseball game server-side and renders it with server-rendered templates + a single vanilla-JS file (`baseball/static/baseball/js/game.js`) that polls/POSTs a JSON API. Findings per requested feature:

1. **Per-inning scoreboard**: Does not exist. Only cumulative `away_score`/`home_score` totals are tracked anywhere (`GameState` in `engine.py`, mirrored into `Game.state` JSON and displayed in `game_detail.html`). No runs-by-inning array/grid exists in any model, the engine, or templates. The only per-inning-tagged data is the play log, where each play dict carries `play_inning`/`play_half` used solely to flag "extra innings" in the play-by-play list.
2. **Visual effects**: None exist. No CSS `@keyframes`/`transition`/`animation` rules anywhere in the baseball app. The only "animation" in the codebase is SortableJS's built-in drag-reorder effect on roster-setup pages (unrelated to live gameplay).
3. **Sounds**: A working but minimal system exists — three `.wav` files (`baseball/static/baseball/sounds/{1,5,10}.wav` = play-ball/home-run/win), loaded as JS `Audio` objects (`sfx` in `game.js`), triggered on home run, game win, and (autoplay mode only) game start. A separate, unused `SOUND_MAP` constant exists in `params.py` but is dead code.
4. **Animating runners**: Runners are shown as three SVG `<circle>` "base markers" on the diamond that instantly toggle an `occupied` CSS class (gray → yellow fill). No movement/transition animation — it's a static color swap. Client-side `sleep()`-based delays (900–1400ms) pace state updates between plays but don't animate anything visually.
5. **Crowd imagery**: Does not exist. The "stadium" is an inline SVG line-drawing (green/tan flat-color polygons for outfield/infield/foul lines) generated server-side from per-team point data in `baseball/data/stadiums.json`. No raster images, no crowd/seating/sky art anywhere in the repo's static trees (the only image asset present, `static/images/exploits_of_a_mom.png`, is unrelated — used in a SQL-injection demo page).
6. **Streaky player**: Does not exist. The most recent related work ("stat-based rolls", commit `c96c3d8`) makes at-bat outcomes draw from a batter's **static career stats** (`PlayerCareerStats` model) once they clear a 200-AB threshold, replacing a fixed 2d6 dice-table lookup. This is a fixed, non-dynamic probability distribution recomputed identically every at-bat — there is no in-game "hot/cold streak" state, no momentum/form field on any model, and no mechanism anywhere that adjusts a player's odds based on recent performance within a game.

## Detailed Findings

### 1. Score tracking / per-inning scoreboard

- `GameState` (`baseball/engine.py:11-31`) stores only two score fields: `self.away_score = 0`, `self.home_score = 0` (`engine.py:27-28`), mutated via `add_runs(runs)` (`engine.py:50-54`), which adds to whichever side is currently batting (`self.half`).
- `Game.state_to_dict`/`state_from_dict` (`baseball/models.py:289-319`) serialize/deserialize `GameState` (including `away_score`/`home_score`) into the `Game.state` `JSONField` (`models.py:279`). No other score-shaped field exists on `Game`.
- `_state_snapshot(gs)` (`baseball/views.py:123-138`) — the per-play state dict sent to the frontend — exposes `inning, half, outs, balls, strikes, bases, away_score, home_score, batting_team, current_batter, game_over, away_name, home_name`. No per-inning runs array.
- Each play dict built in `_advance_game` (`baseball/views.py:141-191`) captures `play_inning`/`play_half` **before** mutating state (`views.py:143-145`), purely so `GameDetailView.get_context_data` (`views.py:518-527`) can flag plays where `play_inning > total_innings` as "extra innings" for the play-by-play log — this is not aggregated into any runs-per-inning structure.
- `game_detail.html:71-106` renders the "Scoreboard" card: header shows `Top`/`Bottom` + `Inning N/{{ total_innings }}` (`sb-half`, `sb-inning`), then a two-row list showing each team's name + batting indicator + cumulative score (`sb-away-score`/`sb-home-score`). This is the entirety of score display — no line-score grid (no per-inning column table, no hits/errors columns; hits/errors aren't tracked anywhere either).
- `game_list.html:37` also shows only the cumulative `{{ g.state.away_score }} – {{ g.state.home_score }}` in the games list.
- Half-inning/inning transitions (when `outs >= 3`, walk-off checks, extra innings) are handled in `_advance_game` (`baseball/views.py:160-190`), calling `gs.reset_half()` (`engine.py:56-59`, zeroes outs/count/bases) or incrementing `gs.inning`/flipping `gs.half`.

### 2. Visual effects

- No CSS `@keyframes`, `transition`, or `animation` declarations exist anywhere under `baseball/templates/` or `baseball/static/` (confirmed by repo-wide search).
- All baseball-specific CSS is a single inline `<style>` block in `game_detail.html:5-13` — seven static-fill-color rules for field polygons and the base-marker circle (no transitions attached).
- All non-field chrome (cards, buttons, alerts, layout) comes from Bootstrap 5.3.3 loaded via CDN in `templates/base.html:6,67` — no custom effect layer on top of it.
- The only "animation" property in the codebase is SortableJS's built-in `animation: 150` drag-reorder config, used on the batting-order drag-and-drop lists in `game_setup.html:124`, `game_roster.html:75`, `game_join.html:72` (roster-setup pages, not the live game view).
- Client-side pacing in `game.js` (`sleep(ms)` at `game.js:176`, used in `handlePlay` at `game.js:178-192`) inserts 900–1400ms delays between DOM state updates (longer after home runs) plus a further 600ms after a half-inning ends — this is timing/sequencing, not a rendered visual effect (no particles, flashes, screen shake, etc.).

### 3. Sounds

- Audio files: `baseball/static/baseball/sounds/1.wav` (play-ball), `5.wav` (home run), `10.wav` (win) — no other formats/files.
- `game_detail.html:28-30` injects their static URLs as JS globals `SOUND_PLAY`, `SOUND_HR`, `SOUND_WIN`.
- `game.js:6-17` builds `sfx = { play_ball: new Audio(...), home_run: new Audio(...), win: new Audio(...) }` and a `playSound(key)` helper (resets `currentTime`, calls `.play()`, swallows rejection).
- Trigger points: `playSound('home_run')` in `handlePlay` when `play.outcome === 'home_run'` (`game.js:186`); `playSound('win')` in `showGameOver` (`game.js:134`), fired in every game mode on completion; `playSound('play_ball')` once at the start of autoplay mode's click handler (`game.js:252`). No sound plays for singles/doubles/triples/strikeouts/walks/outs, and no sound on manual roll/click/CPU-auto modes at game start.
- `baseball/params.py:123-127` defines an unused `SOUND_MAP = {"play_ball": "1.wav", "home_run": "5.wav", "win": "10.wav"}` — not referenced by any view or template; the actual runtime sound paths are the hardcoded `{% static %}` tags in `game_detail.html:28-30`, independent of this constant.
- No `<audio>` HTML tags exist in any template — all playback is JS-driven via the `Audio` objects above.

### 4. Animating runners / base display

- Base occupancy is shown via three SVG `<circle>` elements (`base-marker-1`, `-2`, `-3`) positioned at per-stadium coordinates (`stadium.bases.first_base/second_base/third_base`, from `baseball/stadiums.py:21-35` / `baseball/data/stadiums.json`), rendered in `game_detail.html:52-60`.
- `updateDiamond(bases)` (`game.js:40-44`) does `document.getElementById('base-marker-N').classList.toggle('occupied', !!bases[i])` for each of the three markers. The `.occupied` CSS class (`game_detail.html:12`) simply swaps `fill` from `#e8e8e8` to `#ffd400` — no transition property, so the swap is instantaneous, not animated.
- Initial page load: server renders `data-bases="{{ game.state.bases|join:',' }}"` on `#diamond` (`game_detail.html:43`); `game.js:297-305` parses that string into booleans and calls `updateDiamond` once on load.
- After each play, `updateScoreboard(state)` (`game.js:21-38`) calls `updateDiamond(state.bases)` (`game.js:37`).
- Runner *advancement logic* (which base a runner moves to) lives entirely server-side in `advance_runners(bases, n)` and `walk_runners(bases)` (`baseball/engine.py:75-107`) — these just compute the new `bases` boolean array; there is no concept of an individual runner identity or path, only aggregate base occupancy. No collision detection between runners is performed (`advance_runners` sets each destination independently, per the engine analysis).
- No runner icon/sprite graphics exist — occupancy is color-only, no images.

### 5. Crowd / stadium imagery

- `baseball/stadiums.py` (36 lines) loads `baseball/data/stadiums.json` at import time and exposes `stadium_context(team)` (`stadiums.py:21-35`), which converts a `Team` into template-ready SVG data: `name`, `viewbox`, `marker_radius`, `segments` (six point-list arrays turned into SVG `points=` strings: `outfield_outer/inner`, `infield_outer/inner`, `foul_lines`, `home_plate`), and `bases` coordinates.
- `TEAM_SLUGS` (`stadiums.py:7-18`) maps the 30 MLB team display names to slugs used to key into the JSON (falls back to a `"generic"` entry if unmatched).
- `game_detail.html:44-61` renders this purely as inline SVG `<polygon>`/`<polyline>`/`<circle>` shapes, colored via the flat-fill CSS in `game_detail.html:6-11` (green outfield/infield grass, tan infield dirt, white foul lines/home plate). `stadium.name` appears as plain header text (`game_detail.html:39`).
- `baseball/data/stadiums.json` was generated by the offline, non-runtime script `hack/generate_stadium_data.py`, which pulls raw boundary-point CSV data from pybaseball's `mlbstadiums.csv` (via `urllib.request`) and computes SVG polygon points + derived base coordinates (`derive_bases`, `hack/generate_stadium_data.py:58-98`) using real-world basepath-foot ratios. No park-factor (statistical run-scoring) data is produced — output is purely geometric.
- No crowd, seating, sky, or any photographic/raster ballpark imagery exists anywhere in the repo. The only image file in any `static/` tree is `static/images/exploits_of_a_mom.png`, referenced solely by `manage/templates/manage/sqli_demo.html:91` (a SQL-injection demo page in the unrelated `manage` app) — not used by the baseball game at all.

### 6. Streaky player / stat-based outcome mechanics

- Current outcome resolution (`baseball/engine.py:305-325`, `resolve_dice_roll`): rolls two d6 for display, then either draws from `stat_weights` (if supplied) via `weighted_choice` (`engine.py:69-72`) or falls back to a fixed `(min_die, max_die) → outcome` lookup, `DICE_TABLE` (`baseball/params.py:75-99`).
- `stat_based_weights(row)` (`engine.py:283-302`) converts a batter's **career** counting stats (`at_bats, hits, doubles, triples, home_runs, walks, strikeouts`) into an outcome-weight dict (`walk`, `strikeout`, `single`, `double`, `triple`, `home_run`, `groundout`, `flyout`, `sacrifice`), splitting leftover in-play outs via fixed ratios `STAT_OUT_SPLIT = {"groundout": 0.55, "flyout": 0.43, "sacrifice": 0.02}` (`params.py:120`).
- Gate: `_career_weights_for(player_id)` (`baseball/views.py:63-72`) queries the batter's `PlayerCareerStats` row and only returns computed weights if `at_bats >= STAT_BASED_MIN_AB` (`params.py:115`, value `200`); otherwise returns `None` and the batter falls back to the fixed dice table.
- `_advance_game` (`views.py:141-158`) calls `weights = _career_weights_for(pid)` then `resolve_dice_roll(gs, stat_weights=weights)` **fresh on every at-bat** — the same career-derived (or dice-table) distribution is used every time a given batter comes up; nothing in this path varies based on how that batter has performed earlier in the current game.
- `method = "stat" if weights is not None else "dice"` (`views.py:156`) is recorded per play and surfaced to the frontend (shown in the play log as 🎲 vs 📊, `game_detail.html:155-173`), but this only communicates *which mechanism* produced the outcome, not any streak state.
- `Player` model (`baseball/models.py:50-96`) has no streakiness/momentum/form/hot-cold field. `PlayerCareerStats` (`models.py:170-198`) holds only season-aggregate career counters. `GameStat` (`models.py:328-353`) holds only cumulative within-game counting stats (`ab`, `singles`, `doubles`, etc. plus computed `hits`/`line` properties) — nothing that feeds back into `_career_weights_for` or `resolve_dice_roll`.
- One unrelated special-case precedent exists for "always positive outcome": the hardcoded player "Tushy Scar" (`views.py:147-151`, migration `0010_add_tushy_scar.py`) bypasses rolling entirely and always resolves to a home run (`d1, d2` hardcoded to `6, 6`) — this is a permanent per-player override, not a dynamic in-game streak, but is the closest existing precedent in the codebase for "a specific named player's outcome is forced/boosted."
- The alternate per-pitch resolver (`resolve_action`/`cpu_batter_action`/`resolve_swing`, `engine.py:110-133,328-361`, driven by `params.py`'s `PITCH_TYPES`/`CONTACT_PROB`/`OUTCOME_WEIGHTS`) is fully implemented but **not called from any view** — it's dead/unused code from an earlier design, confirmed by grep showing no references outside `engine.py` itself.
- Thoughts doc `thoughts/shared/plans/2026-07-21-stat-based-at-bat-outcomes.md` is the implementation plan for the current static stat-based system; it does not describe or plan any dynamic hot/cold streak mechanic.

## Code References
- `baseball/engine.py:11-31` — `GameState` fields (scores, bases, outs, inning/half, lineup indices)
- `baseball/engine.py:50-54` — `add_runs()`, only cumulative score mutation
- `baseball/engine.py:56-59` — `reset_half()`, zeroes outs/count/bases per half-inning
- `baseball/engine.py:69-72` — `weighted_choice()`, single-draw random outcome selector
- `baseball/engine.py:75-107` — `advance_runners()` / `walk_runners()`, base-occupancy mutation
- `baseball/engine.py:283-302` — `stat_based_weights()`, converts career stats to outcome weights
- `baseball/engine.py:305-325` — `resolve_dice_roll()`, main outcome-resolution entry point
- `baseball/engine.py:110-133,328-361` — unused alternate per-pitch resolver (`resolve_action` et al.)
- `baseball/models.py:234-325` — `Game` model, `state`/`play_log` JSON fields, (de)serialization helpers
- `baseball/models.py:170-198` — `PlayerCareerStats` model (season-aggregate stats, no streak field)
- `baseball/models.py:328-353` — `GameStat` model (within-game counters, no streak field)
- `baseball/views.py:63-72` — `_career_weights_for()`, 200-AB gate for stat-based weights
- `baseball/views.py:123-138` — `_state_snapshot()`, per-play state dict sent to frontend
- `baseball/views.py:141-191` — `_advance_game()`, one-at-bat game-loop step, `play_inning`/`play_half` tagging
- `baseball/views.py:147-151` — hardcoded "Tushy Scar" always-home-run special case
- `baseball/views.py:468-528` — `GameDetailView`, main scoreboard page context building
- `baseball/views.py:518-527` — extra-innings flagging in play-by-play list (only per-inning-aware logic)
- `baseball/views.py:531-558` — `RollView`, one-at-bat POST endpoint incl. multiplayer turn check
- `baseball/params.py:75-99` — `DICE_TABLE`, fixed 2d6 outcome lookup
- `baseball/params.py:115` — `STAT_BASED_MIN_AB = 200`
- `baseball/params.py:120` — `STAT_OUT_SPLIT` ratios
- `baseball/params.py:123-127` — unused `SOUND_MAP` constant
- `baseball/stadiums.py:7-18` — `TEAM_SLUGS` mapping
- `baseball/stadiums.py:21-35` — `stadium_context()`, SVG template-data builder
- `baseball/data/stadiums.json` — per-team SVG geometry data (generated, not statistical)
- `hack/generate_stadium_data.py:58-98` — `derive_bases()`, geometric base-coordinate derivation
- `baseball/static/baseball/js/game.js:6-17` — `sfx`/`playSound()`, sound playback
- `baseball/static/baseball/js/game.js:21-44` — `updateScoreboard()`/`updateDiamond()`, DOM sync for score/bases
- `baseball/static/baseball/js/game.js:176-192` — `sleep()`/`handlePlay()`, timing between play updates
- `baseball/static/baseball/js/game.js:265-284` — `initMultiplayer()`, 4s reload-polling for turn sync
- `baseball/templates/baseball/game_detail.html:5-13` — inline field/base-marker CSS (no transitions)
- `baseball/templates/baseball/game_detail.html:37-65` — stadium/diamond SVG markup
- `baseball/templates/baseball/game_detail.html:71-106` — scoreboard card markup (totals only, no per-inning grid)
- `baseball/templates/baseball/game_detail.html:28-30` — sound file URL globals

## Architecture Documentation

**Rendering model**: Server-rendered Django templates on initial load (`GameDetailView.get_context_data`, `views.py:484-528`); subsequent updates come from JSON POST responses (`RollView`, `SimulateView`) consumed by `game.js`, which patches specific DOM elements by id (`updateScoreboard`, `updateDiamond`, `showDice`, `appendPlay`, `showGameOver`) rather than re-rendering server-side HTML. No client-side templating framework or build step is used — `game.js` is a single hand-written vanilla-JS file.

**State persistence**: All live game state lives in one `Game.state` `JSONField`, round-tripped through a `GameState` Python object (`baseball/engine.py`) via `Game.state_to_dict`/`state_from_dict` (`models.py:289-319`). There is no separate `Inning`, `AtBat`, or `Play` relational model — the append-only `Game.play_log` JSON list is the only per-play historical record.

**Multiplayer**: Implemented without any real-time push infrastructure (no Django Channels/WebSockets — confirmed absent from `INSTALLED_APPS`, `asgi.py`, and `requirements.txt`). Turn sync uses the same `location.reload()`-every-4-seconds polling pattern used elsewhere in the app, gated by a server-side turn check in `RollView` (`views.py:539-544`) comparing the requesting user's assigned side against `gs.half`.

**Outcome-resolution layering**: Two parallel resolver paths exist in `engine.py` — the dice-table/stat-weighted `resolve_dice_roll()` path (actually wired into `views.py` and used at runtime) and a fuller per-pitch `resolve_action()`/`cpu_batter_action()`/`resolve_swing()` path (fully coded, driven by `PITCH_TYPES`/`CONTACT_PROB`/`OUTCOME_WEIGHTS` in `params.py`, but never invoked by any view).

## Historical Context (from thoughts/)
- `thoughts/shared/plans/2026-07-21-stat-based-at-bat-outcomes.md` — implementation plan for the current static career-stat-weighted outcome system (the "stat-based rolls" commit); includes a checklist item confirming dice still visually roll/display and sound cues still fire, but describes no dynamic streak mechanic.
- `thoughts/shared/research/2026-07-20-pybaseball-stadium-rendering.md` — research behind replacing a placeholder diamond with the real per-team SVG stadium outline sourced from pybaseball's `mlbstadiums.csv`; also references the three existing sound asset files.
- `thoughts/shared/plans/2026-07-20-stadium-outline-rendering.md` — companion implementation plan for the stadium SVG rendering (matches current `stadiums.py`/`stadiums.json` state).
- `thoughts/shared/research/2026-06-25-baseball-web-route.md` — research on porting a CLI baseball game to this Django web route; documents the original `nava`-based desktop `play_sound`/`SOUND_MAP` audio design that was reproduced in-browser as `Audio` objects.
- `thoughts/shared/plans/2026-06-25-baseball-web-game.md` — main web-game implementation plan; Phase 5 ("JavaScript + Sound") covers the `.wav` file placement and `sfx`/`playSound()` design matching the current `game.js`.
- `thoughts/shared/plans/2026-06-29-baseball-game-stats.md` — per-game batting stats plan; notes home-run sound plays alongside stat-line UI additions.
- `thoughts/shared/plans/2026-07-20-multiplayer-mode.md` — multiplayer plan; explicitly documents the decision to avoid WebSockets/Channels and reuse `location.reload()` polling (lines 36-39, 102-103 of that doc), plus the `RollView` turn-check design that matches current `views.py:539-544`.
- `thoughts/shared/plans/2026-07-20-two-page-game-setup.md`, `thoughts/shared/plans/2026-06-29-baseball-batting-order-dragdrop.md` — Sortable.js drag-and-drop batting-order plans (UI setup animation only, unrelated to live-game visual effects).
- `thoughts/shared/plans/2026-06-25-baseball-team-selection.md` — plan wiring real team names into the scoreboard/game list (matches current cumulative-score-only display).

No thoughts document discusses a per-inning line-score grid, crowd visuals/imagery, gameplay visual effects beyond sound cues, or a dynamic hot/cold "streaky player" mechanic — these six requested features are all net-new relative to existing code and existing plans.

## Related Research
- `thoughts/shared/research/2026-07-20-pybaseball-stadium-rendering.md`
- `thoughts/shared/research/2026-06-25-baseball-web-route.md`

## Open Questions
- None identified as blocking — this document covers current-state facts only, per the requested scope.
