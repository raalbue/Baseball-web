# Season Mode Implementation Plan

## Overview

Add a season mode to the baseball web app: the player drafts into an 8- or 16-team league (drawn randomly from the 30 real MLB teams, excluding the AL/NL All-Star pseudo-teams), picks one team and locks in a roster for the whole season, and plays through a round-robin regular-season schedule of 3-game series against every other team in the league. Games where the player's team isn't involved simulate instantly (CPU vs CPU); the player's own games are played interactively exactly like a normal single game today. Progress is saved after every game so a season can be closed and resumed later. Standings (W/L, RS/RA per 9 innings, ERA, team AVG, win%) determine playoff seeding: top 4 of an 8-team season or top 8 of a 16-team season, seeded #1 vs #N, #2 vs #(N-1), etc., first round best-of-3, every round after best-of-5. A purely cosmetic fabricated calendar (dates/times, no gameplay effect) is generated from the season's creation date for the whole regular season and playoffs.

## Current State Analysis

The app has no season/league/schedule/standings/playoff concept anywhere (confirmed by full model, migration, and view audit — see `thoughts/shared/research/2026-08-18-season-mode.md`). What exists that this plan builds directly on top of:

- **`Game`** (`baseball/models.py:246-375`) is the unit of one played game: team/roster/mode fields, a `state` JSONField round-tripped through `state_to_dict`/`state_from_dict`/`load_state`/`save_state`, and a `status` of `active`/`waiting`/`finished`. No FK to anything season-like exists on it today.
- **`SimulateView`** (`baseball/views.py:935-964`) already runs a whole game to completion server-side in one request: loops `_advance_game(gs, roster)` until `gs.game_over`, batches player stat updates, and marks the game `FINISHED`. This is the exact mechanism CPU-vs-CPU season games need, just currently only reachable one game at a time via a button click.
- **`auto_fill_roster`/`auto_fill_bullpen`/`cpu_roster_for`** (`baseball/views.py:115-165`) already build a complete, legal 10-slot roster + bullpen for any `Team` with zero human input — exactly what every non-player team in a season needs.
- **`is_all_star_team(team)`** (`baseball/models.py:114-115`) checks `team.division == "All-Star"`; the two All-Star pseudo-teams are `team_id` 31/32 (seeded in `baseball/migrations/0017_seed_all_star_teams.py`). `Team.objects.exclude(division="All-Star")` gives the 30 real teams available for a season's league.
- **`SideRosterForm`** / **`_position_field.html`** / **`_bullpen_field.html`** (`baseball/forms.py:37-115`, `baseball/templates/baseball/_position_field.html`, `_bullpen_field.html`) are the existing team+roster+bullpen picker UI/form, reused unmodified by `Page1View`, `Page2View`, and `Player2JoinView` — the season creation page reuses this same shape for picking the player's team/roster.
- **Ownership-scoped CRUD conventions**: `GameListView` (list, `baseball/views.py:323-347`), `Page1View` (multi-action create page, `350-533`), `CancelWaitingView` (POST-only owner-scoped delete, `798-805`) are the established patterns a season hub/create/delete page follows.
- **Gaps this plan fills**: no model groups multiple `Game`s together; no schedule/series/bracket model; no standings computation; no artificial calendar generator; no "auto-play CPU games until it's the player's turn" chaining (today `SimulateView` only ever plays one already-existing game to completion, triggered by a human click).

## Desired End State

A logged-in user can:
1. Go to a new "Season Mode" page from the main nav, see any in-progress/finished seasons they own, start a new one, or delete one.
2. Start a new season by picking 8 or 16 teams and one team to play as, with a roster/bullpen picker identical in spirit to the existing new-game setup.
3. Land on a season detail page showing the standings table and a schedule/calendar list.
4. Click "Play Next Game": if the next scheduled matchup involves their team, they're taken to the normal interactive game-detail page to play it (exactly like a regular game); if not, the app auto-simulates every consecutive CPU-vs-CPU matchup instantly and stops as soon as it reaches the player's next game (or the season/round ends).
5. See the season persist exactly where they left off after closing the browser and coming back — every finished game writes its result back into the season immediately.
6. After the regular season's round-robin schedule completes, see the playoff bracket auto-generate from the standings (top 4 of 8 teams, or top 8 of 16), and play through it — first round best-of-3, every round after best-of-5 — with the same "play your games, CPU-vs-CPU auto-plays" flow, until a champion is decided and the season is marked finished.
7. See a fabricated schedule of dates/times for every game in the season and playoffs, generated once at season creation from the creation date — cosmetic only, never read by any gameplay logic.

### Key Discoveries
- `SimulateView`'s loop body (`baseball/views.py:940-963`) needs to be extracted into a plain function so both the existing button-triggered path and the new season auto-chain can call it without duplicating logic.
- `GameStat` (`baseball/models.py:398-423`) is an **unmanaged** model mapped onto a pre-existing external Postgres table (`db_table="game_stat"`) with no pitching columns (no earned runs, no innings pitched) — this plan does **not** add columns to it. Team ERA is instead derived from each season schedule entry's final score/innings (see "ERA / earned runs" decision below), and team batting AVG is computed by aggregating existing `GameStat` rows filtered to a team's own players across the season's `Game` rows — no schema change to `GameStat` needed.
- `Game.away_team`/`home_team` FKs already exist and are nullable/`SET_NULL` (`baseball/models.py:280-287`), so linking a season game back to real `Team` rows for standings/box scores requires no changes there.

## What We're NOT Doing

- No mid-season roster changes, trades, injuries, or lineup edits — the player's roster/bullpen is locked in at season creation and reused for every game of that season (matches how `SavedRoster` already works: pick once, reuse).
- No per-game weather or streaky-player variation for season games — every season game uses `WEATHER_DEFAULT` and streaky off, same as a plain default game. (Could be a future enhancement; explicitly out of scope here.)
- No unearned-run/error tracking — the engine has no fielding-error mechanic beyond flavor text (`"single_error"` is just a commentary variant of a regular single), so season ERA treats all runs allowed as earned. This is a documented simplification, not a gap to fill later in this plan.
- No cross-season persistent standings, career totals, or Hall-of-Fame-style history — each `Season` is self-contained; nothing carries over from one season to the next.
- No trading/free agency/draft between seasons — a new season always draws a fresh random league from the 30 real teams.
- No changes to multiplayer mode, single-game mode, or any existing URL/behavior — season mode is purely additive.
- No use of the existing unmanaged `MLBSchedule` model (`baseball/models.py:139-161`) — it's a dormant, unseeded external table unrelated to the app's own `Game` model; season scheduling gets its own new, app-owned (managed) model instead, consistent with how `Game`/`SavedRoster` were added.
- No home/away "back-and-forth" road-trip realism — each regular-season series between two teams is played once, entirely at one team's park (randomly chosen host), not as two reciprocal series.

## Implementation Approach

Add one new managed model, `Season`, that owns a flattened, ordered `schedule` (JSONField — same "serialize the whole thing as JSON" convention `Game.state` already uses) of individual game entries covering the full round-robin regular season, with playoff-round entries appended once the regular season completes. `Game` gets two new nullable fields (`season` FK, `season_entry_id`) so any season game is also a completely normal `Game` row, playable through the exact same `GameDetailView`/`RollView`/`PitcherChangeView` UI as any other game — season mode adds no new gameplay code path, only a scheduling/bookkeeping layer around existing gameplay. A new pure-function module (`baseball/season.py`) holds schedule generation, the fabricated calendar, standings computation, and bracket/round-advancement logic, kept independent of Django views for testability. A new `SeasonAdvanceView` (plus hooks added to the existing `RollView`/`SimulateView` completion paths) drives the "auto-play every CPU-vs-CPU game until it's the player's turn" behavior by repeatedly creating and immediately simulating entries via the same `simulate_full_game` function `SimulateView` uses.

## Phase 1: Data Model

### Overview
Add the `Season` model and the two new `Game` fields it needs to link back to a season.

### Changes Required

#### 1. `Season` model
**File**: `baseball/models.py`
**Changes**: Add a new managed model after `SavedRoster` (`baseball/models.py:378-395`).

```python
class Season(models.Model):
    SIZE_CHOICES = [(8, "8 Teams"), (16, "16 Teams")]
    REGULAR  = "regular"
    PLAYOFFS = "playoffs"
    FINISHED = "finished"
    STAGE_CHOICES = [
        (REGULAR, "Regular Season"),
        (PLAYOFFS, "Playoffs"),
        (FINISHED, "Finished"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="baseball_seasons")
    size = models.PositiveSmallIntegerField(choices=SIZE_CHOICES)
    player_team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="+")
    player_roster = models.JSONField(default=list)   # same shape as Game.away_roster/home_roster
    player_bullpen = models.JSONField(default=list)   # same shape as Game.away_bullpen/home_bullpen
    team_ids = models.JSONField(default=list)          # league membership, len == size
    schedule = models.JSONField(default=list)           # flattened ordered game entries (see season.py)
    bracket = models.JSONField(default=list)             # playoff round metadata, populated at REGULAR -> PLAYOFFS
    current_index = models.PositiveIntegerField(default=0)  # pointer into `schedule`
    stage = models.CharField(max_length=10, choices=STAGE_CHOICES, default=REGULAR)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.player_team.name} — {self.get_size_display()} Season"
```

#### 2. `Game` FKs to `Season`
**File**: `baseball/models.py`
**Changes**: Add two nullable fields to `Game` (near `away_bullpen`/`home_bullpen`, `baseball/models.py:301-302`).

```python
    season = models.ForeignKey('Season', null=True, blank=True, on_delete=models.CASCADE,
                                related_name='season_games')
    season_entry_id = models.PositiveIntegerField(null=True, blank=True)
```

#### 3. Migration
**File**: `baseball/migrations/00XX_season.py` (auto-generated)
**Changes**: `python manage.py makemigrations baseball` generates the `CreateModel(Season)` + `AddField(Game.season)` + `AddField(Game.season_entry_id)` migration. No data migration needed (new feature, no existing rows to backfill).

### Success Criteria

#### Automated Verification
- [ ] `python manage.py makemigrations baseball --check` shows no missing migrations after running `makemigrations`
- [ ] `python manage.py migrate` applies cleanly
- [ ] `python manage.py check` reports no issues

#### Manual Verification
- [ ] `python manage.py shell` can `Season.objects.create(owner=<user>, size=8, player_team=<team>)` and read it back without error

---

## Phase 2: Schedule & Calendar Generation

### Overview
Pure, view-independent functions that build the round-robin regular-season schedule (team selection, matchup pairing, home/away assignment) and the fabricated calendar (dates/times) laid on top of it. No database writes here — these return plain data structures that `Season.team_ids`/`Season.schedule` get set to.

### Changes Required

#### 1. New module `baseball/season.py`
**File**: `baseball/season.py` (new)
**Changes**: Schedule/calendar generation.

```python
import itertools
import random
from datetime import timedelta

from .models import Team

GAME_TIMES = ["1:05 PM", "1:10 PM", "4:05 PM", "7:05 PM", "7:10 PM", "7:40 PM", "8:10 PM"]
SERIES_LENGTH = {"regular": 3, "first_round": 3, "later_round": 5}


def pick_league(player_team, size):
    """Player's team + (size - 1) other real (non-All-Star) teams, randomly chosen.
    Returns a list of team_ids, length == size."""
    pool = list(Team.objects.exclude(division="All-Star")
                .exclude(pk=player_team.pk)
                .values_list("team_id", flat=True))
    others = random.sample(pool, size - 1)
    team_ids = [player_team.team_id] + others
    random.shuffle(team_ids)
    return team_ids


def build_regular_season_schedule(team_ids, start_date):
    """Every team plays every other team once, as one 3-game series (round robin).
    Series order and home/away are randomized. Returns a flattened list of entry
    dicts, each: id, phase, round, series_id, game_number, away_team_id,
    home_team_id, date, time, status, game_id, away_score, home_score, innings."""
    pairs = list(itertools.combinations(team_ids, 2))
    random.shuffle(pairs)

    entries = []
    day = start_date
    entry_id = 0
    for series_id, (a, b) in enumerate(pairs):
        away_id, home_id = (a, b) if random.random() < 0.5 else (b, a)
        for game_number in range(1, SERIES_LENGTH["regular"] + 1):
            entries.append({
                "id": entry_id,
                "phase": "regular",
                "round": "regular",
                "series_id": series_id,
                "game_number": game_number,
                "away_team_id": away_id,
                "home_team_id": home_id,
                "date": day.isoformat(),
                "time": random.choice(GAME_TIMES),
                "status": "scheduled",
                "game_id": None,
                "away_score": None,
                "home_score": None,
                "innings": None,
            })
            entry_id += 1
            day += timedelta(days=1)
    return entries


def next_entry_id(schedule):
    return (max((e["id"] for e in schedule), default=-1)) + 1


def build_round_entries(schedule, matchups, round_name, best_of, start_date):
    """Append a new playoff round's entries to `schedule` in place (also returned).
    `matchups` is a list of (away_team_id, home_team_id) pairs, one per series,
    higher seed already resolved to the host-heavy side by the caller."""
    entry_id = next_entry_id(schedule)
    day = start_date
    for series_id, (away_id, home_id) in enumerate(matchups):
        for game_number in range(1, best_of + 1):
            # Standard 2-1 (best_of=3) / 2-2-1 (best_of=5) home split favoring the
            # higher (first-listed / "home_id") seed, purely cosmetic scheduling.
            game_home, game_away = (home_id, away_id) if _hosts_home(game_number, best_of) \
                                    else (away_id, home_id)
            schedule.append({
                "id": entry_id,
                "phase": "playoffs",
                "round": round_name,
                "series_id": f"{round_name}-{series_id}",
                "game_number": game_number,
                "away_team_id": game_away,
                "home_team_id": game_home,
                "date": day.isoformat(),
                "time": random.choice(GAME_TIMES),
                "status": "scheduled",
                "game_id": None,
                "away_score": None,
                "home_score": None,
                "innings": None,
            })
            entry_id += 1
            day += timedelta(days=1)
    return schedule


def _hosts_home(game_number, best_of):
    """True if the higher seed hosts this game number."""
    if best_of == 3:
        return game_number in (1, 2)
    return game_number in (1, 2, 5)
```

### Success Criteria

#### Automated Verification
- [ ] New unit tests in `baseball/tests.py` pass: `python manage.py test baseball` — cover `pick_league` (correct size, excludes All-Star teams, includes player's team), `build_regular_season_schedule` (every pair appears exactly once, `3 * C(size, 2)` entries, dates strictly increasing), `build_round_entries` (correct entry count for best_of=3 vs 5, home/away split matches `_hosts_home`)

#### Manual Verification
- [ ] N/A (pure functions, fully covered by automated tests)

---

## Phase 3: Standings Computation

### Overview
Pure functions that derive standings (W/L, RS/RA per-9, ERA, team AVG, win%) from a `Season`'s `schedule` and linked `Game`/`GameStat` rows — computed on demand, not cached, since a season's schedule is at most 360 entries (16-team case).

### Changes Required

#### 1. `compute_standings` in `baseball/season.py`
**File**: `baseball/season.py`
**Changes**: Append standings logic.

```python
from django.db.models import Sum

from .models import GameStat, Team


def compute_standings(season):
    """One row per team in the league, sorted by win_pct desc (tiebreak: run
    differential desc, then runs_for desc, then team_id asc). Only regular-season
    entries feed W/L/RS/RA/ERA/AVG — playoff results are shown separately via the
    bracket, not blended into these standings."""
    teams = {t.team_id: t for t in Team.objects.filter(team_id__in=season.team_ids)}
    rows = {tid: {"team": teams[tid], "wins": 0, "losses": 0, "runs_for": 0,
                  "runs_against": 0, "innings": 0} for tid in season.team_ids}

    for entry in season.schedule:
        if entry["phase"] != "regular" or entry["status"] != "final":
            continue
        away, home = entry["away_team_id"], entry["home_team_id"]
        a_score, h_score = entry["away_score"], entry["home_score"]
        innings = entry["innings"]
        rows[away]["runs_for"] += a_score
        rows[away]["runs_against"] += h_score
        rows[away]["innings"] += innings
        rows[home]["runs_for"] += h_score
        rows[home]["runs_against"] += a_score
        rows[home]["innings"] += innings
        if a_score > h_score:
            rows[away]["wins"] += 1
            rows[home]["losses"] += 1
        else:
            rows[home]["wins"] += 1
            rows[away]["losses"] += 1

    finished_game_ids = [e["game_id"] for e in season.schedule
                          if e["phase"] == "regular" and e["status"] == "final"]
    batting = (GameStat.objects.filter(game_id__in=finished_game_ids,
                                        player__team_id__in=season.team_ids)
               .values("player__team_id")
               .annotate(ab=Sum("ab"), s=Sum("singles"), d=Sum("doubles"),
                         t=Sum("triples"), hr=Sum("home_runs")))
    avg_by_team = {}
    for row in batting:
        hits = row["s"] + row["d"] + row["t"] + row["hr"]
        avg_by_team[row["player__team_id"]] = (hits / row["ab"]) if row["ab"] else 0.0

    out = []
    for tid, r in rows.items():
        games = r["wins"] + r["losses"]
        innings = r["innings"] or 0
        # All runs allowed are treated as earned (engine has no unearned-run
        # concept); era and runs_against_per9 are therefore numerically identical
        # here by design, not by coincidence.
        era = (r["runs_against"] / innings * 9) if innings else 0.0
        out.append({
            "team": r["team"],
            "wins": r["wins"],
            "losses": r["losses"],
            "runs_for": r["runs_for"],
            "runs_against": r["runs_against"],
            "runs_for_per9": (r["runs_for"] / innings * 9) if innings else 0.0,
            "runs_against_per9": era,
            "era": era,
            "avg": avg_by_team.get(tid, 0.0),
            "win_pct": (r["wins"] / games) if games else 0.0,
        })

    out.sort(key=lambda r: (-r["win_pct"], -(r["runs_for"] - r["runs_against"]),
                             -r["runs_for"], r["team"].team_id))
    return out
```

### Success Criteria

#### Automated Verification
- [ ] Unit tests pass: `python manage.py test baseball` — cover W/L accounting for a small fabricated schedule with known scores, tiebreak ordering, zero-games-played teams showing 0.000 avg / 0.0 era / 0.0 win_pct (no division by zero)

#### Manual Verification
- [ ] N/A (pure function, fully covered by automated tests)

---

## Phase 4: Season Creation, List, and Delete

### Overview
The season hub page (list/create/delete), reusing the existing roster-picker form shape and view-action conventions.

### Changes Required

#### 1. `SeasonCreateForm`
**File**: `baseball/forms.py`
**Changes**: New form combining a size + team picker with the existing `SideRosterForm` roster/bullpen fields.

```python
class SeasonCreateForm(SideRosterForm):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("team_queryset", Team.objects.exclude(division="All-Star"))
        super().__init__(*args, **kwargs)
        self.fields["size"] = forms.TypedChoiceField(
            choices=Season.SIZE_CHOICES, coerce=int, initial=8,
            widget=forms.RadioSelect,
        )
```
(`Season` imported alongside the existing `from .models import Game, Team, Player, position_pools, is_all_star_team` at the top of `baseball/forms.py`, extended to include `Season`.)

#### 2. Season views
**File**: `baseball/season_views.py` (new)
**Changes**:

```python
import random

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from .forms import SeasonCreateForm
from .models import Season
from .season import build_regular_season_schedule, pick_league
from .views import _saved_rosters_for, _apply_saved_roster, auto_fill_roster, auto_fill_bullpen


class SeasonListView(LoginRequiredMixin, ListView):
    model = Season
    template_name = "baseball/season_list.html"

    def get_queryset(self):
        return Season.objects.filter(owner=self.request.user)


class SeasonCreateView(LoginRequiredMixin, View):
    template_name = "baseball/season_new.html"

    def get(self, request):
        return render(request, self.template_name,
                      {"form": SeasonCreateForm(), "team_chosen": False})

    def post(self, request):
        team_id = request.POST.get("team")
        team = Team.objects.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")
        saved_rosters = _saved_rosters_for(request.user, team)

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = SeasonCreateForm(data, team=team)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        if action == "auto_roster" and team:
            data = request.POST.copy()
            picks = auto_fill_roster(team)
            for code, pid in picks.items():
                data[code] = str(pid)
            bullpen = auto_fill_bullpen(team, exclude_player_id=picks.get("P"))
            data.setlist("bullpen", [str(b["player_id"]) for b in bullpen])
            form = SeasonCreateForm(data, team=team)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True, "saved_rosters": saved_rosters})

        if action == "load_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            saved = (SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).first()
                     if saved_id and saved_id.isdigit() else None)
            data = request.POST.copy()
            if saved:
                _apply_saved_roster(data, saved, team)
            form = SeasonCreateForm(data, team=team)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True,
                           "saved_rosters": saved_rosters, "loaded_roster": saved})

        form = SeasonCreateForm(request.POST, team=team)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        cd = form.cleaned_data
        team_ids = pick_league(cd["team"], cd["size"])
        schedule = build_regular_season_schedule(team_ids, timezone.now().date())
        season = Season.objects.create(
            owner=request.user, size=cd["size"], player_team=cd["team"],
            player_roster=form.roster_for(), player_bullpen=form.bullpen_for(),
            team_ids=team_ids, schedule=schedule,
        )
        return redirect("season-detail", pk=season.pk)


class SeasonDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        season = get_object_or_404(Season, pk=pk, owner=request.user)
        season.delete()
        return redirect("season-list")
```

(`load_roster`/`auto_roster`/`choose_team` branches mirror `Page1View.post`, `baseball/views.py:363-395`, verbatim in shape — same `SavedRoster` import needed at top of `season_views.py`.)

#### 3. URLs
**File**: `baseball/urls.py`
**Changes**: Add season routes.

```python
from . import season_views

urlpatterns = [
    ... existing patterns ...
    path("season/",              season_views.SeasonListView.as_view(),   name="season-list"),
    path("season/new/",          season_views.SeasonCreateView.as_view(), name="season-new"),
    path("season/<int:pk>/",     season_views.SeasonDetailView.as_view(), name="season-detail"),  # Phase 7
    path("season/<int:pk>/advance/", season_views.SeasonAdvanceView.as_view(), name="season-advance"),  # Phase 5
    path("season/<int:pk>/delete/",  season_views.SeasonDeleteView.as_view(), name="season-delete"),
]
```
(`SeasonDetailView`/`SeasonAdvanceView` land in Phases 5/7; routes are added here so URL names exist for templates from this phase onward, views are stubs — `SeasonDetailView` returns a minimal placeholder render — until their phases land.)

#### 4. Templates
**File**: `baseball/templates/baseball/season_list.html` (new)
**Changes**: Same table-list pattern as `game_list.html` — columns for player team, size, stage badge, created date; row actions "Continue"/"Resume" (`season-detail`) and a delete form (`season-cancel`-style POST, matching `game_list.html:45-50`'s cancel-form pattern). "New Season" button matching `game_list.html:5`'s "New Game" button.

**File**: `baseball/templates/baseball/season_new.html` (new)
**Changes**: Structurally identical to `game_setup.html` (`baseball/templates/baseball/game_setup.html`) minus the mode/innings/weather/opponent sections — just the size radio group, team select (`choose_team` triggers a submit exactly like `game_setup.html:143-146`), and the same pitcher/bullpen/batting-order roster UI (`_position_field.html`, `_bullpen_field.html`, `_saved_roster_controls.html` includes reused verbatim) plus the "Auto-Fill Roster" button already added to `game_setup.html`.

#### 5. Nav link
**File**: `templates/base.html`
**Changes**: Add a nav item next to the existing "Baseball" link.

```html
<li class="nav-item">
    <a class="nav-link" href="{% url 'season-list' %}">Season Mode</a>
</li>
```
(inserted after `templates/base.html:25`)

### Success Criteria

#### Automated Verification
- [ ] `python manage.py check` reports no issues
- [ ] `python manage.py test baseball` passes (add a test creating a season via `SeasonCreateView` and asserting `Season.objects.count() == 1`, `len(season.team_ids) == 8`, `len(season.schedule) == 3 * 28`)

#### Manual Verification
- [ ] "Season Mode" nav link appears and goes to an (empty) season list
- [ ] "New Season" flow: pick 8, pick a team, roster auto-fills, submit creates a season and redirects to its (placeholder) detail page
- [ ] Season list shows the new season with correct team/size/stage
- [ ] Delete removes the season from the list

---

## Phase 5: Season Advance Engine

### Overview
The core "play your games, auto-play CPU-vs-CPU games" mechanism: extract `SimulateView`'s loop into a reusable function, add season-result recording, and add the auto-chain that chews through consecutive CPU-vs-CPU entries until it reaches the player's next game.

### Changes Required

#### 1. Extract `simulate_full_game`
**File**: `baseball/views.py`
**Changes**: Pull the body of `SimulateView.post` (`baseball/views.py:940-963`) into a standalone function; `SimulateView.post` becomes a thin wrapper.

```python
def simulate_full_game(game):
    """Run `game` to completion via the same at-bat loop as a single manual roll,
    looped until game-over. Mutates and saves `game`. Returns the list of plays."""
    gs = game.load_state()
    plays, totals = [], {}
    while not gs.game_over:
        roster = game.away_roster if gs.half == "top" else game.home_roster
        play = _advance_game(gs, roster)
        _maybe_auto_swap_pitcher(game, gs, play)
        pid = _pid_for_name(roster, play["batter"])
        if pid:
            acc = totals.setdefault(pid, {})
            for col, n in _stat_delta(play["outcome"]).items():
                acc[col] = acc.get(col, 0) + n
            h = (acc.get("singles", 0) + acc.get("doubles", 0)
                 + acc.get("triples", 0) + acc.get("home_runs", 0))
            play["stat_update"] = {"player_id": pid, "line": f"{h}-{acc.get('ab', 0)}"}
            play["state"]["batter_line"] = play["stat_update"]["line"]
        plays.append(play)
        if play["game_over"]:
            break
    for pid, cols in totals.items():
        _apply_delta(game, pid, cols)
    game.save_state(gs)
    game.play_log = plays
    game.status = Game.FINISHED
    game.save()
    return plays


class SimulateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        plays = simulate_full_game(game)
        if game.season_id:
            from .season import record_season_game_result, advance_season
            record_season_game_result(game)
            advance_season(game.season)
        return JsonResponse({"plays": plays})
```

#### 2. `record_season_game_result` and `advance_season` in `baseball/season.py`
**File**: `baseball/season.py`
**Changes**: Append.

```python
from .models import Game, Team
from .views import (auto_fill_bullpen, cpu_roster_for, lineup_from_roster,
                     pitcher_from_roster, simulate_full_game)
from baseball.engine import GameState


def record_season_game_result(game):
    """Write a finished season game's result back into its Season's schedule."""
    season = game.season
    entry = next(e for e in season.schedule if e["id"] == game.season_entry_id)
    gs = game.load_state()
    entry["status"] = "final"
    entry["game_id"] = game.pk
    entry["away_score"] = gs.away_score
    entry["home_score"] = gs.home_score
    entry["innings"] = max(len(gs.away_line), len(gs.home_line))
    _close_series_if_clinched(season, entry)
    season.save(update_fields=["schedule"])


def _series_entries(season, series_id):
    return [e for e in season.schedule if e["series_id"] == series_id]


def _close_series_if_clinched(season, entry):
    """For playoff series only: once one team has clinched a series majority,
    mark any remaining scheduled games in that series 'skipped'."""
    if entry["phase"] != "playoffs":
        return
    games = _series_entries(season, entry["series_id"])
    best_of = len(games)
    need = best_of // 2 + 1
    wins = {}
    for g in games:
        if g["status"] != "final":
            continue
        winner = g["away_team_id"] if g["away_score"] > g["home_score"] else g["home_team_id"]
        wins[winner] = wins.get(winner, 0) + 1
    if max(wins.values(), default=0) >= need:
        for g in games:
            if g["status"] == "scheduled":
                g["status"] = "skipped"


def _create_season_game(season, entry):
    away_team = Team.objects.get(pk=entry["away_team_id"])
    home_team = Team.objects.get(pk=entry["home_team_id"])
    is_away, is_home = (entry["away_team_id"] == season.player_team_id,
                         entry["home_team_id"] == season.player_team_id)

    away_roster = season.player_roster if is_away else cpu_roster_for(away_team)
    home_roster = season.player_roster if is_home else cpu_roster_for(home_team)
    away_starter = next((r["player_id"] for r in away_roster if r["position"] == "P"), None)
    home_starter = next((r["player_id"] for r in home_roster if r["position"] == "P"), None)
    away_bullpen = season.player_bullpen if is_away else auto_fill_bullpen(away_team, away_starter)
    home_bullpen = season.player_bullpen if is_home else auto_fill_bullpen(home_team, home_starter)

    if is_away or is_home:
        mode, cpu_side = Game.CPU_AUTO, ("home" if is_away else "away")
    else:
        mode, cpu_side = Game.AUTO_PLAY, None

    gs = GameState(
        away_name=str(away_team), home_name=str(home_team), total_innings=9,
        away_lineup=lineup_from_roster(away_roster), home_lineup=lineup_from_roster(home_roster),
        away_starting_pitcher=pitcher_from_roster(away_roster),
        home_starting_pitcher=pitcher_from_roster(home_roster),
        away_bullpen=away_bullpen, home_bullpen=home_bullpen,
    )
    game = Game.objects.create(
        owner=season.owner, away_name=str(away_team), home_name=str(home_team),
        away_team=away_team, home_team=home_team,
        away_roster=away_roster, home_roster=home_roster,
        away_bullpen=away_bullpen, home_bullpen=home_bullpen,
        total_innings=9, mode=mode, cpu_side=cpu_side,
        state=Game.state_to_dict(gs), status=Game.ACTIVE,
        season=season, season_entry_id=entry["id"],
    )
    entry["game_id"] = game.pk
    entry["status"] = "in_progress"
    return game


def advance_season(season):
    """Auto-simulate consecutive CPU-vs-CPU entries from season.current_index.
    Stops when the next entry involves the player's team (leaving it in_progress
    for interactive play), when a stage transition needs to happen, or when the
    schedule is exhausted."""
    while season.current_index < len(season.schedule):
        entry = season.schedule[season.current_index]
        if entry["status"] in ("final", "skipped"):
            season.current_index += 1
            continue
        involves_player = season.player_team_id in (entry["away_team_id"], entry["home_team_id"])
        if entry["status"] == "scheduled" and not involves_player:
            game = _create_season_game(season, entry)
            simulate_full_game(game)
            record_season_game_result(game)
            season.current_index += 1
            continue
        if entry["status"] == "scheduled" and involves_player:
            _create_season_game(season, entry)
            break
        if entry["status"] == "in_progress":
            break
    _maybe_advance_stage(season)
    season.save()
```
(`_maybe_advance_stage` lands in Phase 6.)

#### 3. Hook `RollView` and `PitcherChangeView`-adjacent completion path
**File**: `baseball/views.py`
**Changes**: In `RollView.post` (`baseball/views.py:904-932`), after `game.save()` when `play["game_over"]` is true, add the same season hook:

```python
        game.save()
        if game.season_id and play["game_over"]:
            from .season import record_season_game_result, advance_season
            record_season_game_result(game)
            advance_season(game.season)
```

#### 4. `SeasonAdvanceView`
**File**: `baseball/season_views.py`
**Changes**: Add.

```python
from django.http import JsonResponse
from django.urls import reverse

from .season import advance_season


class SeasonAdvanceView(LoginRequiredMixin, View):
    def post(self, request, pk):
        season = get_object_or_404(Season, pk=pk, owner=request.user)
        if season.stage == Season.FINISHED:
            return JsonResponse({"error": "season finished"}, status=400)
        advance_season(season)
        if season.current_index < len(season.schedule):
            entry = season.schedule[season.current_index]
            if entry["status"] == "in_progress":
                return JsonResponse({"redirect_url": reverse("baseball-detail", args=[entry["game_id"]])})
        return JsonResponse({"stage": season.stage, "current_index": season.current_index})
```

#### 5. `ReplayView` rejects season games
**File**: `baseball/views.py`
**Changes**: `ReplayView.post` (`baseball/views.py:967-1005`) already 400s for multiplayer games (`970-971`); add the same guard for season games immediately after:

```python
        if game.season_id:
            return JsonResponse({"error": "replay not supported for season games"}, status=400)
```

### Success Criteria

#### Automated Verification
- [ ] `python manage.py test baseball` passes, including new tests: `simulate_full_game` finishes a game and sets `status=FINISHED`; `advance_season` on a season whose next entries are all CPU-vs-CPU simulates through them and stops with an `in_progress` `Game` at the player's next entry; `record_season_game_result` correctly writes scores/innings into the matching schedule entry
- [ ] `python manage.py check` reports no issues

#### Manual Verification
- [ ] From a season's detail page (placeholder is fine at this phase), POSTing to `season-advance` when the next matchup is CPU-vs-CPU silently fast-forwards the schedule (verify via shell/admin that `current_index` moved and schedule entries show `status="final"` with scores)
- [ ] POSTing to `season-advance` when the next matchup involves the player's team creates a `Game` row and returns a `redirect_url` to its detail page
- [ ] Playing that game to completion (via normal roll/simulate) automatically records the result back into the season and immediately continues auto-simulating the following CPU-vs-CPU entries without a second manual "advance" click

---

## Phase 6: Playoff Bracket Generation & Advancement

### Overview
Once every regular-season entry is `final`/`skipped`, compute standings, seed the bracket (top 4 of 8, or top 8 of 16), and generate each round's entries as prior rounds complete, until a champion is decided.

### Changes Required

#### 1. `_maybe_advance_stage` in `baseball/season.py`
**File**: `baseball/season.py`
**Changes**: Append.

```python
from datetime import date, timedelta

from .season import compute_standings  # (same module; illustrative — defined above in Phase 3)


ROUND_BEST_OF = {
    "semifinal_first":    3,   # 8-team bracket's only pre-final round
    "quarterfinal":       3,   # 16-team bracket's first round
    "semifinal":          5,   # 16-team bracket's second round
    "final":               5,
}


def _rounds_for(size):
    return ["semifinal_first", "final"] if size == 8 else \
           ["quarterfinal", "semifinal", "final"]


def _last_schedule_date(schedule):
    return max(date.fromisoformat(e["date"]) for e in schedule)


def _round_entries(schedule, round_name):
    return [e for e in schedule if e.get("round") == round_name]


def _series_winner(season, series_id):
    games = _series_entries(season, series_id)
    wins = {}
    for g in games:
        if g["status"] != "final":
            continue
        w = g["away_team_id"] if g["away_score"] > g["home_score"] else g["home_team_id"]
        wins[w] = wins.get(w, 0) + 1
    return max(wins, key=wins.get)


def _maybe_advance_stage(season):
    if season.stage == Season.REGULAR:
        regular = [e for e in season.schedule if e["phase"] == "regular"]
        if not all(e["status"] in ("final", "skipped") for e in regular):
            return
        standings = compute_standings(season)
        n = 4 if season.size == 8 else 8
        seeds = [row["team"].team_id for row in standings[:n]]
        round_name = _rounds_for(season.size)[0]
        matchups = [(seeds[-(i + 1)], seeds[i]) for i in range(len(seeds) // 2)]
        # e.g. n=4: (seeds[3], seeds[0]) i.e. #1 hosts vs #4, (seeds[2], seeds[1]) #2 hosts vs #3
        start = _last_schedule_date(season.schedule) + timedelta(days=3)
        build_round_entries(season.schedule, matchups, round_name,
                             ROUND_BEST_OF[round_name], start)
        season.bracket = [{"round": round_name, "seeds": seeds}]
        season.stage = Season.PLAYOFFS
        return

    if season.stage == Season.PLAYOFFS:
        rounds = _rounds_for(season.size)
        current_round = season.bracket[-1]["round"]
        current_entries = _round_entries(season.schedule, current_round)
        if not all(e["status"] in ("final", "skipped") for e in current_entries):
            return
        series_ids = sorted({e["series_id"] for e in current_entries})
        winners = [_series_winner(season, sid) for sid in series_ids]
        if current_round == rounds[-1]:
            season.stage = Season.FINISHED
            season.bracket.append({"round": "champion", "team_id": winners[0]})
            return
        next_round = rounds[rounds.index(current_round) + 1]
        matchups = [(winners[-(i + 1)], winners[i]) for i in range(len(winners) // 2)]
        start = _last_schedule_date(season.schedule) + timedelta(days=3)
        build_round_entries(season.schedule, matchups, next_round,
                             ROUND_BEST_OF[next_round], start)
        season.bracket.append({"round": next_round, "seeds": winners})
```

(`ROUND_BEST_OF["semifinal_first"] = 3` names the 8-team bracket's only pre-final round distinctly from the 16-team bracket's `"semifinal"` — which is best-of-5 — so the same round-name string never means two different series lengths.)

### Success Criteria

#### Automated Verification
- [ ] `python manage.py test baseball` passes, including: an 8-team season with a fabricated finished regular-season schedule transitions to `PLAYOFFS` with a `semifinal_first` round seeded #1v#4/#2v#3 (best-of-3, 6 entries); a 16-team season transitions with a `quarterfinal` round seeded #1v#8...#4v#5 (best-of-3, 4 series); simulating a full bracket for each size ends with `stage == "finished"` and exactly one `bracket[-1]["team_id"]`
- [ ] `python manage.py check` reports no issues

#### Manual Verification
- [ ] Play/advance an 8-team season through its full regular season and playoffs end-to-end via the UI (Phase 7 UI required to do this manually — verify via shell/admin inspection of `Season.stage`/`Season.bracket`/`Season.schedule` if Phase 7 isn't ready yet)
- [ ] Confirm a clinched playoff series correctly marks its remaining scheduled game(s) `"skipped"` (e.g. a 2-0 sweep in a best-of-3 leaves game 3 `skipped`)

---

## Phase 7: Season Detail UI

### Overview
The season detail page: standings table, schedule/calendar (grouped by series), bracket display once in playoffs, and the "Play Next Game" button that drives `advance_season` from the browser.

### Changes Required

#### 1. `SeasonDetailView`
**File**: `baseball/season_views.py`
**Changes**: Replace the Phase-4 placeholder view entirely (not extend it).

```python
from .season import compute_standings


class SeasonDetailView(LoginRequiredMixin, View):
    template_name = "baseball/season_detail.html"

    def get(self, request, pk):
        season = get_object_or_404(Season, pk=pk, owner=request.user)
        standings = compute_standings(season)
        next_entry = (season.schedule[season.current_index]
                      if season.current_index < len(season.schedule) else None)
        series = {}
        for e in season.schedule:
            series.setdefault(e["series_id"], []).append(e)
        return render(request, self.template_name, {
            "season": season, "standings": standings, "next_entry": next_entry,
            "series_list": list(series.values()),
        })
```
(Remove the accidental duplicate class stub above when implementing — shown only to flag that Phase 4's placeholder view is fully replaced here, not extended.)

#### 2. Template
**File**: `baseball/templates/baseball/season_detail.html` (new)
**Changes**: Standings table (columns: Team, W, L, Win%, RS/9, RA/9, ERA, AVG — matching `compute_standings`'s returned dict keys), a schedule section listing each series (teams, per-game date/time/status/score), a bracket section shown only when `season.stage != "regular"` (round names, matchups, series scores), and a "Play Next Game" button wired via `fetch` to `season-advance` in the same style as `doReplay`/`doSimulate` in `baseball/static/baseball/js/game.js:321-331,350-354` (POST with `X-CSRFToken`, follow `redirect_url` if present, otherwise re-render the page to show the updated standings/schedule).

```html
{% extends "base.html" %}
{% block content %}
<h2>{{ season.player_team.name }} — {{ season.get_size_display }} Season</h2>
<p class="text-muted">{{ season.get_stage_display }}</p>

<h4>Standings</h4>
<table class="table table-sm">
  <thead><tr><th>Team</th><th>W</th><th>L</th><th>Win%</th><th>RS/9</th><th>RA/9</th><th>ERA</th><th>AVG</th></tr></thead>
  <tbody>
  {% for row in standings %}
    <tr{% if row.team.team_id == season.player_team_id %} class="table-primary"{% endif %}>
      <td>{{ row.team.name }}</td><td>{{ row.wins }}</td><td>{{ row.losses }}</td>
      <td>{{ row.win_pct|floatformat:3 }}</td><td>{{ row.runs_for_per9|floatformat:2 }}</td>
      <td>{{ row.runs_against_per9|floatformat:2 }}</td><td>{{ row.era|floatformat:2 }}</td>
      <td>{{ row.avg|floatformat:3 }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

{% if next_entry %}
<button id="btn-advance" class="btn btn-success" data-url="{% url 'season-advance' season.pk %}">
  Play Next Game
</button>
{% else %}
<p>Season finished. Champion: {{ season.bracket.last.team_id }}</p>
{% endif %}

<h4 class="mt-4">Schedule</h4>
{% for games in series_list %}
  <div class="mb-2">
    <strong>{{ games.0.away_team_id }} @ {{ games.0.home_team_id }} — {{ games.0.round }}</strong>
    <ul class="list-unstyled small">
    {% for g in games %}
      <li>{{ g.date }} {{ g.time }} — Game {{ g.game_number }}:
        {% if g.status == "final" %}{{ g.away_score }}-{{ g.home_score }} Final
        {% elif g.status == "skipped" %}—
        {% else %}Scheduled{% endif %}</li>
    {% endfor %}
    </ul>
  </div>
{% endfor %}

<script>
document.getElementById('btn-advance')?.addEventListener('click', async (e) => {
    const btn = e.target;
    btn.disabled = true;
    const resp = await fetch(btn.dataset.url, {
        method: 'POST',
        headers: { 'X-CSRFToken': document.cookie.match(/csrftoken=([^;]+)/)[1] },
    });
    const data = await resp.json();
    if (data.redirect_url) location.href = data.redirect_url;
    else location.reload();
});
</script>
{% endblock %}
```
(Team names in the schedule loop resolved via a template filter/context dict mapping `team_id -> Team` in the real implementation — `season_id`-scoped teams are few enough to pass as a `{{ team_id: team }}` context dict alongside `series_list`, avoiding an extra query per row.)

#### 3. `game_detail.html` / `game.js`: "Continue Season" affordance
**File**: `baseball/templates/baseball/game_detail.html`, `baseball/static/baseball/js/game.js`
**Changes**: When `game.season_id` is set and the game just finished, show a "Continue Season" link to `season-detail` (using `game.season_id`) instead of the normal Replay/Autoplay controls (which `ReplayView` now rejects for season games per Phase 5) — mirrors the existing `GAME_MODE !== 'multiplayer'` conditional at `baseball/static/baseball/js/game.js:286` with an equivalent `!SEASON_ID` check gating the replay-button block, and an added season-only block rendering the continue link when `SEASON_ID` is set.

### Success Criteria

#### Automated Verification
- [ ] `python manage.py check` reports no issues
- [ ] `python manage.py test baseball` passes

#### Manual Verification
- [ ] Season detail page shows correct standings that update after each game
- [ ] "Play Next Game" auto-fast-forwards through CPU-vs-CPU games and lands the player on their own game when reached
- [ ] Finishing a player game shows a "Continue Season" link (not Replay/Autoplay) and returns to the season detail page with updated standings/schedule
- [ ] Full regular season + playoff run-through for an 8-team season ends with a visible champion and `stage = finished`
- [ ] Full regular season + playoff run-through for a 16-team season ends with a visible champion and `stage = finished`
- [ ] Reloading/revisiting a season mid-way through resumes exactly at `current_index` with no lost progress

---

## Testing Strategy

### Unit Tests
- `baseball/season.py` functions are pure and fully unit-testable without a running server: `pick_league`, `build_regular_season_schedule`, `build_round_entries`, `compute_standings`, `record_season_game_result`, `advance_season`, `_maybe_advance_stage`, `_close_series_if_clinched`.
- Use small fabricated `Season`/`Team`/`Game` fixtures (4-team mini-league) to keep playoff-bracket and full-season-advance tests fast, in addition to at least one full-size (8-team and 16-team) schedule-shape assertion.

### Integration Tests
- End-to-end: `SeasonCreateView` → `SeasonAdvanceView` (loop until stage is `finished`, playing the player's own games via `simulate_full_game` directly in the test rather than through `RollView`) → assert final `Season.stage == "finished"` and a valid champion.
- Assert an entry's `game_id` always resolves to a `Game` whose `state["away_score"]`/`state["home_score"]` match the schedule entry's cached `away_score`/`home_score` after `record_season_game_result`.

### Manual Testing Steps
1. Create an 8-team season, verify the standings/schedule pages render before any games are played.
2. Click "Play Next Game" repeatedly (or once, if it lands on an interactive game) until reaching a game involving the player's team; play it out normally.
3. Verify CPU-vs-CPU games between clicks appear in the schedule as `final` with plausible scores.
4. Close the browser mid-season, reopen, confirm the season resumes exactly where left off.
5. Play through to the end of the regular season, verify playoff bracket seeds match the standings (#1 vs #4/#8, etc.).
6. Play through the playoffs to a champion; verify best-of-3 first round, best-of-5 thereafter, and that clinched series skip their unneeded games.
7. Delete a season, verify it and its `Game` rows are gone.

## Performance Considerations

- `advance_season`'s CPU-vs-CPU auto-chain can simulate many games in one request for a freshly created season (up to `3 * C(size,2)` regular-season games back to back if the player's own first game is scheduled late) — each `simulate_full_game` call is already the same per-game cost as today's single-game `SimulateView`, just looped. For a 16-team season (up to 360 total games across the full season+playoffs), this is bounded and acceptable for a single Django request in this app's existing usage pattern (no async/background job infrastructure exists or is introduced here).
- `compute_standings` iterates the full `schedule` list (≤360 entries) and issues one aggregate `GameStat` query per call — cheap at this scale, computed on demand rather than cached to avoid staleness bugs.

## Migration Notes

New feature, no existing data to migrate. The `Season` model and `Game.season`/`Game.season_entry_id` fields are purely additive; no existing `Game` rows are affected (`season` defaults to `NULL`).

## References

- Research: `thoughts/shared/research/2026-08-18-season-mode.md`
- `Game` model and JSON state round-trip: `baseball/models.py:246-375`
- `SimulateView` (basis for `simulate_full_game`): `baseball/views.py:935-964`
- `auto_fill_roster`/`cpu_roster_for`/`auto_fill_bullpen`: `baseball/views.py:115-165`
- `is_all_star_team`: `baseball/models.py:114-115`
- `SideRosterForm`: `baseball/forms.py:37-115`
- `GameListView`/`Page1View`/`CancelWaitingView` (list/create/delete conventions): `baseball/views.py:323-347,350-533,798-805`
- Existing replay/simulate fetch pattern: `baseball/static/baseball/js/game.js:321-354`
