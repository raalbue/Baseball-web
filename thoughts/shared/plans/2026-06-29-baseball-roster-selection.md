# Baseball Roster Selection — Implementation Plan

## Overview

After picking away/home teams on the game-setup screen, insert a new **roster
screen** where the user fills 10 position dropdowns per team (Pitcher, Catcher,
1B, 2B, SS, 3B, LF, CF, RF, DH). Each dropdown lists that team's players from the
`player` table. The away (CPU) team's dropdowns are pre-filled with an auto-picked
roster that the user may edit; the home team is chosen by the user. The 9
non-pitcher slots become the batting order and their real player names are shown
in the play-by-play. The setup screen's "Play Ball!" button is renamed
"Make Roster" and now leads to the roster screen; the roster screen's "Play Ball!"
creates the game.

## Current State Analysis

- **Setup flow today** (`baseball/views.py:81` `GameCreateView`, a `CreateView`):
  `GameSetupForm` (teams + innings + mode) → `form_valid` builds a `GameState`,
  creates the `Game`, redirects to detail. The submit button is "Play Ball!"
  (`game_setup.html:50`).
- **Engine batter names are fixed** (`engine.py:36` `current_batter`): indexes into
  `params.LINEUP`, a hard-coded list of 9 names (`params.py:24`). `GameState`
  (`engine.py:11`) has no concept of a per-team roster.
- **State serialization** (`models.py:246` `state_to_dict` / `:259` `state_from_dict`)
  round-trips 13 GameState attrs; no lineup data.
- **`Player` model** (`models.py:50`, unmanaged, `db_table='player'`) has 1693 rows
  across 30 teams (~56–65 per team). `Player.position` is **null for every row**, so
  dropdowns cannot be filtered by position — every position dropdown lists the whole
  team roster. `Player.__str__` returns `"First Last"`.
- **`Team`** FK already on `Game` (`models.py:226` `away_team`/`home_team`), set at
  creation in `form_valid` (`views.py:89`).
- Routes: `baseball-list`, `baseball-new`, `baseball-detail`, `baseball-roll`,
  `baseball-simulate` (`urls.py`).

## Desired End State

- `/baseball/new/` shows the existing setup form; its submit button reads
  **"Make Roster"** and, on valid submit, goes to a new roster screen (no `Game`
  row created yet).
- `/baseball/roster/` shows two columns (Away / Home), each with 10 labeled
  position dropdowns populated from the respective team's players. Away dropdowns
  are pre-filled with an auto-picked roster and remain editable; home dropdowns
  start empty. A "Play Ball!" button submits.
- On submit, the rosters are validated (all 10 chosen per side, no player used twice
  on the same side), the `Game` is created with both rosters persisted, and the
  user is redirected to game detail.
- Play-by-play and the scoreboard show the **real selected player names** for the 9
  batting slots, in the order C,1B,2B,SS,3B,LF,CF,RF,DH.
- Existing/old games (no roster stored) keep working — `current_batter` falls back
  to `params.LINEUP`.

### Verify by:
- `/baseball/new/` button text is "Make Roster"; submitting it lands on
  `/baseball/roster/` with no new `Game` in the DB.
- Roster screen: away dropdowns pre-filled, home empty; both list only their team's
  players.
- Picking the same player for two positions on one team shows a validation error.
- After "Play Ball!": detail scoreboard's current batter is one of the home/away
  selected players (not "Diaz"/"Okafor" from `params.LINEUP`).
- An old game created before this change still plays with the fallback lineup.

## What We're NOT Doing

- **No position eligibility filtering.** `Player.position` is null, and the user
  chose "all the team's players in every dropdown." A catcher can be listed (and
  chosen) at shortstop. No use of the `g_c`/`g_1b`/… games-by-position columns.
- **No use of the unmanaged `lineup` / `game_participant` tables.** They are keyed
  to the raw MLB `game` table, not the web `baseball_game`; rosters are stored as
  JSON on `Game` instead.
- **No batting-order reordering UI.** Order is fixed (the 9 non-pitcher positions in
  canonical order). This only affects which name displays; dice outcomes are
  name-independent.
- **No player stats / ratings affecting gameplay.** The dice engine is unchanged;
  rosters are cosmetic (display names only).
- **No editing a roster after the game is created.**

## Implementation Approach

Build bottom-up so the app stays runnable at each phase:

1. Teach the engine and `Game` model to carry per-team lineups (with a safe fallback)
   — no UI change yet, old games unaffected.
2. Add the roster form, position constants, and auto-fill helper — pure Python.
3. Rewire the two-step flow (setup → roster → create) using the session to carry
   setup choices.
4. Templates.

---

## Phase 1: Engine + Model Support for Per-Team Lineups

### Overview
`GameState` learns optional `away_lineup`/`home_lineup` (each a list of 9 names);
`current_batter` uses the batting team's lineup, falling back to `params.LINEUP`.
State (de)serialization carries the lineups. `Game` gains `away_roster`/`home_roster`
JSON fields storing the full 10-slot picks.

### Changes Required

#### 1. `baseball/engine.py` — `GameState.__init__` + `current_batter`

```python
def __init__(self, away_name, home_name, total_innings,
             away_lineup=None, home_lineup=None):
    self.away_name = away_name
    self.home_name = home_name
    self.total_innings = total_innings
    # 9-name batting orders; fall back to the fixed demo lineup.
    self.away_lineup = list(away_lineup) if away_lineup else list(LINEUP)
    self.home_lineup = list(home_lineup) if home_lineup else list(LINEUP)
    self.inning = 1
    # ... rest unchanged ...
```

```python
@property
def current_batter(self) -> str:
    lineup = self.away_lineup if self.half == "top" else self.home_lineup
    idx = self.away_idx if self.half == "top" else self.home_idx
    return lineup[idx % len(lineup)]
```

#### 2. `baseball/models.py` — serialize lineups in state

In `state_to_dict`, add:
```python
"away_lineup": s.away_lineup, "home_lineup": s.home_lineup,
```

In `state_from_dict`, pass them to the constructor (with `.get` fallback for old
state dicts that lack the keys):
```python
gs = GameState(
    d["away_name"], d["home_name"], d["total_innings"],
    away_lineup=d.get("away_lineup"), home_lineup=d.get("home_lineup"),
)
```
(The rest of `state_from_dict` is unchanged.)

#### 3. `baseball/models.py` — add roster JSON fields to `Game`

After `home_team` (around `models.py:233`):
```python
away_roster = models.JSONField(default=list)  # [{position, player_id, name}, ...]
home_roster = models.JSONField(default=list)
```
Each list holds 10 dicts in canonical position order; `away_lineup`/`home_lineup`
in `state` are the derived 9-name batting orders (pitcher excluded).

#### 4. Migration
```
./venv/Scripts/python.exe manage.py makemigrations baseball
./venv/Scripts/python.exe manage.py migrate
```

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] `./venv/Scripts/python.exe manage.py makemigrations baseball --check` exits 0 after running
- [x] Lineup round-trips and falls back:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.engine import GameState; from baseball.models import Game; gs=GameState('A','H',3,away_lineup=['X','Y'],home_lineup=['Z']); d=Game.state_to_dict(gs); gs2=Game.state_from_dict(d); assert gs2.away_lineup==['X','Y']; gs3=GameState('A','H',3); assert len(gs3.home_lineup)==9; print('ok')"`
- [x] Old-state fallback:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.models import Game; from baseball.engine import GameState; gs=GameState('A','H',3); d=Game.state_to_dict(gs); d.pop('away_lineup'); d.pop('home_lineup'); gs2=Game.state_from_dict(d); print(gs2.current_batter)"` prints a `params.LINEUP` name

#### Manual Verification:
- [ ] An existing game opened from the list still plays (fallback lineup)

**Implementation Note**: Pause for manual confirmation before Phase 2.

---

## Phase 2: Roster Form, Position Constants, Auto-Fill Helper

### Overview
Add the canonical position list, a dynamically-built `RosterForm` with 20 player
dropdowns (10 per side, querysets scoped to each team), per-side
duplicate-player validation, and a helper that auto-picks a 10-player roster for a
team.

### Changes Required

#### 1. `baseball/forms.py` — position constants + `RosterForm`

```python
from django import forms
from .models import Game, Team, Player   # add Player

# Canonical position order. Pitcher is defense-only (does not bat).
POSITIONS = [
    ("P",  "Pitcher"),
    ("C",  "Catcher"),
    ("1B", "First Base"),
    ("2B", "Second Base"),
    ("SS", "Shortstop"),
    ("3B", "Third Base"),
    ("LF", "Left Field"),
    ("CF", "Center Field"),
    ("RF", "Right Field"),
    ("DH", "Designated Hitter"),
]
BATTING_POSITIONS = [code for code, _ in POSITIONS if code != "P"]  # 9 slots


class RosterForm(forms.Form):
    """20 player dropdowns: away_<POS> and home_<POS> for each position."""

    def __init__(self, *args, away_team=None, home_team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._sides = {"away": away_team, "home": home_team}
        for side, team in self._sides.items():
            qs = Player.objects.filter(team=team) if team else Player.objects.none()
            for code, label in POSITIONS:
                self.fields[f"{side}_{code}"] = forms.ModelChoiceField(
                    queryset=qs,
                    label=label,
                    empty_label=f"— select {label.lower()} —",
                    widget=forms.Select(attrs={"class": "form-select"}),
                )

    def _clean_side(self, side):
        chosen = [self.cleaned_data.get(f"{side}_{code}") for code, _ in POSITIONS]
        picked = [p for p in chosen if p is not None]
        ids = [p.player_id for p in picked]
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(
                f"Each {side} player can only fill one position."
            )

    def clean(self):
        cleaned = super().clean()
        for side in ("away", "home"):
            self._clean_side(side)
        return cleaned

    def roster_for(self, side):
        """Return the 10-slot roster list for one side, canonical order."""
        out = []
        for code, _ in POSITIONS:
            p = self.cleaned_data[f"{side}_{code}"]
            out.append({"position": code, "player_id": p.player_id, "name": str(p)})
        return out
```

> Field names like `away_1B` are valid template/Python identifiers (they start with
> a letter), so `{{ form.away_1B }}` works in templates.

#### 2. `baseball/forms.py` — rename setup submit (button text lives in template; no
form change). Keep `GameSetupForm` as-is.

#### 3. `baseball/views.py` — auto-fill helper + lineup derivation

```python
from .models import Game, Player
from .forms import GameSetupForm, RosterForm, POSITIONS, BATTING_POSITIONS


def auto_fill_roster(team):
    """Pick 10 distinct players from a team for the away (CPU) side.
    Returns {position_code: player_id} for use as form initials."""
    players = list(Player.objects.filter(team=team)[:10])
    return {code: players[i].player_id
            for i, (code, _) in enumerate(POSITIONS) if i < len(players)}


def lineup_from_roster(roster):
    """9-name batting order from a 10-slot roster (pitcher excluded)."""
    by_pos = {r["position"]: r["name"] for r in roster}
    return [by_pos[code] for code in BATTING_POSITIONS]
```

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] Form builds 20 fields scoped per team:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.forms import RosterForm; from baseball.models import Team; t=Team.objects.all(); f=RosterForm(away_team=t[0], home_team=t[1]); print(len(f.fields)); assert len(f.fields)==20; print(f.fields['away_P'].queryset.count(), f.fields['home_P'].queryset.count())"` prints `20` then two nonzero counts
- [x] Auto-fill returns 10 distinct ids:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.views import auto_fill_roster; from baseball.models import Team; r=auto_fill_roster(Team.objects.first()); print(len(r)); assert len(set(r.values()))==10"`
- [x] Lineup derivation drops the pitcher:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.views import lineup_from_roster; from baseball.forms import POSITIONS; roster=[{'position':c,'player_id':i,'name':c} for i,(c,_) in enumerate(POSITIONS)]; lu=lineup_from_roster(roster); print(lu); assert 'P' not in lu and len(lu)==9"`

**Implementation Note**: Pause for manual confirmation before Phase 3.

---

## Phase 3: Two-Step Flow (Setup → Roster → Create)

### Overview
The setup view stops creating the game; it stashes validated setup choices in the
session and redirects to the roster view. The roster view renders the dropdowns
(away pre-filled), validates on POST, builds both rosters + lineups, creates the
`Game`, and redirects to detail.

### Changes Required

#### 1. `baseball/views.py` — convert setup view, add roster view

Change `GameCreateView` from `CreateView` to a `FormView` that stashes and redirects:
```python
from django.urls import reverse
from django.views.generic import ListView, DetailView, FormView

class GameCreateView(LoginRequiredMixin, FormView):
    form_class    = GameSetupForm
    template_name = "baseball/game_setup.html"

    def form_valid(self, form):
        cd = form.cleaned_data
        self.request.session["bb_setup"] = {
            "away_team_id":  cd["away_team"].team_id,
            "home_team_id":  cd["home_team"].team_id,
            "away_name":     cd["away_team"].name,
            "home_name":     cd["home_team"].name,
            "total_innings": cd["total_innings"],
            "mode":          cd["mode"],
        }
        return redirect("baseball-roster")
```

Add `RosterView`:
```python
class RosterView(LoginRequiredMixin, View):
    template_name = "baseball/game_roster.html"

    def _setup(self):
        return self.request.session.get("bb_setup")

    def _teams(self, setup):
        away = get_object_or_404(Team, pk=setup["away_team_id"])
        home = get_object_or_404(Team, pk=setup["home_team_id"])
        return away, home

    def get(self, request):
        setup = self._setup()
        if not setup:
            return redirect("baseball-new")
        away_team, home_team = self._teams(setup)
        initial = {f"away_{code}": pid
                   for code, pid in auto_fill_roster(away_team).items()}
        form = RosterForm(away_team=away_team, home_team=home_team, initial=initial)
        return render(request, self.template_name,
                      {"form": form, "setup": setup})

    def post(self, request):
        setup = self._setup()
        if not setup:
            return redirect("baseball-new")
        away_team, home_team = self._teams(setup)
        form = RosterForm(request.POST, away_team=away_team, home_team=home_team)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "setup": setup})

        away_roster = form.roster_for("away")
        home_roster = form.roster_for("home")
        gs = GameState(
            setup["away_name"], setup["home_name"], setup["total_innings"],
            away_lineup=lineup_from_roster(away_roster),
            home_lineup=lineup_from_roster(home_roster),
        )
        game = Game.objects.create(
            owner=request.user,
            away_name=setup["away_name"], home_name=setup["home_name"],
            away_team=away_team, home_team=home_team,
            total_innings=setup["total_innings"], mode=setup["mode"],
            state=Game.state_to_dict(gs),
            away_roster=away_roster, home_roster=home_roster,
        )
        del request.session["bb_setup"]
        return redirect("baseball-detail", pk=game.pk)
```

Add imports: `from django.shortcuts import get_object_or_404, redirect, render`
and `from .models import Game, Team, Player`.

#### 2. `baseball/urls.py` — add the roster route

```python
path("roster/", views.RosterView.as_view(), name="baseball-roster"),
```
(Place after `new/`.)

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] URL resolves:
      `./venv/Scripts/python.exe manage.py shell -c "from django.urls import reverse; print(reverse('baseball-roster'))"` prints `/baseball/roster/`

#### Manual Verification:
- [ ] Submitting `/baseball/new/` creates **no** `Game` row and lands on `/baseball/roster/`
- [ ] Hitting `/baseball/roster/` directly (no prior setup) redirects to `/baseball/new/`
- [ ] "Play Ball!" with a valid roster creates the game and redirects to detail
- [ ] Same player at two positions on one side → validation error, no game created
- [ ] Detail scoreboard's current batter is a selected player name

**Implementation Note**: Pause for manual confirmation before Phase 4.

---

## Phase 4: Templates

### Overview
Rename the setup button, add the roster screen template, and (optionally) show the
chosen lineups on the detail page.

### Changes Required

#### 1. `baseball/templates/baseball/game_setup.html` — rename button

Change line 50:
```html
<button type="submit" class="btn btn-success">Make Roster</button>
```

#### 2. `baseball/templates/baseball/game_roster.html` — new

```html
{% extends "base.html" %}
{% block content %}
<h2>Set Rosters</h2>
<p class="text-muted">{{ setup.away_name }} (away, CPU) vs {{ setup.home_name }} (home).
   The away roster is pre-filled — edit it if you like.</p>

<form method="post" class="mt-3">
    {% csrf_token %}
    {% if form.non_field_errors %}
    <div class="alert alert-danger">{{ form.non_field_errors }}</div>
    {% endif %}

    <div class="row">
      {% for side, title in sides %}
      <div class="col-md-6">
        <h4>{{ title }}</h4>
        {% for field in form %}
          {% if field.name|slice:":4" == side|slice:":4" %}
          <div class="mb-2">
            <label class="form-label small fw-semibold">{{ field.label }}</label>
            {{ field }}
            {% if field.errors %}<div class="text-danger small">{{ field.errors }}</div>{% endif %}
          </div>
          {% endif %}
        {% endfor %}
      </div>
      {% endfor %}
    </div>

    <button type="submit" class="btn btn-success mt-3">Play Ball!</button>
    <a href="{% url 'baseball-new' %}" class="btn btn-link mt-3">Back</a>
</form>
{% endblock %}
```

The two-column split needs a `sides` context var; add to both `get`/`post` renders:
`{"form": form, "setup": setup, "sides": [("away", setup["away_name"]+" (Away)"),
("home", setup["home_name"]+" (Home)")]}`.

> The `field.name|slice:":4"` trick groups `away_*` vs `home_*`. Simpler/cleaner
> alternative if it proves fiddly: have `RosterForm` expose `away_fields()` /
> `home_fields()` bound-field lists and iterate those directly. Pick whichever reads
> better during implementation.

#### 3. `baseball/templates/baseball/game_detail.html` — optional lineup display

Optionally add a small card listing `game.away_roster` / `game.home_roster`
(position + name). Not required for the feature to work; the live current-batter
name already comes through the engine.

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0

#### Manual Verification:
- [ ] `/baseball/roster/` shows two columns of 10 labeled dropdowns each
- [ ] Away dropdowns are pre-filled; home dropdowns start empty
- [ ] Each dropdown lists only its own team's players
- [ ] Full play-through (click_all mode) shows real selected names in the play log,
      cycling through the 9 batting slots in C→DH order, pitcher never batting
- [ ] cpu_auto and auto_play modes also show real names

---

## Testing Strategy

### Manual Testing Steps:
1. `/baseball/new/` → pick two different teams, 3 innings, click_all; button says
   "Make Roster"; submit.
2. Confirm landing on `/baseball/roster/`; away side pre-filled, home empty.
3. Set the same player at two home positions → submit → validation error.
4. Fix it, fill all home slots, "Play Ball!" → detail page.
5. Confirm current batter and play-by-play use selected names; play to completion.
6. Repeat with cpu_auto and auto_play modes.
7. Open an old pre-feature game from the list → still plays (fallback lineup).
8. Mid-game refresh → names persist (state JSON carries the lineups).

## Performance Considerations

Each position dropdown renders ~56–65 `<option>`s; 20 dropdowns ≈ ~1.2k options on
the roster page. Acceptable. `Player.objects.filter(team=…)` hits the unmanaged
`player` table with a `team_id` filter — index-friendly. No N+1 (querysets are
shared per side via the form fields).

## Migration Notes

One additive migration (Phase 1: two `JSONField(default=list)` columns on
`baseball_game`). No data backfill — existing rows default to empty rosters and use
the engine's `params.LINEUP` fallback.

## References

- Feature request: roster selection (user, 2026-06-29)
- Research doc: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- Prior plan: `thoughts/shared/plans/2026-06-25-baseball-team-selection.md`
- `baseball/engine.py:11` `GameState`; `:36` `current_batter`; `params.py:24` `LINEUP`
- `baseball/models.py:207` `Game`; `:246` `state_to_dict`; `:50` `Player`
- `baseball/views.py:81` `GameCreateView`
- `baseball/forms.py:5` `GameSetupForm`
- `baseball/templates/baseball/game_setup.html:50` "Play Ball!" button
