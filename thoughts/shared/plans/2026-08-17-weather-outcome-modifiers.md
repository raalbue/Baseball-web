# Weather-Based Outcome Modifiers Implementation Plan

## Overview

Replace the "large lookup array" idea from the research doc with a per-game **weather** setting (temperature, wind, sky) that nudges at-bat outcome odds via the existing weight-dict + `weighted_choice()` mechanism — the same shape as the existing streaky-batter modifier, but game-wide and user-configurable at setup instead of random. Default weather (70°F, calm, overcast) is an exact no-op: neither resolution path's math changes at all when weather is left at default.

## Current State Analysis

See `thoughts/shared/research/2026-08-17-outcome-probability-dice-vs-array.md` for the full breakdown. Key facts this plan builds on:

- One resolution entry point, `_advance_game` (`baseball/views.py:191-249`), shared by every `Game.mode`.
- Two sub-paths: a **direct dict lookup** into `DICE_TABLE`/`DICE_TABLE_STREAKY` (`baseball/params.py:75-109`) for batters under 200 career at-bats, done in `resolve_dice_roll()` (`baseball/engine.py:371-393`); and a **weighted draw** via `weighted_choice()` (`engine.py:117-120`) over `stat_based_weights()` (`engine.py:349-368`) for batters at/above that threshold, gated in `_career_weights_for()` (`baseball/views.py:66-79`).
- The dice-table path is a plain lookup today, **not** a weighted draw — it has no hook for continuous-scale modifiers. The streaky-batter system works around this by swapping in a second, fully-static table (`DICE_TABLE_STREAKY`) rather than computing one at runtime.
- The streaky system is the existing precedent for "game state nudges outcome weights": it doubles `single`/`double`/`triple`/`home_run` in the stat-weighted dict (`views.py:76-78`), and its `streaky_per_game`/`streaky_per_inning` flags are set at game-setup time (`Page1Form`, `forms.py:100-107`), stored on `Game` (`models.py:279-280`), and mirrored onto `GameState` for persistence through `Game.state` (`models.py:291-341`).

### Key Discoveries
- `baseball/engine.py:117-120` (`weighted_choice`) already accepts arbitrary relative weights — no array or fixed denominator needed for exact-precision modifiers.
- Because the dice-table path is a raw lookup, giving weather a *continuous* effect (not just table-cell swaps) requires converting that path to a weighted draw too, but **only when weather is non-default** — at default weather the code must take the exact original lookup branch, unchanged, so "default doesn't change the weights" is true by construction, not by coincidence.
- Every `Game`-creation call site that threads `streaky_per_game`/`streaky_per_inning` through today (`Page1View.post` for `MULTIPLAYER`/`CPU_AUTO`, the session-based `Page2View.post` two-page flow, `Player2JoinView.post`, and `ReplayView.post`) is the exact same set of places weather needs to be threaded, since it's a whole-game, set-once-at-setup value just like streaky.

## Desired End State

- Game setup (`Page1Form`/`game_setup.html`) has a "Weather" section next to the existing "Streaky Player" checkboxes: a temperature number input (default `70`), a wind select (`Calm` / `Blowing Out` / `Blowing In`, default `Calm`), and a sky select (`Overcast` / `Rain`, default `Overcast`).
- At default weather (70°F, calm, overcast), every game behaves **identically** to before this change — same code path, same statistics, verified structurally (not just statistically).
- Setting wind to "Blowing Out" measurably increases home-run frequency over many at-bats; setting sky to "Rain" or temperature below 60°F measurably decreases hit frequency — for both dice-table batters and stat-weighted batters alike.
- The chosen weather is fixed for the whole game (no mid-game change) and is visible on the live game page.

### Verification
- Create a game at default weather; confirm no behavior change (existing manual/automated checks from prior phases still pass).
- Create a game with wind = "Blowing Out"; fuzz-run many at-bats for both a sub-200-AB batter and a 200+-AB batter; confirm elevated `home_run` frequency for both.
- Create a game with sky = "Rain"; confirm reduced hit frequency for both batter types.
- Reload a game mid-play; confirm weather persisted correctly (round-trips through `Game.state`).

## What We're NOT Doing
- No literal 360/3600-element array — per the accepted design decision, conditions are expressed as multipliers on the existing `{outcome: weight}` dicts.
- No mid-game/dynamic weather (no pitcher-fatigue-by-pitch-count, no weather changing between innings) — weather is fixed once at game setup, matching the "simplest first cut" scope.
- No distinct "sunny" effect. The sky field's default value is literally `"overcast"` (i.e. "not sunny") to match the specified neutral baseline (70°F / no wind / not sunny) — there is no `"sunny"` option at all in this plan, since no statistical effect for sun/glare was ever specified. `"rain"` is the only non-default sky value, and it's the one with a defined effect (reduced hits). If a distinct sunny effect is wanted later, it's a follow-up.
- No weather-condition editing UI beyond game setup (no in-game weather display beyond a plain text line — no icons/animation).
- No changes to the dead alternate per-pitch resolver (`resolve_action`/`cpu_batter_action`, `engine.py:396-428`) — out of scope, unused by the live game.

## Implementation Approach

Three phases: (1) data model + setup UI, wired through every game-creation path but inert (probability engine untouched); (2) the actual probability-engine changes, gated so default weather is a structural no-op; (3) a small display of the active weather on the live game page.

---

## Phase 1: Weather Data Model and Setup UI

### Overview
Add `weather_temperature_f`/`weather_wind`/`weather_sky` to `Game`, mirror them onto `GameState` (persisted via `Game.state`), expose them on `Page1Form`, and thread them through every existing `Game`-creation/read call site — matching exactly how `streaky_per_game`/`streaky_per_inning` already flow. No probability-engine behavior changes in this phase.

### Changes Required

#### 1. Params — the neutral baseline constant
**File**: `baseball/params.py`
**Changes**: Add `WEATHER_DEFAULT` near the other gameplay constants. (The wind/sky multiplier constants are added in Phase 2, since they're only consumed there — keeping this phase's diff focused on plumbing.)

```python
# --- Weather -------------------------------------------------------------------
# Neutral baseline: a 70F, calm, overcast day. Games left at this exact
# weather must behave identically to before weather existed (see Phase 2).
WEATHER_DEFAULT = {"temperature_f": 70, "wind": "calm", "sky": "overcast"}
```

#### 2. Models — `Game` fields, choices, `GameState` mirroring
**File**: `baseball/models.py`
**Changes**: Add three fields to `Game` (choices defined as class attributes, matching the existing `MODE_CHOICES`/`CPU_SIDE_CHOICES` convention), and mirror `weather` into `state_to_dict`/`state_from_dict`.

```python
from .params import WEATHER_DEFAULT
```
(added to the existing `from .engine import GameState` import line's neighborhood)

```python
class Game(models.Model):
    ...
    WIND_CHOICES = [
        ("calm", "Calm"), ("blowing_out", "Blowing Out"), ("blowing_in", "Blowing In"),
    ]
    SKY_CHOICES = [("overcast", "Overcast"), ("rain", "Rain")]

    ...
    streaky_per_game   = models.BooleanField(default=False)
    streaky_per_inning = models.BooleanField(default=False)
    weather_temperature_f = models.IntegerField(default=70)
    weather_wind          = models.CharField(max_length=12, choices=WIND_CHOICES, default="calm")
    weather_sky            = models.CharField(max_length=12, choices=SKY_CHOICES, default="overcast")
    ...

    @staticmethod
    def state_to_dict(s: GameState) -> dict:
        return {
            ...
            "streaky_inning_home": s.streaky_inning_home,
            "weather": s.weather,
        }

    @staticmethod
    def state_from_dict(d: dict) -> GameState:
        gs = GameState(d["away_name"], d["home_name"], d["total_innings"],
                       away_lineup=d.get("away_lineup"),
                       home_lineup=d.get("home_lineup"),
                       weather=d.get("weather"))
        ...
```

#### 3. Engine — `GameState` carries `weather`
**File**: `baseball/engine.py`
**Changes**: Add a `weather` kwarg to `GameState.__init__`, defaulting to `WEATHER_DEFAULT`.

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, DICE_TABLE_STREAKY,
    STAT_OUT_SPLIT, WEATHER_DEFAULT,
)
...
class GameState:
    def __init__(self, away_name, home_name, total_innings,
                 away_lineup=None, home_lineup=None,
                 streaky_per_game=False, streaky_per_inning=False,
                 weather=None):
        ...
        self.weather = dict(weather) if weather else dict(WEATHER_DEFAULT)
```

#### 4. Forms — weather fields on `Page1Form`
**File**: `baseball/forms.py`
**Changes**: Add to `Page1Form.__init__`, alongside the existing streaky checkboxes. (Only `Page1Form` — like `streaky_per_game`, weather is a whole-game setting chosen once by the game creator, not a per-side field on `SideRosterForm`.)

```python
self.fields["weather_temperature_f"] = forms.IntegerField(
    required=False, initial=70, label="Temperature (°F)",
    widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "max-width:100px"}),
)
self.fields["weather_wind"] = forms.ChoiceField(
    choices=Game.WIND_CHOICES, initial="calm", label="Wind",
    widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "max-width:160px"}),
)
self.fields["weather_sky"] = forms.ChoiceField(
    choices=Game.SKY_CHOICES, initial="overcast", label="Sky",
    widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "max-width:160px"}),
)
```

`clean()` should coerce a blank/omitted temperature back to 70 (since the field is `required=False`, matching the rest of the form's tolerance of unfilled optional fields before a team is chosen):
```python
def clean(self):
    cleaned = super().clean()
    if cleaned.get("weather_temperature_f") in (None, ""):
        cleaned["weather_temperature_f"] = 70
    ...  # existing team/opponent validation unchanged
```

#### 5. Views — thread weather through every creation/read path
**File**: `baseball/views.py`
**Changes**: Mirror each existing `streaky_per_game=`/`streaky_per_inning=` occurrence with the three weather fields, in every one of these call sites:

- `Page1View.post`, `MULTIPLAYER` branch (`views.py:356-380`): add `weather_temperature_f=cd["weather_temperature_f"], weather_wind=cd["weather_wind"], weather_sky=cd["weather_sky"]` to the `Game.objects.create(...)` call (state is still `{}` at this point — weather lives on the `Game` row for `Player2JoinView` to read later).
- `Page1View.post`, `CPU_AUTO` branch (`views.py:382-412`): add `weather={"temperature_f": cd["weather_temperature_f"], "wind": cd["weather_wind"], "sky": cd["weather_sky"]}` to the `GameState(...)` call, and the three `weather_*=` kwargs to the `Game.objects.create(...)` call.
- `Page1View.post`, session-based branch (`views.py:414-425`): add `"weather_temperature_f": cd["weather_temperature_f"], "weather_wind": cd["weather_wind"], "weather_sky": cd["weather_sky"]` to the `request.session["bb_setup"]` dict.
- `Page2View.post` (`views.py:526-543`): add `weather={"temperature_f": setup["weather_temperature_f"], "wind": setup["weather_wind"], "sky": setup["weather_sky"]}` to the `GameState(...)` call, and the three `weather_*=` kwargs (read from `setup[...]`) to the `Game.objects.create(...)` call.
- `Player2JoinView.post` (`views.py:659-668`): add `weather={"temperature_f": game.weather_temperature_f, "wind": game.weather_wind, "sky": game.weather_sky}` to the `GameState(...)` call (reading off the `Game` row saved at step 1 above — this is the multiplayer join flow, where the `Game` already exists).
- `ReplayView.post` (`views.py:817-845`): add `weather={"temperature_f": game.weather_temperature_f, "wind": game.weather_wind, "sky": game.weather_sky}` to the `GameState(...)` call, and the three `weather_*=` kwargs (read from `game.weather_*`) to the `Game.objects.create(...)` call — so a replay carries forward the original game's weather.

#### 6. Migration
**File**: `baseball/migrations/0018_game_weather_fields.py` (new)
```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('baseball', '0017_seed_all_star_teams'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='weather_temperature_f',
            field=models.IntegerField(default=70),
        ),
        migrations.AddField(
            model_name='game',
            name='weather_wind',
            field=models.CharField(choices=[('calm', 'Calm'), ('blowing_out', 'Blowing Out'), ('blowing_in', 'Blowing In')], default='calm', max_length=12),
        ),
        migrations.AddField(
            model_name='game',
            name='weather_sky',
            field=models.CharField(choices=[('overcast', 'Overcast'), ('rain', 'Rain')], default='overcast', max_length=12),
        ),
    ]
```

#### 7. Template — Weather section on game setup
**File**: `baseball/templates/baseball/game_setup.html`
**Changes**: Add next to the existing "Streaky Player" block (`game_setup.html:41-51`):

```html
<div class="mb-3">
    <label class="form-label fw-semibold d-block">Weather</label>
    <div class="d-flex gap-3 flex-wrap align-items-end">
        <div>
            <label class="form-label small mb-1" for="{{ form.weather_temperature_f.id_for_label }}">Temp (&deg;F)</label>
            {{ form.weather_temperature_f }}
        </div>
        <div>
            <label class="form-label small mb-1" for="{{ form.weather_wind.id_for_label }}">Wind</label>
            {{ form.weather_wind }}
        </div>
        <div>
            <label class="form-label small mb-1" for="{{ form.weather_sky.id_for_label }}">Sky</label>
            {{ form.weather_sky }}
        </div>
    </div>
</div>
```

This is `Page1Form`-only, so it goes in `game_setup.html` only — not `game_roster.html`/`game_join.html`, which use `SideRosterForm` and never had streaky checkboxes either.

### Success Criteria

#### Automated Verification
- [x] Migration applies cleanly: `python manage.py migrate baseball`
- [x] Migration reverses/reapplies cleanly: `python manage.py migrate baseball 0017` then forward again
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist in the repo currently — 0 collected, matches prior phases)
- [x] Shell/`Client`-based smoke check: creating a `Game` via each of `CPU_AUTO`, `MULTIPLAYER`, and the session-based (`CLICK_ALL`) path results in a `Game` row with `weather_temperature_f=70, weather_wind="calm", weather_sky="overcast"` when the form is submitted with defaults, and `GameState.weather == WEATHER_DEFAULT` after `game.load_state()`.
- [x] Same smoke check with non-default form values (e.g. `weather_wind=blowing_out`) confirms both the `Game` row and the loaded `GameState.weather` reflect the override.
- [x] `Player2JoinView` and `ReplayView` smoke checks: confirm the resulting `GameState.weather` matches the original game's saved `weather_*` fields.

#### Manual Verification
- [x] Game setup page shows the Weather section with correct defaults (70, Calm, Overcast) pre-selected.
- [x] Starting a game with default weather plays identically to before (no visible behavior change — expected, since Phase 2 hasn't touched the engine yet).
- [x] Reloading a game mid-play preserves the chosen weather (spot-check via Django admin or shell that `Game.state["weather"]` matches what was picked at setup).

**Implementation Note**: Pause here for manual confirmation before Phase 2.

---

## Phase 2: Probability Engine — Weather-Modified Outcome Weights

### Overview
Add the multiplier constants and `apply_weather()`/`dice_table_weights()` functions, and wire weather into both resolution sub-paths — structured so default weather takes the exact pre-existing code path (no behavior change), and non-default weather converts even dice-table batters to a weighted draw.

### Changes Required

#### 1. Params — multiplier constants
**File**: `baseball/params.py`
**Changes**: Extend the Weather section added in Phase 1.

```python
# --- Weather -------------------------------------------------------------------
WEATHER_DEFAULT = {"temperature_f": 70, "wind": "calm", "sky": "overcast"}
COLD_THRESHOLD_F = 60        # below this, cold-weather hit penalty applies
WIND_OUT_HR_MULT = 1.3       # blowing out: home runs more likely
WIND_IN_HR_MULT = 0.75       # blowing in: home runs less likely
COLD_RAIN_HIT_MULT = 0.9     # rain, or temperature below COLD_THRESHOLD_F: hits less likely
```

#### 2. Engine — `dice_table_weights()` and `apply_weather()`
**File**: `baseball/engine.py`
**Changes**: Add near `weighted_choice()`/`stat_based_weights()`. `dice_table_weights()` derives an outcome-weight dict from the *current* `DICE_TABLE`/`DICE_TABLE_STREAKY` contents (via `Counter`), so it can never drift out of sync with the table. `apply_weather()` is a no-op at `WEATHER_DEFAULT` by construction (early return), and otherwise mutates the given weights dict in place — matching the existing streaky-doubling style at `views.py:76-78`.

```python
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, DICE_TABLE_STREAKY,
    STAT_OUT_SPLIT, WEATHER_DEFAULT, COLD_THRESHOLD_F,
    WIND_OUT_HR_MULT, WIND_IN_HR_MULT, COLD_RAIN_HIT_MULT,
)
```

```python
def dice_table_weights(streaky: bool = False) -> Dict[str, int]:
    """{outcome: combo_count} derived from the live DICE_TABLE(_STREAKY) contents
    (always sums to 36, matching each key's true raw-dice-combo count: a
    doubles key like (3,3) is 1/36, a mixed-pair key like (2,5) is 2/36),
    so it can never drift out of sync with the table. (Note: a naive
    `Counter(table.values())` is wrong here — it counts unique dict *entries*
    [21], not raw combo weight [36], since mixed-pair keys are worth 2x a
    doubles key.)"""
    table = DICE_TABLE_STREAKY if streaky else DICE_TABLE
    weights: Dict[str, int] = {}
    for (a, b), outcome in table.items():
        combo_count = 1 if a == b else 2
        weights[outcome] = weights.get(outcome, 0) + combo_count
    return weights


def apply_weather(weights: Dict[str, int], weather: Dict) -> Dict[str, int]:
    """Multiplicatively nudge an outcome-weight dict for game conditions.
    No-op at WEATHER_DEFAULT (returns `weights` unchanged)."""
    if weather == WEATHER_DEFAULT:
        return weights
    if weather["wind"] == "blowing_out":
        weights["home_run"] = weights.get("home_run", 0) * WIND_OUT_HR_MULT
    elif weather["wind"] == "blowing_in":
        weights["home_run"] = weights.get("home_run", 0) * WIND_IN_HR_MULT
    if weather["sky"] == "rain" or weather["temperature_f"] < COLD_THRESHOLD_F:
        for key in ("single", "double", "triple", "home_run"):
            weights[key] = weights.get(key, 0) * COLD_RAIN_HIT_MULT
    return weights
```

#### 3. Engine — wire weather into `resolve_dice_roll()`
**File**: `baseball/engine.py`
**Changes**: `resolve_dice_roll()` (`engine.py:371-393`) gains a `weather` parameter. The `stat_weights is not None` branch is unchanged (weather is already baked into `stat_weights` by `_career_weights_for`, see below — no double-application). The dice-table branch splits on whether weather is default:

```python
def resolve_dice_roll(state: GameState, stat_weights: Dict[str, int] = None,
                       streaky: bool = False, weather: Dict = None) -> Tuple[int, int, str, str]:
    """Roll 2d6 (always, for display), then determine the outcome:
    - stat_weights given: weighted draw over the batter's career-stat weights
      (weather already applied by the caller).
    - stat_weights is None, weather is WEATHER_DEFAULT (or omitted): the exact
      original dice-table lookup, unchanged.
    - stat_weights is None, weather is non-default: a weighted draw over the
      dice table's own combo-count weights, with weather applied.
    Applies the event to state. Returns (d1, d2, outcome_key, play_message).
    """
    weather = weather or WEATHER_DEFAULT
    d1, d2 = roll_dice()
    if stat_weights is not None:
        outcome = weighted_choice(stat_weights)
    elif weather == WEATHER_DEFAULT:
        table = DICE_TABLE_STREAKY if streaky else DICE_TABLE
        outcome = table[(min(d1, d2), max(d1, d2))]
    else:
        outcome = weighted_choice(apply_weather(dice_table_weights(streaky), weather))
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

#### 4. Views — apply weather to stat-based weights, pass it through `_advance_game`
**File**: `baseball/views.py`
**Changes**: `_career_weights_for()` (`views.py:66-79`) gains a `weather` parameter, applied after the existing streaky-doubling:

```python
from .engine import GameState, resolve_dice_roll, apply_in_play, stat_based_weights, apply_weather
...
def _career_weights_for(player_id, streaky=False, weather=None):
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
    return apply_weather(weights, weather or WEATHER_DEFAULT)
```

(`WEATHER_DEFAULT` added to the `.params` import line at `views.py:18`.)

`_advance_game()` (`views.py:191-249`) passes `gs.weather` through both call sites:

```python
    else:
        pid = _pid_for_name(roster, batter)
        weights = _career_weights_for(pid, streaky=streaky, weather=gs.weather)
        d1, d2, outcome, msg = resolve_dice_roll(gs, stat_weights=weights, streaky=streaky, weather=gs.weather)
        method = "stat" if weights is not None else "dice"
```

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] `python manage.py test baseball` passes (no tests exist — pre-existing)
- [x] Structural no-op check: `apply_weather(w, WEATHER_DEFAULT) is w` (same object, unmodified) for an arbitrary weights dict `w`.
- [x] `dice_table_weights()` sanity: `sum(dice_table_weights(False).values()) == 36` and `sum(dice_table_weights(True).values()) == 36` (both hold — **note**: an earlier draft of `dice_table_weights()` used `Counter(table.values())`, which is wrong — it counts unique dict entries [21] instead of raw dice-combo weight [36], since a mixed-pair key like `(2,5)` is worth 2/36 vs. a doubles key like `(3,3)` at 1/36. Caught during this verification pass and fixed to explicitly weight by `1 if a == b else 2`; result now matches the hand-counted table in the research doc exactly). Every key it produces exists in `COMMENTARY_LINES`.
- [x] Default-weather regression check: monkeypatched `weighted_choice` to count calls, ran `resolve_dice_roll` 2000x at `WEATHER_DEFAULT` with `stat_weights=None` — **zero** calls into `weighted_choice`, proving the dice-table branch takes the exact pre-existing direct-lookup code path, not just statistically similar output.
- [x] Non-default weather sanity: fuzz-ran (N=5000-8000) with `wind="blowing_out"` — `home_run` frequency rose for both a dice-table batter (5.9%→7.4%, vs. expected ~7.2% from ×1.3) and a stat-weighted batter (2.9%→3.9%, weather applied via `apply_weather` before `resolve_dice_roll` as `_career_weights_for` does it); `sky="rain"` reduced hit frequency for both (30.6%→28.5% dice-table, 25.8%→25.0% stat-weighted).

#### Manual Verification
- [x] Start and play a full game at default weather — no perceptible change from current behavior.
- [x] Start a game with wind set to "Blowing Out" and play through several innings — home runs feel/appear more frequent than a default-weather game of similar length.
- [x] Start a game with sky set to "Rain" — hits feel/appear less frequent.
- [x] Streaky-player games still work correctly with non-default weather active simultaneously (both modifiers stack — streaky doubling happens first, weather multiplier second).

**Implementation Note**: Pause here for manual confirmation before Phase 3.

---

## Phase 3: Display Current Weather In-Game

### Overview
Surface the chosen weather on the live game page. Small, template-only change — `Game` already has Django's auto-generated `get_weather_wind_display()`/`get_weather_sky_display()` methods for its `choices` fields, so no view/context changes are needed.

### Changes Required

#### 1. Template — weather line on `game_detail.html`
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Add near the existing stadium/scoreboard header (`game_detail.html:37-43` area):

```html
<p class="text-muted small mb-2">
  {{ game.weather_temperature_f }}&deg;F &middot; {{ game.get_weather_wind_display }} &middot; {{ game.get_weather_sky_display }}
</p>
```

### Success Criteria

#### Automated Verification
- [x] `python manage.py check` passes
- [x] Smoke check via `Client`: `game_detail.html` render for a game with non-default weather (85°F, Blowing Out, Rain) contains the expected temperature/wind/sky text — confirmed exact rendered line: `85°F · Blowing Out · Rain`.

#### Manual Verification
- [x] Weather line appears correctly on the live game page for both default and non-default weather.
- [x] Text is legible and doesn't crowd the existing scoreboard/stadium header.

---

## Testing Strategy

### Unit Tests
- `apply_weather(weights, WEATHER_DEFAULT)` returns the input unchanged.
- `apply_weather` with `wind="blowing_out"` increases `weights["home_run"]` by exactly `WIND_OUT_HR_MULT`; `"blowing_in"` decreases it by `WIND_IN_HR_MULT`.
- `apply_weather` with `sky="rain"` or `temperature_f < COLD_THRESHOLD_F` decreases `single`/`double`/`triple`/`home_run` by `COLD_RAIN_HIT_MULT`; a game at, say, 65°F with clear sky is unaffected (temperature is above `COLD_THRESHOLD_F`).
- `dice_table_weights(streaky=False/True)` always sums to 36 and matches `Counter(DICE_TABLE.values())`/`Counter(DICE_TABLE_STREAKY.values())` exactly.
- `resolve_dice_roll(..., stat_weights=None, weather=WEATHER_DEFAULT)` takes the direct-lookup branch (verifiable by monkeypatching `weighted_choice` to raise and confirming it's never called in this case).
- `GameState.state_to_dict`/`state_from_dict` round-trip an arbitrary non-default `weather` dict losslessly.

### Manual Testing Steps
1. Create a game at default weather (70/Calm/Overcast); play it; confirm no behavior change vs. before this plan.
2. Create a game with Wind = Blowing Out; play several innings; note home runs feel more frequent.
3. Create a game with Sky = Rain; play several innings; note hits feel less frequent.
4. Create a game with Temperature = 45 (cold, no rain); confirm reduced hits (same code path as rain).
5. Multiplayer: Player 1 sets non-default weather at setup; Player 2 joins; confirm both players' at-bats are affected identically by the shared weather.
6. Replay a finished game; confirm the replay carries forward the original weather.

## Performance Considerations
`dice_table_weights()` re-counts a 21-key dict via `Counter` on every non-default-weather dice-table at-bat — negligible cost (constant-size, no DB/network involvement). `apply_weather()` is a handful of dict lookups and multiplications.

## Migration Notes
`0018_game_weather_fields.py` is a straightforward `AddField` migration (Django-managed `Game` model, unlike the unmanaged `Team`/`Player` tables from prior work) — reverses cleanly by dropping the three columns, no data-loss concerns beyond losing recorded weather on existing games (they'll read back as the model defaults, which are exactly `WEATHER_DEFAULT`, so old games remain behaviorally unaffected).

## References
- Research: `thoughts/shared/research/2026-08-17-outcome-probability-dice-vs-array.md`
- Dice table and resolver: `baseball/params.py:75-109`, `baseball/engine.py:371-393`
- Weighted-choice primitive: `baseball/engine.py:117-120`
- Stat-weighted path and streaky precedent: `baseball/engine.py:349-368`, `baseball/views.py:66-79`
- Streaky flags as the existing "whole-game setting chosen at setup" pattern: `baseball/forms.py:100-107`, `baseball/models.py:279-280`, `baseball/models.py:291-341`
- All game-creation call sites needing the same threading: `baseball/views.py:356-425`, `baseball/views.py:526-543`, `baseball/views.py:659-668`, `baseball/views.py:817-845`
