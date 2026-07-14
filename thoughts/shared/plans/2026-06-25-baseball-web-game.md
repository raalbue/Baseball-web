# Baseball Web Game — Implementation Plan

## Overview

Add a `/baseball` route to `todo_list`. Port the console game's dice-roll engine
into a per-user, per-game PostgreSQL-backed web app. Three gameplay modes are
selectable at game-creation time. `engine.py` and `params.py` are copied verbatim
(one import path changed) — no logic rewrite.

## Current State Analysis

- **Console engine** (`baseball-game/baseball/engine.py`, `params.py`): zero
  external deps beyond `random`+`typing`. Fully portable. `GameState` is a plain
  object; `resolve_dice_roll(state)` mutates it and returns `(d1, d2, outcome, msg)`.
- **Display/sound/CLI** (`display.py`, `game.py`): terminal-only, not ported.
- **Django app** (`todo_list`): CBV pattern, `LoginRequiredMixin` everywhere,
  Bootstrap 5 CDN, project `templates/base.html`, PostgreSQL, static at
  `todo_list/static/`. No JS framework. Migration prefix next = `0006`.
- **Routing**: included in `todo_project/urls.py`; baseball gets its own app +
  `path("baseball/", include("baseball.urls"))`.

## Desired End State

`/baseball` (login required) → list of user's games + "New Game" button.

"New Game" → setup form: away name, home name, innings (1-9), **mode (required)**:
- `cpu_auto` — Away bats automatically (paced); user clicks ROLL for each home at-bat.
- `click_all` — User clicks ROLL for every at-bat (both teams).
- `auto_play` — Click PLAY GAME once; server sims full game; browser replays all
  plays with pacing + sound.

Game page shows: scoreboard (inning, half, scores, at-bat marker), diamond (bases),
outs/balls/strikes, current batter, ROLL / PLAY button (per mode), dice result,
growing play-by-play log. Game over → final score + winner banner.

### Verify by:
- All three modes play a full game to completion with correct walk-off/extra-inning
  logic.
- Game state persists: navigate away and back — game resumes.
- Each user's `/baseball` only shows their own games.
- Sound plays on home run and win.
- Pacing delays are visible between plays.

## What We're NOT Doing

- Swing/pitch selection engine (`resolve_action`, `CONTACT_PROB`, `PITCH_TYPES`) — deferred.
- Multiplayer (two humans).
- Game deletion or edit after creation.
- Stats, leaderboards, or aggregates.
- Password-less public access.
- Tests (no existing test suite pattern for views).

## Implementation Approach

Five phases. Each phase leaves the app in a runnable state.

Engine copied into app so it has no cross-project import dependency. GameState
serialized as a plain JSON dict in a `JSONField`. All roll logic is a helper
function called by POST views that return JSON; the template + JS drive the UX.

---

## Phase 1: App Skeleton + Engine

### Overview
Create the `baseball` Django app directory, copy and adapt the engine files, wire
into INSTALLED_APPS and URLs. App is importable; no views yet.

### Changes Required

#### 1. Create app directory
```
todo_list/baseball/
  __init__.py
  apps.py
  engine.py   ← adapted from baseball-game/baseball/engine.py
  params.py   ← copied verbatim from baseball-game/baseball/params.py
  models.py   ← empty stub
  views.py    ← empty stub
  urls.py     ← empty stub
  migrations/
    __init__.py
  templates/baseball/   ← empty dir
  static/baseball/
    js/
    sounds/
```

#### 2. `baseball/apps.py`
```python
from django.apps import AppConfig

class BaseballConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "baseball"
```

#### 3. `baseball/engine.py`
Copy `baseball-game/baseball/engine.py` verbatim **except** change:
```python
# old:
from baseball.params import (
# new:
from .params import (
```
All other logic unchanged.

#### 4. `baseball/params.py`
Copy `baseball-game/baseball/params.py` verbatim. Remove unused console-only keys
from `SOUND_MAP` / `BANNER_FONT` / `PLAY_BALL_TEXT` etc. if desired — or keep as-is
since unused imports don't break anything.

#### 5. `todo_project/settings.py` — add to INSTALLED_APPS
```python
"baseball",   # after "todo_app"
```

#### 6. `todo_project/urls.py`
```python
path("baseball/", include("baseball.urls")),
```
Add before the root `""` include.

### Success Criteria

#### Automated:
- [x] `python manage.py check` exits 0.
- [x] `python -c "from baseball.engine import GameState, resolve_dice_roll; s=GameState('A','H',3); print(resolve_dice_roll(s))"` runs without error.

---

## Phase 2: Model + Migration

### Overview
Define `Game` model, add `GameState` serialization helpers, run migration.

### Changes Required

#### 1. `baseball/models.py`

```python
from django.conf import settings
from django.db import models
from .engine import GameState


class Game(models.Model):
    CPU_AUTO  = "cpu_auto"
    CLICK_ALL = "click_all"
    AUTO_PLAY = "auto_play"
    MODE_CHOICES = [
        (CPU_AUTO,  "CPU auto, you click"),
        (CLICK_ALL, "Click every at-bat"),
        (AUTO_PLAY, "Auto-play whole game"),
    ]

    ACTIVE   = "active"
    FINISHED = "finished"
    STATUS_CHOICES = [(ACTIVE, "Active"), (FINISHED, "Finished")]

    owner         = models.ForeignKey(settings.AUTH_USER_MODEL,
                                      on_delete=models.CASCADE,
                                      related_name="baseball_games")
    away_name     = models.CharField(max_length=50)
    home_name     = models.CharField(max_length=50)
    total_innings = models.PositiveSmallIntegerField(default=3)
    mode          = models.CharField(max_length=20, choices=MODE_CHOICES)
    state         = models.JSONField()           # serialized GameState
    play_log      = models.JSONField(default=list)  # list of play dicts
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default=ACTIVE)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    # -- serialization -------------------------------------------------------

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
        }

    @staticmethod
    def state_from_dict(d: dict) -> GameState:
        gs = GameState(d["away_name"], d["home_name"], d["total_innings"])
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
        return gs

    def load_state(self) -> GameState:
        return self.state_from_dict(self.state)

    def save_state(self, gs: GameState) -> None:
        self.state = self.state_to_dict(gs)
```

#### 2. Run migration
```
python manage.py makemigrations baseball
python manage.py migrate
```

### Success Criteria

#### Automated:
- [x] `python manage.py makemigrations baseball --check` exits 0 after running migrations.
- [x] `python manage.py migrate` exits 0.
- [x] `python manage.py shell -c "from baseball.models import Game; print(Game._meta.fields)"` exits 0.

---

## Phase 3: Views + URLs

### Overview
All views require login. `RollView` and `SimulateView` return JSON. A helper
`process_roll` implements the turn-orchestration logic that replaces the console's
`play_game`/`play_half` while loop.

### Changes Required

#### 1. `baseball/forms.py`
```python
from django import forms
from .models import Game

class GameSetupForm(forms.ModelForm):
    class Meta:
        model   = Game
        fields  = ["away_name", "home_name", "total_innings", "mode"]
        widgets = {
            "total_innings": forms.NumberInput(attrs={"min": 1, "max": 9}),
            "mode": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["away_name"].initial  = "Robots"
        self.fields["home_name"].initial  = "You"
        self.fields["total_innings"].initial = 3
```

#### 2. `baseball/views.py` — helpers
```python
import json
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import ListView, DetailView, CreateView
from django.urls import reverse_lazy, reverse

from .models import Game
from .engine import GameState, resolve_dice_roll
from .params import LINEUP


def _state_snapshot(gs: GameState) -> dict:
    """Minimal dict the JS scoreboard needs to update the DOM."""
    return {
        "inning":        gs.inning,
        "half":          gs.half,
        "outs":          gs.outs,
        "balls":         gs.balls,
        "strikes":       gs.strikes,
        "bases":         gs.bases,
        "away_score":    gs.away_score,
        "home_score":    gs.home_score,
        "batting_team":  gs.batting_team,
        "current_batter": gs.current_batter,
        "game_over":     gs.game_over,
        "away_name":     gs.away_name,
        "home_name":     gs.home_name,
    }


def _advance_game(gs: GameState) -> dict:
    """
    Execute one at-bat. Handles half/inning transitions + walk-off/game-over.
    Returns dict suitable for JSON response.
    """
    d1, d2, outcome, msg = resolve_dice_roll(gs)
    gs.reset_count()
    gs.advance_lineup()

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    # Walk-off: bottom half of final inning, home leads
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg,
                    half_over=True, game_over=True,
                    state=_state_snapshot(gs))

    if gs.outs >= 3:
        half_over = True
        if gs.half == "top":
            # Home team doesn't need to bat if already winning in final inning
            if is_final and gs.home_score > gs.away_score:
                gs.game_over = True
            else:
                gs.half = "bottom"
                gs.reset_half()
        else:  # bottom
            if is_final and gs.home_score != gs.away_score:
                gs.game_over = True
            else:
                gs.inning += 1
                gs.half = "top"
                gs.reset_half()

    return dict(d1=d1, d2=d2, outcome=outcome, message=msg,
                half_over=half_over, game_over=gs.game_over,
                state=_state_snapshot(gs))
```

#### 3. `baseball/views.py` — CBVs
```python
class GameListView(LoginRequiredMixin, ListView):
    model         = Game
    template_name = "baseball/game_list.html"

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)


class GameCreateView(LoginRequiredMixin, CreateView):
    model         = Game
    form_class    = GameSetupForm
    template_name = "baseball/game_setup.html"

    def form_valid(self, form):
        game = form.save(commit=False)
        game.owner = self.request.user
        gs = GameState(game.away_name, game.home_name, game.total_innings)
        game.state = Game.state_to_dict(gs)
        game.save()
        return redirect("baseball-detail", pk=game.pk)


class GameDetailView(LoginRequiredMixin, DetailView):
    model         = Game
    template_name = "baseball/game_detail.html"

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)


class RollView(LoginRequiredMixin, View):
    """POST — execute one at-bat. Returns JSON."""

    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)

        gs   = game.load_state()
        play = _advance_game(gs)
        game.save_state(gs)
        game.play_log = game.play_log + [play]
        if play["game_over"]:
            game.status = Game.FINISHED
        game.save()
        return JsonResponse(play)


class SimulateView(LoginRequiredMixin, View):
    """POST — simulate FULL game. Returns all plays as JSON list."""

    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)

        gs    = game.load_state()
        plays = []
        while not gs.game_over:
            play = _advance_game(gs)
            plays.append(play)
            if play["game_over"]:
                break

        game.save_state(gs)
        game.play_log = plays
        game.status   = Game.FINISHED
        game.save()
        return JsonResponse({"plays": plays})
```

#### 4. `baseball/urls.py`
```python
from django.urls import path
from . import views

urlpatterns = [
    path("",                    views.GameListView.as_view(),   name="baseball-list"),
    path("new/",                views.GameCreateView.as_view(), name="baseball-new"),
    path("<int:pk>/",           views.GameDetailView.as_view(), name="baseball-detail"),
    path("<int:pk>/roll/",      views.RollView.as_view(),       name="baseball-roll"),
    path("<int:pk>/simulate/",  views.SimulateView.as_view(),   name="baseball-simulate"),
]
```

### Success Criteria

#### Automated:
- [x] `python manage.py check` exits 0.

#### Manual:
- [ ] POST to `/baseball/<id>/roll/` returns valid JSON with `d1`, `d2`, `message`, `state`.
- [ ] POST to `/baseball/<id>/simulate/` returns full `plays` list, `game.status` → "finished".
- [ ] Unauthenticated request to `/baseball/` redirects to login.

---

## Phase 4: Templates

### Overview
Three templates extending `templates/base.html`. Game detail template contains all
DOM elements that JS updates. Add Baseball link to navbar.

### Changes Required

#### 1. `templates/base.html` — add navbar link
Inside the `{% if user.is_authenticated %}` block, after "My Lists":
```html
<li class="nav-item">
    <a class="nav-link" href="{% url 'baseball-list' %}">Baseball</a>
</li>
```

#### 2. `baseball/templates/baseball/game_list.html`
```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Your Games</h2>
    <a href="{% url 'baseball-new' %}" class="btn btn-success">New Game</a>
</div>
{% if object_list %}
<table class="table table-hover">
    <thead><tr><th>Away</th><th>Home</th><th>Innings</th><th>Mode</th>
                <th>Status</th><th>Score</th><th></th></tr></thead>
    <tbody>
    {% for g in object_list %}
    <tr>
        <td>{{ g.away_name }}</td>
        <td>{{ g.home_name }}</td>
        <td>{{ g.total_innings }}</td>
        <td>{{ g.get_mode_display }}</td>
        <td>{{ g.get_status_display }}</td>
        <td>{{ g.state.away_score }}–{{ g.state.home_score }}</td>
        <td><a href="{% url 'baseball-detail' g.pk %}" class="btn btn-sm btn-outline-primary">
            {% if g.status == "finished" %}View{% else %}Resume{% endif %}
        </a></td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<p class="text-muted">No games yet. <a href="{% url 'baseball-new' %}">Start one!</a></p>
{% endif %}
{% endblock %}
```

#### 3. `baseball/templates/baseball/game_setup.html`
```html
{% extends "base.html" %}
{% block content %}
<h2>New Game</h2>
<form method="post" class="mt-3" style="max-width:480px">
    {% csrf_token %}
    <div class="mb-3">
        <label class="form-label">Away Team (CPU)</label>
        {{ form.away_name.as_widget }}
    </div>
    <div class="mb-3">
        <label class="form-label">Home Team (You)</label>
        {{ form.home_name.as_widget }}
    </div>
    <div class="mb-3">
        <label class="form-label">Innings</label>
        {{ form.total_innings.as_widget }}
    </div>
    <div class="mb-3">
        <label class="form-label fw-bold">Mode</label>
        {% for radio in form.mode %}
        <div class="form-check">
            {{ radio.tag }}
            <label class="form-check-label" for="{{ radio.id_for_label }}">
                {{ radio.choice_label }}
            </label>
        </div>
        {% endfor %}
    </div>
    <button type="submit" class="btn btn-success">Play Ball!</button>
    <a href="{% url 'baseball-list' %}" class="btn btn-link">Cancel</a>
</form>
{% endblock %}
```

#### 4. `baseball/templates/baseball/game_detail.html`
Key DOM IDs used by JS are shown in comments. Full structure:
```html
{% extends "base.html" %}
{% load static %}
{% block content %}
<!-- CSRF token for JS fetch POSTs -->
<form id="csrf-form" style="display:none">{% csrf_token %}</form>

<!-- JS config vars -->
<script>
const GAME_MODE   = "{{ game.mode }}";
const GAME_STATUS = "{{ game.status }}";
const ROLL_URL    = "{% url 'baseball-roll' game.pk %}";
const SIM_URL     = "{% url 'baseball-simulate' game.pk %}";
const SOUND_HR    = "{% static 'baseball/sounds/5.wav' %}";
const SOUND_WIN   = "{% static 'baseball/sounds/10.wav' %}";
const SOUND_PLAY  = "{% static 'baseball/sounds/1.wav' %}";
</script>

<div class="row">
  <!-- Scoreboard -->
  <div class="col-md-5">
    <div class="card mb-3">
      <div class="card-header fw-bold" id="sb-inning-label">
        {{ game.state.half|title }} of Inning
        <span id="sb-inning">{{ game.state.inning }}</span>/{{ game.total_innings }}
      </div>
      <ul class="list-group list-group-flush">
        <li class="list-group-item d-flex justify-content-between">
          <span>{{ game.away_name }} <small id="sb-away-bat" class="text-muted"></small></span>
          <strong id="sb-away-score">{{ game.state.away_score }}</strong>
        </li>
        <li class="list-group-item d-flex justify-content-between">
          <span>{{ game.home_name }} <small id="sb-home-bat" class="text-muted"></small></span>
          <strong id="sb-home-score">{{ game.state.home_score }}</strong>
        </li>
      </ul>
      <div class="card-body">
        <!-- Outs row -->
        <div class="mb-2">Outs: <span id="sb-outs">{{ game.state.outs }}</span></div>
        <!-- Diamond -->
        <div id="diamond" class="my-2" style="font-family:monospace;font-size:1.2rem">
          <!-- rendered by JS updateDiamond() -->
        </div>
        <!-- Batter -->
        <p class="mt-2 mb-0">Batting: <span id="sb-batter">{{ game.state.current_batter }}</span>
          (<span id="sb-team">{{ game.state.batting_team }}</span>)</p>
      </div>
    </div>

    <!-- Dice / result display -->
    <div id="dice-display" class="card mb-3 d-none">
      <div class="card-body text-center">
        <h4 id="dice-roll"></h4>
        <p id="dice-outcome" class="fw-bold mb-0"></p>
      </div>
    </div>

    <!-- Action buttons -->
    <div id="btn-area">
      {% if game.status == "active" %}
        {% if game.mode == "auto_play" %}
          <button id="btn-play" class="btn btn-success btn-lg w-100">Play Ball!</button>
        {% else %}
          <button id="btn-roll" class="btn btn-primary btn-lg w-100">Roll Dice</button>
        {% endif %}
      {% else %}
        <div class="alert alert-success">Game Over!</div>
      {% endif %}
    </div>
  </div>

  <!-- Play-by-play log -->
  <div class="col-md-7">
    <div class="card">
      <div class="card-header">Play-by-Play</div>
      <div id="play-log" class="card-body" style="max-height:60vh;overflow-y:auto">
        {% for play in game.play_log %}
          <p class="mb-1 small">
            [{{ play.state.half|upper }} {{ play.state.inning }}]
            🎲 [{{ play.d1 }}][{{ play.d2 }}] — {{ play.message }}
          </p>
        {% empty %}
          <p class="text-muted">No plays yet.</p>
        {% endfor %}
      </div>
    </div>
  </div>
</div>

<script src="{% static 'baseball/js/game.js' %}"></script>
{% endblock %}
```

### Success Criteria

#### Manual:
- [ ] `/baseball/` renders game list (empty state + "Start one!" link).
- [ ] `/baseball/new/` renders form with all three mode radio buttons.
- [ ] `/baseball/<id>/` renders scoreboard with correct initial state from DB.
- [ ] Baseball link appears in navbar when logged in.

> Note: two fixes applied vs plan — `_advance_game` captures `play_half`/`play_inning`
> before half transition; `GameDetailView.get_context_data` passes `current_batter` +
> `batting_team` (properties on GameState, not in serialized dict).

---

## Phase 5: JavaScript + Sound

### Overview
`game.js` drives all three modes. On page load it reads the JS config vars injected
by the template, wires up the appropriate button behavior, and provides DOM update
helpers.

### Changes Required

#### 1. Copy sound files
Copy from `baseball-game/mytimer/sounds/`:
- `1.wav`  → `baseball/static/baseball/sounds/1.wav`   (play ball)
- `5.wav`  → `baseball/static/baseball/sounds/5.wav`   (home run)
- `10.wav` → `baseball/static/baseball/sounds/10.wav`  (win)

#### 2. `baseball/static/baseball/js/game.js`

```javascript
/* Baseball web game — drives all three play modes. */

const CSRF = () =>
    document.querySelector('#csrf-form [name=csrfmiddlewaretoken]').value;

const sfx = {
    play_ball: new Audio(SOUND_PLAY),
    home_run:  new Audio(SOUND_HR),
    win:       new Audio(SOUND_WIN),
};

function playSound(key) {
    const a = sfx[key];
    if (!a) return;
    a.currentTime = 0;
    a.play().catch(() => {});
}

// --- DOM helpers -----------------------------------------------------------

const LINEUP = [
    "Diaz","Okafor","Tanaka","Smith","Rossi","Khan","Muller","Santos","Park"
];

function updateScoreboard(state) {
    document.getElementById('sb-inning').textContent = state.inning;
    document.getElementById('sb-inning-label').textContent =
        (state.half === 'top' ? 'Top' : 'Bottom') +
        ' of Inning ' + state.inning + '/' + state.away_name;
    document.getElementById('sb-away-score').textContent = state.away_score;
    document.getElementById('sb-home-score').textContent = state.home_score;
    document.getElementById('sb-outs').textContent = state.outs;
    document.getElementById('sb-batter').textContent = state.current_batter;
    document.getElementById('sb-team').textContent = state.batting_team;

    const awayBat = document.getElementById('sb-away-bat');
    const homeBat = document.getElementById('sb-home-bat');
    awayBat.textContent = state.half === 'top' ? '← batting' : '';
    homeBat.textContent = state.half === 'bottom' ? '← batting' : '';

    updateDiamond(state.bases);
}

function updateDiamond(bases) {
    const b = bases; // [1B, 2B, 3B]
    const on = '🟡', off = '⬜';
    document.getElementById('diamond').innerHTML =
        `<pre style="line-height:1.4;margin:0">` +
        `         ${b[1] ? on : off}\n` +
        `        /   \\\n` +
        `    ${b[2] ? on : off}       ${b[0] ? on : off}\n` +
        `        \\   /\n` +
        `         (H)\n` +
        `</pre>`;
}

function showDice(d1, d2, outcome) {
    const el = document.getElementById('dice-display');
    el.classList.remove('d-none');
    document.getElementById('dice-roll').textContent = `[${d1}]  [${d2}]`;
    document.getElementById('dice-outcome').textContent = outcome.replace(/_/g,' ').toUpperCase();
}

function appendPlay(play) {
    const log = document.getElementById('play-log');
    const empty = log.querySelector('.text-muted');
    if (empty) empty.remove();
    const p = document.createElement('p');
    p.className = 'mb-1 small';
    const s = play.state;
    const half = s.half === 'top' ? 'TOP' : 'BOT';
    p.textContent = `[${half} ${s.inning}] 🎲 [${play.d1}][${play.d2}] — ${play.message}`;
    log.appendChild(p);
    log.scrollTop = log.scrollHeight;
}

function showGameOver(state) {
    const btnArea = document.getElementById('btn-area');
    const winner = state.away_score > state.home_score
        ? state.away_name : (state.home_score > state.away_score
        ? state.home_name : null);
    btnArea.innerHTML = `<div class="alert alert-success fw-bold fs-5">
        ${winner ? winner + ' win!' : "It's a tie!"}
        <br><small>${state.away_name} ${state.away_score} — ${state.home_score} ${state.home_name}</small>
        <br><a href="/baseball/" class="btn btn-outline-success btn-sm mt-2">Back to games</a>
    </div>`;
    playSound('win');
}

// --- Roll mechanics --------------------------------------------------------

async function doRoll() {
    const resp = await fetch(ROLL_URL, {
        method: 'POST',
        headers: {'X-CSRFToken': CSRF(), 'Content-Type': 'application/json'},
    });
    return resp.json();
}

async function doSimulate() {
    const resp = await fetch(SIM_URL, {
        method: 'POST',
        headers: {'X-CSRFToken': CSRF(), 'Content-Type': 'application/json'},
    });
    return resp.json();
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function handlePlay(play, noSound = false) {
    showDice(play.d1, play.d2, play.outcome);
    appendPlay(play);
    updateScoreboard(play.state);
    if (!noSound && play.outcome === 'home_run') playSound('home_run');
    const delay = play.outcome === 'home_run' ? 1400 : 900;
    await sleep(delay);
    if (play.half_over && !play.game_over) {
        await sleep(600); // brief pause at half-inning change
    }
}

// --- Mode: click_all -------------------------------------------------------

function initClickAll() {
    const btn = document.getElementById('btn-roll');
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) {
            showGameOver(play.state);
        } else {
            btn.disabled = false;
        }
    });
}

// --- Mode: cpu_auto --------------------------------------------------------

function initCpuAuto() {
    const btn = document.getElementById('btn-roll');

    async function autoRollCPU() {
        // auto-roll until outs = 3 or game over (top half / CPU)
        while (true) {
            await sleep(1200);
            const play = await doRoll();
            await handlePlay(play);
            if (play.game_over) { showGameOver(play.state); return; }
            if (play.half_over) {
                // switched to bottom (home team bats) — enable button
                btn.disabled = false;
                btn.textContent = 'Roll Dice (Your Turn)';
                return;
            }
        }
    }

    // Determine if we start in top (CPU) or bottom (player)
    // Read from initial state in DOM (state injected as data attrs via template)
    const initHalf = document.getElementById('sb-away-bat').textContent
        ? 'top' : 'bottom';

    if (initHalf === 'top') {
        btn.disabled = true;
        btn.textContent = 'CPU batting…';
        autoRollCPU();
    }

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) { showGameOver(play.state); return; }
        if (play.half_over) {
            // switched to top (CPU bats)
            btn.textContent = 'CPU batting…';
            await autoRollCPU();
        } else {
            btn.disabled = false;
        }
    });
}

// --- Mode: auto_play -------------------------------------------------------

function initAutoPlay() {
    const btn = document.getElementById('btn-play');
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Simulating…';
        playSound('play_ball');
        const data = await doSimulate();
        btn.textContent = 'Replaying…';
        for (const play of data.plays) {
            await handlePlay(play);
        }
        const last = data.plays[data.plays.length - 1];
        if (last) showGameOver(last.state);
    }, { once: true });
}

// --- Init ------------------------------------------------------------------

if (GAME_STATUS === 'active') {
    if (GAME_MODE === 'click_all')  initClickAll();
    if (GAME_MODE === 'cpu_auto')   initCpuAuto();
    if (GAME_MODE === 'auto_play')  initAutoPlay();
}

// Initial diamond render
const initBases = [
    !!document.getElementById('sb-away-bat'), // placeholder — set from template data
];
// Scoreboard already rendered server-side; just init diamond from template state.
// The template must add data-bases attr to the diamond div.
```

> **Note on JS init state**: the `cpu_auto` init needs to know the current half at
> page load (to auto-roll CPU or wait for player). Add `data-half="{{ game.state.half }}"` 
> to the `<div id="diamond">` in the template; the JS reads it. Similarly add
> `data-bases="{{ game.state.bases|join:',' }}"` for initial diamond render.

### Success Criteria

#### Automated:
- [x] `python manage.py collectstatic --noinput` exits 0 (wav files included).

#### Manual:
- [ ] **click_all**: clicking ROLL each time plays a full game; log grows; game-over shows winner.
- [ ] **cpu_auto**: CPU half auto-rolls with ~1.2s delay; ROLL button appears for home half; alternates correctly through innings.
- [ ] **auto_play**: one click sims and replays the full game play by play with pacing.
- [ ] Home run sound plays on home run in all modes.
- [ ] Win sound plays at game end.
- [ ] Refreshing the game page mid-game shows the correct resumed state (play log, scores).
- [ ] Finished game shows "View" link in list; detail page shows play log but no button.

---

## Testing Strategy

### Manual Testing Steps:
1. Create game in each mode (click_all, cpu_auto, auto_play) with custom team names and 3 innings.
2. Play to completion; verify walk-off logic (home leading after top of final → game ends without bottom).
3. Verify extra innings: set up a tie at end of inning 3 (use `--seed` mental model — just play until it happens).
4. Refresh mid-game; confirm state persists.
5. Log in as second user; confirm first user's games not visible.
6. Verify no XSS: try team name `<script>alert(1)</script>`.

## References

- Research doc: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- Engine source: `../../baseball-game/baseball/engine.py`
- Params source: `../../baseball-game/baseball/params.py`
- Sound files: `../../baseball-game/mytimer/sounds/{1,5,10}.wav`
- Django URL pattern: `todo_project/urls.py:20`
- Bootstrap base: `templates/base.html`
