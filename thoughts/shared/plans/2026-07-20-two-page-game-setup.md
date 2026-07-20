# Two-Page Game Setup Implementation Plan

## Overview

Replace the current one-page-plus-roster-page game setup with a true two-page flow:
**Page 1** is Player 1 — pick home/away, team, lineup (drag-reorderable), game mode,
and innings (3/6/9), then **Next**. **Page 2** is Player 2 — gets whichever side
Player 1 didn't pick, chooses their team and lineup, then **Play Ball!**. If Player 1
picks the `cpu_auto` mode, Player 2 doesn't exist as a human — Player 1 also picks
the CPU's team on page 1, the CPU's roster is auto-filled, and page 1's button
creates the game directly (page 2 is skipped).

This also fixes a latent bug: `cpu_auto` mode currently auto-rolls whichever side is
"away" (hardcoded), regardless of who's actually the CPU. A new `Game.cpu_side`
field + a `game.js` fix make the auto-roll follow the real CPU-controlled side.

## Current State Analysis

- **`baseball/forms.py`** — `GameSetupForm` (away_team, home_team, `total_innings`
  free `NumberInput` 1–9, `mode` radio) and `RosterForm` (20 position dropdowns,
  `away_<POS>`/`home_<POS>`, built from `position_pools(team)`, plus hidden
  `away_order`/`home_order` for SortableJS drag-reorder).
- **`baseball/views.py`** — `GameCreateView` (`FormView`) stashes the setup choices
  into `request.session["bb_setup"]`, redirects to `RosterView`. `RosterView.get`
  auto-fills the away side via `auto_fill_roster(team)` (`views.py:45-62`, a
  team-agnostic helper — picks one eligible, distinct player per position,
  preferring each player's main position). `RosterView.post` builds both rosters,
  creates the `GameState`/`Game`, redirects to detail.
- **Structural constraint**: `RosterForm`'s position dropdowns are scoped via
  `position_pools(team)` (`models.py:114`), which requires a `Team` to already be
  known — that's why team selection and roster selection are on separate pages
  today. There's no client-side (AJAX) dropdown-population pattern anywhere in this
  codebase to build on.
- **`baseball/templates/baseball/game_setup.html`** — plain Bootstrap form, no JS.
- **`baseball/templates/baseball/game_roster.html`** — two side-by-side columns
  (away/home), each with a pinned pitcher dropdown + SortableJS-powered 9-row
  batting-order list feeding a hidden `*_order` field (see
  `thoughts/shared/plans/2026-06-29-baseball-batting-order-dragdrop.md`).
- **`baseball/static/baseball/js/game.js:161-191`** (`initCpuAuto`) — auto-rolls
  in a loop **only when `initHalf === 'top'`** (away), otherwise requires a manual
  click. This hardcodes "away = CPU", which breaks once either side can be
  CPU-controlled.
- **`baseball/models.py:235-271`** (`Game`) — has `mode` (`MODE_CHOICES`:
  `cpu_auto`/`click_all`/`auto_play`) but no field marking which side (if any) is
  CPU-controlled.
- No other views/templates/tests reference `GameSetupForm`, `RosterForm`,
  `baseball-new`, or `baseball-roster` beyond what's listed above (confirmed via
  repo-wide grep).

## Desired End State

- `/baseball/new/` (Page 1): side (Home/Away radio), team dropdown, mode radio,
  innings radio (3/6/9). Choosing a team reloads the page (same URL) revealing a
  pinned-pitcher + 9-row drag-orderable batting list, auto-filled with a sensible
  default lineup (via `auto_fill_roster`), fully editable. If `cpu_auto` mode is
  selected, an "Opponent Team (CPU)" dropdown also appears; the button reads
  **"Play Ball!"** and submitting creates the game immediately (CPU roster
  auto-filled, no page 2). For any other mode, the button reads **"Next"** and
  submitting stores Player 1's choices in the session and redirects to page 2.
- `/baseball/roster/` (Page 2): shown only for human-vs-human games. Header states
  which side Player 1 took and which side/mode/innings are locked in. Team dropdown
  (excludes Player 1's team) + same pinned-pitcher/drag-order lineup UI. Submitting
  ("Play Ball!") creates the game and redirects to detail.
- `Game.cpu_side` is `"away"`, `"home"`, or `null` (human vs human). `game.js`'s
  auto-roll loop triggers based on `cpu_side`, not on `half === 'top'`.
- Old games (no `cpu_side`) continue to display and play correctly — `cpu_side`
  defaults to `null`, and non-`cpu_auto` modes never read it.

### Verify by:
- Starting a `cpu_auto` game with Player 1 = Home: one page, pick own team +
  lineup + opponent team, click "Play Ball!" → game created, CPU (away) auto-rolls
  every top half without a click; Player 1 (home) must click every bottom half.
- Starting a `click_all` game with Player 1 = Away: page 1 → Next → page 2 shows
  "Home" locked in, team dropdown excludes Player 1's team → Play Ball! → game
  created with both rosters correct, both sides require manual clicks.
- Picking the same team on page 2 as Player 1 picked → validation error, no game
  created.

## Key Discoveries
- `auto_fill_roster(team)` (`views.py:45`) is already team-agnostic — nothing CPU-
  specific in its logic, just its calling context. Reused as-is for both the
  "default lineup suggestion" on each human page and the CPU's actual roster.
- `lineup_from_roster` (`views.py:65-67`) and `roster_for` (`forms.py:121-131`,
  order-aware per `thoughts/shared/plans/2026-06-29-baseball-batting-order-dragdrop.md`)
  need no changes — both already operate on a plain roster list, independent of
  which side it ends up assigned to.
- Django `ModelChoiceField`s on a **bound** form render using submitted POST data,
  not `initial=` — so pre-filling a default lineup on the "team just chosen" reload
  requires injecting picks into a mutable copy of `request.POST` (`QueryDict.copy()`)
  before constructing the bound form, not passing `initial=`.
- `GameState.__init__` (`engine.py:14-20`) takes `away_name, home_name,
  total_innings, away_lineup=None, home_lineup=None` — unchanged, reused identically
  from both the cpu_auto direct-create path and the page-2 create path.
- No other code references `GameSetupForm`/`RosterForm`/the two view classes by
  name — safe to rewrite in place without breaking other call sites.

## What We're NOT Doing
- No AJAX/dynamic dropdown population — team changes trigger a full-page POST
  reload (matches the only pattern this codebase already uses).
- No change to `click_all` / `auto_play` gameplay behavior — both already treat
  every at-bat as requiring a manual click regardless of side, so they already work
  correctly for two human players with no `game.js` changes needed.
- No random/AI opponent-team suggestion — Player 1 explicitly picks the CPU's team
  when `cpu_auto` is selected.
- No changes to `RollView`/`SimulateView` — gameplay POST handling doesn't care who
  configured which side.
- No migration of existing in-progress games — `cpu_side` is nullable and only
  read when `mode == cpu_auto`.

## Implementation Approach

Five phases, each independently runnable: schema field first, then the shared form
layer, then views (session hand-off + direct-create branch), then templates, then
the `game.js` fix that closes the loop on the CPU-side bug the new flow surfaces.

---

## Phase 1: `cpu_side` Field

### Overview
Add a nullable field to `Game` marking which side (if any) is CPU-controlled.

### Changes Required

#### 1. `baseball/models.py` — add to `Game`, after the `mode` field

```python
class Game(models.Model):
    CPU_AUTO  = "cpu_auto"
    CLICK_ALL = "click_all"
    AUTO_PLAY = "auto_play"
    MODE_CHOICES = [
        (CPU_AUTO,  "CPU auto, you click"),
        (CLICK_ALL, "Click every at-bat"),
        (AUTO_PLAY, "Auto-play whole game"),
    ]

    CPU_SIDE_CHOICES = [("away", "Away"), ("home", "Home")]

    ...
    mode          = models.CharField(max_length=20, choices=MODE_CHOICES)
    cpu_side      = models.CharField(max_length=4, choices=CPU_SIDE_CHOICES,
                                     null=True, blank=True)
    state         = models.JSONField()
```

#### 2. Migration

```
python manage.py makemigrations baseball
python manage.py migrate
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py makemigrations baseball --check` — **pre-existing unrelated
      failure**, not caused by this phase: it perpetually re-detects a cosmetic
      `away_team`/`home_team` FK diff (bare `'Team'` string ref vs resolved
      `'baseball.team'`) that predates this work. Confirmed un-appliable even in
      isolation — attempting it throws `psycopg2.errors.DuplicateObject` against a
      pre-existing Postgres FK constraint name. Trimmed out of migration 0008 so
      `cpu_side` applies cleanly on its own.
- [x] `python manage.py shell -c "from baseball.models import Game; print(Game._meta.get_field('cpu_side'))"` exits 0 (`baseball.Game.cpu_side`)

#### Manual Verification:
- [ ] Existing games (created before this change) still load on `/baseball/<pk>/` with no errors

**Implementation Note**: Pause here for manual confirmation before Phase 2.

---

## Phase 2: Shared Single-Side Roster Form

### Overview
Replace `GameSetupForm` + `RosterForm` with `SideRosterForm` (team + 10-slot roster,
unprefixed field names, usable for either page) and `Page1Form` (`SideRosterForm`
plus side/mode/innings/opponent-team).

### Changes Required

#### 1. `baseball/forms.py` — full replacement

```python
from django import forms
from .models import Game, Team, Player, position_pools

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
BATTING_POSITIONS = [code for code, _ in POSITIONS if code != "P"]


class SideRosterForm(forms.Form):
    """One side's team pick + 10-slot roster (unprefixed position field names)."""

    def __init__(self, *args, team=None, team_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"] = forms.ModelChoiceField(
            queryset=team_queryset if team_queryset is not None else Team.objects.all(),
            label="Team",
            empty_label="— select team —",
            widget=forms.Select(attrs={"class": "form-select", "id": "id_team"}),
        )
        pools = position_pools(team) if team else {}
        for code, label in POSITIONS:
            ids = pools.get(code, [])
            qs = Player.objects.filter(player_id__in=ids) if team else Player.objects.none()
            self.fields[code] = forms.ModelChoiceField(
                queryset=qs,
                label=label,
                empty_label=f"— select {label.lower()} —",
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        self.fields["order"] = forms.CharField(
            required=False,
            initial=",".join(BATTING_POSITIONS),
            widget=forms.HiddenInput(),
        )

    def pitcher_field(self):
        return self["P"]

    def batting_fields(self):
        return [(code, self[code]) for code in BATTING_POSITIONS]

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
        return cleaned

    def roster_for(self):
        """10-slot roster: pitcher first, then 9 batting slots in chosen order."""
        raw = (self.cleaned_data.get("order") or "").split(",")
        order = [c for c in raw if c]
        if sorted(order) != sorted(BATTING_POSITIONS):
            order = list(BATTING_POSITIONS)
        out = []
        for code in ["P"] + order:
            p = self.cleaned_data[code]
            out.append({"position": code, "player_id": p.player_id, "name": str(p)})
        return out


class Page1Form(SideRosterForm):
    """Page 1: side + team + roster + mode + innings (+ opponent team if cpu_auto)."""

    SIDE_CHOICES = [("away", "Away"), ("home", "Home")]
    INNINGS_CHOICES = [(3, "3"), (6, "6"), (9, "9")]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["side"] = forms.ChoiceField(
            choices=self.SIDE_CHOICES, widget=forms.RadioSelect, initial="away",
        )
        self.fields["mode"] = forms.ChoiceField(
            choices=Game.MODE_CHOICES, widget=forms.RadioSelect,
            initial=Game.CPU_AUTO,
        )
        self.fields["total_innings"] = forms.TypedChoiceField(
            choices=self.INNINGS_CHOICES, coerce=int, initial=3,
            widget=forms.RadioSelect,
        )
        self.fields["opponent_team"] = forms.ModelChoiceField(
            queryset=Team.objects.all(), required=False,
            label="Opponent Team (CPU)",
            empty_label="— select opponent team —",
            widget=forms.Select(attrs={"class": "form-select"}),
        )

    def clean(self):
        cleaned = super().clean()
        team = cleaned.get("team")
        opp  = cleaned.get("opponent_team")
        if cleaned.get("mode") == Game.CPU_AUTO:
            if not opp:
                self.add_error("opponent_team", "Pick the CPU's team.")
            elif team and team.team_id == opp.team_id:
                self.add_error("opponent_team", "Opponent team must differ from your team.")
        return cleaned
```

`Page2Form` is not a new class — page 2 uses `SideRosterForm` directly, with
`team_queryset=Team.objects.exclude(pk=<player 1's team id>)`.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0 — note: this only became true again once Phase 3's
      view import swap landed (forms.py/views.py are coupled; `check` fails with an
      `ImportError` on forms.py alone until views.py stops importing the old names).
      The forms-only shell check below passed in isolation as expected.
- [x] `python manage.py shell -c "from baseball.forms import SideRosterForm, Page1Form; from baseball.models import Team; t=Team.objects.first(); f=SideRosterForm(team=t); assert len(f.batting_fields())==9; f2=Page1Form(); assert 'opponent_team' in f2.fields and 'side' in f2.fields; print('ok')"` → `ok`

#### Manual Verification:
- [ ] None yet — forms aren't wired to views until Phase 3

**Implementation Note**: Pause here for manual confirmation before Phase 3.

---

## Phase 3: Views — Page 1 / Page 2

### Overview
Replace `GameCreateView`/`RosterView` with `Page1View`/`Page2View`. Each handles two
POST actions: `choose_team` (reload with team-scoped roster fields, no validation)
and `next` (full validation → advance or create). `Page1View` branches on mode:
`cpu_auto` creates the game directly; anything else hands off to `Page2View` via
session.

### Changes Required

#### 1. `baseball/views.py` — imports

```python
from .forms import Page1Form, SideRosterForm, POSITIONS, BATTING_POSITIONS
```
(replaces the old `from .forms import GameSetupForm, RosterForm, POSITIONS, BATTING_POSITIONS`)

#### 2. `baseball/views.py` — CPU roster helper, next to `auto_fill_roster`

```python
def cpu_roster_for(team):
    """Full 10-slot roster (canonical order) auto-picked for a CPU-controlled team."""
    picks = auto_fill_roster(team)  # {position_code: player_id}
    players = {p.player_id: p for p in Player.objects.filter(player_id__in=picks.values())}
    out = []
    for code, _ in POSITIONS:
        pid = picks.get(code)
        if pid is None:
            continue
        out.append({"position": code, "player_id": pid, "name": str(players[pid])})
    return out
```

#### 3. `baseball/views.py` — replace `GameCreateView` and `RosterView`

```python
class Page1View(LoginRequiredMixin, View):
    template_name = "baseball/game_setup.html"

    def get(self, request):
        return render(request, self.template_name, {"form": Page1Form(), "team_chosen": False})

    def post(self, request):
        team_id = request.POST.get("team")
        team = Team.objects.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = Page1Form(data, team=team)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None})

        form = Page1Form(request.POST, team=team)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None})

        cd = form.cleaned_data
        side = cd["side"]
        own_team = cd["team"]
        own_roster = form.roster_for()

        if cd["mode"] == Game.CPU_AUTO:
            opponent_team = cd["opponent_team"]
            cpu_roster = cpu_roster_for(opponent_team)
            if side == "away":
                away_team, home_team = own_team, opponent_team
                away_roster, home_roster = own_roster, cpu_roster
                cpu_side = "home"
            else:
                away_team, home_team = opponent_team, own_team
                away_roster, home_roster = cpu_roster, own_roster
                cpu_side = "away"

            gs = GameState(
                away_team.name, home_team.name, cd["total_innings"],
                away_lineup=lineup_from_roster(away_roster),
                home_lineup=lineup_from_roster(home_roster),
            )
            game = Game.objects.create(
                owner=request.user,
                away_name=away_team.name, home_name=home_team.name,
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                cpu_side=cpu_side,
                state=Game.state_to_dict(gs),
                away_roster=away_roster, home_roster=home_roster,
            )
            return redirect("baseball-detail", pk=game.pk)

        request.session["bb_setup"] = {
            "side":          side,
            "p2_side":       "home" if side == "away" else "away",
            "team_id":       own_team.team_id,
            "team_name":     own_team.name,
            "mode":          cd["mode"],
            "total_innings": cd["total_innings"],
            "roster":        own_roster,
        }
        return redirect("baseball-roster")


class Page2View(LoginRequiredMixin, View):
    template_name = "baseball/game_roster.html"

    def _setup(self, request):
        return request.session.get("bb_setup")

    def _team_qs(self, setup):
        return Team.objects.exclude(pk=setup["team_id"])

    def get(self, request):
        setup = self._setup(request)
        if not setup:
            return redirect("baseball-new")
        form = SideRosterForm(team_queryset=self._team_qs(setup))
        return render(request, self.template_name,
                      {"form": form, "setup": setup, "team_chosen": False})

    def post(self, request):
        setup = self._setup(request)
        if not setup:
            return redirect("baseball-new")
        team_qs = self._team_qs(setup)
        team_id = request.POST.get("team")
        team = team_qs.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": team is not None})

        form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": team is not None})

        p2_team = form.cleaned_data["team"]
        p2_roster = form.roster_for()
        p1_team = get_object_or_404(Team, pk=setup["team_id"])

        if setup["side"] == "away":
            away_team, home_team = p1_team, p2_team
            away_roster, home_roster = setup["roster"], p2_roster
        else:
            away_team, home_team = p2_team, p1_team
            away_roster, home_roster = p2_roster, setup["roster"]

        gs = GameState(
            away_team.name, home_team.name, setup["total_innings"],
            away_lineup=lineup_from_roster(away_roster),
            home_lineup=lineup_from_roster(home_roster),
        )
        game = Game.objects.create(
            owner=request.user,
            away_name=away_team.name, home_name=home_team.name,
            away_team=away_team, home_team=home_team,
            total_innings=setup["total_innings"], mode=setup["mode"],
            cpu_side=None,
            state=Game.state_to_dict(gs),
            away_roster=away_roster, home_roster=home_roster,
        )
        del request.session["bb_setup"]
        return redirect("baseball-detail", pk=game.pk)
```

`GameListView` and the roll/simulate/replay views are unchanged.

#### 4. `baseball/urls.py` — point existing names at the new views

```python
path("new/",    views.Page1View.as_view(), name="baseball-new"),
path("roster/", views.Page2View.as_view(), name="baseball-roster"),
```
(paths and names unchanged — `game_list.html`'s `{% url 'baseball-new' %}` links
keep working with no template change there.)

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from baseball.views import cpu_roster_for; from baseball.models import Team; r=cpu_roster_for(Team.objects.first()); assert isinstance(r, list) and any(e['position']=='P' for e in r); print('ok')"` → `ok`

Also fixed `ReplayView` (added in a prior session) to carry `cpu_side=game.cpu_side`
into the cloned game — it predates this field and would otherwise silently drop
CPU-side tracking on replayed `cpu_auto` games.

#### Manual Verification:
- [ ] None yet — templates still reference old form field names until Phase 4

**Implementation Note**: Pause here for manual confirmation before Phase 4.

---

## Phase 4: Templates

### Overview
Rewrite `game_setup.html` (page 1) and `game_roster.html` (page 2) around the new
forms: side/mode/innings radios, auto-submitting team `<select>`, conditional
opponent-team block, and the pinned-pitcher/drag-order lineup list reused from the
current roster page.

### Changes Required

#### 1. `baseball/templates/baseball/game_setup.html` — full replacement

```html
{% extends "base.html" %}
{% block content %}
<h2>New Game — Player 1</h2>
<form method="post" class="mt-3" id="side-form">
    {% csrf_token %}
    <input type="hidden" name="action" id="id_action" value="next">

    {% if form.non_field_errors %}
    <div class="alert alert-danger">{{ form.non_field_errors }}</div>
    {% endif %}

    <div class="mb-3">
        <label class="form-label fw-semibold d-block">You are</label>
        {% for radio in form.side %}
        <div class="form-check form-check-inline">
            {{ radio.tag }}
            <label class="form-check-label" for="{{ radio.id_for_label }}">{{ radio.choice_label }}</label>
        </div>
        {% endfor %}
    </div>

    <div class="mb-3" style="max-width:400px">
        <label class="form-label fw-semibold">Your Team</label>
        {{ form.team }}
        {% if form.team.errors %}<div class="text-danger small">{{ form.team.errors }}</div>{% endif %}
    </div>

    <div class="mb-3" style="max-width:400px">
        <label class="form-label fw-semibold">Innings</label>
        {% for radio in form.total_innings %}
        <div class="form-check form-check-inline">
            {{ radio.tag }}
            <label class="form-check-label" for="{{ radio.id_for_label }}">{{ radio.choice_label }}</label>
        </div>
        {% endfor %}
    </div>

    <div class="mb-3">
        <label class="form-label fw-semibold d-block">Mode</label>
        {% for radio in form.mode %}
        <div class="form-check">
            {{ radio.tag }}
            <label class="form-check-label" for="{{ radio.id_for_label }}">{{ radio.choice_label }}</label>
        </div>
        {% endfor %}
        {% if form.mode.errors %}<div class="text-danger small">{{ form.mode.errors }}</div>{% endif %}
    </div>

    <div id="opponent-team-wrap" class="mb-3" style="max-width:400px;display:none">
        <label class="form-label fw-semibold">Opponent Team (CPU)</label>
        {{ form.opponent_team }}
        {% if form.opponent_team.errors %}<div class="text-danger small">{{ form.opponent_team.errors }}</div>{% endif %}
    </div>

    {% if team_chosen %}
    <hr>
    <div class="mb-3">
        <label class="form-label small fw-semibold">
            Pitcher <span class="text-muted fw-normal">(does not bat)</span>
        </label>
        {{ form.pitcher_field }}
        {% if form.pitcher_field.errors %}<div class="text-danger small">{{ form.pitcher_field.errors }}</div>{% endif %}
    </div>

    {{ form.order }}
    <label class="form-label small fw-semibold">Batting Order <span class="text-muted fw-normal">(drag to reorder)</span></label>
    <ol class="list-group list-group-numbered" id="batting-list" style="max-width:500px">
        {% for code, field in form.batting_fields %}
        <li class="list-group-item d-flex align-items-center gap-2" data-pos="{{ code }}">
            <span class="drag-handle text-muted" style="cursor:grab;font-size:1.1rem;user-select:none">⠿</span>
            <div class="flex-grow-1">
                <div class="small text-muted mb-1">{{ field.label }}</div>
                {{ field }}
                {% if field.errors %}<div class="text-danger small">{{ field.errors }}</div>{% endif %}
            </div>
        </li>
        {% endfor %}
    </ol>
    {% endif %}

    <div class="mt-4">
        <button type="submit" id="next-btn" class="btn btn-success">Next</button>
        <a href="{% url 'baseball-list' %}" class="btn btn-link">Cancel</a>
    </div>
</form>

<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script>
document.getElementById('id_team').addEventListener('change', () => {
    document.getElementById('id_action').value = 'choose_team';
    document.getElementById('side-form').submit();
});

function syncModeUI() {
    const checked = document.querySelector('input[name="mode"]:checked');
    const cpuMode = checked && checked.value === 'cpu_auto';
    document.getElementById('opponent-team-wrap').style.display = cpuMode ? '' : 'none';
    document.getElementById('next-btn').textContent = cpuMode ? 'Play Ball!' : 'Next';
}
document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener('change', syncModeUI));
syncModeUI();

const battingList = document.getElementById('batting-list');
if (battingList) {
    const order = document.getElementById('id_order');
    function sync() {
        order.value = Array.from(battingList.children).map(li => li.dataset.pos).join(',');
    }
    new Sortable(battingList, { handle: '.drag-handle', animation: 150, onEnd: sync });
    sync();
}
</script>
{% endblock %}
```

#### 2. `baseball/templates/baseball/game_roster.html` — full replacement

```html
{% extends "base.html" %}
{% block content %}
<h2>New Game — Player 2</h2>
<p class="text-muted">
  Player 1 is {{ setup.team_name }} ({{ setup.side|title }}). You are
  {{ setup.p2_side|title }}. Mode: {{ setup.mode }} · {{ setup.total_innings }} innings.
</p>

<form method="post" class="mt-3" id="side-form">
    {% csrf_token %}
    <input type="hidden" name="action" id="id_action" value="next">

    {% if form.non_field_errors %}
    <div class="alert alert-danger">{{ form.non_field_errors }}</div>
    {% endif %}

    <div class="mb-3" style="max-width:400px">
        <label class="form-label fw-semibold">Your Team</label>
        {{ form.team }}
        {% if form.team.errors %}<div class="text-danger small">{{ form.team.errors }}</div>{% endif %}
    </div>

    {% if team_chosen %}
    <div class="mb-3">
        <label class="form-label small fw-semibold">
            Pitcher <span class="text-muted fw-normal">(does not bat)</span>
        </label>
        {{ form.pitcher_field }}
        {% if form.pitcher_field.errors %}<div class="text-danger small">{{ form.pitcher_field.errors }}</div>{% endif %}
    </div>

    {{ form.order }}
    <label class="form-label small fw-semibold">Batting Order <span class="text-muted fw-normal">(drag to reorder)</span></label>
    <ol class="list-group list-group-numbered" id="batting-list" style="max-width:500px">
        {% for code, field in form.batting_fields %}
        <li class="list-group-item d-flex align-items-center gap-2" data-pos="{{ code }}">
            <span class="drag-handle text-muted" style="cursor:grab;font-size:1.1rem;user-select:none">⠿</span>
            <div class="flex-grow-1">
                <div class="small text-muted mb-1">{{ field.label }}</div>
                {{ field }}
                {% if field.errors %}<div class="text-danger small">{{ field.errors }}</div>{% endif %}
            </div>
        </li>
        {% endfor %}
    </ol>
    {% endif %}

    <div class="mt-4">
        <button type="submit" class="btn btn-success">Play Ball!</button>
        <a href="{% url 'baseball-new' %}" class="btn btn-link">Back</a>
    </div>
</form>

<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script>
document.getElementById('id_team').addEventListener('change', () => {
    document.getElementById('id_action').value = 'choose_team';
    document.getElementById('side-form').submit();
});

const battingList = document.getElementById('batting-list');
if (battingList) {
    const order = document.getElementById('id_order');
    function sync() {
        order.value = Array.from(battingList.children).map(li => li.dataset.pos).join(',');
    }
    new Sortable(battingList, { handle: '.drag-handle', animation: 150, onEnd: sync });
    sync();
}
</script>
{% endblock %}
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from django.template.loader import get_template; get_template('baseball/game_setup.html'); get_template('baseball/game_roster.html'); print('ok')"` → `ok`
- [x] End-to-end HTTP-driven verification (temp test user, real dev server, cleaned up
      after): confirmed via 3 scenarios —
      (A) `cpu_auto`/side=away: team-choose reload reveals all 10 position fields,
          submit creates the game directly (no page 2 redirect), `cpu_side="home"`,
          away_team/home_team assigned correctly, both rosters have 10 entries.
      (B) `cpu_auto`/side=home: same, with `cpu_side="away"` and teams swapped correctly.
      (C) `click_all`/side=away: submit redirects to `/baseball/roster/`; page 2's team
          dropdown excludes Player 1's team (confirmed by set membership); a tampered
          same-team `choose_team` POST correctly reveals no lineup section (team
          resolves to `None` since it's outside the excluded queryset); real page 2
          flow with a different team creates the game with `cpu_side=None`,
          `total_innings=9`, correct away/home mapping, 10-entry rosters.

#### Manual Verification:
- [ ] `/baseball/new/`: side radios, team dropdown, innings (3/6/9), mode all render;
      picking a team reloads the page and reveals pitcher + 9 draggable rows,
      pre-filled with a default lineup
- [ ] Selecting `cpu_auto` mode reveals "Opponent Team (CPU)" and changes the button
      to "Play Ball!"; selecting any other mode hides it and shows "Next"
- [ ] `cpu_auto` submit creates the game directly (no page 2) and redirects to detail
- [ ] Non-`cpu_auto` submit redirects to `/baseball/roster/`, which shows the correct
      locked-in side/mode/innings and a team dropdown that excludes Player 1's team
- [ ] Page 2 team reload reveals lineup fields the same way page 1 does
- [ ] Picking the same team as Player 1 (via direct POST tampering or a stale
      dropdown) is rejected with a validation error
- [ ] Dragging reorders the batting list on both pages; submitting without dragging
      yields canonical order

**Implementation Note**: Pause here for manual confirmation before Phase 5.

---

## Phase 5: Fix `cpu_auto` Auto-Roll to Follow `cpu_side`

### Overview
`game.js`'s `initCpuAuto` currently auto-rolls whenever the *initial half* is
`top`, hardcoding "away = CPU". Switch it to check the actual CPU-controlled side.

### Changes Required

#### 1. `baseball/templates/baseball/game_detail.html` — expose `cpu_side`

```html
<script>
const GAME_MODE   = "{{ game.mode }}";
const GAME_STATUS = "{{ game.status }}";
const CPU_SIDE    = "{{ game.cpu_side|default:'' }}";
const ROLL_URL    = "{% url 'baseball-roll' game.pk %}";
const SIM_URL     = "{% url 'baseball-simulate' game.pk %}";
const REPLAY_URL  = "{% url 'baseball-replay' game.pk %}";
...
</script>
```

#### 2. `baseball/static/baseball/js/game.js` — `initCpuAuto`

```javascript
function initCpuAuto() {
    const btn = document.getElementById('btn-roll');
    const initHalf = document.getElementById('diamond').dataset.half;
    const cpuHalf = CPU_SIDE === 'home' ? 'bottom' : 'top';  // default: away is CPU

    async function autoRollCPU() {
        while (true) {
            await sleep(1200);
            const play = await doRoll();
            await handlePlay(play);
            if (play.game_over) { showGameOver(play.state); return; }
            if (play.half_over) {
                location.reload();
                return;
            }
        }
    }

    if (initHalf === cpuHalf) {
        btn.disabled = true;
        btn.textContent = 'CPU batting…';
        autoRollCPU();
    }

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) { showGameOver(play.state); return; }
        location.reload();
    });
}
```

`CPU_SIDE === 'home' ? 'bottom' : 'top'` covers both the new `cpu_side` values and
the empty-string default (old games / non-`cpu_auto` games never call this function
in the first place, since `GAME_MODE !== 'cpu_auto'` guards the call site at
`game.js` bottom — unchanged).

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] End-to-end HTTP verification (temp test user, real dev server, cleaned up after):
      created a `cpu_auto` game with side=away and one with side=home, fetched each
      detail page and confirmed `const CPU_SIDE = "..."` renders `"home"` and
      `"away"` respectively (matching the stored `game.cpu_side`); confirmed the
      served `game.js` contains the new `cpuHalf`/`initHalf === cpuHalf` logic and
      no longer contains the old hardcoded `initHalf === 'top'` check.

#### Manual Verification:
- [ ] `cpu_auto` game with Player 1 = Away (`cpu_side = "home"`): away (Player 1)
      must click every top half; bottom half auto-rolls without a click
- [ ] `cpu_auto` game with Player 1 = Home (`cpu_side = "away"`): away auto-rolls;
      home (Player 1) must click every bottom half — same as today's behavior,
      confirming no regression for this side assignment
- [ ] A `click_all`/`auto_play` game (human vs human) is unaffected — no
      auto-rolling on either side

---

## Testing Strategy

### Manual Testing Steps (end-to-end):
1. `/baseball/new/` → side = Away, pick a team → page reloads, lineup appears
   pre-filled → pick innings = 6, mode = `click_all` → drag a batting row → click
   Next.
2. Land on `/baseball/roster/` → header confirms "Player 1 is ... (Away). You are
   Home." → pick a different team → lineup appears → drag a row → Play Ball!.
3. Detail page: confirm away/home teams and lineups match what was picked on each
   page, in the dragged order; play a few rolls, confirm both sides require clicks.
4. Repeat from step 1 with mode = `cpu_auto`: opponent-team dropdown appears,
   button reads "Play Ball!"; submit goes straight to detail (no roster page); away
   or home (whichever is CPU) auto-rolls without clicks.
5. On page 2, attempt to submit Player 1's team via browser devtools (bypassing the
   excluded dropdown) → confirm the server-side same-team check rejects it.
6. Create an old-style game (if any pre-existing games in the DB) → confirm it still
   loads and plays correctly with `cpu_side = null`.

## Performance Considerations

No change — same query patterns (`position_pools`, `auto_fill_roster`) as today,
just invoked once per page instead of once per roster-page load.

## Migration Notes

`cpu_side` is nullable with no default; existing rows get `NULL` automatically,
which is the correct "no CPU side" value for previously-created human-vs-human-only
games (the old flow had no CPU concept at all — every existing game was effectively
`cpu_side = NULL`, which is also correct even for historically CPU-vs-you games,
since `game.js` masked that gap with the `half === 'top'` hardcode; the fix's new
default (`CPU_SIDE === 'home' ? 'bottom' : 'top'` → `'top'` when `CPU_SIDE` is
`''`) reproduces the exact old hardcoded behavior for those rows).

## References

- Prior plan: `thoughts/shared/plans/2026-06-29-baseball-batting-order-dragdrop.md`
  (SortableJS drag-order pattern reused here)
- Prior plan: `thoughts/shared/plans/2026-06-25-baseball-team-selection.md` (team
  dropdown / same-team validation pattern reused here)
- `baseball/forms.py` — `GameSetupForm`, `RosterForm` (current, being replaced)
- `baseball/views.py:45-62` — `auto_fill_roster`; `:145-213` — `GameCreateView`,
  `RosterView` (current, being replaced)
- `baseball/static/baseball/js/game.js:161-191` — `initCpuAuto` (the bug being fixed)
- `baseball/models.py:114-124` — `position_pools`; `:235-271` — `Game`
- `baseball/engine.py:14-20` — `GameState.__init__`
