# Old-Fashioned Scoreboard Implementation Plan

## Overview

Replace the current text-only "Scoreboard" card in the live game view with an old-fashioned mechanical line-score board (like a Fenway-style wall scoreboard) positioned above the field: team names in place of "HOME"/"VISITOR", a per-inning run grid with flip-card rotation animation, R/H totals, and a 3-dot outs indicator (black → red) that flashes fully lit for a beat on the 3rd out before resetting for the new half-inning.

## Current State Analysis

- `GameState` (`baseball/engine.py:11-31`) tracks only two cumulative score fields, `away_score`/`home_score` — no per-inning breakdown, no hits tracking at all.
- The existing "Scoreboard" card (`baseball/templates/baseball/game_detail.html:71-106`) shows: inning/half header, a 2-row list of team name + batting indicator + cumulative score, and plain text "Outs: N" + current batter name/stat line. No per-inning grid, no light-style out indicators.
- Half-inning/inning transitions are entirely orchestrated in `_advance_game()` (`baseball/views.py:141-191`), which is the single chokepoint every game mode (`click_all`, `cpu_auto`, `auto_play`, `multiplayer`) routes through per at-bat.
- No CSS `@keyframes`/`transition`/`animation` exists anywhere in the baseball app (confirmed in `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`) — this plan introduces the app's first custom animation.

### Key Discoveries:
- `Game.state` is a `JSONField` (`baseball/models.py:279`) — no database migration is needed for the new per-inning/hits data, only extending the `state_to_dict`/`state_from_dict` round-trip (`models.py:289-319`).
- Half-inning-ending logic in `_advance_game()` has exactly 4 branches (walk-off, top-ends-game-over, top-continues, bottom-ends-game-over, bottom-continues) but only 2 distinct points where a half actually *closes* need instrumenting: the walk-off early return, and the single `if gs.outs >= 3:` block (whose 4 sub-branches all still have the correct `gs.half` value at entry, before any of them flip it) — so exactly 2 call sites need a "close out this half's line-score entry" hook, not 4.
- `GameDetailView.get_context_data()` (`baseball/views.py:484-528`) is the only place that needs new context (the per-inning cell values, hit totals); `RollView`/`SimulateView`'s JSON responses need no view changes beyond what `_state_snapshot()` already exposes, once extended.

## Desired End State

The live game page shows a dark mechanical-style board above the field: team names + per-inning run cells (each flipping via a CSS rotation animation when it updates) + R/H total columns, and a 3-dot outs row that turns dots red one at a time as outs accrue, flashes all 3 red briefly when the 3rd out ends a half, then resets to black for the new half. This board fully replaces the old scoreboard card (batter name/stat-line move into the board's own "AT BAT" line).

### Verification
- `python manage.py check` passes.
- Manually playing a game in each of the 4 modes shows: per-inning cells filling in as each half is played (live partial total for the inning in progress, blank for innings not yet reached), out-dots lighting up correctly and flashing on the 3rd out, flip animation firing only on inning-cell value changes, extra-inning columns appearing dynamically without a page reload during `auto_play`'s no-reload loop.

## What We're NOT Doing

- Not adding an Errors (E) column — the engine has no error-tracking mechanism at all (aside from the unrelated `single_error` dice-table outcome introduced by a separate streaky-player plan, which is a hit-type flag, not a fielding-error counter); R+H only.
- Not backfilling per-inning history for games created before this change — their `state` JSON lacks `away_line`/`home_line`/hits keys entirely; `state_from_dict()`'s `.get()` defaults let them load safely, but their board starts blank for all prior innings going forward (known limitation, not fixed).
- Not touching `game_list.html`'s score display — it shows only cumulative totals today and stays that way; out of scope (not the live game view).
- Not adding ball/strike count lights — the existing scoreboard card never displayed balls/strikes in the UI either (dead server-side data), so nothing is lost by the new board also omitting them.
- Not restyling the dice-result card, action buttons, or play-by-play log — only the scoreboard card is replaced.

## Implementation Approach

Three phases: backend state (per-inning runs/hits tracking + persistence + view context), then the new board markup/CSS, then the `game.js` wiring (flip animation, out-dot flash sequencing, dynamic extra-inning columns). Each phase is independently testable before moving to the next.

**Note on overlapping work**: This plan, `thoughts/shared/plans/2026-07-23-sounds-fireworks-crowd.md`, and `thoughts/shared/plans/2026-07-23-runner-animation-streaky-player.md` all touch `_advance_game()`, `_state_snapshot()`, `GameState.__init__`/`state_to_dict`/`state_from_dict`, and `game_detail.html`/`game.js`. None have been implemented yet as of this writing — if implementing more than one, do them sequentially (not in parallel) and re-diff each subsequent plan's snippets against the actual post-previous-phase file contents rather than applying the stale snippets verbatim.

## Phase 1: Backend — per-inning runs, hits, and half-closing

### Overview
Track per-inning run totals and hit counts on `GameState`, close out each half's line-score entry at the right moment in `_advance_game()`, and expose ready-to-render per-inning cell data from the view.

### Changes Required:

#### 1. `GameState` gains line-score and hit tracking
**File**: `baseball/engine.py`
**Changes**: In `__init__()` (currently lines 14-31), add after `self.home_score = 0` (line 28):

```python
        self.away_line = []          # completed runs-per-inning, away
        self.home_line = []          # completed runs-per-inning, home
        self.runs_this_half = 0      # running total for the half in progress
        self.away_hits = 0
        self.home_hits = 0
```

Update `add_runs()` (currently lines 50-54):

```python
    def add_runs(self, runs: int) -> None:
        if self.half == "top":
            self.away_score += runs
        else:
            self.home_score += runs
        self.runs_this_half += runs
```

Add two new methods after `reset_count()` (currently lines 61-63):

```python
    def add_hit(self) -> None:
        if self.half == "top":
            self.away_hits += 1
        else:
            self.home_hits += 1

    def close_half(self) -> None:
        """Append the just-finished half's run total to that team's line score
        and reset the running counter. Must be called once per half, using the
        *current* self.half value, before flipping to the next half."""
        line = self.away_line if self.half == "top" else self.home_line
        line.append(self.runs_this_half)
        self.runs_this_half = 0
```

#### 2. Track hits at the point of contact
**File**: `baseball/engine.py`
**Changes**: In `apply_in_play()` (currently lines 169-208), the hit branch — add `state.add_hit()`:

```python
    if outcome in HIT_BASES:
        n = HIT_BASES[outcome]
        state.bases, runs = advance_runners(state.bases, n)
        state.add_runs(runs)
        state.add_hit()
        names = {1: "singles", 2: "doubles", 3: "triples", 4: "homers"}
        ...
```

#### 3. Close out each half at the right moment
**File**: `baseball/views.py`
**Changes**: In `_advance_game()` (currently lines 141-191):

Walk-off branch (currently lines 164-169) — add `gs.close_half()` before `gs.game_over = True`:
```python
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.close_half()
        gs.game_over = True
        return dict(...)
```

The `if gs.outs >= 3:` block (currently lines 171-186) — add `gs.close_half()` as the first statement, before the `if gs.half == "top":` dispatch (this single call correctly covers all 4 sub-branches, since `gs.half` hasn't been flipped yet at this point in any of them):
```python
    if gs.outs >= 3:
        half_over = True
        gs.close_half()
        if gs.half == "top":
            ...
```

#### 4. Persist the new fields
**File**: `baseball/models.py`
**Changes**: Extend `state_to_dict()` (currently lines 289-301) — add after `"away_score"/"home_score"`:

```python
            "away_line": s.away_line, "home_line": s.home_line,
            "runs_this_half": s.runs_this_half,
            "away_hits": s.away_hits, "home_hits": s.home_hits,
```

Extend `state_from_dict()` (currently lines 303-319) — use `.get()` with safe defaults so games created before this change still load:
```python
        gs.away_line      = d.get("away_line", [])
        gs.home_line      = d.get("home_line", [])
        gs.runs_this_half = d.get("runs_this_half", 0)
        gs.away_hits      = d.get("away_hits", 0)
        gs.home_hits      = d.get("home_hits", 0)
```

#### 5. Surface the new fields per play
**File**: `baseball/views.py`
**Changes**: Extend `_state_snapshot()` (currently lines 123-138) — add:

```python
        "away_line":      gs.away_line,
        "home_line":      gs.home_line,
        "runs_this_half": gs.runs_this_half,
        "away_hits":      gs.away_hits,
        "home_hits":      gs.home_hits,
```

#### 6. Compute ready-to-render board cells for initial page load
**File**: `baseball/views.py`
**Changes**: Add a module-level helper near the other small helpers (after `_apply_delta()`, currently ending line 80):

```python
def _line_cells(line, num_cols, current_inning, is_active_half, runs_this_half):
    """Per-inning board cells: completed innings from `line`, the live partial
    total for the inning in progress, blank for innings not yet reached."""
    cells = []
    for n in range(1, num_cols + 1):
        if n <= len(line):
            cells.append({"n": n, "value": line[n - 1]})
        elif n == current_inning and is_active_half:
            cells.append({"n": n, "value": runs_this_half})
        else:
            cells.append({"n": n, "value": ""})
    return cells
```

In `GameDetailView.get_context_data()` (currently lines 484-528), add before the `play_log_reversed` block:

```python
        num_cols = max(self.object.total_innings, gs.inning,
                        len(gs.away_line), len(gs.home_line))
        ctx["away_cells"] = _line_cells(gs.away_line, num_cols, gs.inning,
                                          gs.half == "top", gs.runs_this_half)
        ctx["home_cells"] = _line_cells(gs.home_line, num_cols, gs.inning,
                                          gs.half == "bottom", gs.runs_this_half)
        ctx["away_hits"] = gs.away_hits
        ctx["home_hits"] = gs.home_hits
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] Playing through a full half-inning and checking the Django shell/admin (or a temporary debug print) shows `away_line`/`home_line` populate correctly after each half ends, including the walk-off and extra-innings cases
- [ ] Hits increment only on single/double/triple/home_run outcomes, not walks/sacrifices/outs

**Implementation Note**: Pause here for manual confirmation the backend data is correct before wiring up the (harder-to-debug-blind) frontend in Phase 2/3.

---

## Phase 2: Board markup and CSS

### Overview
Replace the old scoreboard card with the new mechanical-board markup, styled dark with a monospace/bold look, positioned above the existing field+scoreboard row.

### Changes Required:

#### 1. Remove the old scoreboard card
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Delete the entire `<!-- Scoreboard card -->` block (currently lines 70-106).

#### 2. Add the new board, positioned above the existing `row g-4`
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Insert right after the JS config `<script>` block (currently ends line 32) and before `<div class="row g-4">` (currently line 34):

```html
<div class="row g-4 mb-1">
  <div class="col-12">
    <div class="scoreboard-board" id="scoreboard-board" data-outs="{{ game.state.outs }}">
      <table class="board-table">
        <thead>
          <tr id="board-header-row">
            <th class="board-team-col"></th>
            {% for cell in away_cells %}<th>{{ cell.n }}</th>{% endfor %}
            <th class="board-total-col">R</th>
            <th class="board-total-col">H</th>
          </tr>
        </thead>
        <tbody>
          <tr id="board-away-row">
            <td class="board-team-col">
              {{ game.away_name }}
              <span id="board-away-bat" class="board-bat-arrow">{% if game.state.half == "top" %}▶{% endif %}</span>
            </td>
            {% for cell in away_cells %}
            <td class="board-cell" id="board-away-{{ cell.n }}"><span class="flip-value">{{ cell.value }}</span></td>
            {% endfor %}
            <td class="board-total-col" id="board-away-r">{{ game.state.away_score }}</td>
            <td class="board-total-col" id="board-away-h">{{ away_hits }}</td>
          </tr>
          <tr id="board-home-row">
            <td class="board-team-col">
              {{ game.home_name }}
              <span id="board-home-bat" class="board-bat-arrow">{% if game.state.half == "bottom" %}▶{% endif %}</span>
            </td>
            {% for cell in home_cells %}
            <td class="board-cell" id="board-home-{{ cell.n }}"><span class="flip-value">{{ cell.value }}</span></td>
            {% endfor %}
            <td class="board-total-col" id="board-home-r">{{ game.state.home_score }}</td>
            <td class="board-total-col" id="board-home-h">{{ home_hits }}</td>
          </tr>
        </tbody>
      </table>
      <div class="board-outs-row">
        <span class="board-outs-label">OUTS</span>
        <span class="out-dot" id="out-dot-1"></span>
        <span class="out-dot" id="out-dot-2"></span>
        <span class="out-dot" id="out-dot-3"></span>
        <span class="board-atbat">
          AT BAT <strong id="board-batter">{{ current_batter }}</strong>
          <span id="board-batter-line" class="text-muted">{% if current_batter_line %}({{ current_batter_line }}){% endif %}</span>
        </span>
      </div>
    </div>
  </div>
</div>
```

#### 3. Board CSS
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Extend the existing `<style>` block (currently lines 5-13):

```css
  .scoreboard-board {
    background: #3d4440;
    color: #f0f0f0;
    border-radius: 6px;
    padding: 12px 16px;
    font-family: 'Courier New', monospace;
  }
  .board-table { width: 100%; border-collapse: collapse; text-align: center; }
  .board-table th, .board-table td { padding: 4px 8px; }
  .board-team-col { text-align: left; font-weight: bold; min-width: 8rem; }
  .board-bat-arrow { color: #ffd400; margin-left: 4px; }
  .board-total-col { border-left: 2px solid #f0f0f0; font-weight: bold; }
  .flip-value {
    display: inline-block;
    min-width: 1.4em;
    background: #1c1f1d;
    border-radius: 3px;
    padding: 2px 4px;
    transform-style: preserve-3d;
  }
  .flip-value.flipping { animation: flip-rotate 420ms ease-in-out; }
  @keyframes flip-rotate {
    0%   { transform: rotateX(0deg); }
    50%  { transform: rotateX(-90deg); }
    100% { transform: rotateX(0deg); }
  }
  .board-outs-row {
    display: flex; align-items: center; gap: 10px; margin-top: 10px;
    border-top: 2px solid #f0f0f0; padding-top: 8px;
  }
  .board-outs-label { font-weight: bold; letter-spacing: .1em; }
  .out-dot {
    width: 16px; height: 16px; border-radius: 50%;
    background: #111; border: 1px solid #000;
    display: inline-block;
    transition: background-color 150ms ease;
  }
  .out-dot.lit { background: #d21f1f; }
  .board-atbat { margin-left: auto; }
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] Page loads showing the new dark board above the field, with correct team names (not "HOME"/"VISITOR"), correct initial per-inning cells, R/H totals, and the batting-team arrow on the right side
- [ ] Board doesn't visually clip or overlap adjacent content at common browser widths

---

## Phase 3: `game.js` wiring — live updates, flip animation, out-dot flash

### Overview
Replace `updateScoreboard()`'s old `sb-*` element updates with the new board's element updates, add the flip-card animation trigger, add dynamic column growth for extra innings (needed by `auto_play` mode's no-reload client-side loop), and sequence the 3rd-out flash before the half-inning reset.

### Changes Required:

#### 1. Replace `updateScoreboard()` with `updateBoard()`
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Replace the entire function (currently lines 21-38) and add supporting helpers:

```js
function lineCells(line, numCols, currentInning, isActiveHalf, runsThisHalf) {
    const cells = [];
    for (let n = 1; n <= numCols; n++) {
        if (n <= line.length) cells.push(line[n - 1]);
        else if (n === currentInning && isActiveHalf) cells.push(runsThisHalf);
        else cells.push(null);
    }
    return cells;
}

function currentColumnCount() {
    return document.querySelectorAll('#board-away-row .board-cell').length;
}

function ensureColumns(n) {
    const have = currentColumnCount();
    if (n <= have) return;
    const headRow = document.getElementById('board-header-row');
    const awayRow = document.getElementById('board-away-row');
    const homeRow = document.getElementById('board-home-row');
    for (let i = have + 1; i <= n; i++) {
        const th = document.createElement('th');
        th.textContent = i;
        headRow.insertBefore(th, headRow.querySelector('.board-total-col'));

        const tdA = document.createElement('td');
        tdA.className = 'board-cell';
        tdA.id = `board-away-${i}`;
        tdA.innerHTML = '<span class="flip-value"></span>';
        awayRow.insertBefore(tdA, awayRow.querySelector('.board-total-col'));

        const tdH = document.createElement('td');
        tdH.className = 'board-cell';
        tdH.id = `board-home-${i}`;
        tdH.innerHTML = '<span class="flip-value"></span>';
        homeRow.insertBefore(tdH, homeRow.querySelector('.board-total-col'));
    }
}

function setCell(id, value) {
    const cell = document.getElementById(id);
    if (!cell) return;
    const span = cell.querySelector('.flip-value');
    const text = (value === null || value === '') ? '' : String(value);
    if (span.textContent === text) return;
    span.classList.remove('flipping');
    void span.offsetWidth;  // restart animation
    span.textContent = text;
    span.classList.add('flipping');
}

function updateOuts(n) {
    for (let i = 1; i <= 3; i++) {
        document.getElementById(`out-dot-${i}`).classList.toggle('lit', i <= n);
    }
}

function updateBoard(state) {
    const numCols = Math.max(TOTAL_INN, state.inning, state.away_line.length, state.home_line.length);
    ensureColumns(numCols);

    const awayCells = lineCells(state.away_line, numCols, state.inning, state.half === 'top', state.runs_this_half);
    const homeCells = lineCells(state.home_line, numCols, state.inning, state.half === 'bottom', state.runs_this_half);
    awayCells.forEach((v, i) => setCell(`board-away-${i + 1}`, v));
    homeCells.forEach((v, i) => setCell(`board-home-${i + 1}`, v));

    document.getElementById('board-away-r').textContent = state.away_score;
    document.getElementById('board-home-r').textContent = state.home_score;
    document.getElementById('board-away-h').textContent = state.away_hits;
    document.getElementById('board-home-h').textContent = state.home_hits;

    document.getElementById('board-away-bat').textContent = state.half === 'top' ? '▶' : '';
    document.getElementById('board-home-bat').textContent = state.half === 'bottom' ? '▶' : '';

    document.getElementById('board-batter').textContent = state.current_batter;
    const lineEl = document.getElementById('board-batter-line');
    if (lineEl) lineEl.textContent = state.batter_line ? `(${state.batter_line})` : '';

    updateOuts(state.outs);
    updateDiamond(state.bases);
}
```

#### 2. Sequence the 3rd-out flash before the reset
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Add a constant near the top (after `const CSRF = ...`, currently `game.js:3-4`):

```js
const OUT_FLASH_MS = 500;
```

Update `handlePlay()` (currently lines 178-192) — the `if (play.half_over && !play.game_over)` case in this codebase's branch structure is, by construction of `_advance_game()`'s two "continue game" branches, always the 3-outs case (walk-offs always set `game_over=True`), so no new backend flag is needed to detect it:

```js
async function handlePlay(play) {
    showDice(play.d1, play.d2, play.outcome, play.method);
    appendPlay(play);
    if (play.stat_update) {
        const cell = document.getElementById('stat-' + play.stat_update.player_id);
        if (cell) cell.textContent = play.stat_update.line;
    }
    if (play.half_over && !play.game_over) {
        updateOuts(3);
        await sleep(OUT_FLASH_MS);
    }
    updateBoard(play.state);
    if (play.outcome === 'home_run') playSound('home_run');
    const delay = play.outcome === 'home_run' ? 1400 : 900;
    await sleep(delay);
    if (play.half_over && !play.game_over) {
        await sleep(600);
    }
}
```

#### 3. Initial out-dot render on page load
**File**: `baseball/static/baseball/js/game.js`
**Changes**: In the initial-load block at the bottom of the file (currently lines 297-305), add after the diamond init:

```js
const boardEl = document.getElementById('scoreboard-board');
if (boardEl) {
    updateOuts(parseInt(boardEl.dataset.outs, 10) || 0);
}
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] An inning-cell only visually flips when its value actually changes, not on every play
- [ ] Outs light up one at a time (dot 1, then dot 2) as they occur
- [ ] On the 3rd out, all 3 dots flash red briefly, then the board updates to the new half/inning with outs reset to 0 dots lit
- [ ] Playing an `auto_play` game past the configured `total_innings` into extra innings dynamically adds new columns to the board without a page reload
- [ ] Reloading the page mid-game (any mode) shows the board's initial render exactly matching where the live JS updates left off

---

## Testing Strategy

### Manual Testing Steps:
1. Play a `click_all` game through several full innings, confirming per-inning cells fill in correctly for both the completed innings and the live in-progress inning (showing the running partial total, not just 0 or blank).
2. Trigger a 3-out half-inning ending and confirm the flash-then-reset sequence on the out-dots.
3. Play (or force, via a short `total_innings` setting) a game into extra innings and confirm new columns appear correctly in both a reload-based mode (`click_all`) and the no-reload `auto_play` loop.
4. Trigger a walk-off finish and confirm the final half's runs still correctly append to the line score before the game-over screen shows.
5. Check the H column increments correctly across singles/doubles/triples/home runs and never on walks/outs/sacrifices.

## Performance Considerations

None beyond the existing per-play JSON payload size (5 new small fields/arrays), negligible for a turn-based game.

## Migration Notes

No database migration — `Game.state` is a `JSONField`. Games created before this change simply lack the new keys in their persisted `state`; `state_from_dict()`'s `.get(..., default)` calls handle this safely, and their board starts fresh (no retroactive per-inning history) from whatever point they're next loaded after the deploy.

## References
- Related research: `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`
- Related plans (overlapping files, not yet implemented): `thoughts/shared/plans/2026-07-23-sounds-fireworks-crowd.md`, `thoughts/shared/plans/2026-07-23-runner-animation-streaky-player.md`
- `baseball/engine.py:11-31,50-63,169-208` — `GameState`, `add_runs`/`reset_count`, `apply_in_play`
- `baseball/views.py:123-138,141-191,484-528` — `_state_snapshot`, `_advance_game`, `GameDetailView.get_context_data`
- `baseball/models.py:289-319` — `state_to_dict`/`state_from_dict`
- `baseball/templates/baseball/game_detail.html:5-13,70-106` — existing style block and the scoreboard card being replaced
- `baseball/static/baseball/js/game.js:21-44,178-192,297-305` — `updateScoreboard`/`updateDiamond`, `handlePlay`, initial-load block
