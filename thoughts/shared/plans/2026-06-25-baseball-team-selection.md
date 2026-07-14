# Baseball Team Selection — Implementation Plan

## Overview

Add unmanaged Django models for all 8 raw SQL tables the user created in Postgres
(stadium, team, player, schedule, game, stats, game_participant, lineup). Then wire
the `team` table into the baseball game setup: replace the free-text away/home name
inputs with dropdowns populated from the DB, enforce that the same team can't play
itself, and show real team names in the scoreboard and game list.

## Current State Analysis

- `baseball/models.py` has one model: `Game` (managed, table `baseball_game`).
  `away_name`/`home_name` are plain `CharField(50)`, set by the user via free-text.
- 8 raw SQL tables created directly in Postgres (not via Django migrations).
  30 MLB teams + stadiums seeded; player/stats/schedule/lineup tables exist but empty.
- `GameSetupForm` exposes `away_name`/`home_name` as TextInput fields.
- `GameCreateView.form_valid` passes `game.away_name`/`game.home_name` to `GameState()`.
- `game_list.html` renders `g.away_name`/`g.home_name` from the CharField.
- `game_detail.html` scoreboard uses `game.state.away_name`/`game.state.home_name`
  (from the JSONField snapshot), so it already works correctly after creation.

## Desired End State

- All 8 raw tables accessible as Django ORM models (`managed = False`).
- New game setup: two dropdowns ("Away Team", "Home Team") populated from the
  `team` table. Submitting the same team for both sides is rejected at form validation.
- Game list shows team name (e.g., "Yankees") for away/home columns.
- Game detail scoreboard continues to show team names (already works via state JSON).
- Existing games (which have no team FK) continue to display correctly via the
  `away_name`/`home_name` CharFields which are kept on the model.

### Verify by:
- `Team.objects.count()` returns 30.
- New game setup form shows two dropdowns; picking the same team both sides shows
  an error.
- Created game: list shows "Yankees" not blank; detail scoreboard shows "Yankees".
- Old games (null team FK) still render correctly in the list.

## What We're NOT Doing

- CRUD views for teams, players, stadiums — admin only / future.
- Using `player` table rows as lineup names in the engine (engine still uses
  `params.LINEUP` fixed names).
- Exposing `schedule`, `stats`, `game_participant`, or `lineup` in any views.
- Removing `away_name`/`home_name` CharFields from `Game` (kept for backward compat).
- Filtering teams by conference/division/active status in the dropdown.

## Implementation Approach

Two independent concerns, done in order:

1. **Unmanaged models** — pure Python, one migration (state-only, no DDL). All 8 tables.
2. **Team selection** — FK columns on `Game`, form change, view tweak, template tweak.

Each phase leaves the app fully runnable.

---

## Phase 1: Unmanaged Models for All 8 Raw Tables

### Overview
Add Django model classes for all 8 Postgres tables with `managed = False`. Django
tracks their schema in migrations but never creates/drops/alters the tables.
This makes the ORM available for future features without touching the existing data.

### Changes Required

#### 1. `baseball/models.py` — add all 8 unmanaged models

Add **before** the existing `Game` class:

```python
# ---------------------------------------------------------------------------
# Unmanaged models — raw Postgres tables; Django does not manage DDL.
# ---------------------------------------------------------------------------

class Stadium(models.Model):
    stadium_id = models.AutoField(primary_key=True)
    name       = models.CharField(max_length=100)
    city       = models.CharField(max_length=50)
    state      = models.CharField(max_length=50, blank=True, null=True)
    country    = models.CharField(max_length=50, default='USA')
    capacity   = models.IntegerField(null=True, blank=True)

    class Meta:
        managed  = False
        db_table = 'stadium'
        ordering = ['name']

    def __str__(self):
        return self.name


class Team(models.Model):
    team_id      = models.AutoField(primary_key=True)
    name         = models.CharField(max_length=100)
    city         = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=5, blank=True, null=True)
    conference   = models.CharField(max_length=50, blank=True, null=True)
    division     = models.CharField(max_length=50, blank=True, null=True)
    head_coach   = models.CharField(max_length=50, blank=True, null=True)
    stadium      = models.ForeignKey(
        Stadium, db_column='stadium_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )
    founded_year = models.IntegerField(null=True, blank=True)

    class Meta:
        managed  = False
        db_table = 'team'
        ordering = ['name']

    def __str__(self):
        return f"{self.city} {self.name}"


class Player(models.Model):
    player_id     = models.AutoField(primary_key=True)
    first_name    = models.CharField(max_length=50)
    last_name     = models.CharField(max_length=50)
    team          = models.ForeignKey(
        Team, db_column='team_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )
    position      = models.CharField(max_length=30, blank=True, null=True)
    jersey_number = models.IntegerField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    height_inches = models.IntegerField(null=True, blank=True)
    weight_lbs    = models.IntegerField(null=True, blank=True)
    nationality   = models.CharField(max_length=50, blank=True, null=True)
    bats          = models.CharField(max_length=1, blank=True, null=True)
    throws        = models.CharField(max_length=1, blank=True, null=True)
    team_abbrev   = models.CharField(max_length=10, blank=True, null=True)
    season        = models.IntegerField(null=True, blank=True)
    g    = models.IntegerField(null=True, blank=True)
    g_p  = models.IntegerField(null=True, blank=True)
    g_sp = models.IntegerField(null=True, blank=True)
    g_rp = models.IntegerField(null=True, blank=True)
    g_c  = models.IntegerField(null=True, blank=True)
    g_1b = models.IntegerField(null=True, blank=True)
    g_2b = models.IntegerField(null=True, blank=True)
    g_3b = models.IntegerField(null=True, blank=True)
    g_ss = models.IntegerField(null=True, blank=True)
    g_lf = models.IntegerField(null=True, blank=True)
    g_cf = models.IntegerField(null=True, blank=True)
    g_rf = models.IntegerField(null=True, blank=True)
    g_of = models.IntegerField(null=True, blank=True)
    g_dh = models.IntegerField(null=True, blank=True)
    g_ph = models.IntegerField(null=True, blank=True)
    g_pr = models.IntegerField(null=True, blank=True)
    first_game  = models.IntegerField(null=True, blank=True)
    last_game   = models.IntegerField(null=True, blank=True)
    dataid      = models.CharField(max_length=255, blank=True, null=True)
    status      = models.CharField(max_length=50, default='available')
    active      = models.BooleanField(default=True)

    class Meta:
        managed  = False
        db_table = 'player'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class MLBSchedule(models.Model):
    """Maps to the raw `schedule` table (distinct from baseball.Game)."""
    game_id    = models.AutoField(primary_key=True)
    home_team  = models.ForeignKey(
        Team, db_column='home_team_id',
        on_delete=models.DO_NOTHING, related_name='schedule_home',
    )
    away_team  = models.ForeignKey(
        Team, db_column='away_team_id',
        on_delete=models.DO_NOTHING, related_name='schedule_away',
    )
    stadium    = models.ForeignKey(
        Stadium, db_column='stadium_id', on_delete=models.DO_NOTHING,
    )
    game_date  = models.DateField()
    game_time  = models.TimeField(null=True, blank=True)
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    status     = models.CharField(max_length=20, default='Scheduled')

    class Meta:
        managed  = False
        db_table = 'schedule'


class MLBGame(models.Model):
    """Maps to the raw `game` table (distinct from baseball.Game web-app model)."""
    game_id    = models.AutoField(primary_key=True)
    status     = models.CharField(max_length=20, default='Pending')
    start_time = models.DateTimeField()
    end_time   = models.DateTimeField()
    home_score = models.IntegerField(default=0)
    away_score = models.IntegerField(default=0)
    stadium    = models.ForeignKey(
        Stadium, db_column='stadium_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )

    class Meta:
        managed  = False
        db_table = 'game'


class Stats(models.Model):
    stat_id           = models.AutoField(primary_key=True)
    player            = models.ForeignKey(
        Player, db_column='player_id', on_delete=models.DO_NOTHING,
    )
    game              = models.ForeignKey(
        MLBSchedule, db_column='game_id', on_delete=models.DO_NOTHING,
    )
    at_bats           = models.IntegerField(default=0)
    hits              = models.IntegerField(default=0)
    runs              = models.IntegerField(default=0)
    rbis              = models.IntegerField(default=0)
    doubles           = models.IntegerField(default=0)
    triples           = models.IntegerField(default=0)
    home_runs         = models.IntegerField(default=0)
    walks             = models.IntegerField(default=0)
    strikeouts        = models.IntegerField(default=0)
    stolen_bases      = models.IntegerField(default=0)
    innings_pitched   = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pitches_thrown    = models.IntegerField(null=True, blank=True)
    hits_allowed      = models.IntegerField(default=0)
    runs_allowed      = models.IntegerField(default=0)
    earned_runs       = models.IntegerField(default=0)
    walks_allowed     = models.IntegerField(default=0)
    ks_pitched        = models.IntegerField(default=0)
    home_runs_allowed = models.IntegerField(default=0)

    class Meta:
        managed  = False
        db_table = 'stats'


class GameParticipant(models.Model):
    participant_id  = models.AutoField(primary_key=True)
    game            = models.ForeignKey(
        MLBGame, db_column='game_id', on_delete=models.DO_NOTHING,
    )
    player_sequence = models.IntegerField(default=1)
    user_id         = models.IntegerField()
    team            = models.ForeignKey(
        Team, db_column='team_id', on_delete=models.DO_NOTHING,
    )

    class Meta:
        managed  = False
        db_table = 'game_participant'


class Lineup(models.Model):
    lineup_id     = models.AutoField(primary_key=True)
    participant   = models.ForeignKey(
        GameParticipant, db_column='participant_id', on_delete=models.DO_NOTHING,
    )
    player        = models.ForeignKey(
        Player, db_column='player_id', on_delete=models.DO_NOTHING,
    )
    batting_order = models.IntegerField()

    class Meta:
        managed  = False
        db_table = 'lineup'
```

#### 2. Run migration (state-only — no DDL executed)

```
python manage.py makemigrations baseball
python manage.py migrate
```

### Success Criteria

#### Automated:
- [x] `python manage.py check` exits 0.
- [x] `python manage.py makemigrations baseball --check` exits 0 after running.
- [x] `python manage.py shell -c "from baseball.models import Team; print(Team.objects.count())"` prints `30`.
- [x] `python manage.py shell -c "from baseball.models import Stadium, Player, MLBSchedule, MLBGame, Stats, GameParticipant, Lineup; print('ok')"` exits 0.

---

## Phase 2: Add Team FKs to `Game` + Migration

### Overview
Add `away_team` and `home_team` ForeignKey fields (nullable) to `Game`. Keep the
existing `away_name`/`home_name` CharFields — they serve as a snapshot for
existing games and for the engine's `GameState` constructor.

### Changes Required

#### 1. `baseball/models.py` — add FK fields to `Game`

Inside `class Game(models.Model)`, add after `home_name`:

```python
away_team = models.ForeignKey(
    'Team', null=True, blank=True,
    on_delete=models.SET_NULL, related_name='away_games',
)
home_team = models.ForeignKey(
    'Team', null=True, blank=True,
    on_delete=models.SET_NULL, related_name='home_games',
)
```

#### 2. Run migration

```
python manage.py makemigrations baseball
python manage.py migrate
```

### Success Criteria

#### Automated:
- [x] `python manage.py check` exits 0.
- [x] `python manage.py makemigrations baseball --check` exits 0 after running.
- [x] `python manage.py shell -c "from baseball.models import Game; print(Game._meta.get_field('away_team'))"` exits 0.

---

## Phase 3: Form + View Updates

### Overview
Replace the `away_name`/`home_name` TextInput fields with `ModelChoiceField`
team dropdowns. Add `clean()` validation. Update `GameCreateView.form_valid` to
populate `away_name`/`home_name` from the selected teams.

### Changes Required

#### 1. `baseball/forms.py` — full replacement

```python
from django import forms
from .models import Game, Team


class GameSetupForm(forms.ModelForm):
    away_team = forms.ModelChoiceField(
        queryset=Team.objects.all(),
        label="Away Team",
        empty_label="— select away team —",
    )
    home_team = forms.ModelChoiceField(
        queryset=Team.objects.all(),
        label="Home Team",
        empty_label="— select home team —",
    )

    class Meta:
        model  = Game
        fields = ["away_team", "home_team", "total_innings", "mode"]
        widgets = {
            "total_innings": forms.NumberInput(attrs={"min": 1, "max": 9, "class": "form-control"}),
            "mode":          forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["total_innings"].initial = 3

    def clean(self):
        cleaned = super().clean()
        away = cleaned.get("away_team")
        home = cleaned.get("home_team")
        if away and home and away == home:
            raise forms.ValidationError("Away and home teams must be different.")
        return cleaned
```

#### 2. `baseball/views.py` — update `GameCreateView.form_valid`

Replace:
```python
def form_valid(self, form):
    game = form.save(commit=False)
    game.owner = self.request.user
    gs = GameState(game.away_name, game.home_name, game.total_innings)
    game.state = Game.state_to_dict(gs)
    game.save()
    return redirect("baseball-detail", pk=game.pk)
```

With:
```python
def form_valid(self, form):
    game = form.save(commit=False)
    game.owner = self.request.user
    away_team = form.cleaned_data["away_team"]
    home_team = form.cleaned_data["home_team"]
    game.away_name = away_team.name
    game.home_name = home_team.name
    gs = GameState(game.away_name, game.home_name, game.total_innings)
    game.state = Game.state_to_dict(gs)
    game.save()
    return redirect("baseball-detail", pk=game.pk)
```

### Success Criteria

#### Automated:
- [ ] `python manage.py check` exits 0.

#### Manual:
- [ ] `/baseball/new/` shows two dropdowns (not text inputs), both listing all 30 teams.
- [ ] Submitting same team for both sides shows a validation error, does not create game.
- [ ] Submitting two different teams creates the game and redirects to game detail.

---

## Phase 4: Template Updates

### Overview
Update `game_setup.html` to render team dropdowns correctly (Bootstrap `form-select`
class) and `game_list.html` to show team name for games that have a team FK.
`game_detail.html` needs no change — scoreboard reads from `game.state` which is
set at creation from team names.

### Changes Required

#### 1. `baseball/templates/baseball/game_setup.html` — replace name fields with team selects

Replace the Away Team and Home Team blocks:

```html
<div class="mb-3">
    <label class="form-label fw-semibold">Away Team (CPU)</label>
    {{ form.away_team }}
    {% if form.away_team.errors %}
    <div class="text-danger small">{{ form.away_team.errors }}</div>
    {% endif %}
</div>

<div class="mb-3">
    <label class="form-label fw-semibold">Home Team (You)</label>
    {{ form.home_team }}
    {% if form.home_team.errors %}
    <div class="text-danger small">{{ form.home_team.errors }}</div>
    {% endif %}
</div>
```

Add Bootstrap `form-select` class via `forms.py` widget attrs on the two `ModelChoiceField`s:

Back in `forms.py`, add `widget` to each field:
```python
away_team = forms.ModelChoiceField(
    queryset=Team.objects.all(),
    label="Away Team",
    empty_label="— select away team —",
    widget=forms.Select(attrs={"class": "form-select"}),
)
home_team = forms.ModelChoiceField(
    queryset=Team.objects.all(),
    label="Home Team",
    empty_label="— select home team —",
    widget=forms.Select(attrs={"class": "form-select"}),
)
```

#### 2. `baseball/templates/baseball/game_list.html` — show team or fallback name

The `g.away_name`/`g.home_name` CharFields are still populated for all games
(old ones set by the old form, new ones set by `form_valid`), so the list template
**requires no change**. It already reads `g.away_name` / `g.home_name` which
contain the team name string set at creation.

> If you want to show `g.away_team.abbreviation` (e.g., "NYY") in a future column,
> add it in a later pass.

### Success Criteria

#### Manual:
- [ ] `/baseball/new/` — dropdowns render with Bootstrap styling; all 30 MLB teams appear as "City Name" (e.g., "New York Yankees").
- [ ] Submitting same team both sides: form stays, shows error.
- [ ] After creating game: list shows team name (e.g., "Yankees") in Away/Home columns.
- [ ] Game detail scoreboard shows team name in the inning header and batting indicators.
- [ ] Existing games (created before this change) still display correctly in the list.

---

## Testing Strategy

### Manual Testing Steps:
1. Go to `/baseball/new/`; confirm dropdowns, not text boxes.
2. Pick "New York Yankees" for both — confirm error message.
3. Pick "New York Yankees" away, "Boston Red Sox" home, 3 innings, click_all mode → submit.
4. Game list: confirm "Yankees" / "Red Sox" columns.
5. Game detail: confirm scoreboard header "Top of Inning 1/3" and "Yankees ← batting".
6. Play a few rolls; confirm team names stay correct.
7. Refresh mid-game; confirm team names persist.

## References

- Research doc: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- Prior plan: `thoughts/shared/plans/2026-06-25-baseball-web-game.md`
- Raw SQL schema: provided by user 2026-06-25 (stadium, team, player, schedule, game, stats, game_participant, lineup)
- `baseball/models.py:6` — existing Game model
- `baseball/forms.py:5` — GameSetupForm
- `baseball/views.py:82` — GameCreateView
