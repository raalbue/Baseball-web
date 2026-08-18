---
date: 2026-08-17T13:49:00-04:00
researcher: Claude
git_commit: 67153d711d743e4175e9744f18444e8265c12e79
branch: main
repository: baseball-web
topic: "How at-bat outcome probability is currently calculated (2d6 dice table vs. stat-weighted), and where situational modifiers would plug in"
tags: [research, codebase, engine, params, views, outcome-resolution, probability, streaky]
status: complete
last_updated: 2026-08-17
last_updated_by: Claude
---

# Research: How at-bat outcome probability is currently calculated

**Date**: 2026-08-17T13:49:00-04:00
**Researcher**: Claude
**Git Commit**: 67153d711d743e4175e9744f18444e8265c12e79
**Branch**: main
**Repository**: baseball-web

## Research Question
How does the current system decide the outcome of an at-bat (the "roll of two dice" mechanism), where does that logic live, and what existing precedent is there in the codebase for skewing/modifying those probabilities situationally? Asked in the context of a proposal to replace the 2d6/36-combination table with a large lookup array (360 or 3600 elements) indexed by a single random draw, to allow small manual tweaks to represent things like pitcher fatigue or weather.

## Summary
There is exactly **one** outcome-resolution path wired into the live game, and it is shared by **every** `Game.mode` (`click_all`, `cpu_auto`, `auto_play`, `multiplayer`) — there is no mode-specific probability logic. It has two sub-paths, chosen per at-bat:

1. **Fixed 2d6 dice table** (`baseball/params.py:75-109`, `DICE_TABLE`/`DICE_TABLE_STREAKY`) — the default, used for any batter without enough career at-bats.
2. **Career-stat-derived integer weight dict** (`baseball/engine.py:349-368`, `stat_based_weights()`) — used once a batter clears a 200-AB threshold, fed through the *same* generic weighted-random-choice function as the dice table.

Both sub-paths ultimately call one shared primitive, `weighted_choice()` (`baseball/engine.py:117-120`), which wraps Python's `random.choices(population, weights=...)`. That function already accepts **arbitrary relative weights** (not restricted to any fixed denominator like 36, 360, or 3600) and already implements the same "cumulative distribution + single random draw" mechanism the proposal describes for a large array — it's just backed by a small dict instead of a big list.

The codebase's existing precedent for *situationally modifying* outcome odds is the "streaky batter" system (`baseball/engine.py:12-114`, `is_streaky()`/`reroll_inning_streaky()`), which multiplies the stat-weighted single/double/triple/home_run weights by 2× (`baseball/views.py:66-79`) or swaps two dice-table cells from `groundout` to `single_error` (`baseball/params.py:105-109`), depending on whether the current batter is that half-inning's/game's randomly-picked "hot" player. There is also one fully hardcoded override (`baseball/views.py:198-202`, the "Tushy Scar" special case) that bypasses probability entirely and always resolves to a home run.

## Detailed Findings

### 1. The 2d6 dice table (default path)

- `roll_dice()` (`baseball/engine.py:312-314`) rolls two independent d6 via `random.randint(1, 6)` twice — this always happens (36 raw equally-likely `(d1, d2)` outcomes), regardless of which resolution sub-path is ultimately used, because the dice are also shown in the UI.
- `DICE_TABLE` (`baseball/params.py:75-99`) is a dict keyed on `(min(d1,d2), max(d1,d2))` — i.e., 21 unique keys covering the 36 raw rolls: 6 "doubles" keys (`(1,1)`...`(6,6)`, each representing 1/36 of raw rolls) and 15 "mixed pair" keys (each representing 2/36, since e.g. `(2,5)` and `(5,2)` collapse to the same key). A comment in the file (`params.py:72-74`) states this arrangement explicitly: "Doubles (6 combos, 1/36 each)... Mixed pairs (15 combos, 2/36 each)."
- `resolve_dice_roll()` (`baseball/engine.py:371-393`) does the lookup: `table[(min(d1, d2), max(d1, d2))]` when no stat weights are supplied.
- Given the table's structure, the *implied* probability of each outcome (as a fraction of 36) is fixed by how many dice-pair keys map to it. Counting the current `DICE_TABLE` entries:

  | outcome | combos / 36 |
  |---|---|
  | strikeout | 8 |
  | groundout | 6 |
  | flyout | 6 |
  | single | 5 |
  | walk | 3 |
  | double | 3 |
  | sacrifice | 2 |
  | home_run | 2 |
  | triple | 1 |

- `DICE_TABLE_STREAKY` (`baseball/params.py:105-109`) is `DICE_TABLE` with two mixed-pair keys, `(2,4)` and `(2,6)`, overridden from `groundout` to `single_error` — i.e., when the current batter is the active streaky pick and no stat-weight path applies, 2 of the 6 groundout-mapped combos become a (still-an-at-bat, still-not-a-hit) reached-on-error single instead. `resolve_dice_roll()` picks which table to use via its `streaky: bool` parameter (`engine.py:383`).
- `DICE_EVENT_LABELS` (`baseball/params.py:111-121`) is a separate display-label dict (e.g. `"home_run": "HOME RUN"`), unrelated to probability — just used for showing the rolled outcome in the UI.

### 2. The stat-weighted path (used once a batter has enough at-bats)

- `stat_based_weights(row)` (`baseball/engine.py:349-368`) converts a batter's career counting stats (`at_bats, hits, doubles, triples, home_runs, walks, strikeouts`) into a `{outcome: integer_weight}` dict. Hits are decomposed (`singles = hits - doubles - triples - home_runs`); the remaining in-play outs (`at_bats - hits - strikeouts`) are split into `groundout`/`flyout`/`sacrifice` using fixed ratios `STAT_OUT_SPLIT = {"groundout": 0.55, "flyout": 0.43, "sacrifice": 0.02}` (`baseball/params.py:127-130`), since no batted-ball-type data was ever imported.
- `_career_weights_for(player_id, streaky=False)` (`baseball/views.py:66-79`) is the gate: it queries `PlayerCareerStats` (`baseball/models.py:170-198`), and only returns a weight dict if `at_bats >= STAT_BASED_MIN_AB` (`params.py:125`, currently `200`); otherwise returns `None`, which causes the caller to fall back to the dice table. When `streaky=True`, it doubles the `single`/`double`/`triple`/`home_run` entries in place (`views.py:76-78`) before returning.
- These weights are **not normalized to any fixed total** — they're raw career counting-stat integers (e.g. a batter with 50 career walks and 900 at-bats gets `weight["walk"] = 50` alongside `weight["strikeout"] = <their career K count>`, etc.), and `weighted_choice()` doesn't care what they sum to.

### 3. The shared weighted-choice primitive

- `weighted_choice(weights: Dict[str, int]) -> str` (`baseball/engine.py:117-120`):
  ```python
  def weighted_choice(weights: Dict[str, int]) -> str:
      """Pick a key from a {key: weight} mapping."""
      population = list(weights.keys())
      return random.choices(population, weights=[weights[k] for k in population])[0]
  ```
  This is the **only** place either sub-path (dice-table-derived or stat-derived) actually draws a random outcome from a weighted distribution once `stat_weights` is supplied; `resolve_dice_roll()` calls it at `engine.py:381` for the stat-weighted branch, and does a plain dict lookup (not a weighted draw) for the dice-table branch since the "weighting" there is already baked into how many table keys map to each outcome.
  - Python's `random.choices` internally builds a cumulative-weight list once and does a single `random.random()` draw plus a bisection against it — functionally the same "one random draw into a distribution" shape as an indexed-array approach, but the weights can be arbitrary relative numbers (ints or floats), not restricted to summing to 36, 360, 3600, or any other fixed denominator.

### 4. Where outcome resolution is invoked from (mode-agnostic)

- `_advance_game(gs, roster)` (`baseball/views.py:191-249`) is the single per-at-bat entry point. It:
  1. Special-cases the batter name `"Tushy Scar"` to always resolve `home_run` with `d1=d2=6` (`views.py:198-202`), bypassing both the dice table and stat weights entirely.
  2. Otherwise looks up `weights = _career_weights_for(pid, streaky=streaky)` and calls `resolve_dice_roll(gs, stat_weights=weights, streaky=streaky)` (`views.py:205-207`).
- `_advance_game` is called from exactly two views: `RollView.post` (`baseball/views.py:756-783`, one at-bat per POST — used by `click_all`, `cpu_auto`, and `multiplayer` modes) and `SimulateView.post` (`baseball/views.py:786-814`, loops calling it until `gs.game_over` — used by `auto_play`/replay-autoplay). Both call the exact same function with no mode-specific branching of the probability logic. `Game.mode` (`baseball/models.py:234-244`) only controls *how often/when* the client asks for a roll (click-driven vs. auto-looped vs. turn-gated for multiplayer), not which outcome-probability code path runs.

### 5. Existing precedent for situational probability modification

- **Streaky batter** (`baseball/engine.py:12-114`): `GameState` picks a random per-game streaky batter per side at game start (`streaky_game_away`/`streaky_game_home`, `engine.py:42-45`) if `streaky_per_game` is enabled, and/or rerolls a random per-inning streaky batter per side at the start of each half-inning (`reroll_inning_streaky()`, `engine.py:101-108`) if `streaky_per_inning` is enabled. `is_streaky(batter_name)` (`engine.py:110-114`) checks whether the current batter matches either active pick for the side now batting. Both flags are user-selectable at game-setup time (`Page1Form`, `baseball/forms.py:100-107`) and stored per-`Game` (`Game.streaky_per_game`/`streaky_per_inning`, `baseball/models.py:279-280`) and per-`GameState` (persisted in the `state` JSONField via `Game.state_to_dict`/`state_from_dict`, `models.py:291-341`).
- The *effect* of being streaky is applied at two points depending on which resolution sub-path is active for that batter:
  - Stat-weighted batters: `single`/`double`/`triple`/`home_run` weights ×2 (`views.py:76-78`).
  - Dice-table batters: swap to `DICE_TABLE_STREAKY`, which converts 2 of the table's `groundout` combos to `single_error` (`params.py:105-109`, `engine.py:383`).
- **Hardcoded override**: the `"Tushy Scar"` special case (`views.py:198-202`, seeded via migration `0010_add_tushy_scar.py`) is a permanent, always-on override rather than a probabilistic modifier — the closest existing precedent for "force a specific outcome," as opposed to "shift the odds."
- There is **no** concept of pitcher fatigue, weather, or day-of-game conditions anywhere in the codebase — no field on `Game`, `GameState`, or any model represents these, and no code path reads or applies such a thing. The only two things that currently vary an at-bat's odds mid-game are (a) which batter is up (career-stat weights differ per player) and (b) whether that batter is the active streaky pick.

### 6. The unused alternate per-pitch resolver

- `engine.py` also contains a second, fully-coded outcome-resolution system that is **not called from any view** (confirmed by the prior codebase research on this same repo, and still true — `resolve_action`/`cpu_batter_action`/`resolve_swing` are only referenced within `engine.py` itself):
  - `pitch_in_zone(strike_prob=STRIKE_PROB)` (`engine.py:183-185`) — single Bernoulli draw, `STRIKE_PROB = 0.50` (`params.py:30`).
  - `resolve_swing(swing_type, in_zone, contact_mod)` (`engine.py:188-205`) — looks up `CONTACT_PROB[swing_type][location]` (`params.py:35-39`, a 3×2 grid of contact chances by swing type × zone/ball) plus a per-pitch `contact_mod`, then on contact draws from `OUTCOME_WEIGHTS[swing_type]` (`params.py:42-51`, two dicts of integer weights — `contact` and `power` swings — again via the same `weighted_choice()`).
  - `cpu_batter_action(state, in_zone)` (`engine.py:396-405`) and `resolve_action(state, action, in_zone, contact_mod)` (`engine.py:408-428`) tie this together into a pitch-by-pitch (not single-roll) at-bat simulation, driven by `PITCH_TYPES` (`params.py:54-59`, 4 pitch types each with their own `strike_prob`/`contact_mod`) and `SWING_MENU` (`params.py:62-67`, the batter's 4 possible actions).
  - This is dead code relative to the live game today, but it is a second existing example (alongside `stat_based_weights`) of the codebase already representing "outcome odds" as small dicts of relative weights fed through `weighted_choice()`, rather than as a large flat array.

## Code References
- `baseball/engine.py:117-120` — `weighted_choice()`, the shared weighted-random-draw primitive (wraps `random.choices`)
- `baseball/engine.py:312-314` — `roll_dice()`, always-rolled 2d6 for display
- `baseball/engine.py:349-368` — `stat_based_weights()`, career-stats → outcome-weight dict
- `baseball/engine.py:371-393` — `resolve_dice_roll()`, the main entry point combining dice-table lookup and stat-weighted draw
- `baseball/engine.py:12-114` — `GameState`, including streaky-batter pick/reroll/check logic
- `baseball/engine.py:183-205` — unused alternate resolver: `pitch_in_zone()`, `resolve_swing()`
- `baseball/engine.py:396-428` — unused alternate resolver: `cpu_batter_action()`, `resolve_action()`
- `baseball/params.py:30-32` — `STRIKE_PROB`, `FOUL_PROB`, `DOUBLE_PLAY_PROB` (unused-path + double-play knobs)
- `baseball/params.py:35-51` — `CONTACT_PROB`, `OUTCOME_WEIGHTS` (unused alternate resolver's weight tables)
- `baseball/params.py:54-67` — `PITCH_TYPES`, `SWING_MENU` (unused alternate resolver's menus)
- `baseball/params.py:75-99` — `DICE_TABLE`, the live 21-key/36-combo lookup table
- `baseball/params.py:101-109` — `DICE_TABLE_STREAKY`, the streaky-batter dice-table variant
- `baseball/params.py:111-121` — `DICE_EVENT_LABELS`, display-only labels
- `baseball/params.py:125` — `STAT_BASED_MIN_AB = 200`, the gate for using stat weights instead of the dice table
- `baseball/params.py:127-130` — `STAT_OUT_SPLIT`, fixed groundout/flyout/sacrifice split ratios
- `baseball/views.py:66-79` — `_career_weights_for()`, the 200-AB gate + streaky-doubling
- `baseball/views.py:191-249` — `_advance_game()`, per-at-bat orchestration incl. the Tushy Scar override
- `baseball/views.py:198-202` — hardcoded always-home-run special case
- `baseball/views.py:756-783` — `RollView.post`, single-at-bat entry point (click_all/cpu_auto/multiplayer)
- `baseball/views.py:786-814` — `SimulateView.post`, looped entry point (auto_play)
- `baseball/models.py:234-244` — `Game.MODE_CHOICES`, confirms mode only affects request cadence, not probability logic
- `baseball/models.py:279-280` — `Game.streaky_per_game`/`streaky_per_inning` persisted flags
- `baseball/forms.py:100-107` — streaky checkboxes exposed at game-setup time

## Architecture Documentation

**Single resolution path, mode-agnostic**: There is one outcome-resolution function (`_advance_game` → `resolve_dice_roll`) called identically from every `Game.mode`. "Auto mode" in the user's phrasing does not correspond to a distinct code path in the current implementation — `cpu_auto`, `click_all`, `auto_play`, and `multiplayer` all resolve each at-bat through the exact same dice-table/stat-weight logic; they differ only in how the client triggers/paces `RollView`/`SimulateView` requests (`baseball/static/baseball/js/game.js:362-450`).

**Weight-dict-as-probability-representation is already the codebase's pattern**: Both the live stat-based path (`stat_based_weights`) and the dead alternate per-pitch resolver (`OUTCOME_WEIGHTS`) represent relative outcome odds as small `{outcome_name: number}` dicts consumed by one shared `weighted_choice()`/`random.choices()` call, rather than as a literal array of pre-expanded outcome slots. The 2d6 dice table is the one path that *is* array/table-like (a fixed 21-key lookup derived from 36 equally-likely raw dice combinations), and it is also the one path with no situational-modifier hook today — `DICE_TABLE_STREAKY` is a full second static copy of the table with two cells changed, not a runtime-computed variant.

**Streaky state lives on `GameState`, persisted per-game**: The only currently-implemented "conditions can shift odds mid-game" mechanism (streaky batter) stores its state (`streaky_game_away/home`, `streaky_inning_away/home`) directly on `GameState` and round-trips it through `Game.state` (a `JSONField`) via `state_to_dict`/`state_from_dict`, rather than as a separate model or a per-play override.

## Historical Context (from thoughts/)
- `thoughts/shared/plans/2026-07-21-stat-based-at-bat-outcomes.md` — implementation plan for the current stat-based outcome system (the "stat-based rolls" commit, `c96c3d8`); establishes the `stat_based_weights`/`STAT_BASED_MIN_AB`/`STAT_OUT_SPLIT` design as it exists today.
- `thoughts/shared/plans/2026-07-23-runner-animation-streaky-player.md` — implementation plan for the streaky-batter feature (per-game/per-inning random pick + weight-doubling / dice-table-swap), matching the current `GameState`/`views.py` code.
- `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md` — prior research pass covering (among other things) the streaky mechanism and confirming the alternate `resolve_action`/`cpu_batter_action` per-pitch resolver is unused/dead code; still accurate as of this commit.

## Related Research
- `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`
- `thoughts/shared/research/2026-06-25-baseball-web-route.md`

## Open Questions
- None — this document covers the current-state mechanics as requested. See the advisory note below for the specific granularity question, which was explicitly asked for.

---

## Advisory Note (explicitly requested — not part of the documentation above)

You asked directly for advice on the 360-vs-3600 granularity question, so, briefly:

`weighted_choice()`/`random.choices()` (`engine.py:117-120`) already gives you **exact, unbounded granularity** today — the weights it takes are arbitrary numbers (the stat-weighted path already passes it raw career counting stats like 247, 812, etc.), not fractions of some fixed array length. A physical 360- or 3600-element array is one specific way to implement "weighted random choice," but it's the *lower-precision* way relative to what's already running in this codebase: any percentage you could represent by dedicating N of 3600 slots to an outcome (a multiple of 1/3600 ≈ 0.0278%), you can represent *exactly* by just setting that outcome's weight in a dict — no rounding to a slot count at all, and no array to allocate/regenerate.

Concretely, "pitcher getting tired → a couple strikeout slots become walk slots" or "windy day → more home run slots" maps directly onto: take the current 9-key frequency table above (or a stat-weighted batter's dict), and multiply/add to a couple of entries — e.g. `weights["walk"] *= 1.15; weights["strikeout"] *= 0.9` for fatigue, or `weights["home_run"] *= 1.3` for wind — then hand that dict to the existing `weighted_choice()`. This is exactly the shape of adjustment the streaky-batter system already makes (`views.py:76-78`, `single/double/triple/home_run` weights ×2), just parameterized by a game/weather condition instead of a random streaky flag. No array of any size needs to be built, stored, or maintained, and the "slight modification" granularity is limited only by floating-point precision, not by how many cells you chose to carve the array into.

If you still want an explicit, hand-editable array purely because it's easier to *reason about visually* ("go change these 3 cells"), 3600 over 360 costs nothing extra at this scale (a Python list that size is trivial memory/CPU-wise) and avoids rounding collisions when representing small percentage shifts across 9-10 outcomes — but functionally it would be reproducing, at lower precision, a mechanism (`weighted_choice`) that's already sitting one call away.
