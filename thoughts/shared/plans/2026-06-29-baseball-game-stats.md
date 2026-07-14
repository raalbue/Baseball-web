# Per-Game Batting Stats (game_stat) + At-Bat Line Display Implementation Plan

## Overview

Record each batter's per-game line into the existing `game_stat` table (one cumulative
row per player per game) as at-bats resolve, and surface that line — hits-for-at-bats,
e.g. `0-0`, `0-1`, `1-3` — next to the current batter on the scoreboard and beside every
name in the batting-order cards. Stats update live as the game is played and persist so a
resumed game shows the running line.

## Current State Analysis

- **At-bat resolution** runs in `_advance_game(gs)` (`baseball/views.py:43`): captures
  `play_half`/`play_inning`, special-cases `"Tushy Scar"` to a forced `home_run`, else
  calls `resolve_dice_roll(gs)`, then `reset_count()` + `advance_lineup()` and transition
  logic. Returns a JSON-ready dict (`d1,d2,outcome,message,play_half,play_inning,
  half_over,game_over,state`). It is a **pure helper with no DB access**.
- **`RollView`** (`baseball/views.py:194`) runs one `_advance_game`, appends the play to
  `play_log`, persists. **`SimulateView`** (`baseball/views.py:209`) loops `_advance_game`
  to completion and replaces `play_log`. Both already have the `game` object in hand.
- **Outcome keys** from `resolve_dice_roll` (`engine.py:283`, via `DICE_TABLE`): `single,
  double, triple, home_run, strikeout, walk, sacrifice, groundout, flyout`. A sac fly is
  emitted as `flyout` (the message says "sacrifice fly" but the key is `flyout`).
- **Batter identity**: `gs.current_batter` (`engine.py:39`) is a **name string** from the
  batting team's lineup. Real `player_id`s live only in `game.away_roster` /
  `game.home_roster` JSON (`{"position","player_id","name"}` per entry), populated for
  roster-flow games. Legacy/default-lineup games have empty rosters and no player_ids.
- **`GameDetailView.get_context_data`** (`baseball/views.py:177`) already injects
  `current_batter`, `batting_team`, optional `winner`, and `lineups`
  (`[(away_roster, away_name),(home_roster, home_name)]`) when `away_roster` is non-empty.
- **Template** `game_detail.html`: scoreboard shows `#sb-batter` (`:63`); batting-order
  cards iterate `lineups` and render `entry.name` + `entry.position` (`:126`–`:146`).
- **`game.js`** `updateScoreboard(state)` (`:21`) sets `#sb-batter` from
  `state.current_batter`; `handlePlay(play)` (`:125`) drives the per-roll UI. Cards are
  static (rendered once server-side).
- **`game_stat` table already exists** in Postgres (created manually by the user) with
  `UNIQUE(player_id, game_id)` and columns `ab, singles, doubles, triples, home_runs,
  strikeouts, walks, sac_hits`. `Player` and `Team` are already mapped as **unmanaged**
  models; `Game` is managed.

### Key Discoveries
- AB counting (standard scoring): an at-bat is charged for `single, double, triple,
  home_run, strikeout, groundout, flyout`; **not** for `walk` or `sacrifice`.
- The line `"1-3"` = `hits-for-at-bats` where hits = `singles+doubles+triples+home_runs`.
- The play dict is the single channel from engine to view to JS; adding the batter name
  and a per-play line to it threads the data through cleanly without new endpoints.

## Desired End State

- As each at-bat resolves, the batting player's `game_stat` row for that game is
  created-or-incremented: `ab` (when applicable) plus the matching hit/strikeout/walk/
  sac column.
- The scoreboard shows the current batter's running line, e.g. `Batting: Joe Smith
  (1-3)`, updating live each at-bat (click_all, cpu_auto, and auto_play replay).
- Each batting-order card row shows that player's running line, updating live as they bat
  and rendering correctly on page load / resume.
- Walks and sacrifices do not inflate AB; hits increment both `ab` and their column.

### Verify by:
- Play a roster-flow game; watch the current-batter `(H-AB)` tick and the card lines
  update. After several at-bats, query `game_stat` and confirm totals match the
  play-by-play (e.g. a player who singled then walked then struck out shows `ab=2,
  singles=1, walks=1, strikeouts=1`, line `1-2`).
- Resume a mid-game; cards and batter line reflect prior at-bats.

## What We're NOT Doing

- **No pitching stats**, no runs/RBI, no SB/CS — only the eight columns the table defines.
- **No sac-fly column.** A run-scoring `flyout` is charged as an AB (there is no SF
  column and the outcome key is `flyout`). Accepted scoring imperfection.
- **No backfill.** Games already in progress start their stats at zero from the first
  at-bat after this ships; finished games are not reconstructed.
- **No stats for legacy/default-lineup games** (empty rosters → no player_ids). Those
  already don't render batting-order cards.
- **No migration / schema change.** The table exists; the model is unmanaged.
- **No new engine logic** — outcome keys are mapped, not changed.

## Implementation Approach

Map outcome keys to column deltas, resolve the batter name to a `player_id` via the
batting team's roster, and upsert the per-game row. Recording lives in the views (they
hold `game` + roster); `_advance_game` only gains the batter name in its play dict. Phase
1 lands recording (backend, verifiable by querying the table). Phase 2 surfaces the line
in the scoreboard and cards, live and on load.

---

## Phase 1: GameStat model + at-bat recording

### Overview
Map the existing table, thread the batter name through the play dict, and upsert stats in
`RollView` (one at-bat) and `SimulateView` (batched).

### Changes Required

#### 1. `baseball/models.py` — unmanaged GameStat model
Add after the `Game` model:
```python
class GameStat(models.Model):
    game       = models.ForeignKey(Game, db_column="game_id",
                                   on_delete=models.DO_NOTHING,
                                   related_name="game_stats")
    player     = models.ForeignKey(Player, db_column="player_id",
                                   on_delete=models.DO_NOTHING)
    ab         = models.SmallIntegerField(default=0)
    singles    = models.SmallIntegerField(default=0)
    doubles    = models.SmallIntegerField(default=0)
    triples    = models.SmallIntegerField(default=0)
    home_runs  = models.SmallIntegerField(default=0)
    strikeouts = models.SmallIntegerField(default=0)
    walks      = models.SmallIntegerField(default=0)
    sac_hits   = models.SmallIntegerField(default=0)

    class Meta:
        managed  = False
        db_table = "game_stat"

    @property
    def hits(self) -> int:
        return self.singles + self.doubles + self.triples + self.home_runs

    @property
    def line(self) -> str:
        return f"{self.hits}-{self.ab}"
```
(`managed=False` → no migration; maps the manually-created table. `id` auto-PK maps to
the existing `id SERIAL`. The DB already enforces `UNIQUE(player_id, game_id)`.)

#### 2. `baseball/views.py` — outcome→column mapping + batter name
Add module-level mapping helpers:
```python
from .models import Game, Player, Team, GameStat, position_pools, main_position

_HIT_STAT = {"single": "singles", "double": "doubles",
             "triple": "triples", "home_run": "home_runs"}
_OTHER_STAT = {"strikeout": "strikeouts", "walk": "walks", "sacrifice": "sac_hits"}
_AB_OUTCOMES = {"single", "double", "triple", "home_run",
                "strikeout", "groundout", "flyout"}


def _stat_delta(outcome):
    """Column increments for one at-bat outcome, e.g. {'ab':1,'singles':1}."""
    delta = {}
    if outcome in _AB_OUTCOMES:
        delta["ab"] = 1
    col = _HIT_STAT.get(outcome) or _OTHER_STAT.get(outcome)
    if col:
        delta[col] = 1
    return delta


def _pid_for_name(roster, name):
    for e in roster:
        if e.get("name") == name:
            return e.get("player_id")
    return None


def _apply_delta(game, player_id, delta):
    """Upsert one player's game_stat row and apply the delta. Returns the row."""
    obj, _ = GameStat.objects.get_or_create(game=game, player_id=player_id)
    for col, n in delta.items():
        setattr(obj, col, getattr(obj, col) + n)
    obj.save()
    return obj
```

In `_advance_game`, capture the batter once at the top and include it in **both** return
dicts:
```python
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter      # NEW: before advance_lineup()
```
Add `batter=batter,` to the walk-off early-return dict and the normal return dict.

#### 3. `baseball/views.py` — record in RollView
After `play = _advance_game(gs)` and before/after saving state:
```python
        roster = game.away_roster if play["play_half"] == "top" else game.home_roster
        pid = _pid_for_name(roster, play["batter"])
        delta = _stat_delta(play["outcome"])
        if pid and delta:
            row = _apply_delta(game, pid, delta)
            play["stat_update"] = {"player_id": pid, "line": row.line}
            play["state"]["batter_line"] = _current_line(game, gs)
```
where a small helper computes the *new* current batter's line (for the scoreboard):
```python
def _current_line(game, gs):
    roster = game.away_roster if gs.half == "top" else game.home_roster
    pid = _pid_for_name(roster, gs.current_batter)
    if not pid:
        return ""
    row = GameStat.objects.filter(game=game, player_id=pid).first()
    return row.line if row else "0-0"
```

#### 4. `baseball/views.py` — record in SimulateView (batched, with per-play lines)
Maintain running per-player counters while looping so each replayed play carries the
batted player's running line and the upcoming batter's line, then flush to the DB once
per player:
```python
        plays, totals = [], {}        # totals: pid -> {col: count}
        while not gs.game_over:
            play = _advance_game(gs)
            roster = game.away_roster if play["play_half"] == "top" else game.home_roster
            pid = _pid_for_name(roster, play["batter"])
            if pid:
                acc = totals.setdefault(pid, {})
                for col, n in _stat_delta(play["outcome"]).items():
                    acc[col] = acc.get(col, 0) + n
                h = acc.get("singles", 0) + acc.get("doubles", 0) \
                    + acc.get("triples", 0) + acc.get("home_runs", 0)
                play["stat_update"] = {"player_id": pid, "line": f"{h}-{acc.get('ab', 0)}"}
            plays.append(play)
            if play["game_over"]:
                break
        for pid, cols in totals.items():
            _apply_delta(game, pid, cols)
```
(Replaces the current `plays`-building loop; rest of `SimulateView` unchanged.)

### Success Criteria

#### Automated Verification:
- [ ] `./venv/Scripts/python.exe manage.py check` exits 0
- [ ] No migration is generated for the unmanaged model:
      `./venv/Scripts/python.exe manage.py makemigrations --check --dry-run`
- [ ] Table maps and is queryable:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.models import GameStat; print('rows', GameStat.objects.count())"`
- [ ] Outcome mapping is correct (AB rules + columns):
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.views import _stat_delta; assert _stat_delta('single')=={'ab':1,'singles':1}; assert _stat_delta('home_run')=={'ab':1,'home_runs':1}; assert _stat_delta('strikeout')=={'ab':1,'strikeouts':1}; assert _stat_delta('groundout')=={'ab':1}; assert _stat_delta('flyout')=={'ab':1}; assert _stat_delta('walk')=={'walks':1}; assert _stat_delta('sacrifice')=={'sac_hits':1}; print('mapping ok')"`

#### Manual Verification:
- [ ] Create a roster-flow game, play several at-bats, then check the DB:
      `SELECT player_id, ab, singles, doubles, triples, home_runs, strikeouts, walks, sac_hits FROM game_stat WHERE game_id = <id>;` — totals match the play-by-play
- [ ] A walk shows `walks=1` with `ab` unchanged; a sacrifice shows `sac_hits=1` with
      `ab` unchanged
- [ ] auto_play (simulate) game writes one row per batter with correct totals
- [ ] Re-playing/resuming does not double-count past at-bats (only new at-bats add)

**Implementation Note**: After automated checks pass, pause for manual confirmation
before Phase 2.

---

## Phase 2: Display the H-AB line (scoreboard + cards, live)

### Overview
Render the running line server-side on load, push live updates through the play dict.

### Changes Required

#### 1. `baseball/views.py` — GameDetailView context
In `get_context_data`, when `self.object.away_roster` is set, build a per-player line map,
annotate the lineups, and compute the current batter's line:
```python
        if self.object.away_roster:
            stats = {s.player_id: s.line
                     for s in GameStat.objects.filter(game=self.object)}

            def annotate(roster):
                return [{**e, "line": stats.get(e["player_id"], "0-0")} for e in roster]

            ctx["lineups"] = [
                (annotate(self.object.away_roster), self.object.away_name),
                (annotate(self.object.home_roster), self.object.home_name),
            ]
            cur_roster = (self.object.away_roster if gs.half == "top"
                          else self.object.home_roster)
            cur_pid = _pid_for_name(cur_roster, gs.current_batter)
            ctx["current_batter_line"] = stats.get(cur_pid, "0-0") if cur_pid else ""
```
(`gs` is already loaded at the top of the method; replaces the existing `lineups` block.)

#### 2. `baseball/templates/baseball/game_detail.html`
Scoreboard batter line (`:62`–`:65`):
```html
        <p class="mt-2 mb-0">
          Batting: <strong><span id="sb-batter">{{ current_batter }}</span></strong>
          <span id="sb-batter-line" class="text-muted">{% if current_batter_line %}({{ current_batter_line }}){% endif %}</span>
          (<span id="sb-team">{{ batting_team }}</span>)
        </p>
```
Card rows (`:135`–`:138`) — add the line, keyed by player for live updates:
```html
        <li class="list-group-item d-flex justify-content-between">
          <span>{{ entry.name }}</span>
          <span>
            <small id="stat-{{ entry.player_id }}" class="text-primary fw-semibold me-2">{{ entry.line }}</small>
            <small class="text-muted">{{ entry.position }}</small>
          </span>
        </li>
```

#### 3. `baseball/static/baseball/js/game.js`
In `updateScoreboard(state)`, update the batter line if present:
```javascript
    const lineEl = document.getElementById('sb-batter-line');
    if (lineEl) lineEl.textContent = state.batter_line ? `(${state.batter_line})` : '';
```
In `handlePlay(play)`, update the batted player's card cell:
```javascript
    if (play.stat_update) {
        const cell = document.getElementById('stat-' + play.stat_update.player_id);
        if (cell) cell.textContent = play.stat_update.line;
    }
```

### Success Criteria

#### Automated Verification:
- [ ] `./venv/Scripts/python.exe manage.py check` exits 0
- [ ] Detail page renders for a roster-flow game without template errors (smoke):
      `./venv/Scripts/python.exe manage.py shell -c "from django.test import Client; from django.contrib.auth import get_user_model; from baseball.models import Game; u=get_user_model().objects.filter(baseball_games__isnull=False).first(); g=Game.objects.filter(owner=u).first(); c=Client(); c.force_login(u); r=c.get(f'/baseball/{g.pk}/'); print('status', r.status_code); assert r.status_code==200" `

#### Manual Verification:
- [ ] Scoreboard shows `Batting: <name> (H-AB)` and the value ticks each at-bat
- [ ] Each batting-order card row shows the player's H-AB; the batted player's cell
      updates live as he bats (click_all, cpu_auto, and auto_play replay)
- [ ] Resuming a mid-game shows correct lines on load for both cards and current batter
- [ ] A legacy/default game (no roster) renders normally with no line and no JS errors

**Implementation Note**: After automated checks pass, pause for manual confirmation.

---

## Testing Strategy

### Manual Testing Steps
1. New roster game → click_all. Single with the leadoff man → card shows `1-1`, batter
   line for the next man `0-0`. Walk the next man → his card `0-1`? No: walk → `0-0` with
   `ab` unchanged (walks don't add AB) — confirm card stays `0-0` but a later DB check
   shows `walks=1`.
2. Strike a man out → card `0-1`. Homer → `1-1` and the HR sound still plays.
3. auto_play a full game → every batter's card has a plausible line; DB rows match.
4. Resume an active game mid-way → lines render correctly from the DB on load.
5. Open a legacy game (no roster) → no lines, no console errors.

## Performance Considerations
`RollView` adds one `get_or_create` + one `save` per at-bat (negligible). `SimulateView`
accumulates in memory and flushes one upsert per distinct batter (≈9–18 rows) at the end
rather than per at-bat. `GameDetailView` adds one `game_stat` query per page load.

## Migration Notes
None. `game_stat` exists; `GameStat` is `managed=False`. `makemigrations --check` must
report no changes.

## References
- Research: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- `baseball/views.py:43` — `_advance_game`; `:194` `RollView`; `:209` `SimulateView`;
  `:177` `GameDetailView.get_context_data`
- `baseball/engine.py:39` — `current_batter`; `:283` `resolve_dice_roll` / `DICE_TABLE`
- `baseball/models.py:235` — `Game` (managed); `Player`/`Team` unmanaged precedent
- `baseball/templates/baseball/game_detail.html:62,126` — scoreboard batter + cards
- `baseball/static/baseball/js/game.js:21,125` — `updateScoreboard`, `handlePlay`
