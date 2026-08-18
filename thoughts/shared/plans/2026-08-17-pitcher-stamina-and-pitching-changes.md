# Pitcher Stamina and Pitching Changes Implementation Plan

## Overview

Add a per-pitcher stamina meter that drains as a pitcher faces batters, makes walks/hits progressively more likely as it drains (a fourth weight-modifier alongside streaky/weather/fatigue-free baseline), and lets you swap in a reliever — either manually at any time, or via a one-time "change pitcher?" prompt once stamina crosses a threshold. CPU-controlled sides (and both sides during `auto_play`, which has no interaction point) auto-swap on the same threshold.

## Current State Analysis

There is currently **exactly one pitcher per team**, picked once at game setup and never changed:

- `SideRosterForm` (`baseball/forms.py:27-87`) has one `"P"` field among its 10 `POSITIONS` (`forms.py:5-16`); `roster_for()` (`forms.py:77-87`) emits a single `{"position": "P", ...}` entry.
- `lineup_from_roster(roster)` (`baseball/engine.py:127-129`) excludes only that one `"P"` entry from the batting order; nothing else in the codebase represents a bullpen, a "current pitcher," or pitching stamina.
- `GameStat` (`baseball/models.py`, unchanged by this plan) tracks only batting counting stats — there is no pitching-stat concept at all today.
- `Player.g_sp`/`g_rp` (career starts/relief-appearance counts, `models.py:70-71`) already exist and are used today only to exclude pitchers from the DH pool in `position_pools()` (`models.py:114-124`) — this is the same signal (`g_sp>0 or g_rp>0`) already used by `auto_fill_roster` (`views.py:107-124`) to identify "is this player a pitcher," and it's what a bullpen pool query reuses.

This plan extends the exact modifier architecture already built for weather (see `thoughts/shared/research/2026-08-17-outcome-probability-dice-vs-array.md` and `thoughts/shared/plans/2026-08-17-weather-outcome-modifiers.md`):

- `apply_weather()` (`baseball/engine.py:387-399`) multiplicatively nudges an `{outcome: weight}` dict, no-ops at the neutral baseline, and is applied identically to both the dice-table path (via `dice_table_weights()`, `engine.py:374-384`) and the stat-weighted path (via `_career_weights_for()`, `views.py:67-80`) inside the shared `resolve_dice_roll()` (`engine.py:402-...`). Fatigue will be `apply_fatigue()`, built the same way, composed alongside `apply_weather()`.
- `weather` lives as a single dict on `GameState`, persisted through `Game.state_to_dict`/`state_from_dict` (`models.py:311-363`). Pitching state (`away_pitching`/`home_pitching`) will live the same way — except, like the streaky-pick fields (`streaky_game_away`, etc.), it's *mutable runtime state* (current pitcher, remaining stamina, remaining bullpen), so it follows the **streaky** pattern specifically: built fresh in `GameState.__init__` from setup-time data, then unconditionally overwritten by `state_from_dict` from whatever was last persisted, rather than re-derived from setup data on every load.
- All 6 `GameState`-construction/`Game`-creation call sites that already thread `streaky_per_game`/weather through (`views.py` — `Page1View.post`'s `MULTIPLAYER` and `CPU_AUTO` branches, the session-based branch + `Page2View.post`, `Player2JoinView.post`, `ReplayView.post`) need the same treatment again for bullpen/starting-pitcher data.

### Key Discoveries
- `auto_play` mode runs the **entire game inside one `SimulateView.post` request** (`views.py:806-834`, a `while not gs.game_over` loop with no per-play round trip) and `game.status` is already set to `Game.FINISHED` before the response is returned — there is no point at which a human can be asked anything mid-simulation. Both sides must use the auto-swap heuristic during `auto_play`, including the human's own team.
- `cpu_auto` mode's CPU-batting stretch (`initCpuAuto`'s `autoRollCPU()` loop, `game.js:386-397`) does **not** reload between plays. Since the CPU is *batting* during that stretch, the *human* is fielding/pitching — meaning a human's stamina threshold can be crossed mid-loop, before the eventual `location.reload()` at `half_over`. The pitching-change prompt therefore needs to reach the client two ways: (a) inline in the immediate `play` JSON response (for this no-reload stretch), and (b) server-rendered on page load (for multiplayer, where the *fielding* side is often not the one whose `RollView` request just ran, and only discovers state via their own poll-driven reload).
- Because `_career_weights_for()` already composes streaky-doubling → `apply_weather()` in a fixed order (`views.py:67-80`), fatigue slots in as a third step in that same function, and a third argument on `resolve_dice_roll()` — no new architecture, just one more link in an existing chain.

## Desired End State

- Game setup (all three roster-building templates) has a "Bullpen" field: pick 2-4 relievers from the team's eligible pitchers, alongside the existing single starting-pitcher pick.
- Each side's currently-pitching player has a stamina value (100 down to 0) that drops by a fixed amount every batter they face, persisted across innings until they're replaced.
- As stamina drops, walks and hits become progressively more likely for that pitcher specifically (both dice-table and stat-weighted batters affected identically) — at full stamina, this is an exact no-op (same code path as before this plan).
- Once a pitcher's stamina crosses a threshold, whoever controls that side is asked once whether to change pitchers (human sides) or automatically swapped to the next reliever (CPU sides, and both sides during `auto_play`). A manual "Change Pitcher" button/picker is available at any time regardless of stamina, for human-controlled fielding sides.
- The live game page shows both sides' current pitcher and stamina.

### Verification
- Set up a game, confirm the bullpen picker requires 2-4 relievers and rejects picking your starter into the bullpen too.
- Play enough at-bats to drain a pitcher below threshold: confirm hits/walks become more frequent for that pitcher (fuzz-verifiable, same technique as the weather plan), and that the change-pitcher prompt appears exactly once.
- Change pitchers manually mid-game with full stamina remaining; confirm the new pitcher starts at full stamina and the old one's remaining bullpen slot is gone.
- Play a `cpu_auto` game as the CPU's opponent; confirm the CPU auto-swaps its own tiring pitcher without any prompt.
- Run `auto_play`; confirm it completes without needing interaction, and that pitching changes happened automatically if any pitcher tired out during the simulation (visible in hindsight via `play_log`, e.g. an `auto_pitching_change` marker).

## What We're NOT Doing
- No pitching *stats* (batters faced, earned runs allowed, etc.) — this plan only adds stamina and the change mechanism, not a pitching box score. `GameStat` is untouched.
- No `SavedRoster` integration for bullpens — saved rosters continue to cover only the 10-slot batting roster; bullpen must be picked fresh every game setup, even when loading a saved roster. (Noted as a reasonable follow-up, not required here.)
- No ranked/smart reliever selection for auto-swaps — CPU/auto_play always takes the next bullpen entry in list order (FIFO), not "best available."
- No stamina recovery/rest between games or across innings beyond what "don't touch it until swapped" already implies — a pitcher's stamina only ever goes down until they're replaced.
- No changes to the unused alternate per-pitch resolver (`resolve_action`/`cpu_batter_action`, `engine.py:396-428`).

## Implementation Approach

Four independent phases, each building on the last, matching the structure already agreed:

1. **Bullpen data model + setup UI** — inert, no engine/GameState changes.
2. **GameState pitching-staff state** — `away_pitching`/`home_pitching` seeded and persisted; still inert (nothing drains stamina yet).
3. **Fatigue engine wiring** — stamina now actually drains and measurably affects outcomes; no change-pitcher UI yet.
4. **Pitching-change mechanism + UI** — the prompt, the manual button/picker, CPU/auto_play auto-swap, and the live stamina display.

---

## Phase 1: Bullpen Data Model and Setup UI

### Overview
Add a bullpen field (2-4 relievers) to `SideRosterForm`, `Game.away_bullpen`/`home_bullpen` fields + migration, an `auto_fill_bullpen()` helper for the CPU_AUTO opponent, and thread bullpen data through all 6 game-creation/read call sites — mirroring exactly how weather was threaded through the same 6 sites.

### Changes Required

#### 1. Forms — bullpen field, cardinality validation, All-Star-aware labels
**File**: `baseball/forms.py`
**Changes**: Generalize the existing `_PlayerChoiceField` label override into a mixin so a new multi-select field class can reuse it; add `BULLPEN_MIN`/`BULLPEN_MAX`; add the `bullpen` field to `SideRosterForm.__init__`; validate cardinality + starter/bullpen overlap in `clean()`; add `bullpen_for()`.

```python
POSITIONS = [...]
BATTING_POSITIONS = [code for code, _ in POSITIONS if code != "P"]
BULLPEN_MIN = 2
BULLPEN_MAX = 4


class _TeamLabelMixin:
    """Trailing team abbreviation on player labels, for All-Star pools where
    multiple teams' players are mixed together."""
    def label_from_instance(self, obj):
        return f"{obj} ({obj.team_abbrev})" if obj.team_abbrev else str(obj)


class _PlayerChoiceField(_TeamLabelMixin, forms.ModelChoiceField):
    pass


class _PlayerMultipleChoiceField(_TeamLabelMixin, forms.ModelMultipleChoiceField):
    pass


class SideRosterForm(forms.Form):
    def __init__(self, *args, team=None, team_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_star = is_all_star_team(team)
        self.fields["team"] = forms.ModelChoiceField(...)  # unchanged
        pools = position_pools(team) if team else {}
        field_cls = _PlayerChoiceField if self.all_star else forms.ModelChoiceField
        for code, label in POSITIONS:
            ...  # unchanged
        bullpen_cls = _PlayerMultipleChoiceField if self.all_star else forms.ModelMultipleChoiceField
        self.fields["bullpen"] = bullpen_cls(
            queryset=(Player.objects.filter(player_id__in=pools.get("P", []))
                      if team else Player.objects.none()),
            required=True, label="Bullpen",
            widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
        )
        self.fields["order"] = forms.CharField(...)  # unchanged

    def clean(self):
        cleaned = super().clean()
        chosen = {code: cleaned.get(code) for code, _ in POSITIONS}
        ids = [pl.player_id for pl in chosen.values() if pl is not None]
        p_pick, dh_pick = chosen.get("P"), chosen.get("DH")
        if (p_pick is not None and dh_pick is not None
                and p_pick.player_id == dh_pick.player_id):
            ids.remove(dh_pick.player_id)
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(
                "Each player can only fill one position "
                "(except a pitcher may also be the DH)."
            )
        bullpen = cleaned.get("bullpen")
        if bullpen is not None:
            if not (BULLPEN_MIN <= len(bullpen) <= BULLPEN_MAX):
                self.add_error("bullpen", f"Pick {BULLPEN_MIN}-{BULLPEN_MAX} relievers.")
            elif p_pick and any(p.player_id == p_pick.player_id for p in bullpen):
                self.add_error("bullpen", "Your starting pitcher can't also be in the bullpen.")
        return cleaned

    def roster_for(self):
        ...  # unchanged

    def bullpen_for(self):
        """List of {player_id, name} for the picked relievers."""
        return [{"player_id": p.player_id, "name": str(p)}
                for p in self.cleaned_data["bullpen"]]
```

#### 2. Models — `Game.away_bullpen`/`home_bullpen`
**File**: `baseball/models.py`
**Changes**: Two new JSONFields, same shape as bullpen entries elsewhere: `[{"player_id": int, "name": str}, ...]`.

```python
    weather_temperature_f = models.IntegerField(default=70)
    weather_wind          = models.CharField(max_length=12, choices=WIND_CHOICES, default="calm")
    weather_sky            = models.CharField(max_length=12, choices=SKY_CHOICES, default="overcast")
    away_bullpen  = models.JSONField(default=list)
    home_bullpen  = models.JSONField(default=list)
    state         = models.JSONField()
```

#### 3. Migration
**File**: `baseball/migrations/0019_game_bullpen_fields.py` (new)
```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('baseball', '0018_game_weather_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='away_bullpen',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='game',
            name='home_bullpen',
            field=models.JSONField(default=list),
        ),
    ]
```

#### 4. Views — `auto_fill_bullpen()` for the CPU opponent
**File**: `baseball/views.py`
**Changes**: Add near `auto_fill_roster`/`cpu_roster_for` (`views.py:107-142`).

```python
def auto_fill_bullpen(team, exclude_player_id, n=BULLPEN_MAX):
    """Up to n distinct eligible relievers for a CPU-controlled team's bullpen,
    excluding whichever player was auto-picked as the starter."""
    pool = position_pools(team).get("P", [])
    picks = [pid for pid in pool if pid != exclude_player_id][:n]
    players = {p.player_id: p for p in Player.objects.filter(player_id__in=picks)}
    return [{"player_id": pid, "name": str(players[pid])} for pid in picks if pid in players]
```

Import `BULLPEN_MAX` from `.forms` alongside the existing `POSITIONS, BATTING_POSITIONS` import (`views.py:13`).

#### 5. Views — thread bullpen through all 6 call sites
**File**: `baseball/views.py`
**Changes**: Mirror each `weather_*=`/`weather={...}` occurrence added for weather with a bullpen equivalent.

- `Page1View.post`, `MULTIPLAYER` branch (`views.py:358-385`): compute `own_bullpen = form.bullpen_for()`; split into `away_bullpen, home_bullpen` alongside the existing `away_roster, home_roster` split; add `away_bullpen=away_bullpen, home_bullpen=home_bullpen` to `Game.objects.create(...)`.
- `Page1View.post`, `CPU_AUTO` branch (`views.py:387-422`):
  ```python
  own_bullpen = form.bullpen_for()
  cpu_roster = cpu_roster_for(opponent_team)
  cpu_starter_pid = next(e["player_id"] for e in cpu_roster if e["position"] == "P")
  cpu_bullpen = auto_fill_bullpen(opponent_team, exclude_player_id=cpu_starter_pid)
  if side == "away":
      away_team, home_team = own_team, opponent_team
      away_roster, home_roster = own_roster, cpu_roster
      away_bullpen, home_bullpen = own_bullpen, cpu_bullpen
      cpu_side = "home"
  else:
      away_team, home_team = opponent_team, own_team
      away_roster, home_roster = cpu_roster, own_roster
      away_bullpen, home_bullpen = cpu_bullpen, own_bullpen
      cpu_side = "away"
  ```
  add `away_bullpen=away_bullpen, home_bullpen=home_bullpen` to `Game.objects.create(...)`. (`GameState(...)` itself doesn't need bullpen data until Phase 2.)
- `Page1View.post`, session-based branch (`views.py:424-438`): add `"bullpen": form.bullpen_for()` to `request.session["bb_setup"]`.
- `Page2View.post` (`views.py:528-561`): compute `p2_bullpen = form.bullpen_for()`; split `away_bullpen, home_bullpen` the same way `away_roster, home_roster` is split via `setup["side"]`/`setup["bullpen"]`; add `away_bullpen=away_bullpen, home_bullpen=home_bullpen` to `Game.objects.create(...)`.
- `Player2JoinView.post` (`views.py:667-687`): compute `p2_bullpen = form.bullpen_for()`; mirror the existing `game.home_roster = p2_roster` / `game.away_roster = p2_roster` branch with `game.home_bullpen = p2_bullpen` / `game.away_bullpen = p2_bullpen`.
- `ReplayView.post` (`views.py:848-870`): add `away_bullpen=game.away_bullpen, home_bullpen=game.home_bullpen` to `Game.objects.create(...)` (carries the original bullpen forward, matching how weather/streaky already carry forward on replay).

#### 6. Templates — Bullpen field on all three roster-building pages
**Files**: `baseball/templates/baseball/game_setup.html`, `game_roster.html`, `game_join.html`
**Changes**: Add next to the existing Pitcher block in each (reusing `_position_field.html`, which already works for any Django form field rendered via `{{ field }}`, including a `SelectMultiple` — the existing `.player-search` JS filters `<option>` elements regardless of the `multiple` attribute).

`game_setup.html`, after the Pitcher `</div>` (`game_setup.html:94-107`) and before `{{ form.order }}`:
```html
<div class="mb-3">
    <label class="form-label small fw-semibold d-block">
        Bullpen <span class="text-muted fw-normal">(pick 2-4 relievers; ctrl/cmd-click for multiple)</span>
    </label>
    <div style="max-width:500px">
        {% include "baseball/_position_field.html" with field=form.bullpen all_star=form.all_star %}
    </div>
</div>
```
Same block (adjusted to match each template's exact surrounding markup) in `game_roster.html` (after its Pitcher block, `game_roster.html:26-38`) and `game_join.html` (after its Pitcher block, `game_join.html:27-33`).

### Success Criteria

#### Automated Verification
- [x] Migration applies cleanly: `python manage.py migrate baseball`
- [x] Migration reverses/reapplies cleanly: `python manage.py migrate baseball 0018` then forward again
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist in the repo — pre-existing)
- [x] Shell/`Client` smoke check: submitting a roster with exactly 3 relievers (none overlapping the starter) succeeds; submitting 1 or 5 relievers fails with the cardinality error; submitting the starter's own `player_id` inside the bullpen fails with the overlap error.
- [x] CPU_AUTO creation smoke check: the resulting `Game.home_bullpen` (or `away_bullpen`, whichever is CPU) has up to `BULLPEN_MAX` entries, none matching the CPU's own starting-pitcher `player_id`.
- [x] Multiplayer create + join smoke check: both `Game.away_bullpen` and `Game.home_bullpen` end up populated after both sides have gone through setup.
- [x] Replay smoke check: the new game's `away_bullpen`/`home_bullpen` match the original game's.

#### Manual Verification
- [x] Game setup page shows the Bullpen multi-select with a 2-4 helper hint, positioned under the Pitcher field.
- [x] Picking your starter into the bullpen, or picking fewer than 2 / more than 4, shows a clear validation error and doesn't submit.
- [x] For an All-Star team, bullpen options show the `(ABB)` team-abbreviation suffix and the search box filters them, same as the single-pitcher field.
- [x] Repeat on `game_roster.html` and `game_join.html`.

**Implementation Note**: Pause here for manual confirmation before Phase 2.

---

## Phase 2: GameState Pitching-Staff State

### Overview
Add `away_pitching`/`home_pitching` dicts to `GameState` (current pitcher, stamina, remaining bullpen, prompt/dismiss flags), seeded at game creation from the starting `"P"` roster entry and the Phase 1 bullpen data, and persisted through `Game.state` the same way the streaky-pick fields already are. Still no behavior change — stamina exists but nothing reads or drains it yet.

### Changes Required

#### 1. Params — stamina constants
**File**: `baseball/params.py`
**Changes**: Add near the Weather section.

```python
# --- Pitcher stamina -------------------------------------------------------------
PITCHER_STAMINA_MAX = 100
```
(The drain rate, change threshold, and fatigue multipliers are added in Phase 3, where they're first consumed — keeping this phase's diff focused on the state shape.)

#### 2. Engine — `GameState` carries pitching-staff dicts
**File**: `baseball/engine.py`
**Changes**: Import `PITCHER_STAMINA_MAX`; add a small internal helper `_fresh_pitching()`; add constructor params.

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, DICE_TABLE_STREAKY,
    STAT_OUT_SPLIT, WEATHER_DEFAULT, COLD_THRESHOLD_F,
    WIND_OUT_HR_MULT, WIND_IN_HR_MULT, COLD_RAIN_HIT_MULT, PITCHER_STAMINA_MAX,
)


def _fresh_pitching(starting_pitcher, bullpen):
    """A fresh pitching-staff state dict for one side."""
    return {
        "current": dict(starting_pitcher) if starting_pitcher else None,
        "stamina": PITCHER_STAMINA_MAX,
        "bullpen": [dict(p) for p in (bullpen or [])],
        "prompted": False,
        "dismissed": False,
    }


class GameState:
    def __init__(self, away_name, home_name, total_innings,
                 away_lineup=None, home_lineup=None,
                 streaky_per_game=False, streaky_per_inning=False,
                 weather=None,
                 away_starting_pitcher=None, home_starting_pitcher=None,
                 away_bullpen=None, home_bullpen=None) -> None:
        ...  # unchanged through the existing weather line
        self.weather = dict(weather) if weather else dict(WEATHER_DEFAULT)
        self.away_pitching = _fresh_pitching(away_starting_pitcher, away_bullpen)
        self.home_pitching = _fresh_pitching(home_starting_pitcher, home_bullpen)
```

#### 3. Views — `pitcher_from_roster()` helper
**File**: `baseball/views.py`
**Changes**: Add near `lineup_from_roster` (`views.py:127-129`), which it mirrors.

```python
def pitcher_from_roster(roster):
    """The starting pitcher's {player_id, name} from a 10-slot roster, or None."""
    entry = next((r for r in roster if r["position"] == "P"), None)
    return {"player_id": entry["player_id"], "name": entry["name"]} if entry else None
```

#### 4. Views — pass starting pitcher + bullpen into every fresh `GameState(...)` call
**File**: `baseball/views.py`
**Changes**: The `MULTIPLAYER` branch of `Page1View.post` doesn't build a `GameState` yet (unchanged — `state={}` until join). The other three fresh-construction call sites each gain two more kwargs:

- `Page1View.post`, `CPU_AUTO` branch (`views.py:399-407`):
  ```python
  gs = GameState(
      away_team.name, home_team.name, cd["total_innings"],
      away_lineup=lineup_from_roster(away_roster),
      home_lineup=lineup_from_roster(home_roster),
      streaky_per_game=cd["streaky_per_game"],
      streaky_per_inning=cd["streaky_per_inning"],
      weather={"temperature_f": cd["weather_temperature_f"],
               "wind": cd["weather_wind"], "sky": cd["weather_sky"]},
      away_starting_pitcher=pitcher_from_roster(away_roster),
      home_starting_pitcher=pitcher_from_roster(home_roster),
      away_bullpen=away_bullpen, home_bullpen=home_bullpen,
  )
  ```
- `Page2View.post` (`views.py:539-547`): same two additions, using the `away_roster`/`home_roster`/`away_bullpen`/`home_bullpen` already computed in Phase 1's step 5.
- `Player2JoinView.post` (`views.py:675-683`): same two additions, reading `pitcher_from_roster(game.away_roster)`/`pitcher_from_roster(game.home_roster)` and `game.away_bullpen`/`game.home_bullpen` (both sides' rosters/bullpens are final by this point).
- `ReplayView.post` (`views.py:848-856`): same two additions, reading from `game.away_roster`/`game.home_roster`/`game.away_bullpen`/`game.home_bullpen` — giving the replay a fully fresh, fully-rested pitching staff (matches how streaky/weather already reset fresh on replay via a brand-new `GameState`).

#### 5. Models — persist `away_pitching`/`home_pitching` through `Game.state`
**File**: `baseball/models.py`
**Changes**: Following the streaky-field pattern exactly (built fresh in the constructor above, then unconditionally overwritten here from the persisted dict on every load — not re-passed through the `GameState(...)` constructor call in `state_from_dict`).

```python
    @staticmethod
    def state_to_dict(s: GameState) -> dict:
        return {
            ...
            "weather": s.weather,
            "away_pitching": s.away_pitching,
            "home_pitching": s.home_pitching,
        }

    @staticmethod
    def state_from_dict(d: dict) -> GameState:
        gs = GameState(d["away_name"], d["home_name"], d["total_innings"],
                       away_lineup=d.get("away_lineup"),
                       home_lineup=d.get("home_lineup"),
                       weather=d.get("weather"))
        ...  # unchanged existing field restores
        gs.streaky_inning_home = d.get("streaky_inning_home")
        gs.away_pitching = d.get("away_pitching") or gs.away_pitching
        gs.home_pitching = d.get("home_pitching") or gs.home_pitching
        return gs
```

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist — pre-existing)
- [x] Shell check: constructing `GameState(..., away_starting_pitcher={"player_id": 1, "name": "X"}, away_bullpen=[{"player_id": 2, "name": "Y"}, {"player_id": 3, "name": "Z"}])` produces `gs.away_pitching == {"current": {"player_id": 1, "name": "X"}, "stamina": 100, "bullpen": [{"player_id": 2, "name": "Y"}, {"player_id": 3, "name": "Z"}], "prompted": False, "dismissed": False}`.
- [x] `Game.state_to_dict`/`state_from_dict` round-trip: build a `GameState`, mutate `gs.away_pitching["stamina"] = 42` and pop a bullpen entry, round-trip through `Game.state_to_dict`/`state_from_dict`, confirm the restored `GameState.away_pitching` matches exactly (proves the streaky-style direct-overwrite restore works, not just the fresh-construction path).
- [x] End-to-end `Client` smoke check (CPU_AUTO creation): `game.load_state().home_pitching` (or `away_pitching`, whichever is CPU) has a non-null `current` matching the CPU's auto-picked starter, and a `bullpen` matching `auto_fill_bullpen`'s output.
- [x] End-to-end `Client` smoke check (multiplayer create + join): after both sides complete setup, both `gs.away_pitching["current"]` and `gs.home_pitching["current"]` are non-null and match each side's picked starter.

#### Manual Verification
- [x] No visible behavior change anywhere in the app yet (this phase is purely additive state) — spot check that games still play normally.
- [x] Via Django admin/shell, confirm a newly created game's `Game.state` JSON contains populated `away_pitching`/`home_pitching` keys with the expected starter/bullpen.

**Implementation Note**: Pause here for manual confirmation before Phase 3.

---

## Phase 3: Fatigue Engine Wiring

### Overview
Add `apply_fatigue()` (mirroring `apply_weather()`), drain stamina once per at-bat in `_advance_game`, and compose fatigue into both `resolve_dice_roll()` and `_career_weights_for()` — with the same "exact no-op at full stamina" discipline already established for weather at its default.

### Changes Required

#### 1. Params — drain rate and fatigue multipliers
**File**: `baseball/params.py`
**Changes**: Extend the Pitcher stamina section from Phase 2.

```python
# --- Pitcher stamina -------------------------------------------------------------
PITCHER_STAMINA_MAX = 100
STAMINA_DRAIN_PER_BATTER = 4   # -> ~25 batters faced before a pitcher is fully spent
FATIGUE_WALK_MULT = 0.5        # at zero stamina, walk weight is *1.5
FATIGUE_HIT_MULT = 0.4         # at zero stamina, single/double/triple/home_run weights are *1.4
```

#### 2. Engine — `apply_fatigue()`, wired into `resolve_dice_roll()`
**File**: `baseball/engine.py`
**Changes**: Add alongside `apply_weather()`; extend `resolve_dice_roll()`'s signature and no-op condition.

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, DICE_TABLE_STREAKY,
    STAT_OUT_SPLIT, WEATHER_DEFAULT, COLD_THRESHOLD_F,
    WIND_OUT_HR_MULT, WIND_IN_HR_MULT, COLD_RAIN_HIT_MULT,
    PITCHER_STAMINA_MAX, FATIGUE_WALK_MULT, FATIGUE_HIT_MULT,
)
```

```python
def apply_fatigue(weights: Dict[str, int], stamina: float) -> Dict[str, int]:
    """Multiplicatively nudge an outcome-weight dict as a pitcher tires.
    No-op at PITCHER_STAMINA_MAX (returns `weights` unchanged)."""
    if stamina >= PITCHER_STAMINA_MAX:
        return weights
    fatigue = max(0.0, (PITCHER_STAMINA_MAX - stamina) / PITCHER_STAMINA_MAX)  # 0..1
    weights["walk"] = weights.get("walk", 0) * (1 + fatigue * FATIGUE_WALK_MULT)
    for key in ("single", "double", "triple", "home_run"):
        weights[key] = weights.get(key, 0) * (1 + fatigue * FATIGUE_HIT_MULT)
    return weights


def resolve_dice_roll(state: GameState, stat_weights: Dict[str, int] = None,
                       streaky: bool = False, weather: Dict = None,
                       stamina: float = None) -> Tuple[int, int, str, str]:
    """... (docstring extended to mention stamina) ..."""
    weather = weather or WEATHER_DEFAULT
    stamina = PITCHER_STAMINA_MAX if stamina is None else stamina
    d1, d2 = roll_dice()
    if stat_weights is not None:
        outcome = weighted_choice(stat_weights)
    elif weather == WEATHER_DEFAULT and stamina >= PITCHER_STAMINA_MAX:
        table = DICE_TABLE_STREAKY if streaky else DICE_TABLE
        outcome = table[(min(d1, d2), max(d1, d2))]
    else:
        weights = apply_fatigue(apply_weather(dice_table_weights(streaky), weather), stamina)
        outcome = weighted_choice(weights)
    ...  # rest unchanged
```

#### 3. Views — fatigue in `_career_weights_for()`, drain + weights in `_advance_game()`
**File**: `baseball/views.py`
**Changes**: `_career_weights_for()` (`views.py:67-80`) applies fatigue after weather, same as it already applies weather after streaky-doubling:

```python
from .engine import (
    GameState, resolve_dice_roll, apply_in_play, stat_based_weights,
    apply_weather, apply_fatigue,
)
from .params import STAT_BASED_MIN_AB, COMMENTARY_LINES, WEATHER_DEFAULT
from .params import PITCHER_STAMINA_MAX


def _career_weights_for(player_id, streaky=False, weather=None, stamina=None):
    """Stat-based outcome weights for a batter, or None to use the dice table."""
    if not player_id:
        return None
    row = PlayerCareerStats.objects.filter(player_id=player_id).values(...).first()
    if not row or row["at_bats"] < STAT_BASED_MIN_AB:
        return None
    weights = stat_based_weights(row)
    if streaky:
        for key in ("single", "double", "triple", "home_run"):
            weights[key] *= 2
    weights = apply_weather(weights, weather or WEATHER_DEFAULT)
    weights = apply_fatigue(weights, PITCHER_STAMINA_MAX if stamina is None else stamina)
    return weights
```

`_advance_game()` (`views.py:191-250`) determines the fielding side's pitching dict *before* resolving the at-bat (so the batter faces the stamina the pitcher had *entering* the at-bat), passes `stamina` through both calls, then drains *after* resolving:

```python
def _advance_game(gs: GameState, roster) -> dict:
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter
    gs.last_moves = []
    streaky = gs.is_streaky(batter)
    pitching = gs.home_pitching if gs.half == "top" else gs.away_pitching
    stamina = pitching["stamina"] if pitching["current"] else PITCHER_STAMINA_MAX

    if batter == "Tushy Scar":
        d1, d2 = 6, 6
        msg, _ = apply_in_play(gs, "home_run")
        outcome = "home_run"
        method = "dice"
    else:
        pid = _pid_for_name(roster, batter)
        weights = _career_weights_for(pid, streaky=streaky, weather=gs.weather, stamina=stamina)
        d1, d2, outcome, msg = resolve_dice_roll(gs, stat_weights=weights, streaky=streaky,
                                                  weather=gs.weather, stamina=stamina)
        method = "stat" if weights is not None else "dice"
    commentary = random.choice(COMMENTARY_LINES[outcome]).format(batter=batter)

    if pitching["current"]:
        pitching["stamina"] = max(0, pitching["stamina"] - STAMINA_DRAIN_PER_BATTER)

    gs.reset_count()
    gs.advance_lineup()
    ...  # rest unchanged in this phase (the prompt flag is added in Phase 4)
```

Import `STAMINA_DRAIN_PER_BATTER` alongside the other `.params` imports at the top of `views.py`.

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist — pre-existing)
- [x] Structural no-op check: `apply_fatigue(w, PITCHER_STAMINA_MAX) is w` (same object, unmodified).
- [x] Default-stamina regression check (same technique used for weather): monkeypatch `weighted_choice` to count calls, run `resolve_dice_roll` many times at full stamina + default weather with `stat_weights=None` — zero calls into `weighted_choice`, proving the dice-table branch is untouched at full stamina.
- [x] Fatigue sanity: fuzz-run `resolve_dice_roll` with `stamina=20` (well below max) many times and confirm elevated walk/hit frequency vs. `stamina=100` — dice-table batter went 38.9%→45.9%, stat-weighted batter went 34.2%→41.1%.
- [x] Drain check: call `_advance_game` repeatedly against a fresh `GameState` and confirm `gs.home_pitching["stamina"]` decreases by exactly `STAMINA_DRAIN_PER_BATTER` per at-bat (verified 100→96→92→88→84→80), and that it does **not** decrease (stays 100) when `pitching["current"]` is `None`.

#### Manual Verification
- [x] Play a game with default settings — no perceptible change yet (no UI shows stamina; behavior is only measurable via fuzz-testing at this phase).
- [x] Via Django shell, drain a live game's pitcher below ~30 stamina manually (`gs.home_pitching["stamina"] = 25`, `game.save_state(gs)`, `game.save()`) and confirm subsequent at-bats against that side show visibly more walks/hits than earlier in the same game.

**Implementation Note**: Pause here for manual confirmation before Phase 4.

---

## Phase 4: Pitching-Change Mechanism and UI

### Overview
Add the threshold, the one-time prompt-availability signal from `_advance_game`, a new `PitcherChangeView` endpoint (change or dismiss), CPU/`auto_play` auto-swap logic in `RollView`/`SimulateView`, and the live-game UI: stamina display for both sides, the change-pitcher prompt banner, and a manual change button + picker.

### Changes Required

#### 1. Params — change threshold
**File**: `baseball/params.py`
**Changes**: Extend the Pitcher stamina section again.

```python
PITCHER_CHANGE_THRESHOLD = 30   # stamina at/below this triggers the change-pitcher prompt
```

#### 2. Views — prompt-availability signal in `_advance_game()`
**File**: `baseball/views.py`
**Changes**: After the stamina-drain line added in Phase 3, detect the threshold crossing and attach it to the play dict (both the walk-off-early-return dict and the normal return dict, same as `commentary` was added in the announcer-commentary phase).

```python
    pitching_change_available = None
    if pitching["current"]:
        pitching["stamina"] = max(0, pitching["stamina"] - STAMINA_DRAIN_PER_BATTER)
        if (not pitching["prompted"] and not pitching["dismissed"]
                and pitching["stamina"] <= PITCHER_CHANGE_THRESHOLD
                and pitching["bullpen"]):
            pitching["prompted"] = True
            pitching_change_available = {
                "side": "home" if gs.half == "top" else "away",
                "pitcher": dict(pitching["current"]),
                "stamina": pitching["stamina"],
                "bullpen": [dict(p) for p in pitching["bullpen"]],
            }

    gs.reset_count()
    gs.advance_lineup()
    ...
    return dict(d1=d1, d2=d2, outcome=outcome, message=msg, commentary=commentary,
                method=method, play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=..., game_over=...,
                streaky=streaky, moves=gs.last_moves,
                pitching_change_available=pitching_change_available,
                state=_state_snapshot(gs))
```
(Add `pitching_change_available=pitching_change_available` to *both* `return dict(...)` statements in `_advance_game`, matching how `commentary` was added to both in the earlier phase.)

#### 3. Views — auto-swap helper, wired into `RollView` and `SimulateView`
**File**: `baseball/views.py`
**Changes**: A shared helper, since both views need identical logic.

```python
def _maybe_auto_swap_pitcher(game, gs, play):
    """If the play just made a pitching change available for a CPU-controlled
    side (or auto_play, which controls both sides), swap immediately and mark
    the play so the client doesn't also show a human prompt for it."""
    pca = play.get("pitching_change_available")
    if not pca:
        return
    side = pca["side"]
    is_cpu = game.mode == Game.AUTO_PLAY or game.cpu_side == side
    if not is_cpu:
        return
    pitching = gs.home_pitching if side == "home" else gs.away_pitching
    if not pitching["bullpen"]:
        return
    new_pitcher = pitching["bullpen"].pop(0)
    pitching["current"] = new_pitcher
    pitching["stamina"] = PITCHER_STAMINA_MAX
    pitching["prompted"] = False
    pitching["dismissed"] = False
    play["pitching_change_available"] = None
    play["auto_pitching_change"] = {"side": side, "name": new_pitcher["name"]}
```

`RollView.post` (`views.py:776-803`) and `SimulateView.post`'s loop body (`views.py:806-834`) each call it right after `_advance_game`:
```python
        roster = game.away_roster if gs.half == "top" else game.home_roster
        play = _advance_game(gs, roster)
        _maybe_auto_swap_pitcher(game, gs, play)
        pid = _pid_for_name(roster, play["batter"])
        ...  # rest unchanged
```

#### 4. Views — `PitcherChangeView`
**File**: `baseball/views.py`
**Changes**: New view, following the existing turn-check pattern from `RollView` (`views.py:783-789`).

```python
class PitcherChangeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(
            Game, Q(owner=request.user) | Q(player2=request.user), pk=pk,
        )
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        gs = game.load_state()
        fielding_side = "home" if gs.half == "top" else "away"

        if game.mode == Game.MULTIPLAYER:
            my_side = (game.owner_side if request.user == game.owner
                       else ("home" if game.owner_side == "away" else "away"))
            if fielding_side != my_side:
                return JsonResponse({"error": "not your pitcher"}, status=403)
        elif game.cpu_side == fielding_side:
            return JsonResponse({"error": "cpu-controlled side"}, status=403)

        pitching = gs.home_pitching if fielding_side == "home" else gs.away_pitching
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            body = {}
        action = body.get("action")

        if action == "dismiss":
            pitching["dismissed"] = True
        elif action == "change":
            pid = body.get("player_id")
            match = next((p for p in pitching["bullpen"] if p["player_id"] == pid), None)
            if not match:
                return JsonResponse({"error": "not in bullpen"}, status=400)
            pitching["bullpen"].remove(match)
            pitching["current"] = match
            pitching["stamina"] = PITCHER_STAMINA_MAX
            pitching["prompted"] = False
            pitching["dismissed"] = False
        else:
            return JsonResponse({"error": "bad action"}, status=400)

        game.save_state(gs)
        game.save()
        return JsonResponse({"pitching": pitching})
```

#### 5. URLs
**File**: `baseball/urls.py`
**Changes**: Add alongside the other `<int:pk>/...` action routes.

```python
    path("<int:pk>/change-pitcher/", views.PitcherChangeView.as_view(), name="baseball-change-pitcher"),
```

#### 6. Views — `_state_snapshot()` and `GameDetailView` context for live display
**File**: `baseball/views.py`
**Changes**: `_state_snapshot()` (`views.py:168-188`) gains current-pitcher/stamina for both sides, so no-reload stretches (`cpu_auto`'s CPU-batting loop) can update the display live:

```python
def _state_snapshot(gs: GameState) -> dict:
    return {
        ...  # unchanged
        "away_name":      gs.away_name,
        "home_name":      gs.home_name,
        "away_pitcher": {"name": gs.away_pitching["current"]["name"] if gs.away_pitching["current"] else None,
                         "stamina": gs.away_pitching["stamina"]},
        "home_pitcher": {"name": gs.home_pitching["current"]["name"] if gs.home_pitching["current"] else None,
                         "stamina": gs.home_pitching["stamina"]},
    }
```

`GameDetailView.get_context_data` (`views.py:716-773`) gains the fielding-side/permission/prompt context needed for the server-rendered banner and manual-change button (covers page-load discovery — critical for the multiplayer fielding side, who isn't the one whose `RollView` request most recently ran):

```python
        gs = self.object.load_state()
        ctx["current_batter"] = gs.current_batter
        ctx["batting_team"]   = gs.batting_team
        ...  # existing winner/stadium/my_side/lineups/cells blocks unchanged
        ctx["away_pitching"] = gs.away_pitching
        ctx["home_pitching"] = gs.home_pitching
        fielding_side = "home" if gs.half == "top" else "away"
        ctx["fielding_side"] = fielding_side
        if self.object.mode == Game.AUTO_PLAY:
            can_manage_pitching = False
        elif self.object.mode == Game.MULTIPLAYER:
            can_manage_pitching = ctx.get("my_side") == fielding_side
        elif self.object.mode == Game.CPU_AUTO:
            can_manage_pitching = self.object.cpu_side != fielding_side
        else:
            can_manage_pitching = True
        can_manage_pitching = can_manage_pitching and self.object.status == Game.ACTIVE
        ctx["can_manage_pitching"] = can_manage_pitching
        fielding_pitching = gs.home_pitching if fielding_side == "home" else gs.away_pitching
        ctx["fielding_pitching"] = fielding_pitching
        ctx["pitching_prompt"] = bool(
            can_manage_pitching and fielding_pitching["prompted"]
            and not fielding_pitching["dismissed"] and fielding_pitching["bullpen"]
        )
```

#### 7. Templates — stamina display, prompt banner, manual change button + picker
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**:

Add a small two-column "Pitching" card below the existing scoreboard card (`game_detail.html:129-178` area), showing both sides' current pitcher + a stamina bar:
```html
<div class="row g-4 mt-1">
  <div class="col-md-6">
    <div class="card">
      <div class="card-body py-2">
        <div class="small text-muted">{{ game.away_name }} Pitching</div>
        <div class="fw-semibold" id="away-pitcher-name">{{ game.state.away_pitching.current.name|default:"—" }}</div>
        <div class="progress" style="height:6px">
          <div class="progress-bar" id="away-pitcher-stamina"
               style="width:{{ game.state.away_pitching.stamina|default:100 }}%"></div>
        </div>
      </div>
    </div>
  </div>
  <div class="col-md-6">
    <div class="card">
      <div class="card-body py-2">
        <div class="small text-muted">{{ game.home_name }} Pitching</div>
        <div class="fw-semibold" id="home-pitcher-name">{{ game.state.home_pitching.current.name|default:"—" }}</div>
        <div class="progress" style="height:6px">
          <div class="progress-bar" id="home-pitcher-stamina"
               style="width:{{ game.state.home_pitching.stamina|default:100 }}%"></div>
        </div>
      </div>
    </div>
  </div>
</div>
```

Add the manual-change button + server-rendered prompt banner + bullpen picker, near `#btn-area` (`game_detail.html:234-269`):
```html
{% if can_manage_pitching and fielding_pitching.bullpen %}
<div id="pitching-controls" class="mb-3">
  {% if pitching_prompt %}
  <div class="alert alert-warning py-2 px-3 mb-2">
    <strong>{{ fielding_pitching.current.name }}</strong> is tiring
    ({{ fielding_pitching.stamina }}% stamina). Change pitchers?
    <div class="mt-1 d-flex gap-2">
      <button type="button" class="btn btn-sm btn-warning" id="btn-open-pitcher-picker">Change Pitcher</button>
      <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-dismiss-pitcher-prompt">Keep Pitching</button>
    </div>
  </div>
  {% else %}
  <button type="button" class="btn btn-sm btn-outline-secondary" id="btn-open-pitcher-picker">
    Change Pitcher
  </button>
  {% endif %}
  <div id="pitcher-picker" class="mt-2" style="display:none">
    {% for p in fielding_pitching.bullpen %}
    <button type="button" class="btn btn-sm btn-outline-primary me-1 mb-1 pitcher-pick-btn"
            data-player-id="{{ p.player_id }}">{{ p.name }}</button>
    {% endfor %}
  </div>
</div>
{% endif %}
```

#### 8. JS — wire the manual controls, the server-rendered prompt, and the one-shot in-loop prompt
**File**: `baseball/static/baseball/js/game.js`
**Changes**:

`updateBoard(state)` (`game.js:95-118`) updates the two stamina bars/names live (covers the `cpu_auto` no-reload stretch):
```javascript
function updateBoard(state) {
    ...  // unchanged existing lines
    updateOuts(state.outs);
    updateDiamond(state.bases, RUNNER_ANIM_MS);
    updatePitching(state);
}

function updatePitching(state) {
    if (state.away_pitcher) {
        document.getElementById('away-pitcher-name').textContent = state.away_pitcher.name || '—';
        document.getElementById('away-pitcher-stamina').style.width = state.away_pitcher.stamina + '%';
    }
    if (state.home_pitcher) {
        document.getElementById('home-pitcher-name').textContent = state.home_pitcher.name || '—';
        document.getElementById('home-pitcher-stamina').style.width = state.home_pitcher.stamina + '%';
    }
}
```

A new section, after `handlePlay` (`game.js:334-361`), for the one-shot in-loop prompt and the manual controls:
```javascript
// --- Pitching changes --------------------------------------------------

async function postPitcherAction(pk, body) {
    const resp = await fetch(`/baseball/${pk}/change-pitcher/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return resp.json();
}

function maybeShowPitchingPrompt(play) {
    const pca = play.pitching_change_available;
    if (!pca) return;
    // Server-rendered banner/button will pick this up on the next reload for
    // most modes; this handles the cpu_auto no-reload CPU-batting stretch,
    // where the fielding (human) side's client won't reload until half_over.
    const banner = document.createElement('div');
    banner.className = 'alert alert-warning py-2 px-3 mb-2';
    banner.innerHTML = `<strong>${pca.pitcher.name}</strong> is tiring (${pca.stamina}% stamina). Change pitchers?`;
    const btnArea = document.getElementById('btn-area');
    btnArea.prepend(banner);
}

const GAME_PK = ROLL_URL.match(/\/baseball\/(\d+)\//)[1];

document.getElementById('btn-open-pitcher-picker')?.addEventListener('click', () => {
    const picker = document.getElementById('pitcher-picker');
    picker.style.display = picker.style.display === 'none' ? '' : 'none';
});

document.getElementById('btn-dismiss-pitcher-prompt')?.addEventListener('click', async () => {
    await postPitcherAction(GAME_PK, { action: 'dismiss' });
    location.reload();
});

document.querySelectorAll('.pitcher-pick-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
        await postPitcherAction(GAME_PK, { action: 'change', player_id: parseInt(btn.dataset.playerId, 10) });
        location.reload();
    });
});
```

Call `maybeShowPitchingPrompt(play)` from `handlePlay(play)` (`game.js:334-361`), right after `appendPlay(play)`:
```javascript
async function handlePlay(play) {
    showDice(play.d1, play.d2, play.outcome, play.method);
    appendPlay(play);
    maybeShowPitchingPrompt(play);
    ...  // rest unchanged
}
```

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist — pre-existing)
- [x] Shell check: drove a `GameState` (fielding side starting at stamina 34, threshold 30) through 60 at-bats without letting the pitcher change — `pitching_change_available` fired exactly once (at stamina 30) and never reappeared even as stamina dropped to 0.
- [x] `PitcherChangeView` smoke check via `Client`: `{"action": "change", "player_id": <bullpen id>}` swapped `current`, reset `stamina` to 100, reset `prompted`/`dismissed` to `False`, removed the entry from `bullpen`; `player_id=999` (not in bullpen) returned 400; `{"action": "dismiss"}` set `dismissed=True` without changing `current`.
- [x] Turn-check smoke check: CPU-controlled fielding side → 403 `"cpu-controlled side"`; wrong multiplayer side (owner when home/fielding belongs to player2) → 403 `"not your pitcher"`; correct multiplayer side → 200.
- [x] `_maybe_auto_swap_pitcher` smoke check: `Game` with `mode=CPU_AUTO`, `cpu_side="home"`, stamina crossing threshold on the roll — swap happened server-side in the same `RollView` request, response had `pitching_change_available=None` and `auto_pitching_change={"side": "home", "name": "HomeReliever1"}`.
- [x] `auto_play` smoke check: 88-play simulated game with both sides pre-loaded near the threshold — both sides auto-swapped exactly once (`auto_pitching_change` for both `"home"` and `"away"`), zero unhandled `pitching_change_available` left in any play, game finished successfully.

#### Manual Verification
- [ ] Play a `click_all` game, drain a pitcher below threshold, confirm the prompt banner appears exactly once; clicking "Keep Pitching" dismisses it and it doesn't reappear; clicking "Change Pitcher" shows the bullpen picker, and picking a reliever updates the name/stamina display and doesn't re-prompt until *that* pitcher also tires out.
- [ ] Use the manual "Change Pitcher" button with a fully-rested pitcher (no threshold crossed) — confirm it's available and works regardless of stamina.
- [ ] Play a `cpu_auto` game as the human batting side (CPU fielding) — confirm the CPU's own pitcher auto-swaps with no prompt shown to you, and the stamina bar reflects the CPU's new pitcher.
- [ ] Play a `cpu_auto` game as the human fielding side while the CPU bats (the no-reload `autoRollCPU` stretch) — confirm the in-loop banner appears if your pitcher tires during that stretch, before any page reload.
- [ ] Multiplayer: as the fielding-side player (not the one whose roll just happened), confirm you see the prompt/manual button on your own next poll-reload, and the batting-side player does not see pitching controls for your team.
- [ ] Run `auto_play` end to end — confirm it completes without any interaction, and the play log shows evidence of auto-swaps if applicable.
- [ ] Confirm the bullpen depletes correctly — once all relievers are used, no further prompt/auto-swap occurs (the pitcher just stays in, increasingly fatigued) since the code gates on `pitching["bullpen"]` being non-empty.

**Implementation Note**: This is the final phase — no further pause needed after manual confirmation here.

---

## Testing Strategy

### Unit Tests
- `apply_fatigue(w, PITCHER_STAMINA_MAX)` returns the input unchanged.
- `apply_fatigue` at low stamina increases `walk`/`single`/`double`/`triple`/`home_run` weights proportionally to `(PITCHER_STAMINA_MAX - stamina) / PITCHER_STAMINA_MAX`.
- `_fresh_pitching(None, None)` produces `{"current": None, "stamina": 100, "bullpen": [], "prompted": False, "dismissed": False}`.
- `Game.state_to_dict`/`state_from_dict` round-trip an arbitrary mutated `away_pitching`/`home_pitching` dict losslessly.
- `_advance_game` drains exactly `STAMINA_DRAIN_PER_BATTER` per at-bat, floors at 0, and sets `pitching_change_available` exactly once per outing.
- `PitcherChangeView`: change swaps correctly and resets stamina/flags; dismiss sets `dismissed` only; wrong-side/wrong-mode requests are rejected.
- `_maybe_auto_swap_pitcher` only acts on CPU-controlled sides (or both sides in `auto_play`), and no-ops when the side's bullpen is empty.

### Manual Testing Steps
1. Set up a game, confirm bullpen cardinality/overlap validation.
2. Play until a pitcher tires; confirm the one-time prompt, then confirm no re-prompting after decline.
3. Manually change a fully-rested pitcher via the always-available button.
4. Play `cpu_auto` both as the CPU's opponent and (separately) observe the CPU's own auto-swap.
5. Play `cpu_auto` specifically through the no-reload CPU-batting stretch to confirm the in-loop banner.
6. Play multiplayer with both players, confirming the fielding side (not the active roller) sees their own prompt/controls.
7. Run `auto_play` end to end.
8. Exhaust a bullpen entirely and confirm the game continues (fatigued pitcher stays in, no further prompts).

## Performance Considerations
All pitching-staff state lives in the already-loaded `GameState`/`Game.state` JSON — no new queries beyond what Phase 1's `auto_fill_bullpen` adds (one extra `position_pools()` call, already O(team roster size)) and what `PitcherChangeView` adds (one `Game` fetch + save, same cost as `RollView`).

## Migration Notes
`0019_game_bullpen_fields.py` is a straightforward `AddField` migration (both new fields default to `[]`) — reverses cleanly. Pre-existing games created before this plan will have `away_bullpen=home_bullpen=[]` and, after Phase 2, `away_pitching`/`home_pitching` built with `current=None` (since `pitcher_from_roster` is only called for *newly created* games — existing in-progress games loaded via `state_from_dict` will fall back to the constructor's fresh empty pitching dicts, since `d.get("away_pitching")` will be `None`/missing for them). This means: fatigue is a no-op for pre-existing games (`pitching["current"]` is `None`, so `_advance_game`'s drain block is skipped entirely, matching the defensive case already covered in Phase 3's success criteria), and no pitching-change UI appears for them (`fielding_pitching.bullpen` is empty). They continue to play exactly as before this plan, indefinitely, with no data migration required.

## References
- Prior art (identical modifier-composition pattern): `thoughts/shared/plans/2026-08-17-weather-outcome-modifiers.md`
- Background research: `thoughts/shared/research/2026-08-17-outcome-probability-dice-vs-array.md`
- Roster/bullpen source data: `baseball/models.py:70-71` (`Player.g_sp`/`g_rp`), `baseball/models.py:99-124` (`FIELDING_COLS`/`position_pools`)
- Existing roster form/pool logic: `baseball/forms.py:1-87`
- Weighted-choice primitive and weather modifier (pattern to replicate): `baseball/engine.py:117-120`, `baseball/engine.py:374-399`
- Streaky-state persistence pattern (pattern to replicate for pitching state): `baseball/models.py:311-363`
- All game-creation call sites needing threading: `baseball/views.py:358-438`, `baseball/views.py:528-561`, `baseball/views.py:667-687`, `baseball/views.py:837-870`
- Play resolution / at-bat orchestration: `baseball/views.py:191-250`
- Live play round trip and mode-specific client loops: `baseball/views.py:776-834`, `baseball/static/baseball/js/game.js:363-453`
