# Runner-Movement Animation and Streaky Player Implementation Plan

## Overview

Add two independent gameplay features to the live game view: (1) base runners visually slide from their origin to their destination base (or off toward home when scoring) instead of a base marker instantly changing color, and (2) a "streaky player" system with two independent setup checkboxes — a per-game random hot batter (picked once at game creation, one per side) and a per-inning random hot batter (re-picked every half-inning, one per side) — whose chance of a hit is doubled. Dice-table (non-stat) batters, who have no weights to double, get an equivalent buff while streaky: 2 of the table's 3 groundout rolls become "reaches on an error" singles.

## Current State Analysis

- Base occupancy is 3 static SVG `<circle>` markers (`base-marker-1/2/3`) that instantly toggle an `occupied` CSS class (`baseball/static/baseball/js/game.js:40-44`) — no movement, no per-runner identity, just a boolean-per-base color swap.
- Runner advancement math lives in `advance_runners()`/`walk_runners()` (`baseball/engine.py:75-107`) and inline shift logic duplicated in `apply_sacrifice()`/`apply_bunt()` (`engine.py:211-238,262-280`) — all operate on a 3-element boolean array with no origin→destination tracking.
- At-bat outcome resolution (`resolve_dice_roll()`, `engine.py:305-325`) either draws from career-stat-derived weights (`stat_based_weights()`, `engine.py:283-302`, gated on `at_bats >= STAT_BASED_MIN_AB = 200` in `baseball/views.py:63-72`) or falls back to a fixed 2d6 lookup, `DICE_TABLE` (`baseball/params.py:75-99`) — this table has 21 total combos (6 doubles + 15 mixed), of which **3** map to `"groundout"`: `(1,5)`, `(2,4)`, `(2,6)`.
- No player/model has any streak, momentum, or hot/cold field anywhere (`Player`, `PlayerCareerStats`, `GameStat` — confirmed in `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`).
- Game setup is a 4-path creation flow: `Page1View` (CPU_AUTO — creates `GameState`+`Game` directly; MULTIPLAYER — creates a `WAITING` `Game` with `state={}`, no `GameState` yet; two-page hotseat — stashes choices in `request.session["bb_setup"]`), `Page2View` (creates `GameState`+`Game` for hotseat), `Player2JoinView` (creates the real `GameState` for multiplayer once the second player joins), `ReplayView` (creates a fresh `GameState`+`Game` copying the original's settings). All 4 construct `GameState(...)` directly except the MULTIPLAYER branch of `Page1View`, which only creates the `Game` row (the `GameState` comes later in `Player2JoinView`).

### Key Discoveries:
- `baseball/stadiums.py:21-35`'s `stadium_context()` already passes through a `home_plate` point (`{x, y}`) alongside `first_base`/`second_base`/`third_base` in `stadium.bases` — needed as the animation's "batter origin" coordinate, but currently unused/unexposed in the template (only the 3 base circles read their own coords).
- `Game.state_from_dict()` (`baseball/models.py:303-319`) reconstructs `GameState` via its constructor on **every single request** (every `RollView`/`SimulateView` POST reloads state from the DB). This means any "pick a random streaky player" logic inside `GameState.__init__` must NOT fire during reconstruction, or it would re-roll a new random player on every request instead of once at game creation — the plan's `state_from_dict` change explicitly avoids passing the streaky flags to the constructor and restores the already-persisted picks as plain attribute assignment afterward.
- `_advance_game()` (`baseball/views.py:141-191`) is the single chokepoint for every at-bat across all 4 game modes (`click_all`, `cpu_auto`, `auto_play`'s loop, `multiplayer`) — both new features hook in here once and all modes get them automatically.
- `GameStat`'s `_AB_OUTCOMES`/`_HIT_STAT` split (`baseball/views.py:18-32`) already distinguishes "counts as an at-bat" from "counts as a hit" — the new `single_error` outcome slots into this existing mechanism with one line, no new stat-tracking infrastructure needed.

## Desired End State

On the live game page: every play that moves a runner shows a small token sliding along the basepath from its origin to its destination (or fading out toward home when scoring, or fading in place when forced out), with the base-marker color change synced to land when the token arrives. Game setup has two new checkboxes ("Streaky player: per game" / "per inning"); when checked, one random non-pitcher batter per side gets doubled hit-outcome weights (stat-based batters) or an improved dice-table (non-stat batters, 2 of 3 groundouts become error-reached singles) whenever they're at the plate, visibly flagged with a 🔥 in the play-by-play log.

### Verification
- `python manage.py check` passes.
- `python manage.py makemigrations --check` shows no missing migrations after the model change is migrated.
- Manually playing a game with both checkboxes on shows: a 🔥-flagged streaky batter each half-inning (and one frozen for the whole game), visibly more hits from streaky batters over several at-bats, runner tokens sliding on every hit/walk/sacrifice, and dice-table streaky batters occasionally "reaching on an error" instead of grounding out.

## What We're NOT Doing

- Not adding true per-runner identity/base-running strategy (tagging up, stealing, etc.) — the animation is a visual reconstruction from the existing deterministic (outcome, prior-bases) logic, not a new simulation layer.
- Not letting the streaky picks be limited to only the human-controlled side — both sides get independent random picks (per your choice: "each team gets its own pick").
- Not stacking effects if the same batter happens to be both the per-game and per-inning pick — `is_streaky()` is a boolean OR, always just the single doubled effect.
- Not touching the dead `resolve_action`/`cpu_batter_action`/`resolve_swing` per-pitch resolver path (`engine.py:110-133,328-361`) — confirmed unused by any view, out of scope.
- Not making the dice-table groundout→error tweak universal — it only applies when the batter is the active streaky pick (per your choice), not a general rules change for every dice-table batter.
- Not adding a database field for `single_error`'s box-score treatment beyond the existing `GameStat` columns — it increments `ab` only (via `_AB_OUTCOMES`), never `singles`, matching real baseball's "reach on error ≠ hit" scoring.

## Implementation Approach

Four phases: runner animation first since it's fully self-contained (no schema/forms changes, purely engine.py + views.py + template + JS), then the streaky-player data model and setup UI (forms, migration, threading through all 4 creation paths), then the streaky-player gameplay effect (weight doubling, dice-table swap, half-inning reroll timing) which builds on that data model, then a final verification pass.

## Phase 1: Runner-movement animation

### Overview
Reconstruct each runner's origin→destination move server-side (deterministic from the existing advance/walk/shift logic, no new simulation), send it as a transient `moves` list on the play response, and animate SVG token(s) sliding along the basepath client-side, with the base-marker color flip delayed to land when the token arrives.

### Changes Required:

#### 1. `GameState` gains a transient moves scratch-field
**File**: `baseball/engine.py`
**Changes**: In `__init__` (currently lines 14-31), add one line after `self.game_over = False`:

```python
self.last_moves = []   # transient: origin/destination of runners moved by the most recent event
```

#### 2. Extend the base-movement helpers to also report moves
**File**: `baseball/engine.py`
**Changes**: Replace `advance_runners()` (currently lines 75-92):

```python
def advance_runners(bases: List[bool], n: int) -> Tuple[List[bool], int, List[Dict[str, object]]]:
    """
    Advance all runners (and the batter) by ``n`` bases on a clean hit.
    Returns (new_bases, runs, moves) where each move is
    {"from": "batter"|1|2|3, "to": "home"|1|2|3}.
    """
    positions = [i + 1 for i in range(3) if bases[i]]
    positions.append(0)  # the batter, starting at home plate
    runs = 0
    new_bases = [False, False, False]
    moves = []
    for pos in positions:
        origin = "batter" if pos == 0 else pos
        dest = pos + n
        if dest >= 4:
            runs += 1
            moves.append({"from": origin, "to": "home"})
        else:
            new_bases[dest - 1] = True
            moves.append({"from": origin, "to": dest})
    return new_bases, runs, moves
```

Replace `walk_runners()` (currently lines 95-107):

```python
def walk_runners(bases: List[bool]) -> Tuple[List[bool], int, List[Dict[str, object]]]:
    """Force-advance runners on a walk; returns (new_bases, runs, moves)."""
    new = bases[:]
    runs = 0
    if not new[0]:
        new[0] = True
        moves = [{"from": "batter", "to": 1}]
    elif not new[1]:
        new[1] = True
        moves = [{"from": 1, "to": 2}, {"from": "batter", "to": 1}]
    elif not new[2]:
        new[2] = True
        moves = [{"from": 2, "to": 3}, {"from": 1, "to": 2}, {"from": "batter", "to": 1}]
    else:
        runs = 1  # bases loaded: runner forced home, bases stay loaded
        moves = [{"from": 3, "to": "home"}, {"from": 2, "to": 3},
                 {"from": 1, "to": 2}, {"from": "batter", "to": 1}]
    return new, runs, moves
```

Add a new shared helper right after `walk_runners()`, extracted from the duplicated sacrifice-shift logic in `apply_sacrifice()`/`apply_bunt()`:

```python
def _shift_runners_one(bases: List[bool]) -> Tuple[List[bool], int, List[Dict[str, object]]]:
    """Advance any existing runners one base each (sacrifice-style); batter doesn't move."""
    new = [False, False, False]
    runs = 0
    moves = []
    if bases[2]:
        runs += 1
        moves.append({"from": 3, "to": "home"})
    if bases[1]:
        new[2] = True
        moves.append({"from": 2, "to": 3})
    if bases[0]:
        new[1] = True
        moves.append({"from": 1, "to": 2})
    return new, runs, moves
```

#### 3. Wire the new 3-tuple returns through every caller
**File**: `baseball/engine.py`
**Changes**:

`apply_ball()` (currently lines 137-147), walk branch:
```python
if state.balls >= 4:
    state.bases, runs, moves = walk_runners(state.bases)
    state.last_moves = moves
    state.add_runs(runs)
```

`apply_in_play()` (currently lines 169-208) — full replacement:
```python
def apply_in_play(state: GameState, outcome: str) -> Tuple[str, bool]:
    """Resolve a batted ball; returns (message, at_bat_over)."""
    batter = state.current_batter
    if outcome in HIT_BASES:
        n = HIT_BASES[outcome]
        state.bases, runs, moves = advance_runners(state.bases, n)
        state.last_moves = moves
        state.add_runs(runs)
        if outcome == "single_error":
            msg = "{batter} reaches on an error!".format(batter=batter)
        else:
            names = {1: "singles", 2: "doubles", 3: "triples", 4: "homers"}
            msg = "{batter} {verb}!".format(batter=batter, verb=names[n])
        if outcome == "home_run":
            msg = "{batter} crushes a {runs}-run HOME RUN!".format(
                batter=batter, runs=runs) if runs > 1 else \
                "{batter} goes deep, SOLO HOME RUN!".format(batter=batter)
        elif runs:
            msg += " {runs} run{p} score{q}.".format(
                runs=runs, p="s" if runs > 1 else "", q="" if runs > 1 else "s")
        return msg, True

    if outcome == "groundout":
        if state.bases[0] and state.outs < 2 and random.random() < DOUBLE_PLAY_PROB:
            state.outs += 2
            state.bases[0] = False
            state.last_moves = [{"from": 1, "to": "out"}]
            return "{batter} grounds into a double play!".format(batter=batter), True
        state.outs += 1
        return "{batter} grounds out.".format(batter=batter), True

    if outcome == "flyout":
        scored = False
        if state.bases[2] and state.outs < 2:
            state.bases[2] = False
            state.add_runs(1)
            state.last_moves = [{"from": 3, "to": "home"}]
            scored = True
        state.outs += 1
        if scored:
            return "{batter} lifts a sacrifice fly, a run scores!".format(batter=batter), True
        return "{batter} flies out.".format(batter=batter), True

    state.outs += 1
    return "{batter} is out.".format(batter=batter), True
```
(Note: this also drops the pre-existing dead line `extra = state.runners_on()`, which was assigned but never read — it sat inside the block being rewritten anyway.)

`apply_bunt()` (currently lines 211-238), single-branch and sac-branch:
```python
def apply_bunt(state: GameState) -> Tuple[str, bool]:
    """Resolve a bunt put in play; returns (message, at_bat_over)."""
    batter = state.current_batter
    if random.random() < 0.25:
        state.bases, runs, moves = advance_runners(state.bases, 1)
        state.last_moves = moves
        state.add_runs(runs)
        msg = "{batter} drops a bunt single!".format(batter=batter)
        if runs:
            msg += " A run scores!"
        return msg, True
    runs = 0
    if any(state.bases):
        state.bases, runs, moves = _shift_runners_one(state.bases)
        state.last_moves = moves
        state.add_runs(runs)
    state.outs += 1
    msg = "{batter} lays down a sacrifice bunt.".format(batter=batter)
    if runs:
        msg += " A run scores!"
    return msg, True
```

`apply_walk()` (currently lines 246-253):
```python
def apply_walk(state: GameState) -> Tuple[str, bool]:
    """Award a direct walk (no count update)."""
    state.bases, runs, moves = walk_runners(state.bases)
    state.last_moves = moves
    state.add_runs(runs)
    msg = "{batter} draws a walk.".format(batter=state.current_batter)
    if runs:
        msg += " A run forces in!"
    return msg, True
```

`apply_sacrifice()` (currently lines 262-280):
```python
def apply_sacrifice(state: GameState) -> Tuple[str, bool]:
    """Batter is out; all base runners advance one base."""
    batter = state.current_batter
    runs = 0
    if any(state.bases):
        state.bases, runs, moves = _shift_runners_one(state.bases)
        state.last_moves = moves
        state.add_runs(runs)
    state.outs += 1
    msg = "{batter} hits a sacrifice.".format(batter=batter)
    if runs:
        msg += " A run scores!"
    return msg, True
```

#### 4. Reset the scratch-field once per at-bat and surface it in the play dict
**File**: `baseball/views.py`
**Changes**: In `_advance_game()` (currently lines 141-191), add `gs.last_moves = []` right after capturing `batter` (line 145):

```python
def _advance_game(gs: GameState, roster) -> dict:
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter
    gs.last_moves = []
    ...
```

Add `moves=gs.last_moves,` to both `return dict(...)` statements (the walk-off early return and the final return) in that function.

#### 5. Expose the home-plate coordinate for JS
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Inside the field `<svg>` (currently lines 44-61), add an invisible anchor circle next to the 3 existing base markers:

```html
<circle id="home-plate-marker"
        cx="{{ stadium.bases.home_plate.x }}" cy="{{ stadium.bases.home_plate.y }}"
        r="0" style="opacity:0" />
```

Extend the `<style>` block (currently lines 5-13) with the runner-token look:

```css
.runner-token {
  fill: #ff5722;
  stroke: #fff;
  stroke-width: 1;
  transition: cx 550ms ease-in-out, cy 550ms ease-in-out, opacity 550ms ease-in-out;
}
.runner-token.runner-token-fade {
  transition: cx 550ms ease-in-out, cy 550ms ease-in-out, opacity 550ms ease-in-out 350ms;
  opacity: 0;
}
```

#### 6. Animate on the client
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Add a duration constant near the top (after `const CSRF = ...`, `game.js:3-4`):

```js
const RUNNER_ANIM_MS = 550;
```

Replace `updateDiamond()` (currently `game.js:40-44`) to accept an optional delay:

```js
function updateDiamond(bases, delayMs = 0) {
    const apply = () => {
        document.getElementById('base-marker-1').classList.toggle('occupied', !!bases[0]);
        document.getElementById('base-marker-2').classList.toggle('occupied', !!bases[1]);
        document.getElementById('base-marker-3').classList.toggle('occupied', !!bases[2]);
    };
    if (delayMs > 0) setTimeout(apply, delayMs); else apply();
}
```

In `updateScoreboard()` (currently `game.js:21-38`), change the call at line 37 from `updateDiamond(state.bases);` to `updateDiamond(state.bases, RUNNER_ANIM_MS);` (the initial-page-load call at the bottom of the file, `game.js:297-305`, is untouched and stays instant).

Add the animation functions after `updateDiamond()`:

```js
function baseCoord(marker) {
    const id = (marker === 'home' || marker === 'batter') ? 'home-plate-marker' : `base-marker-${marker}`;
    const el = document.getElementById(id);
    return el ? { x: +el.getAttribute('cx'), y: +el.getAttribute('cy') } : null;
}

function animateRunners(moves) {
    if (!moves || !moves.length) return;
    const svg = document.querySelector('#diamond svg');
    if (!svg) return;
    moves.forEach((mv, i) => {
        const from = baseCoord(mv.from);
        if (!from) return;
        const token = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        token.setAttribute('class', 'runner-token');
        token.setAttribute('cx', from.x);
        token.setAttribute('cy', from.y);
        token.setAttribute('r', 5);
        svg.appendChild(token);
        requestAnimationFrame(() => {
            const to = mv.to === 'out' ? from : baseCoord(mv.to);
            if (to) {
                token.setAttribute('cx', to.x);
                token.setAttribute('cy', to.y);
            }
            if (mv.to === 'out' || mv.to === 'home') {
                token.classList.add('runner-token-fade');
            }
        });
        setTimeout(() => token.remove(), RUNNER_ANIM_MS + 350);
    });
}
```

In `handlePlay()` (currently `game.js:178-192`), add the animation call right before `updateScoreboard(play.state)`:

```js
async function handlePlay(play) {
    showDice(play.d1, play.d2, play.outcome, play.method);
    appendPlay(play);
    animateRunners(play.moves);
    updateScoreboard(play.state);
    ...
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] A single with an empty base moves the batter's token from home to first, and the first-base marker lights up right as the token arrives (not before)
- [ ] A home run with runners on shows all runners' (and the batter's) tokens sliding toward/through home and fading out
- [ ] A walk with bases loaded shows the forced run scoring (token to home) and the chain of runners shifting up one base each
- [ ] A sacrifice/sac-fly shows only the scoring/advancing runners moving; the batter (out) shows no token
- [ ] A double-play groundout shows the forced-out runner's token fading in place at first base, not sliding anywhere
- [ ] No leftover token DOM nodes accumulate in the SVG after many plays (spot-check element count in dev tools)

**Implementation note**: Line numbers in this plan's snippets were written against a pre-scoreboard-work snapshot of `engine.py`/`views.py`/`game.js`; actual edits were applied against current file contents (post `old-fashioned-scoreboard` plan — `add_hit()`, `close_half()`, `updateBoard()`/`lineCells()`, sfx additions, etc. all already present) with matching logic, not matching line numbers. Dead `extra = state.runners_on()` line inside `apply_in_play`'s home-run branch was dropped as the plan noted.

---

## Phase 2: Streaky player — data model and setup UI

### Overview
Add the two setup checkboxes, a migration for `Game.streaky_per_game`/`streaky_per_inning`, and thread the choices through all 4 game-creation code paths. No gameplay effect yet — this phase is purely plumbing, verified by confirming the picked names round-trip correctly through persistence.

### Changes Required:

#### 1. `GameState` gains streaky fields and selection logic
**File**: `baseball/engine.py`
**Changes**: Extend `__init__()` signature and body (currently lines 14-31):

```python
def __init__(self, away_name: str, home_name: str, total_innings: int,
             away_lineup=None, home_lineup=None,
             streaky_per_game: bool = False, streaky_per_inning: bool = False) -> None:
    self.away_name = away_name
    self.home_name = home_name
    self.total_innings = total_innings
    self.away_lineup = list(away_lineup) if away_lineup else list(LINEUP)
    self.home_lineup = list(home_lineup) if home_lineup else list(LINEUP)
    self.inning = 1
    self.half = "top"            # "top" (away bats) or "bottom" (home bats)
    self.outs = 0
    self.balls = 0
    self.strikes = 0
    self.bases = [False, False, False]   # 1B, 2B, 3B
    self.away_score = 0
    self.home_score = 0
    self.away_idx = 0            # lineup rotation index
    self.home_idx = 0
    self.game_over = False
    self.last_moves = []
    self.streaky_per_game = streaky_per_game
    self.streaky_per_inning = streaky_per_inning
    self.streaky_game_away = (random.choice(self.away_lineup)
                               if streaky_per_game and self.away_lineup else None)
    self.streaky_game_home = (random.choice(self.home_lineup)
                               if streaky_per_game and self.home_lineup else None)
    self.streaky_inning_away = None
    self.streaky_inning_home = None
    if streaky_per_inning:
        self.reroll_inning_streaky()
```

Add two new methods after `runners_on()` (currently `engine.py:65-66`):

```python
def reroll_inning_streaky(self) -> None:
    """Pick a fresh random per-inning streaky batter for the side now batting."""
    if not self.streaky_per_inning:
        return
    if self.half == "top":
        self.streaky_inning_away = random.choice(self.away_lineup) if self.away_lineup else None
    else:
        self.streaky_inning_home = random.choice(self.home_lineup) if self.home_lineup else None

def is_streaky(self, batter_name: str) -> bool:
    """True if `batter_name` is the active streaky pick (per-game or per-inning) for the side now batting."""
    if self.half == "top":
        return batter_name in (self.streaky_game_away, self.streaky_inning_away)
    return batter_name in (self.streaky_game_home, self.streaky_inning_home)
```

#### 2. Persist the streaky fields
**File**: `baseball/models.py`
**Changes**: Extend `state_to_dict()` (currently lines 289-301):

```python
@staticmethod
def state_to_dict(s: GameState) -> dict:
    return {
        "away_name": s.away_name, "home_name": s.home_name,
        "total_innings": s.total_innings,
        "inning": s.inning, "half": s.half,
        "outs": s.outs, "balls": s.balls, "strikes": s.strikes,
        "bases": s.bases,
        "away_score": s.away_score, "home_score": s.home_score,
        "away_idx": s.away_idx, "home_idx": s.home_idx,
        "game_over": s.game_over,
        "away_lineup": s.away_lineup, "home_lineup": s.home_lineup,
        "streaky_per_game": s.streaky_per_game,
        "streaky_per_inning": s.streaky_per_inning,
        "streaky_game_away": s.streaky_game_away,
        "streaky_game_home": s.streaky_game_home,
        "streaky_inning_away": s.streaky_inning_away,
        "streaky_inning_home": s.streaky_inning_home,
    }
```

Extend `state_from_dict()` (currently lines 303-319) — **important**: do not pass the streaky flags to the `GameState(...)` constructor call, since that would re-trigger the random pick on every single request. Restore the already-persisted picks as plain attribute assignment afterward instead:

```python
@staticmethod
def state_from_dict(d: dict) -> GameState:
    gs = GameState(d["away_name"], d["home_name"], d["total_innings"],
                   away_lineup=d.get("away_lineup"),
                   home_lineup=d.get("home_lineup"))
    gs.inning      = d["inning"]
    gs.half        = d["half"]
    gs.outs        = d["outs"]
    gs.balls       = d["balls"]
    gs.strikes     = d["strikes"]
    gs.bases       = d["bases"]
    gs.away_score  = d["away_score"]
    gs.home_score  = d["home_score"]
    gs.away_idx    = d["away_idx"]
    gs.home_idx    = d["home_idx"]
    gs.game_over   = d["game_over"]
    gs.streaky_per_game    = d.get("streaky_per_game", False)
    gs.streaky_per_inning  = d.get("streaky_per_inning", False)
    gs.streaky_game_away   = d.get("streaky_game_away")
    gs.streaky_game_home   = d.get("streaky_game_home")
    gs.streaky_inning_away = d.get("streaky_inning_away")
    gs.streaky_inning_home = d.get("streaky_inning_home")
    return gs
```

#### 3. `Game` model fields + migration
**File**: `baseball/models.py`
**Changes**: Add two fields to `Game` (currently lines 274-279, right after `mode`):

```python
    streaky_per_game   = models.BooleanField(default=False)
    streaky_per_inning = models.BooleanField(default=False)
```

Then generate the migration:
```bash
python manage.py makemigrations baseball
```
(Expected output: a new `baseball/migrations/0014_game_streaky_per_game_streaky_per_inning.py` adding the two `BooleanField`s, default `False`.)

#### 4. Setup form checkboxes
**File**: `baseball/forms.py`
**Changes**: In `Page1Form.__init__()` (currently lines 87-114), add after the `total_innings` field definition:

```python
        self.fields["streaky_per_game"] = forms.BooleanField(
            required=False, label="Streaky player (per game)",
            widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        )
        self.fields["streaky_per_inning"] = forms.BooleanField(
            required=False, label="Streaky player (per inning)",
            widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        )
```

#### 5. Render the checkboxes
**File**: `baseball/templates/baseball/game_setup.html`
**Changes**: Insert after the "Innings" block (currently lines 28-36):

```html
    <div class="mb-3">
        <label class="form-label fw-semibold d-block">Streaky Player</label>
        <div class="form-check">
            {{ form.streaky_per_game }}
            <label class="form-check-label" for="{{ form.streaky_per_game.id_for_label }}">Per game</label>
        </div>
        <div class="form-check">
            {{ form.streaky_per_inning }}
            <label class="form-check-label" for="{{ form.streaky_per_inning.id_for_label }}">Per inning</label>
        </div>
    </div>
```

#### 6. Thread the choices through all 4 creation paths
**File**: `baseball/views.py`
**Changes**:

`Page1View.post()`, CPU_AUTO branch (currently lines 288-302):
```python
            gs = GameState(
                away_team.name, home_team.name, cd["total_innings"],
                away_lineup=lineup_from_roster(away_roster),
                home_lineup=lineup_from_roster(home_roster),
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
            )
            game = Game.objects.create(
                owner=request.user,
                away_name=away_team.name, home_name=home_team.name,
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                cpu_side=cpu_side,
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
                state=Game.state_to_dict(gs),
                away_roster=away_roster, home_roster=home_roster,
            )
```

`Page1View.post()`, MULTIPLAYER branch (currently lines 263-274) — no `GameState` yet, store on the `Game` row for `Player2JoinView` to read later:
```python
            game = Game.objects.create(
                owner=request.user, player2=opponent_user,
                away_name=away_team.name if away_team else "",
                home_name=home_team.name if home_team else "",
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                owner_side=owner_side,
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
                status=Game.WAITING,
                state={},
                away_roster=away_roster, home_roster=home_roster,
            )
```

`Page1View.post()`, two-page hotseat branch (currently lines 304-312):
```python
        request.session["bb_setup"] = {
            "side":          side,
            "p2_side":       "home" if side == "away" else "away",
            "team_id":       own_team.team_id,
            "team_name":     own_team.name,
            "mode":          cd["mode"],
            "total_innings": cd["total_innings"],
            "streaky_per_game":   cd["streaky_per_game"],
            "streaky_per_inning": cd["streaky_per_inning"],
            "roster":        own_roster,
        }
```

`Page2View.post()` (currently lines 367-380):
```python
        gs = GameState(
            away_team.name, home_team.name, setup["total_innings"],
            away_lineup=lineup_from_roster(away_roster),
            home_lineup=lineup_from_roster(home_roster),
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
        )
        game = Game.objects.create(
            owner=request.user,
            away_name=away_team.name, home_name=home_team.name,
            away_team=away_team, home_team=home_team,
            total_innings=setup["total_innings"], mode=setup["mode"],
            cpu_side=None,
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
            state=Game.state_to_dict(gs),
            away_roster=away_roster, home_roster=home_roster,
        )
```

`Player2JoinView.post()` (currently lines 447-454) — reads back from the `Game` row created in the MULTIPLAYER branch above:
```python
        gs = GameState(
            game.away_name, game.home_name, game.total_innings,
            away_lineup=lineup_from_roster(game.away_roster),
            home_lineup=lineup_from_roster(game.home_roster),
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
        )
        game.state = Game.state_to_dict(gs)
        game.status = Game.ACTIVE
        game.save()
```

`ReplayView.post()` (currently lines 603-616) — carry the original game's settings forward:
```python
        gs = GameState(
            game.away_name, game.home_name, game.total_innings,
            away_lineup=lineup_from_roster(game.away_roster),
            home_lineup=lineup_from_roster(game.home_roster),
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
        )
        new_game = Game.objects.create(
            owner=request.user,
            away_name=game.away_name, home_name=game.home_name,
            away_team=game.away_team, home_team=game.home_team,
            total_innings=game.total_innings, mode=mode,
            cpu_side=game.cpu_side,
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
            state=Game.state_to_dict(gs),
            away_roster=game.away_roster, home_roster=game.home_roster,
        )
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py makemigrations baseball --check` reports no missing migrations (after running `makemigrations` once for real)
- [x] `python manage.py migrate` applies cleanly
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] Setup form shows both checkboxes under "Streaky Player", correctly submits as booleans
- [ ] Creating a CPU_AUTO game with "per game" checked, then reloading the game-detail page several times, shows the SAME streaky player name persists (does not re-roll on every page load/roll)
- [ ] Creating a two-page hotseat game with either box checked correctly carries the choice from page 1 to the created game
- [ ] Creating a multiplayer game with either box checked, then having the second player join, correctly creates a `GameState` with the original inviter's streaky settings
- [ ] Replaying a finished game preserves its original streaky settings on the new game

**Implementation Note**: Pause here for manual confirmation that the streaky picks persist correctly across requests before proceeding to Phase 3, since a persistence bug here would silently make Phase 3's doubling logic look broken (or randomly-inconsistent) rather than obviously wrong.

**Deviation found and fixed**: `makemigrations` also surfaced a pre-existing, unrelated migration-history/DB drift on `Game.away_team`/`home_team` (their FK constraints already existed in the DB but Django's migration state didn't know it — predates this session, unrelated to streaky work). The real change is migration `0014_game_streaky_per_game_game_streaky_per_inning_and_more` (the two `BooleanField`s only — its auto-generated spurious `AlterField` ops on away_team/home_team were stripped since applying them errored with `constraint ... already exists`). Migration `0015_alter_game_away_team_alter_game_home_team` was then generated and applied with `--fake` (per user's choice) purely to sync Django's migration history with the DB's actual state — no schema was touched by 0015.

---

## Phase 3: Streaky player — gameplay effect

### Overview
Apply the actual buff: double hit-outcome weights for stat-based streaky batters, swap in an improved dice table for non-stat streaky batters, re-roll the per-inning pick at each half-inning transition, and surface a 🔥 flag in the play log.

**User addition (requested before Phase 2/3 existed, queued here)**: also flag the streaky batter with 🔥 next to their name in the batting-order roster list (`game_detail.html`'s lineup loop, `entry.name`), not just in the play-by-play log after they've batted — so the streaky pick is visible up front. Needs `GameDetailView.get_context_data()` to annotate each roster entry with whether that player is the active per-game/per-inning streaky pick for their side (using `gs.is_streaky(entry["name"])`, mind that `is_streaky()` is keyed off `gs.half` — for the *non-batting* side's roster list, check against that side's `streaky_game_*`/`streaky_inning_*` fields directly rather than `is_streaky()`, which only reflects the side currently up).

### Changes Required:

#### 1. Dice-table streaky variant and error-single outcome
**File**: `baseball/params.py`
**Changes**: Extend `HIT_BASES` (currently line 69):

```python
HIT_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4, "single_error": 1}
```

Add after `DICE_TABLE` (currently ends at line 99):

```python
# Streaky-batter variant of the dice table: 2 of the 3 groundout rolls become
# "reaches on an error" singles (still an at-bat, not a hit) when the current
# batter is that half-inning's/game's streaky pick. (1,5) stays a groundout so
# streaky dice-table batters still have some groundout risk.
DICE_TABLE_STREAKY = dict(DICE_TABLE, **{
    (2, 4): "single_error",
    (2, 6): "single_error",
})
```

#### 2. Use the streaky table and double stat-based hit weights
**File**: `baseball/engine.py`
**Changes**: Update the import (currently line 5-8):

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, DICE_TABLE_STREAKY,
    STAT_OUT_SPLIT,
)
```

Update `resolve_dice_roll()` (currently lines 305-325):

```python
def resolve_dice_roll(state: GameState, stat_weights: Dict[str, int] = None,
                       streaky: bool = False) -> Tuple[int, int, str, str]:
    """Roll 2d6 (always, for display), then either look up DICE_TABLE by the
    die pair or -- when stat_weights is given -- draw the outcome from the
    batter's own career-stat weights. Applies the event to state.

    Returns (d1, d2, outcome_key, play_message).
    """
    d1, d2 = roll_dice()
    if stat_weights is not None:
        outcome = weighted_choice(stat_weights)
    else:
        table = DICE_TABLE_STREAKY if streaky else DICE_TABLE
        outcome = table[(min(d1, d2), max(d1, d2))]
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

#### 3. Double hit weights for streaky stat-based batters
**File**: `baseball/views.py`
**Changes**: Update `_career_weights_for()` (currently lines 63-72):

```python
def _career_weights_for(player_id, streaky=False):
    """Stat-based outcome weights for a batter, or None to use the dice table."""
    if not player_id:
        return None
    row = PlayerCareerStats.objects.filter(player_id=player_id).values(
        "at_bats", "hits", "doubles", "triples", "home_runs", "walks", "strikeouts",
    ).first()
    if not row or row["at_bats"] < STAT_BASED_MIN_AB:
        return None
    weights = stat_based_weights(row)
    if streaky:
        for key in ("single", "double", "triple", "home_run"):
            weights[key] *= 2
    return weights
```

#### 4. Wire streaky detection and per-half-inning rerolls into the game loop
**File**: `baseball/views.py`
**Changes**: Update `_advance_game()` (currently lines 141-191):

```python
def _advance_game(gs: GameState, roster) -> dict:
    # Capture before any mutation so play-log labels show the inning/half of the play.
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter
    gs.last_moves = []
    streaky = gs.is_streaky(batter)

    if batter == "Tushy Scar":
        d1, d2 = 6, 6
        msg, _ = apply_in_play(gs, "home_run")
        outcome = "home_run"
        method = "dice"
    else:
        pid = _pid_for_name(roster, batter)
        weights = _career_weights_for(pid, streaky=streaky)
        d1, d2, outcome, msg = resolve_dice_roll(gs, stat_weights=weights, streaky=streaky)
        method = "stat" if weights is not None else "dice"
    gs.reset_count()
    gs.advance_lineup()

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    # Walk-off: bottom half of final inning, home leads after the at-bat
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg, method=method,
                    play_half=play_half, play_inning=play_inning,
                    batter=batter, half_over=True, game_over=True,
                    streaky=streaky, moves=gs.last_moves,
                    state=_state_snapshot(gs))

    if gs.outs >= 3:
        half_over = True
        if gs.half == "top":
            # Home already winning at end of final top half — skip bottom
            if is_final and gs.home_score > gs.away_score:
                gs.game_over = True
            else:
                gs.half = "bottom"
                gs.reset_half()
                gs.reroll_inning_streaky()
        else:  # bottom
            if is_final and gs.home_score != gs.away_score:
                gs.game_over = True
            else:
                gs.inning += 1
                gs.half = "top"
                gs.reset_half()
                gs.reroll_inning_streaky()

    return dict(d1=d1, d2=d2, outcome=outcome, message=msg, method=method,
                play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=half_over, game_over=gs.game_over,
                streaky=streaky, moves=gs.last_moves,
                state=_state_snapshot(gs))
```

#### 5. `single_error` counts as an at-bat, not a hit
**File**: `baseball/views.py`
**Changes**: Update `_AB_OUTCOMES` (currently line 21-22) — intentionally NOT added to `_HIT_STAT`, matching real baseball's "reach on error ≠ hit" scoring:

```python
_AB_OUTCOMES = {"single", "double", "triple", "home_run",
                "strikeout", "groundout", "flyout", "single_error"}
```

#### 6. Flag streaky at-bats in the play log
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Add near `methodTag()` (currently `game.js:46-48`):

```js
function streakyTag(streaky) {
    return streaky ? ' 🔥' : '';
}
```

Update `appendPlay()` (currently `game.js:58-75`), the `p.textContent` line:
```js
    p.textContent = `[${half} ${play.play_inning}] ⚾ [${play.d1}][${play.d2}] — ${play.message} ${methodTag(play.method)}${streakyTag(play.streaky)}`;
```

**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Update the play-log loop (currently lines 160-165):

```html
        {% for play in play_log_reversed %}
        <p class="mb-1">
          [{% if play.play_half == "top" %}TOP{% else %}BOT{% endif %} {{ play.play_inning }}]
          ⚾ [{{ play.d1 }}][{{ play.d2 }}] &mdash; {{ play.message }}
          {% if play.method|default:"dice" == "dice" %}(🎲){% else %}(📊){% endif %}{% if play.streaky %} 🔥{% endif %}
        </p>
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] With "per inning" checked, the play-by-play log shows a 🔥 on exactly one batter per side per half-inning (changes each half-inning)
- [ ] With "per game" checked, the SAME player is 🔥-flagged across the whole game whenever they're up, for both teams independently
- [ ] A streaky stat-based batter (≥200 career AB) visibly gets more hits over a simulated full game than a non-streaky teammate with similar career stats (spot-check via `auto_play` mode's box score)
- [ ] A streaky dice-table batter occasionally produces a "reaches on an error!" message instead of "grounds out." — a non-streaky dice-table batter never does
- [ ] A "reaches on an error" play increments the batter's at-bat count but not their hit count in the batting-order stat line (e.g. `0-3` after 3 ABs including one error-reach, not `1-3`)
- [ ] Both checkboxes checked simultaneously doesn't crash or double-apply — same visible buff as either alone when the picks coincide
- [ ] Batting-order list (below the field/scoreboard) shows 🔥 next to the streaky pick's name for each side, visible from page load, not just after they've batted (user-requested addition, see note below)

**Deviations found and fixed**:
- Plan's `dict(DICE_TABLE, **{...})` syntax errors (`TypeError: keywords must be strings`) since `DICE_TABLE`'s keys are `(int, int)` tuples, not strings — `**` unpacking requires string keys. Fixed to `{**DICE_TABLE, (2, 4): "single_error", (2, 6): "single_error"}`.
- Added the user's queued request from Phase 1: `GameDetailView.get_context_data()`'s `annotate()` now tags each batting-order entry with `"streaky"` by checking name membership against that *side's* `streaky_game_*`/`streaky_inning_*` fields directly (not `gs.is_streaky()`, which only reflects whichever side is currently at bat) — rendered as 🔥 next to the name in `game_detail.html`'s batting-order loop.

---

## Phase 4: Full verification pass

### Overview
End-to-end regression across all 4 game modes with both new features active together.

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes
- [x] `python manage.py migrate --plan` shows nothing pending (all applied); fresh-DB apply reasoned consistent — `0014` is a plain 2-field `AddField` w/ defaults, `0015`'s FK alter was `--fake`d here only due to pre-existing drift on this DB and would apply as real (non-conflicting) DDL against a genuinely fresh DB. `manage.py test --noinput` couldn't serve as a live fresh-DB proxy since no DB-touching tests exist in this project (Django skipped test-DB setup entirely).

#### Manual Verification:
- [ ] `click_all` mode: runner animation + streaky flags both visible across a full manually-played game
- [ ] `cpu_auto` mode: same, during the CPU's automated turns
- [ ] `auto_play` mode: same, across the tight client-side replay loop (no reloads mid-game) — confirm no leftover animation DOM nodes pile up after a full 9-inning game
- [ ] `multiplayer` mode: streaky settings chosen by the inviter correctly apply for both players once the second player joins; runner animation renders correctly after each reload-polled turn
- [ ] An old game created before this change (missing the new `state` JSON keys) still loads without error — `streaky_per_game`/`streaky_per_inning` default to `False`, no runner-move data on its next play is fine (empty `moves` list, no animation, no crash)

## Testing Strategy

### Manual Testing Steps:
1. Start a CPU_AUTO game with both streaky checkboxes on, click through several at-bats, confirm 🔥 tags rotate per half-inning for the per-inning pick while the per-game pick stays fixed.
2. Trigger a walk with bases loaded, a sacrifice fly, a double-play groundout, and a home run with runners on — confirm each produces the expected token movement/fade pattern.
3. Simulate a full `auto_play` game and check the final box score for elevated hit rates on streaky batters vs their career averages.
4. Create a multiplayer game with a streaky box checked, join as the second player, confirm both sides get independent streaky picks.

## Performance Considerations

Runner animation spawns at most 4 short-lived SVG nodes per play (self-removing via `setTimeout`), negligible for a turn-based game. Streaky lookups are O(1) attribute checks, no added queries beyond the existing `PlayerCareerStats` lookup already made per at-bat.

## Migration Notes

The `baseball/migrations/0014_...` migration adds two `BooleanField`s defaulting to `False` — existing `Game` rows get `streaky_per_game=False, streaky_per_inning=False` automatically, and their persisted `state` JSON lacks the new streaky keys entirely; `state_from_dict()`'s `.get(..., False)`/`.get(...)` defaults handle this without error, and `moves` simply won't be present on any of their historical `play_log` entries (fine — animation only ever needs it on the live response of the play that just happened, not historical entries).

## References
- Related research: `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`
- `baseball/engine.py:11-31,75-107,169-280,305-325` — `GameState`, base-movement helpers, `apply_in_play`, `resolve_dice_roll`
- `baseball/views.py:63-72,141-191` — `_career_weights_for`, `_advance_game`
- `baseball/models.py:289-319` — `state_to_dict`/`state_from_dict`
- `baseball/params.py:69,75-99` — `HIT_BASES`, `DICE_TABLE`
- `baseball/forms.py:81-114` — `Page1Form`
- `baseball/stadiums.py:21-35` — `stadium_context()` (source of the `home_plate` coordinate)
