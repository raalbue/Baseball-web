# All-Star Mode, Player Search, and Announcer Commentary — Implementation Plan

## Overview

Three additions to the roster-building and live-game flow:

1. **All-Star mode**: pick "AL All-Stars" or "NL All-Stars" as your team, drawing eligible players from every team in that league instead of one real team's roster.
2. **Player search**: a type-to-filter search box on each position's player dropdown, so picking from a large All-Star pool is usable.
3. **Announcer commentary**: a second, randomized flavor line appended to each play-by-play entry, alongside the existing mechanical message.

## Current State Analysis

- `Team` (`baseball/models.py:27-47`) is an **unmanaged** model backed by a pre-existing Postgres table (`db_table='team'`, `managed=False`) — Django does not own its DDL. All 30 real MLB teams were seeded via raw `RunSQL` in `baseball/migrations/0001... /0006_seed_stadiums_teams.py:38-71`, and `Team.conference` already holds `"American League"` / `"National League"` per team. There is no separate `League` model.
- Roster building is fully server-rendered, whole-page-reload — no SPA/AJAX. `Page1View`/`Page2View`/`Player2JoinView` (`baseball/views.py:278-670`) all build a `SideRosterForm` (`baseball/forms.py:20-78`) scoped to **one** `Team` via `position_pools(team)` (`baseball/models.py:114-124`), which does `Player.objects.filter(team=team)`.
- The team `<select>` (`form.team`, id `id_team`) already auto-submits on change (`document.getElementById('id_team').addEventListener('change', ...)`, present in `game_setup.html:118-121`, `game_roster.html:67-70`, `game_join.html:64-67`) — choosing a team is already a single round trip that re-renders the position dropdowns.
- `SavedRoster` (`baseball/models.py:350-367`) has a plain `Team` FK — any `Team` row (real or pseudo) works with saved rosters for free.
- Play resolution (`baseball/views.py:190-248`, `_advance_game`) already returns a `message` string built by `engine.py`'s `apply_in_play`/`apply_walk`/`apply_strikeout`/`apply_sacrifice` (e.g. `"{batter} crushes a 2-run HOME RUN!"`, `engine.py:243-346`). This same play `dict` is: (a) `JsonResponse`'d directly to the browser (`views.py:783`, `814`), (b) appended verbatim into `Game.play_log` (`views.py:779`, `811` — a `JSONField`), and (c) read back out of `play_log` for the server-rendered play-by-play on initial page load (`views.py:748-752`, `game_detail.html:274-285`). One injection point in `_advance_game` reaches all three call sites.
- `game.js` (already contains uncommitted work for sounds/fireworks/runner animation/scoreboard — the `2026-07-23-game-effects-scoreboard-streaky-player.md` research doc is stale on this). `appendPlay()` (`game.js:211-228`) renders each play row client-side during live play; `game_detail.html:274-285` renders the same rows server-side on load. Both need the same new field.
- `baseball/params.py` already holds the outcome vocabulary: `DICE_TABLE`/`DICE_TABLE_STREAKY` (`params.py:75-109`) and `stat_based_weights()` (`engine.py:349-368`) only ever produce one of: `walk, strikeout, single, double, triple, home_run, groundout, flyout, sacrifice`, plus `single_error` (streaky-dice-table only, `params.py:105-109`).
- `baseball/stadiums.py:21-35` (`stadium_context`) keys off `team.name` (e.g. `"Yankees"`) into `TEAM_SLUGS`, falling back to `_STADIUMS["generic"]` for any unmatched name — an All-Star pseudo-team will hit this fallback automatically, no changes needed.

### Key Discoveries

- Because `position_pools(team)` (`models.py:114-124`) is the **only** place that turns a `Team` into a player pool, and it's called uniformly from `forms.py:31`, `views.py:110` (`auto_fill_roster`), and `views.py:155` (`_apply_saved_roster`), branching its query on the team is enough to make every existing call site (form rendering, CPU auto-roster fill, saved-roster re-apply) League-aware with no call-site changes.
- The team `<select>` already drives a full re-render round trip on change, so All-Star teams can be added as two more rows in that same dropdown — no new mode toggle, no new page, no new session/state fields.
- Because the play `dict` returned by `_advance_game` flows unmodified into persistence and both render paths, adding one new key there is sufficient for commentary — no `Game`/`GameState` schema changes needed.

## Desired End State

- The team dropdown on `game_setup.html`, `game_roster.html`, and `game_join.html` includes two additional entries: **"American League All-Stars"** and **"National League All-Stars"**.
- Picking one of those populates each position's dropdown with every eligible player from that league's real teams (not one team's roster), each with a search box above it that filters the dropdown's options as you type, auto-selecting when exactly one match remains.
- Regular (single real-team) roster selection is visually unchanged — no search box appears, since those pools are already small.
- Every play-by-play line (both live-play and server-rendered-on-load) shows the existing mechanical message plus a second, randomized announcer-style flavor line for that play's outcome.
- Saved rosters, CPU-auto opponent picking, and multiplayer team picking all work identically for All-Star pseudo-teams as they do for real teams, with no special-casing required at those call sites.

### Verification
- Start a new game, pick "American League All-Stars" as your team: position dropdowns show players from multiple AL teams (verify by the `(TEAM)` suffix in each option's label), not just one team.
- Type a partial last name into a position's search box: the dropdown narrows to matching options only; typing to a single remaining match auto-selects it.
- Pick a normal single real team: no search box appears, dropdown behaves exactly as before.
- Play a game through to completion: every play-by-play row shows the original message plus a second flavor line; reload the page — the same commentary persists (it was saved into `play_log`, not regenerated).

## What We're NOT Doing

- No new `League` model, no schema/column changes to the unmanaged `team`/`player` tables.
- No change to `SideRosterForm.clean()` / `roster_for()` validation logic — All-Star picks are validated exactly like real-team picks (still one player per position, still a real `Player` row).
- No dedicated "announcer" UI banner — commentary is log-only, appended to the existing play-by-play row text (per product decision).
- No replacement of the existing mechanical play message — commentary supplements it, doesn't replace it (per product decision).
- No All-Star-specific stadium art — falls back to the existing generic ballpark SVG.
- No changes to CPU-auto or multiplayer opponent-exclusion logic — the existing `team_id`-based exclusion already prevents picking the identical pseudo-team on both sides while allowing AL vs. NL All-Star matchups.

## Implementation Approach

Three independent phases, each self-contained and separately testable:

1. **Data + pool logic** — seed the two All-Star pseudo-teams and make `position_pools`/`auto_fill_roster` league-aware.
2. **Search UI** — a small shared template partial + one vanilla-JS filter snippet, wired into the three roster-building templates, active only when the chosen team is an All-Star pseudo-team.
3. **Announcer commentary** — a static phrase-pool in `params.py`, picked once per play in `_advance_game`, rendered in the two existing play-by-play render paths.

---

## Phase 1: All-Star Teams and League-Wide Player Pools

### Overview
Seed two pseudo-`Team` rows and make the position-pool/auto-roster logic pull from every team in a league when the chosen team is one of them.

### Changes Required

#### 1. Migration — seed the two pseudo-teams
**File**: `baseball/migrations/0017_seed_all_star_teams.py` (new)
**Changes**: `RunSQL` insert, following the exact pattern of `0006_seed_stadiums_teams.py`. Mark them via `division='All-Star'` (a value no real team has) — this is the single source of truth used everywhere else to detect an All-Star pseudo-team. Point `stadium_id` at existing real stadium rows (1, 2) to avoid any risk of a `NOT NULL` constraint on that column — `stadium_context()` never uses this FK (it keys off `team.name` instead), so the value is cosmetic only.

```python
from django.db import migrations

TEAMS_SQL = """
INSERT INTO team (team_id, name, city, abbreviation, conference, division, head_coach, stadium_id, founded_year) VALUES
(31, 'All-Stars', 'American League', 'ALAS', 'American League', 'All-Star', NULL, 1, NULL),
(32, 'All-Stars', 'National League', 'NLAS', 'National League', 'All-Star', NULL, 2, NULL)
ON CONFLICT (team_id) DO NOTHING;
"""

REVERSE_SQL = "DELETE FROM team WHERE team_id IN (31, 32);"


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0016_savedroster"),
    ]
    operations = [
        migrations.RunSQL(sql=TEAMS_SQL, reverse_sql=REVERSE_SQL),
    ]
```

#### 2. Models — league-aware player pool
**File**: `baseball/models.py`
**Changes**: Add `is_all_star_team()` and `players_for_team()` helpers; use the latter in `position_pools()`.

```python
def is_all_star_team(team) -> bool:
    return bool(team) and team.division == "All-Star"


def players_for_team(team):
    """All eligible players for a roster pick: one real team's roster, or
    every player across the league for an All-Star pseudo-team."""
    if is_all_star_team(team):
        return Player.objects.filter(team__conference=team.conference)
    return Player.objects.filter(team=team)


def position_pools(team) -> dict:
    pools = {c: [] for c in FIELDING_COLS}
    pools["DH"] = []
    for p in players_for_team(team):
        for code, col in FIELDING_COLS.items():
            if (getattr(p, col) or 0) > 0:
                pools[code].append(p.player_id)
        is_pitcher = (p.g_sp or 0) > 0 or (p.g_rp or 0) > 0
        if not is_pitcher or (p.g_dh or 0) > 0:
            pools["DH"].append(p.player_id)
    return pools
```

#### 3. Views — league-aware CPU auto-roster fill
**File**: `baseball/views.py`
**Changes**: `auto_fill_roster` currently does its own `Player.objects.filter(team=team)` for the "prefer main position" map (`views.py:110-112`); switch it to the same `players_for_team()` helper so a CPU-controlled All-Star team also prefers each player's real main position.

```python
from .models import (
    Game, Player, Team, GameStat, PlayerCareerStats, SavedRoster,
    position_pools, main_position, players_for_team,
)
...
def auto_fill_roster(team):
    pools = position_pools(team)
    primary = {p.player_id: main_position(p)
               for p in players_for_team(team)}
    ...
```

### Success Criteria

#### Automated Verification
- [x] Migration applies cleanly: `python manage.py migrate baseball`
- [x] Migration reverses cleanly: `python manage.py migrate baseball 0016`, then forward again
- [x] `python manage.py check` passes
- [x] Existing roster/game-setup tests (if any) still pass: `python manage.py test baseball` (no tests exist in the repo — 0 collected, pre-existing)

#### Manual Verification
- [x] In the Django shell, `Team.objects.get(pk=31).conference == "American League"` and `position_pools(Team.objects.get(pk=31))` returns players from more than one distinct `team_id`.
- [x] Starting a CPU-auto game with an All-Star pseudo-team as the CPU opponent produces a full 10-slot roster with no missing positions.
- [x] A saved roster for a real team still loads correctly (regression check on `players_for_team`'s real-team branch).

---

## Phase 2: Player Search on Position Dropdowns

### Overview
When the chosen team is an All-Star pseudo-team, show a text filter above each position `<select>` that narrows its options as you type and auto-selects on a single remaining match. Regular team selection is untouched.

### Changes Required

#### 1. Forms — expose an `all_star` flag and disambiguating labels
**File**: `baseball/forms.py`
**Changes**: Import `is_all_star_team`; set `self.all_star` in `SideRosterForm.__init__`; use a `ModelChoiceField` subclass with a team-suffixed label only when `all_star` is true (disambiguates same-named players across teams in the pooled list).

```python
from .models import Game, Team, Player, position_pools, is_all_star_team


class _PlayerChoiceField(forms.ModelChoiceField):
    """Player choice with a trailing team abbreviation, for All-Star pools
    where multiple teams' players are mixed together."""
    def label_from_instance(self, obj):
        return f"{obj} ({obj.team_abbrev})" if obj.team_abbrev else str(obj)


class SideRosterForm(forms.Form):
    def __init__(self, *args, team=None, team_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_star = is_all_star_team(team)
        self.fields["team"] = forms.ModelChoiceField(
            queryset=team_queryset if team_queryset is not None else Team.objects.all(),
            label="Team",
            empty_label="— select team —",
            widget=forms.Select(attrs={"class": "form-select", "id": "id_team"}),
        )
        pools = position_pools(team) if team else {}
        field_cls = _PlayerChoiceField if self.all_star else forms.ModelChoiceField
        for code, label in POSITIONS:
            ids = pools.get(code, [])
            qs = Player.objects.filter(player_id__in=ids) if team else Player.objects.none()
            self.fields[code] = field_cls(
                queryset=qs,
                label=label,
                empty_label=f"— select {label.lower()} —",
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        ...  # "order" field unchanged
```

#### 2. New shared partial — search box + field
**File**: `baseball/templates/baseball/_position_field.html` (new)
**Changes**: Renders the search input (only in All-Star mode) followed by the field and its errors, replacing the repeated `{{ field }} {% if field.errors %}...{% endif %}` snippet in three templates.

```html
{% if all_star %}
<input type="text" class="form-control form-control-sm mb-1 player-search"
       data-select="{{ field.id_for_label }}" placeholder="Search players…">
{% endif %}
{{ field }}
{% if field.errors %}<div class="text-danger small">{{ field.errors }}</div>{% endif %}
```

#### 3. Wire the partial into the three roster templates
**Files**: `baseball/templates/baseball/game_setup.html`, `baseball/templates/baseball/game_roster.html`, `baseball/templates/baseball/game_join.html`
**Changes**: Replace the pitcher-field and each batting-field's `{{ field }} {% if field.errors %}...{% endif %}` with the include, and add one filter-wiring `<script>` snippet (once per template, alongside the existing inline script block).

`game_setup.html` pitcher block (`game_setup.html:84-85`) becomes:
```html
{% include "baseball/_position_field.html" with field=form.pitcher_field all_star=form.all_star %}
```
Batting loop (`game_setup.html:100-101`) becomes:
```html
{% include "baseball/_position_field.html" with field=field all_star=form.all_star %}
```
Same substitution in `game_roster.html` (lines 33-34, 49-50) and `game_join.html` (lines 32-33, 44-45).

Append to each template's existing `<script>` block:
```javascript
document.querySelectorAll('.player-search').forEach((input) => {
    const select = document.getElementById(input.dataset.select);
    if (!select) return;
    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        const matches = [];
        Array.from(select.options).forEach((opt) => {
            if (!opt.value) return;  // keep the "— select —" placeholder visible
            const isMatch = !q || opt.text.toLowerCase().includes(q);
            opt.hidden = !isMatch;
            if (isMatch) matches.push(opt);
        });
        if (q && matches.length === 1) {
            select.value = matches[0].value;
            select.dispatchEvent(new Event('change'));
        }
    });
});
```

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes (template syntax valid)
- [x] `python manage.py test baseball` passes (no tests exist in the repo — 0 collected, pre-existing)
- [x] Smoke-tested via `Client` (not a persisted test, ad hoc verification): All-Star pick on `game_setup.html`/`game_roster.html`/`game_join.html` each render exactly 10 `data-select=` search inputs with team-abbrev-suffixed option labels (e.g. `(NYY)`); real-team pick on the same pages renders zero.

#### Manual Verification
- [x] Pick "American League All-Stars": every position dropdown shows options labeled `Last, First (ABB)`, sourced from multiple team abbreviations.
- [x] Search box appears above each position dropdown only in All-Star mode; typing filters the list live.
- [x] Typing a name unique to one player auto-selects it (dropdown value changes without a click).
- [x] Pick a normal single MLB team: no search box renders; dropdowns behave exactly as before this change.
- [x] Repeat on `game_roster.html` (Player 1 second-page flow) and `game_join.html` (Player 2 invite flow).
- [x] Submit a full All-Star roster and start a game; confirm no validation errors and the roster displays correctly on `game_detail.html`.

---

## Phase 3: Announcer Commentary

### Overview
Add a second, randomized flavor line to every play, generated once server-side and persisted with the play (so replays/reloads show the same line, not a freshly re-rolled one).

### Changes Required

#### 1. Params — commentary phrase pool
**File**: `baseball/params.py`
**Changes**: Add `COMMENTARY_LINES`, keyed by every outcome string `_advance_game` can produce (`walk, strikeout, single, double, triple, home_run, groundout, flyout, sacrifice, single_error`). Each entry a list of `{batter}`-templated strings.

```python
# --- Announcer commentary -----------------------------------------------------
# A second, randomized flavor line shown alongside the mechanical play message.
COMMENTARY_LINES = {
    "home_run": [
        "Get up, get up, get outta here! {batter} goes deep!",
        "Absolutely crushed — {batter} sends one a long way!",
        "That ball is gone — {batter} with the moonshot!",
        "{batter} takes a well-earned curtain call!",
        "No doubt about that one off the bat of {batter}!",
    ],
    "triple": [
        "{batter} legs it out for a stand-up triple!",
        "Into the gap and {batter} is rolling — triple!",
        "Off the wall and {batter} cruises into third!",
        "{batter} never stops running — three-bagger!",
        "{batter} makes that look easy — triple!",
    ],
    "double": [
        "{batter} rips one into the corner for a double!",
        "Line drive into the gap — {batter} stands on second!",
        "Base hit, and {batter} stretches it into two!",
        "That's got extra bases written all over it, {batter} doubles!",
        "{batter} carves out a two-bagger!",
    ],
    "single": [
        "{batter} slaps one through the infield for a base hit!",
        "Clean single up the middle for {batter}!",
        "{batter} finds a hole for a base hit!",
        "{batter} pokes one the other way for a single!",
        "Ground ball finds the outfield grass — single for {batter}!",
    ],
    "walk": [
        "{batter} works the count and draws a walk!",
        "Ball four — {batter} takes the free pass!",
        "Patient at-bat there, {batter} strolls to first!",
        "{batter} wasn't giving in — walk!",
        "Four wide ones, {batter} jogs down to first!",
    ],
    "strikeout": [
        "{batter} is caught looking — strike three!",
        "Swing and a miss — {batter} strikes out!",
        "{batter} couldn't catch up to that one!",
        "Down goes {batter} on strikes!",
        "{batter} fans — back to the dugout!",
    ],
    "groundout": [
        "{batter} beats it into the dirt — routine groundout.",
        "Chopper to the infield, {batter} is out at first.",
        "{batter} rolls one over — can't beat the throw.",
        "Ground ball, {batter} hustles but comes up short.",
        "Easy play on that grounder from {batter}.",
    ],
    "flyout": [
        "{batter} skies one — caught in the outfield.",
        "Lazy fly ball, {batter} is retired.",
        "{batter} gets under it — routine out.",
        "Deep, but not deep enough — {batter} flies out.",
        "{batter} pops it up, easy out.",
    ],
    "sacrifice": [
        "{batter} gives himself up to move the runner along.",
        "Smart at-bat — {batter} sacrifices for the team.",
        "{batter} puts the ball in play just to advance the runner.",
        "That's a professional at-bat from {batter}.",
        "{batter} trades an out to push the runner up a base.",
    ],
    "single_error": [
        "{batter} reaches on a wild throw — error on the play!",
        "The defense boots it — {batter} is aboard on the error!",
        "{batter} beats it out after a bobble in the infield!",
        "Miscue on defense lets {batter} reach base!",
        "{batter} reaches after the defense couldn't handle it!",
    ],
}
```

#### 2. Views — pick and attach commentary
**File**: `baseball/views.py`
**Changes**: Import `random` and `COMMENTARY_LINES`; pick one line right after `outcome` is known in `_advance_game`, and include `commentary` in both returned dicts (the walk-off early return and the normal return).

```python
import random
...
from .params import STAT_BASED_MIN_AB, COMMENTARY_LINES
...
def _advance_game(gs: GameState, roster) -> dict:
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
    commentary = random.choice(COMMENTARY_LINES[outcome]).format(batter=batter)
    gs.reset_count()
    gs.advance_lineup()

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.close_half()
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg, commentary=commentary,
                    method=method, play_half=play_half, play_inning=play_inning,
                    batter=batter, half_over=True, game_over=True,
                    streaky=streaky, moves=gs.last_moves,
                    state=_state_snapshot(gs))

    if gs.outs >= 3:
        ...  # unchanged

    return dict(d1=d1, d2=d2, outcome=outcome, message=msg, commentary=commentary,
                method=method, play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=half_over, game_over=gs.game_over,
                streaky=streaky, moves=gs.last_moves,
                state=_state_snapshot(gs))
```

#### 3. Templates — render commentary in the server-side play log
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Append the commentary line inside the existing play `<p>` (around line 277). Guard with `default:""` for any pre-existing `play_log` entries saved before this change (so old games don't error on a missing key).

```html
⚾ [{{ play.d1 }}][{{ play.d2 }}] &mdash; {{ play.message }}
{% if play.commentary %}<br><span class="text-muted fst-italic">{{ play.commentary }}</span>{% endif %}
{% if play.method|default:"dice" == "dice" %}(🎲){% else %}(📊){% endif %}{% if play.streaky %} 🔥{% endif %}
```

#### 4. JS — render commentary in the live play log
**File**: `baseball/static/baseball/js/game.js`
**Changes**: `appendPlay()` (`game.js:222-227`) — append commentary on its own line, guarded the same way.

```javascript
function appendPlay(play) {
    const log = document.getElementById('play-log');
    const empty = document.getElementById('log-empty');
    if (empty) empty.remove();
    if (!inExtraInnings && play.play_inning > TOTAL_INN) {
        inExtraInnings = true;
        const sep = document.createElement('p');
        sep.className = 'text-center fw-bold text-danger my-2';
        sep.textContent = '========= E X T R A   I N N I N G S =========';
        log.prepend(sep);
    }
    const p = document.createElement('p');
    p.className = 'mb-1';
    const half = play.play_half === 'top' ? 'TOP' : 'BOT';
    let html = `[${half} ${play.play_inning}] ⚾ [${play.d1}][${play.d2}] — ${play.message}`;
    if (play.commentary) html += `<br><span class="text-muted fst-italic">${play.commentary}</span>`;
    html += ` ${methodTag(play.method)}${streakyTag(play.streaky)}`;
    p.innerHTML = html;
    log.prepend(p);
    log.scrollTop = 0;
}
```

Note: this switches `appendPlay` from `textContent` to `innerHTML` for this element. `play.message`/`play.commentary` are server-generated from fixed template strings plus a batter name interpolation — batter names come from `LINEUP`/`Player` data, not free-form user input, so this is not introducing an XSS vector in practice, but keep the interpolated pieces limited to those two trusted fields.

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist in the repo — 0 collected, pre-existing)
- [x] `KeyError` never raised for any of the 10 possible `outcome` values: `python manage.py shell -c "from baseball.params import COMMENTARY_LINES, DICE_TABLE_STREAKY; assert set(DICE_TABLE_STREAKY.values()) | {'sacrifice'} <= set(COMMENTARY_LINES)"`
- [x] Fuzz-ran `_advance_game` 300x directly: every play returned a non-empty `commentary`, no `KeyError`, 9/10 outcomes hit (the 10th, `single_error`, is streaky-only, already covered by the assertion above).
- [x] Smoke-tested end-to-end via `Client`: `RollView` POST returns `commentary` in its JSON, it's persisted into `Game.play_log`, and `game_detail.html` renders the `fst-italic` commentary span on reload.

#### Manual Verification
- [ ] Play a full game in `click_all` mode: every play row shows a commentary line under the mechanical message.
- [ ] Play in `auto_play` (simulate) mode: same, for every play in the replayed log.
- [ ] Reload a `game_detail.html` page mid-game: server-rendered rows show the same commentary as when they were first appended live (proves it's persisted, not re-rolled on read).
- [ ] Trigger a home run, a strikeout, and a walk at minimum — confirm distinct, outcome-appropriate flavor text for each (not the same line every time, thanks to randomization).

---

## Testing Strategy

### Unit Tests
- `position_pools(all_star_team)` returns player IDs spanning more than one `team_id`.
- `is_all_star_team()` returns `True` only for `division == "All-Star"` rows.
- `SideRosterForm(team=all_star_team).all_star is True`; `SideRosterForm(team=real_team).all_star is False`.
- `_advance_game` result dict always contains a non-empty `commentary` string for every outcome in `DICE_TABLE_STREAKY.values()` plus `"sacrifice"`.

### Manual Testing Steps
1. New game → pick American League All-Stars → confirm multi-team player pools + search boxes.
2. New game → pick a single real team (e.g. Yankees) → confirm no search boxes, unchanged behavior.
3. CPU-auto mode with All-Star opponent → confirm full auto-filled roster.
4. Multiplayer: Player 1 picks NL All-Stars, Player 2 picks AL All-Stars → confirm both can independently search/pick, game starts normally.
5. Save an All-Star roster, start a new game, load it back → confirm picks restore correctly.
6. Play a full game, watch for commentary on every play type (hit, out, walk, strikeout, sacrifice, home run).

## Performance Considerations

`players_for_team()` for an All-Star pseudo-team queries ~15 teams' worth of players instead of one (still a single indexed `WHERE conference = ...` query, not N+1) — negligible cost at this data scale (hundreds of rows, not thousands).

## Migration Notes

`0017_seed_all_star_teams.py` uses `ON CONFLICT (team_id) DO NOTHING`, matching the idempotent style of `0006_seed_stadiums_teams.py` — safe to re-run. Reverse migration deletes both seeded rows; note this would orphan (`SET_NULL`) any `Game`/`SavedRoster` rows that reference them, same behavior as deleting any other team.

## References

- Background research: `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md` (note: stale on sounds/fireworks/runner-animation/scoreboard, which are now implemented in the working tree; still accurate on engine/outcome-resolution architecture)
- Team/League data: `baseball/models.py:27-47`, `baseball/migrations/0006_seed_stadiums_teams.py:38-71`
- Roster form/pool logic: `baseball/forms.py:20-78`, `baseball/models.py:114-124`
- Roster-building views: `baseball/views.py:106-124`, `278-670`
- Play resolution / commentary injection point: `baseball/views.py:190-248`, `baseball/engine.py:243-346`, `baseball/params.py:75-109`
- Play-by-play rendering: `baseball/templates/baseball/game_detail.html:268-287`, `baseball/static/baseball/js/game.js:211-228`
- Stadium fallback: `baseball/stadiums.py:21-35`
