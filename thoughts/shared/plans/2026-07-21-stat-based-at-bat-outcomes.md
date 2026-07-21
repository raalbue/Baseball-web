# Stat-Based At-Bat Outcomes Implementation Plan

## Overview

Make at-bat resolution use a batter's real career stats (from `player_career_stats`)
when he has a big enough sample, instead of the fixed universal dice table. A batter
with < 200 career at-bats (or no career-stats row at all) keeps today's behavior
exactly: a 2d6 roll against the static `DICE_TABLE`.

## Current State Analysis

- `resolve_dice_roll(state)` (`baseball/engine.py:283`) rolls 2d6, looks up
  `DICE_TABLE` (`baseball/params.py:75`) keyed on the sorted die pair, and applies
  the same fixed odds for every batter in every game.
- The engine has **no notion of batter identity**. `lineup_from_roster()`
  (`baseball/views.py:92`) reduces the roster to a bare list of names;
  `GameState.current_batter` (`baseball/engine.py:39`) is just a string. The real
  `player_id` only re-enters the picture after the fact, via `_pid_for_name()`
  (`baseball/views.py:33`), purely to update `GameStat` rows.
- `_advance_game(gs)` (`baseball/views.py:128`) special-cases the batter name
  `"Tushy Scar"` (forced home run), then calls `resolve_dice_roll(gs)` for
  everyone else, uniformly.
- `weighted_choice(weights: Dict[str, int])` (`baseball/engine.py:69`) already
  exists and is used today to pick from `OUTCOME_WEIGHTS` (`baseball/params.py:42`).
  It wraps `random.choices`, which **normalizes weights itself** — raw counts can
  be passed directly, no percentage math required.
- `PlayerCareerStats` (`baseball/models.py`) has one row per player:
  `at_bats, hits, doubles, triples, home_runs, walks, strikeouts, stolen_bases`
  (plus `runs`, `rbis`, unused here). 1471 of 1695 players have a row; 224 do not
  (never matched a `dataid` in the source CSV).
- **No groundout/flyout/sacrifice split exists anywhere in the data.** The
  Retrosheet source had `b_sh`/`b_sf` columns but they were never imported
  (`baseball/migrations/0012_seed_stats_from_batting.py`). Real per-batter
  groundout-vs-flyout rates are not derivable from what's in the DB.
- `_advance_game` is called from exactly two places:
  `RollView.post` (`baseball/views.py:528`) and `SimulateView.post`
  (`baseball/views.py:552`). Both already compute
  `roster = game.away_roster if <top-half check> else game.home_roster` right
  after the call, to resolve `play["batter"]` → `player_id` for `GameStat`
  bookkeeping. That same roster is exactly what's needed to resolve the batter's
  `player_id` *before* the call too.

### Key Discoveries
- No model or migration changes are needed — `game.away_roster`/`home_roster`
  already carry `player_id` per lineup slot, and `player_career_stats` already
  exists and is populated.
- `weighted_choice` already returns exactly the outcome vocabulary
  (`walk, single, double, triple, home_run, strikeout, groundout, flyout,
  sacrifice`) that `apply_walk`/`apply_strikeout`/`apply_in_play`
  (`baseball/engine.py:246,256,169`) already know how to apply — no new
  "apply" logic needed, only a new way to pick the outcome key.
- The weight total for any qualifying row is always `at_bats + walks`, which is
  always > 0 for `at_bats >= 200` — no divide-by-zero / empty-weights guard
  needed in `stat_based_weights`.

## Desired End State

- A batter with a `player_career_stats` row and `at_bats >= 200` has his
  at-bat outcome drawn from a weighted distribution built from his own career
  counts (walks, strikeouts, 1B/2B/3B/HR rates, and a fixed-ratio split of his
  remaining in-play outs into groundout/flyout/sacrifice).
- A batter with `at_bats < 200`, or no career-stats row, resolves exactly as
  today: 2d6 vs. `DICE_TABLE`.
- Dice are still rolled and displayed/animated for **every** at-bat (cosmetic),
  regardless of which path decided the outcome — no frontend changes needed.
- Verify by: simulating many at-bats for a real high-AB player and a real
  low-AB player back-to-back and confirming their outcome-frequency profiles
  diverge in the expected direction (see Phase 3).

## What We're NOT Doing

- **No pitcher stats.** Only the batter's career line matters, matching today's
  engine (which has no pitcher-stat concept at all) and confirmed out of scope.
  Pitching stats aren't even imported into `player_career_stats` yet.
- **No small-sample shrinkage/regression toward league average.** Raw career
  counts are used as-is, even for a batter just over the 200 AB line. Accepted
  as realistic small-sample flavor per decision.
- **No real per-batter groundout/flyout/sacrifice split.** Filled with a fixed
  ratio applied to every qualifying batter's leftover in-play outs, since the
  underlying data doesn't exist.
- **No UI/dice-display changes.** Dice keep rolling and animating for every
  at-bat; the numbers just don't drive the outcome when stat-based weights are
  used.
- **No changes to `GameState` persistence** (the JSON blob on `Game.state`) —
  this feature reads `player_career_stats` fresh each at-bat, nothing new to
  serialize.
- **No caching of career stats across at-bats within a game.** One extra
  `PlayerCareerStats` lookup per at-bat is negligible (a few thousand rows,
  PK-adjacent lookup by `player_id`); not worth the complexity.

## Implementation Approach

Keep `engine.py` framework-agnostic (it has zero Django imports today and should
stay that way): it gains a pure function that turns a plain dict of career
counts into a weights dict, and `resolve_dice_roll` grows an optional
`stat_weights` parameter so the outcome key can come from `weighted_choice`
instead of `DICE_TABLE` — dice are still rolled either way. `views.py` becomes
the only place that touches the DB: it resolves the current batter's
`player_id` from the roster (reusing `_pid_for_name`, already used for
`GameStat`), looks up his `PlayerCareerStats` row, and decides which path to
use.

---

## Phase 1: Engine — stat-based outcome selection

### Overview
Add the pure, DB-free pieces: constants for the threshold and out-split ratio,
a function that builds a weights dict from career counts, and an optional
parameter on `resolve_dice_roll` to use those weights instead of `DICE_TABLE`.

### Changes Required

#### 1. `baseball/params.py`
**Changes**: add the threshold and the fixed out-type split (sums to 1.0).

```python
# Minimum career at-bats before stat-based outcome resolution kicks in;
# below this, the fixed dice table is used (small-sample fallback).
STAT_BASED_MIN_AB = 200

# No per-batter groundout/flyout/sacrifice split exists in the imported data
# (Retrosheet b_sh/b_sf were never loaded); split each batter's leftover
# in-play outs by this fixed ratio instead.
STAT_OUT_SPLIT = {"groundout": 0.55, "flyout": 0.43, "sacrifice": 0.02}
```

#### 2. `baseball/engine.py`
**Changes**: add `stat_based_weights`, extend `resolve_dice_roll` with an
optional `stat_weights` param.

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, STAT_OUT_SPLIT,
)


def stat_based_weights(row: Dict[str, int]) -> Dict[str, int]:
    """
    Build a {outcome: weight} dict from a batter's career counting stats.

    :param row: dict with at_bats, hits, doubles, triples, home_runs,
                walks, strikeouts (extra keys ignored).
    """
    singles = row["hits"] - row["doubles"] - row["triples"] - row["home_runs"]
    in_play_outs = row["at_bats"] - row["hits"] - row["strikeouts"]
    return {
        "walk": row["walks"],
        "strikeout": row["strikeouts"],
        "single": singles,
        "double": row["doubles"],
        "triple": row["triples"],
        "home_run": row["home_runs"],
        "groundout": round(in_play_outs * STAT_OUT_SPLIT["groundout"]),
        "flyout": round(in_play_outs * STAT_OUT_SPLIT["flyout"]),
        "sacrifice": round(in_play_outs * STAT_OUT_SPLIT["sacrifice"]),
    }
```

Modify `resolve_dice_roll`:

```python
def resolve_dice_roll(state: GameState, stat_weights: Dict[str, int] = None) -> Tuple[int, int, str, str]:
    """Roll 2d6 (always, for display), then either look up DICE_TABLE by the
    die pair or — when stat_weights is given — draw the outcome from the
    batter's own career-stat weights. Applies the event to state.

    Returns (d1, d2, outcome_key, play_message).
    """
    d1, d2 = roll_dice()
    if stat_weights is not None:
        outcome = weighted_choice(stat_weights)
    else:
        outcome = DICE_TABLE[(min(d1, d2), max(d1, d2))]
    if outcome == "walk":
        msg, _ = apply_walk(state)
    elif outcome == "strikeout":
        msg, _ = apply_strikeout(state)
    elif outcome == "sacrifice":
        msg, _ = apply_sacrifice(state)
    else:
        msg, _ = apply_in_play(state, outcome)
    return d1, d2, outcome, msg
```

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] `stat_based_weights` produces the expected dict for known counts:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.engine import stat_based_weights; w = stat_based_weights({'at_bats':500,'hits':150,'doubles':30,'triples':5,'home_runs':20,'walks':50,'strikeouts':100}); assert w['single']==95 and w['double']==30 and w['triple']==5 and w['home_run']==20 and w['walk']==50 and w['strikeout']==100; assert w['groundout']+w['flyout']+w['sacrifice']==round(250*0.55)+round(250*0.43)+round(250*0.02); print('weights ok', w)"`
- [x] `resolve_dice_roll` still works with no `stat_weights` (existing dice path unchanged):
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.engine import GameState, resolve_dice_roll; gs = GameState('A','B',3); d1,d2,outcome,msg = resolve_dice_roll(gs); assert outcome in {'walk','single','double','triple','home_run','strikeout','groundout','flyout','sacrifice'}; print('dice path ok', outcome)"`
- [x] `resolve_dice_roll` with `stat_weights` only ever returns outcomes present in the weights dict:
      `./venv/Scripts/python.exe manage.py shell -c "
from baseball.engine import GameState, resolve_dice_roll, stat_based_weights
w = stat_based_weights({'at_bats':500,'hits':150,'doubles':30,'triples':5,'home_runs':20,'walks':50,'strikeouts':100})
seen = set()
for _ in range(500):
    gs = GameState('A','B',3)
    _,_,outcome,_ = resolve_dice_roll(gs, stat_weights=w)
    seen.add(outcome)
assert seen <= set(w.keys())
print('stat path ok', seen)
"`

#### Manual Verification:
- None for this phase (pure functions, fully covered by automated checks).

**Implementation Note**: After automated checks pass, proceed directly to
Phase 2 (no manual step needed for pure engine code).

---

## Phase 2: Wiring — pick the batter's stats, choose the path

### Overview
Resolve the current batter's `player_id` from the roster before calling
`resolve_dice_roll`, look up his career row, and decide dice vs. stat-based.

### Changes Required

#### 1. `baseball/views.py` — imports
```python
from .engine import GameState, resolve_dice_roll, apply_in_play, stat_based_weights
from .params import STAT_BASED_MIN_AB
```
(`PlayerCareerStats` is already imported.)

#### 2. `baseball/views.py` — new helper
Add near `_stat_delta` / `_pid_for_name`:

```python
def _career_weights_for(player_id):
    """Stat-based outcome weights for a batter, or None to use the dice table."""
    if not player_id:
        return None
    row = PlayerCareerStats.objects.filter(player_id=player_id).values(
        "at_bats", "hits", "doubles", "triples", "home_runs", "walks", "strikeouts",
    ).first()
    if not row or row["at_bats"] < STAT_BASED_MIN_AB:
        return None
    return stat_based_weights(row)
```

#### 3. `baseball/views.py` — `_advance_game` gains a `roster` param
```python
def _advance_game(gs: GameState, roster) -> dict:
    # Capture before any mutation so play-log labels show the inning/half of the play.
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter

    if batter == "Tushy Scar":
        d1, d2 = 6, 6
        msg, _ = apply_in_play(gs, "home_run")
        outcome = "home_run"
    else:
        pid = _pid_for_name(roster, batter)
        weights = _career_weights_for(pid)
        d1, d2, outcome, msg = resolve_dice_roll(gs, stat_weights=weights)
    gs.reset_count()
    gs.advance_lineup()
    ...  # unchanged below this point
```

#### 4. `baseball/views.py` — call sites pass `roster` in, reuse it after
`RollView.post` (`views.py:514`):
```python
        roster = game.away_roster if gs.half == "top" else game.home_roster
        play = _advance_game(gs, roster)
        pid = _pid_for_name(roster, play["batter"])
        delta = _stat_delta(play["outcome"])
        ...  # unchanged — roster/pid lines below the call are just no longer recomputed
```
(Remove the old `roster = game.away_roster if play["play_half"] == "top" else game.home_roster` line that came *after* the call — the new one before the call is equivalent, since `play_half` was always captured as `gs.half` pre-mutation.)

`SimulateView.post` (`views.py:544`), inside the `while not gs.game_over:` loop:
```python
        while not gs.game_over:
            roster = game.away_roster if gs.half == "top" else game.home_roster
            play = _advance_game(gs, roster)
            pid = _pid_for_name(roster, play["batter"])
            ...  # unchanged
```

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] `./venv/Scripts/python.exe manage.py makemigrations --check --dry-run` shows no *new* drift beyond the pre-existing unrelated `game` FK alteration
- [x] `_career_weights_for` returns `None` below threshold and for unknown ids, a dict at/above it:
      `./venv/Scripts/python.exe manage.py shell -c "
from baseball.views import _career_weights_for
from baseball.models import PlayerCareerStats
low = PlayerCareerStats.objects.filter(at_bats__lt=200).first()
high = PlayerCareerStats.objects.filter(at_bats__gte=200).first()
assert _career_weights_for(low.player_id) is None
assert _career_weights_for(999999999) is None
w = _career_weights_for(high.player_id)
assert isinstance(w, dict) and sum(w.values()) > 0
print('ok', low.player_id, high.player_id, w)
"`
- [x] A full `RollView` smoke test (existing test-client pattern from earlier sessions) still returns 200 and a valid play dict for a game with a real roster.
      Also verified `SimulateView` end-to-end (29 plays, `game_over: true`) against a disposable throwaway game.

#### Manual Verification:
- [ ] Start a `click_all` game where the home lineup includes at least one
      real ≥200-AB player (e.g. Freddie Freeman) at a known batting slot; play
      through his at-bats several times across replays/simulations and confirm
      outcomes lean toward his real tendencies (e.g. a high-AVG/high-HR guy
      shows visibly more hits/HRs than a .200 bench bat over enough trials) —
      not a strict statistical test, just a sanity read.
- [ ] Confirm dice still visually roll/animate and play sound cues normally
      for stat-based at-bats — no UI regression.
- [ ] Confirm a low-AB or unmatched player (< 200 AB or no career-stats row)
      plays exactly as before (dice table odds, unchanged feel).
- [ ] Play a full `auto_play` simulated game end-to-end without errors.

**Implementation Note**: After automated checks pass, pause here for manual
confirmation from the human before proceeding to Phase 3.

---

## Phase 3: Verification — distribution sanity check

### Overview
A lightweight script (not a permanent test) that simulates many isolated
at-bats for two real players — one high-AB, one low-AB/unmatched — and prints
outcome frequencies, to eyeball that the stat-based path actually differs from
the dice-table path in the expected direction.

### Changes Required

No production code changes. Run ad hoc via `manage.py shell`:

```python
from collections import Counter
from baseball.engine import GameState, resolve_dice_roll
from baseball.models import PlayerCareerStats
from baseball.views import _career_weights_for

high = PlayerCareerStats.objects.filter(at_bats__gte=200).order_by("-home_runs").first()
low = PlayerCareerStats.objects.filter(at_bats__lt=200).first()

for label, pid in [("high-AB", high.player_id), ("low-AB", low.player_id)]:
    weights = _career_weights_for(pid)
    counts = Counter()
    for _ in range(2000):
        gs = GameState("A", "B", 3)
        _, _, outcome, _ = resolve_dice_roll(gs, stat_weights=weights)
        counts[outcome] += 1
    print(label, pid, dict(counts))
```

### Success Criteria

#### Automated Verification:
- [x] Script runs without error and prints two distinct `Counter` distributions
      (`low-AB` should reflect `None` weights → same profile as
      `DICE_TABLE`; `high-AB` should reflect that player's real career shape,
      e.g. a high-HR player's `home_run` share is visibly larger than the
      dice-table's ~5.5%/36 baseline).
      Ran against Giancarlo Stanton (130520, 6459 AB, 472 HR, real HR rate
      6.48%) vs. player 129036 (0 logged AB, correctly fell back to `None`
      weights). Stanton's simulated HR share was 7.45% over 2000 draws —
      matches his real rate within normal sampling noise.

#### Manual Verification:
- [ ] Human eyeballs the printed distributions and confirms they look sane
      (no outcome key missing that should be present, no wildly wrong skew).

**Implementation Note**: This is the final phase; no further pause needed
after manual sign-off.

---

## Testing Strategy

### Unit-style (Phase 1):
- `stat_based_weights` against hand-computed expected dicts.
- `resolve_dice_roll` with and without `stat_weights`, asserting outcome
  vocabulary stays within the expected key set for each path.

### Integration (Phase 2):
- `_career_weights_for` threshold/fallback behavior against real DB rows.
- Existing `RollView`/`SimulateView` smoke tests (test client, force-login,
  real game with a roster) still pass with the new `_advance_game` signature.

### Manual Testing Steps:
1. Play a `click_all` game with a known ≥200-AB real player in the lineup;
   confirm the game behaves normally (dice animate, play-by-play reads
   naturally) across multiple at-bats.
2. Play a game with only low-AB/unmatched players; confirm feel is unchanged
   from before this plan.
3. Run an `auto_play` full simulation to completion, no errors.
4. Run the Phase 3 distribution script and compare a real high-HR player's
   printed `home_run` share against a low-AB player's — should differ clearly.

## Performance Considerations

One extra `PlayerCareerStats.objects.filter(player_id=...).values(...).first()`
query per at-bat (`.values()` avoids full model instantiation). Table has 1471
rows; `player_id` lookups are cheap. Negligible versus existing per-at-bat
`GameStat` upsert already on this path.

## Migration Notes

None. No schema changes — `player_career_stats` and `game.away_roster`/
`home_roster` already have everything needed.

## References

- Research: `thoughts/shared/research/2026-06-25-baseball-web-route.md` (stale
  on engine/roster details — current code diverges as noted throughout this
  plan; used only for original app-structure context)
- `baseball/engine.py:283` — `resolve_dice_roll` (extended in Phase 1)
- `baseball/engine.py:69` — `weighted_choice` (reused, unchanged)
- `baseball/params.py:75` — `DICE_TABLE`; `:42` — `OUTCOME_WEIGHTS` (precedent for weight dicts)
- `baseball/views.py:33` — `_pid_for_name`; `:92` — `lineup_from_roster`;
  `:128` — `_advance_game`; `:514` — `RollView`; `:544` — `SimulateView`
- `baseball/models.py` — `PlayerCareerStats`
- `baseball/migrations/0012_seed_stats_from_batting.py` — confirms `b_sh`/`b_sf`
  were never imported (why groundout/flyout/sacrifice can't be per-batter)
