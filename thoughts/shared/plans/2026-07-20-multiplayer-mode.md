# Multiplayer Mode Implementation Plan

## Overview

Add a fourth game mode, `multiplayer`, where Player 1 invites another registered
account to play. The game sits in a new `waiting` status — a real, persisted `Game`
row, not session state — until Player 2 visits their own join page, picks a team
and lineup, and hits Start. From then on both accounts share one game, each only
able to roll during their own half-inning; the non-active player's screen polls
and refreshes until it's their turn.

## Current State Analysis

- **Setup flow today** (`baseball/views.py:161-297`, `baseball/forms.py`) is a
  two-page flow built earlier this session: `Page1View` (side/team/lineup/mode/
  innings) either creates a `cpu_auto` game directly, or stashes Player 1's picks
  in `request.session["bb_setup"]` and redirects to `Page2View` for a second human
  to fill in their side. **That session hand-off only works because it's the same
  browser/account acting as both players in sequence** — a genuinely separate
  logged-in account (Player 2, on their own device) can't see Player 1's session.
  Multiplayer needs Player 1's picks persisted to the database the moment they hit
  Next, not to session state.
- **`Game` model** (`models.py:235-278`) already has the pieces this can build on:
  `away_team`/`home_team` are nullable FKs (`null=True, blank=True`), so a game can
  exist with only one side's team known. `cpu_side` (added earlier this session,
  `models.py:249,268-269`) is exactly the pattern needed for "which side does the
  other account control" — I'll add a parallel `owner_side` field for multiplayer
  rather than overload `cpu_side`, since a game is never simultaneously CPU- and
  human-controlled on the "other" side.
- **`GameListView.get_queryset`** (`views.py:157-158`) filters `owner=request.user`
  only — Player 2 would never see an invite in their list without a change here.
- **`GameDetailView`/`RollView`** (`views.py:300-305`, `345-364`) both filter/require
  `owner=request.user` — same problem, plus `RollView` currently lets the owner roll
  at any time regardless of whose half it is (fine today since only one account is
  ever involved; not fine once a second account can also POST to this endpoint).
- **No real-time infra anywhere in this project** — no channels, no websockets, no
  JS build step. Every existing "live update" in `game.js` (all 3 current modes) is
  a full-page `location.reload()`. I'm following that same convention for turn-sync
  rather than introducing new infrastructure.
- **`game_list.html`** currently labels the non-CPU side with `{{ user.username }}`
  (`game_list.html:24-25`) — correct today only because `owner` always equals the
  viewer (single-owner queryset). Once Player 2 can view rows they don't own, this
  mislabels the opponent's team with the viewer's own name. Must be fixed as part of
  relaxing the queryset — this is a direct consequence of this feature, not a
  pre-existing bug to route around.

## Desired End State

- Page 1 (`game_setup.html`) gets a fourth mode radio, "Multiplayer (invite a
  player)". Selecting it swaps the "Opponent Team (CPU)" dropdown for an "Opponent
  Player" dropdown (all users except yourself). Hitting Next creates a `waiting`
  `Game` (your side's team/lineup saved, the other side empty) and redirects to a
  waiting page.
- Waiting page: "Waiting for `<player2>` to join" + a Cancel button; polls and
  auto-redirects to the real game once Player 2 joins.
- Player 2's game list shows the invite as "Waiting" with a **Join** link (instead
  of Resume/View) leading to their own team+lineup setup page (reusing the existing
  drag-order roster UI), ending in a **Start Game** button.
- Once started, both accounts see the same game at `/baseball/<pk>/`. Each can only
  roll during their own half (away = whoever's `owner_side`/opposite is "away");
  attempting to roll out-of-turn is rejected server-side. The non-active player's
  page shows "Waiting for `<opponent>`…" and polls until it's their turn.
- Either account can cancel/decline a still-`waiting` invite from the game list (or
  from the waiting page), deleting it — so an unavailable invitee doesn't leave a
  dead entry around forever.
- Existing modes (`cpu_auto`, `click_all`, `auto_play`) are unaffected.

### Verify by:
- Account A invites Account B (different browser/incognito session). A sees
  "Waiting…"; B's game list shows "Waiting — Join"; B joins, both redirect to the
  same active game.
- A is away, B is home (or vice versa, depending on A's side pick): only the
  correct account's Roll button is enabled each half; the other shows "Waiting for
  `<name>`…" and auto-refreshes once it becomes their turn.
- A cancels before B joins → row disappears from both A's and B's lists.
- B declines before joining → same.
- A tries to POST to the roll endpoint during B's half (e.g. via devtools) → 403,
  no state change.

## Key Discoveries
- `Page1Form`/`SideRosterForm` (`forms.py`) already fully generalize "team + 10-slot
  roster" independent of which side it ends up on — Player 2's join form reuses
  `SideRosterForm` completely unchanged, exactly like `Page2View` does today.
- `auto_fill_roster`/`cpu_roster_for` (`views.py:48-83`) stay untouched — multiplayer
  never auto-fills an opponent roster, both sides are always human-picked.
- The team-reload dance (`action=choose_team` vs `action=next`, `views.py:172-184`)
  is identical for Player 2's join page — same pattern as `Page2View`, just backed
  by the `Game` row instead of `request.session`.
- `Game.state` is a required (non-nullable) `JSONField` with no default. A `waiting`
  game is created with `state={}` and **must never** have `load_state()` called on
  it until status flips to `active` — enforced by view guards, not a schema change.
- Relaxing `GameDetailView`/`RollView`/`GameListView` to include `player2` requires
  `Q(owner=request.user) | Q(player2=request.user)` (`django.db.models.Q`) — no
  existing view in this codebase uses `Q`, but it's the standard Django tool for
  this and needs no new dependency.
- `ReplayView` (`views.py:398-421`) doesn't carry `player2`/`owner_side` when
  cloning a game — replaying a finished multiplayer game would silently produce a
  broken single-owner "multiplayer" game with no invited opponent. Simplest fix:
  don't offer Replay for multiplayer games at all (hide the button, guard the view).

## What We're NOT Doing
- No real-time push (websockets/SSE/channels) — polling via `location.reload()`,
  matching every existing mode's pattern.
- No email/notification when invited — Player 2 only discovers it by visiting their
  game list, since there's no notification system anywhere in this app.
- No restriction on the opponent dropdown beyond excluding yourself — any registered
  user is invitable (per your answer).
- No Replay support for multiplayer games (button hidden, endpoint guarded) — see
  Key Discoveries above.
- No limit on concurrent invites/games between the same two accounts.
- No change to `cpu_auto`/`click_all`/`auto_play` behavior.

## Implementation Approach

Five phases: schema first, then the form field, then the view/URL layer (the bulk
of the logic — new views, relaxed querysets, turn enforcement), then templates,
then the `game.js` wiring for turn-gated rolling and polling.

---

## Phase 1: Data Model

### Overview
Add the `multiplayer` mode, `waiting` status, `player2` FK, and `owner_side` field.

### Changes Required

#### 1. `baseball/models.py` — extend `Game`

```python
class Game(models.Model):
    CPU_AUTO    = "cpu_auto"
    CLICK_ALL   = "click_all"
    AUTO_PLAY   = "auto_play"
    MULTIPLAYER = "multiplayer"
    MODE_CHOICES = [
        (CPU_AUTO,    "CPU auto, you click"),
        (CLICK_ALL,   "Click every at-bat"),
        (AUTO_PLAY,   "Auto-play whole game"),
        (MULTIPLAYER, "Multiplayer (invite a player)"),
    ]

    ACTIVE   = "active"
    WAITING  = "waiting"
    FINISHED = "finished"
    STATUS_CHOICES = [
        (ACTIVE, "Active"), (WAITING, "Waiting for player"), (FINISHED, "Finished"),
    ]

    CPU_SIDE_CHOICES = [("away", "Away"), ("home", "Home")]

    owner         = models.ForeignKey(settings.AUTH_USER_MODEL,
                                      on_delete=models.CASCADE,
                                      related_name="baseball_games")
    player2       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.CASCADE,
                                      related_name="baseball_games_as_player2")
    away_name     = models.CharField(max_length=50)
    home_name     = models.CharField(max_length=50)
    away_team     = models.ForeignKey(
        'Team', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='away_games',
    )
    home_team     = models.ForeignKey(
        'Team', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='home_games',
    )
    away_roster   = models.JSONField(default=list)
    home_roster   = models.JSONField(default=list)
    total_innings = models.PositiveSmallIntegerField(default=3)
    mode          = models.CharField(max_length=20, choices=MODE_CHOICES)
    cpu_side      = models.CharField(max_length=4, choices=CPU_SIDE_CHOICES,
                                     null=True, blank=True)
    owner_side    = models.CharField(max_length=4, choices=CPU_SIDE_CHOICES,
                                     null=True, blank=True)
    state         = models.JSONField()
    play_log      = models.JSONField(default=list)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default=ACTIVE)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)
```

(Only additions: `MULTIPLAYER` choice, `WAITING` status, `player2`, `owner_side`.
Everything else in the class — `state_to_dict`/`state_from_dict`/`load_state`/
`save_state` — is unchanged.)

#### 2. Migration

```
python manage.py makemigrations baseball
python manage.py migrate
```

Expect an `AddField` for `player2` and `owner_side`, plus metadata-only
`AlterField`s for `mode`/`status` reflecting the new choices lists (no real column
change — `choices` isn't DB-enforced for a plain `CharField`). If `makemigrations`
surfaces anything touching `away_team`/`home_team`, that's the same pre-existing
`'Team'`-string-reference cosmetic drift documented in this session's earlier
two-page-setup plan (Phase 1) — trim it out of the generated migration file the
same way, don't apply it.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from baseball.models import Game; print(Game._meta.get_field('player2')); print(Game._meta.get_field('owner_side')); print(Game.MULTIPLAYER); print(Game.WAITING)"` exits 0

#### Manual Verification:
- [ ] Existing games (all modes) still load and play correctly on `/baseball/<pk>/`

**Implementation Note**: Pause here for manual confirmation before Phase 2.

---

## Phase 2: Form — Opponent Player Field

### Overview
`Page1Form` grows an `opponent_user` field (parallel to the existing
`opponent_team`), required only when `mode == multiplayer`.

### Changes Required

#### 1. `baseball/forms.py` — imports + `Page1Form` changes

```python
from django import forms
from django.contrib.auth import get_user_model
from .models import Game, Team, Player, position_pools
```

Inside `Page1Form.__init__`, after the existing `opponent_team` field:

```python
    def __init__(self, *args, request_user=None, **kwargs):
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
        User = get_user_model()
        opp_qs = (User.objects.exclude(pk=request_user.pk)
                  if request_user else User.objects.all())
        self.fields["opponent_user"] = forms.ModelChoiceField(
            queryset=opp_qs, required=False,
            label="Opponent Player",
            empty_label="— select opponent —",
            widget=forms.Select(attrs={"class": "form-select"}),
        )
```

Extend `clean()`:

```python
    def clean(self):
        cleaned = super().clean()
        team = cleaned.get("team")
        opp  = cleaned.get("opponent_team")
        mode = cleaned.get("mode")
        if mode == Game.CPU_AUTO:
            if not opp:
                self.add_error("opponent_team", "Pick the CPU's team.")
            elif team and team.team_id == opp.team_id:
                self.add_error("opponent_team", "Opponent team must differ from your team.")
        if mode == Game.MULTIPLAYER and not cleaned.get("opponent_user"):
            self.add_error("opponent_user", "Pick an opponent to invite.")
        return cleaned
```

`SideRosterForm` (used as-is for Player 2's join page) needs no changes.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from baseball.forms import Page1Form; from django.contrib.auth import get_user_model; U=get_user_model(); u=U.objects.first(); f=Page1Form(request_user=u); assert 'opponent_user' in f.fields; assert u.pk not in f.fields['opponent_user'].queryset.values_list('pk', flat=True); print('ok')"`

#### Manual Verification:
- [ ] None yet — form isn't wired to views until Phase 3

**Implementation Note**: Pause here for manual confirmation before Phase 3.

---

## Phase 3: Views + URLs

### Overview
The core of the feature: `Page1View`'s multiplayer branch, three new views
(waiting page, Player 2's join page, cancel/decline), and relaxing
`GameListView`/`GameDetailView`/`RollView` to include `player2` — with turn
enforcement added to `RollView` and a multiplayer guard added to `ReplayView`.

### Changes Required

#### 1. `baseball/views.py` — imports

```python
from django.db.models import Q
```
(add alongside the existing imports at the top)

#### 2. `baseball/views.py` — pass `request_user` into every `Page1Form(...)` call

In `Page1View.get`, the `choose_team` branch, and the validation branch of `post`,
change every `Page1Form(...)` construction to include `request_user=request.user`:

```python
    def get(self, request):
        return render(request, self.template_name,
                      {"form": Page1Form(request_user=request.user), "team_chosen": False})

    def post(self, request):
        team_id = request.POST.get("team")
        team = Team.objects.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = Page1Form(data, team=team, request_user=request.user)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None})

        form = Page1Form(request.POST, team=team, request_user=request.user)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None})
```

#### 3. `baseball/views.py` — `Page1View.post`, multiplayer branch

Add alongside the existing `cd["mode"] == Game.CPU_AUTO` branch (same `cd`/`side`/
`own_team`/`own_roster` already computed above it):

```python
        if cd["mode"] == Game.MULTIPLAYER:
            opponent_user = cd["opponent_user"]
            if side == "away":
                away_team, home_team = own_team, None
                away_roster, home_roster = own_roster, []
                owner_side = "away"
            else:
                away_team, home_team = None, own_team
                away_roster, home_roster = [], own_roster
                owner_side = "home"

            game = Game.objects.create(
                owner=request.user, player2=opponent_user,
                away_name=away_team.name if away_team else "",
                home_name=home_team.name if home_team else "",
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                owner_side=owner_side,
                status=Game.WAITING,
                state={},
                away_roster=away_roster, home_roster=home_roster,
            )
            return redirect("baseball-waiting", pk=game.pk)
```

Place this **before** the existing `cd["mode"] == Game.CPU_AUTO` branch's `return`
(both are `if` blocks with early `return`, order between them doesn't matter) and
before the fall-through `click_all`/`auto_play` session-handoff code.

#### 4. `baseball/views.py` — three new views

Add after `Page2View`:

```python
class WaitingView(LoginRequiredMixin, View):
    template_name = "baseball/game_waiting.html"

    def get(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status != Game.WAITING:
            return redirect("baseball-detail", pk=game.pk)
        return render(request, self.template_name, {"game": game})


class Player2JoinView(LoginRequiredMixin, View):
    template_name = "baseball/game_join.html"

    def _game(self, request, pk):
        game = get_object_or_404(Game, pk=pk, player2=request.user)
        if game.status != Game.WAITING:
            return None, redirect("baseball-detail", pk=game.pk)
        return game, None

    def _team_qs(self, game):
        p1_team_id = game.away_team_id or game.home_team_id
        return Team.objects.exclude(pk=p1_team_id)

    def get(self, request, pk):
        game, bail = self._game(request, pk)
        if bail:
            return bail
        form = SideRosterForm(team_queryset=self._team_qs(game))
        return render(request, self.template_name,
                      {"form": form, "game": game, "team_chosen": False})

    def post(self, request, pk):
        game, bail = self._game(request, pk)
        if bail:
            return bail
        team_qs = self._team_qs(game)
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
                          {"form": form, "game": game, "team_chosen": team is not None})

        form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": team is not None})

        p2_team = form.cleaned_data["team"]
        p2_roster = form.roster_for()

        if game.owner_side == "away":
            game.home_team, game.home_roster, game.home_name = p2_team, p2_roster, p2_team.name
        else:
            game.away_team, game.away_roster, game.away_name = p2_team, p2_roster, p2_team.name

        gs = GameState(
            game.away_name, game.home_name, game.total_innings,
            away_lineup=lineup_from_roster(game.away_roster),
            home_lineup=lineup_from_roster(game.home_roster),
        )
        game.state = Game.state_to_dict(gs)
        game.status = Game.ACTIVE
        game.save()
        return redirect("baseball-detail", pk=game.pk)


class CancelWaitingView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(
            Game, Q(owner=request.user) | Q(player2=request.user),
            pk=pk, status=Game.WAITING,
        )
        game.delete()
        return redirect("baseball-list")
```

#### 5. `baseball/views.py` — relax `GameListView`, add per-side username labels

```python
class GameListView(LoginRequiredMixin, ListView):
    model         = Game
    template_name = "baseball/game_list.html"

    def get_queryset(self):
        u = self.request.user
        return (Game.objects.filter(Q(owner=u) | Q(player2=u))
                .select_related("owner", "player2"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for g in ctx["object_list"]:
            g.away_username, g.home_username = self._side_usernames(g)
        return ctx

    @staticmethod
    def _side_usernames(g):
        def label(side):
            if g.cpu_side == side:
                return "cpu"
            if g.mode == Game.MULTIPLAYER:
                controller = g.owner if g.owner_side == side else g.player2
                return controller.username if controller else "?"
            return g.owner.username
        return label("away"), label("home")
```

This replaces the old `{{ user.username }}` template hack (which only worked
because `owner` was always the viewer) with a correctly-computed label for either
viewer, any mode.

#### 6. `baseball/views.py` — relax `GameDetailView`, redirect waiting games, expose turn info

```python
class GameDetailView(LoginRequiredMixin, DetailView):
    model         = Game
    template_name = "baseball/game_detail.html"

    def get_queryset(self):
        u = self.request.user
        return Game.objects.filter(Q(owner=u) | Q(player2=u))

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.status == Game.WAITING:
            if request.user == self.object.owner:
                return redirect("baseball-waiting", pk=self.object.pk)
            return redirect("baseball-join", pk=self.object.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        gs = self.object.load_state()
        ctx["current_batter"] = gs.current_batter
        ctx["batting_team"]   = gs.batting_team
        if self.object.status == Game.FINISHED:
            away, home = gs.away_score, gs.home_score
            ctx["winner"] = gs.away_name if away > home else (
                gs.home_name if home > away else None)
        if self.object.mode == Game.MULTIPLAYER:
            if self.request.user == self.object.owner:
                ctx["my_side"] = self.object.owner_side
                opp = self.object.player2
            else:
                ctx["my_side"] = "home" if self.object.owner_side == "away" else "away"
                opp = self.object.owner
            ctx["opponent_username"] = opp.username if opp else ""
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
            ctx["current_batter_line"] = stats.get(cur_pid, "") if cur_pid else ""

        seen_extra = False
        annotated = []
        for play in self.object.play_log:
            is_extra = play.get("play_inning", 0) > self.object.total_innings
            annotated.append({**play, "starts_extra": is_extra and not seen_extra})
            seen_extra = seen_extra or is_extra
        ctx["play_log_reversed"] = list(reversed(annotated))
        return ctx
```

(Only the `get_queryset` filter, the new `get()` override, and the new
`if self.object.mode == Game.MULTIPLAYER:` block are additions — the rest of the
method is unchanged from its current form.)

#### 7. `baseball/views.py` — `RollView` turn enforcement

```python
class RollView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(
            Game, Q(owner=request.user) | Q(player2=request.user), pk=pk,
        )
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        gs = game.load_state()
        if game.mode == Game.MULTIPLAYER:
            my_side = (game.owner_side if request.user == game.owner
                       else ("home" if game.owner_side == "away" else "away"))
            my_half = "bottom" if my_side == "home" else "top"
            if gs.half != my_half:
                return JsonResponse({"error": "not your turn"}, status=403)
        play = _advance_game(gs)
        roster = game.away_roster if play["play_half"] == "top" else game.home_roster
        pid = _pid_for_name(roster, play["batter"])
        delta = _stat_delta(play["outcome"])
        if pid and delta:
            row = _apply_delta(game, pid, delta)
            play["stat_update"] = {"player_id": pid, "line": row.line}
            play["state"]["batter_line"] = row.line
        game.save_state(gs)
        game.play_log = game.play_log + [play]
        if play["game_over"]:
            game.status = Game.FINISHED
        game.save()
        return JsonResponse(play)
```

(Changed: the `get_object_or_404` filter now uses `Q(owner=...) | Q(player2=...)`;
`gs = game.load_state()` moved above the turn check so `gs.half` is available for
it; the multiplayer turn-check block is new. Everything after is unchanged.)

`SimulateView` is untouched — `auto_play` and `multiplayer` are mutually exclusive
`mode` values, so a multiplayer game never reaches `SimulateView`.

#### 8. `baseball/views.py` — `ReplayView` multiplayer guard

```python
class ReplayView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.mode == Game.MULTIPLAYER:
            return JsonResponse({"error": "replay not supported for multiplayer games"}, status=400)
        ...  # unchanged from here
```

#### 9. `baseball/urls.py` — three new routes

```python
from django.urls import path
from . import views

urlpatterns = [
    path("",                   views.GameListView.as_view(),   name="baseball-list"),
    path("new/",               views.Page1View.as_view(),      name="baseball-new"),
    path("roster/",            views.Page2View.as_view(),      name="baseball-roster"),
    path("<int:pk>/",          views.GameDetailView.as_view(), name="baseball-detail"),
    path("<int:pk>/roll/",     views.RollView.as_view(),       name="baseball-roll"),
    path("<int:pk>/simulate/", views.SimulateView.as_view(),   name="baseball-simulate"),
    path("<int:pk>/replay/",   views.ReplayView.as_view(),     name="baseball-replay"),
    path("<int:pk>/waiting/",  views.WaitingView.as_view(),        name="baseball-waiting"),
    path("<int:pk>/join/",     views.Player2JoinView.as_view(),    name="baseball-join"),
    path("<int:pk>/cancel/",   views.CancelWaitingView.as_view(),  name="baseball-cancel"),
]
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from baseball.views import GameListView; print('ok')"` exits 0

#### Manual Verification:
- [ ] None yet — templates still reference old field names / don't exist until Phase 4

**Implementation Note**: Pause here for manual confirmation before Phase 4.

---

## Phase 4: Templates

### Overview
Add the opponent-player picker to page 1, two new pages (waiting, join), and fix
the game list to show correct per-side usernames plus waiting-state rows.

### Changes Required

#### 1. `baseball/templates/baseball/game_setup.html` — opponent-user block + JS

Add alongside the existing `#opponent-team-wrap` block:

```html
    <div id="opponent-user-wrap" class="mb-3" style="max-width:400px;display:none">
        <label class="form-label fw-semibold">Opponent Player</label>
        {{ form.opponent_user }}
        {% if form.opponent_user.errors %}<div class="text-danger small">{{ form.opponent_user.errors }}</div>{% endif %}
    </div>
```

Update `syncModeUI()`:

```javascript
function syncModeUI() {
    const checked = document.querySelector('input[name="mode"]:checked');
    const mode = checked ? checked.value : '';
    document.getElementById('opponent-team-wrap').style.display = mode === 'cpu_auto' ? '' : 'none';
    document.getElementById('opponent-user-wrap').style.display = mode === 'multiplayer' ? '' : 'none';
    document.getElementById('next-btn').textContent = mode === 'cpu_auto' ? 'Play Ball!' : 'Next';
}
```

(Multiplayer keeps the "Next" label — it goes to a waiting page, not straight into
a game.)

#### 2. `baseball/templates/baseball/game_waiting.html` — new file

```html
{% extends "base.html" %}
{% block content %}
<h2>Waiting for Player 2</h2>
<p class="text-muted">
  Waiting for <strong>{{ game.player2.username }}</strong> to join —
  {{ game.away_name|default:"your team" }}{% if game.home_name %} vs {{ game.home_name }}{% endif %}
  · {{ game.total_innings }} innings.
</p>
<div class="spinner-border text-primary mb-3" role="status"></div>
<div>
  <form method="post" action="{% url 'baseball-cancel' game.pk %}" class="d-inline">
    {% csrf_token %}
    <button type="submit" class="btn btn-outline-danger">Cancel Invite</button>
  </form>
  <a href="{% url 'baseball-list' %}" class="btn btn-link">Back to games</a>
</div>
<script>
setInterval(() => location.reload(), 4000);
</script>
{% endblock %}
```

#### 3. `baseball/templates/baseball/game_join.html` — new file

Same structure as `game_roster.html`, different header/intro and a Decline button
instead of a plain Back link:

```html
{% extends "base.html" %}
{% block content %}
<h2>Join Game — Player 2</h2>
<p class="text-muted">
  {{ game.owner.username }} invited you —
  {{ game.away_name|default:"their team" }}{% if game.home_name %} vs {{ game.home_name }}{% endif %}
  · {{ game.total_innings }} innings. Pick your team and lineup, then Start.
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
        <button type="submit" class="btn btn-success">Start Game</button>
    </div>
</form>

<form method="post" action="{% url 'baseball-cancel' game.pk %}" class="mt-2">
    {% csrf_token %}
    <button type="submit" class="btn btn-link text-danger p-0">Decline invite</button>
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

#### 4. `baseball/templates/baseball/game_list.html` — waiting rows + correct usernames

```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Your Games</h2>
    <a href="{% url 'baseball-new' %}" class="btn btn-success">New Game</a>
</div>

{% if object_list %}
<table class="table table-hover align-middle">
    <thead class="table-dark">
        <tr>
            <th>Away</th>
            <th>Home</th>
            <th>Inn.</th>
            <th>Mode</th>
            <th>Status</th>
            <th>Score</th>
            <th></th>
        </tr>
    </thead>
    <tbody>
    {% for g in object_list %}
    <tr>
        <td>{{ g.away_name|default:"?" }} <small class="text-muted">({{ g.away_username }})</small></td>
        <td>{{ g.home_name|default:"?" }} <small class="text-muted">({{ g.home_username }})</small></td>
        <td>{{ g.total_innings }}</td>
        <td><small>{{ g.get_mode_display }}</small></td>
        <td>
            {% if g.status == "finished" %}
            <span class="badge bg-secondary">Finished</span>
            {% elif g.status == "waiting" %}
            <span class="badge bg-warning text-dark">Waiting</span>
            {% else %}
            <span class="badge bg-success">Active</span>
            {% endif %}
        </td>
        <td>{% if g.status != "waiting" %}{{ g.state.away_score }} – {{ g.state.home_score }}{% else %}—{% endif %}</td>
        <td class="d-flex align-items-center gap-1">
            {% if g.status == "waiting" %}
                {% if g.player2 == user %}
                <a href="{% url 'baseball-join' g.pk %}" class="btn btn-sm btn-success">Join</a>
                {% else %}
                <a href="{% url 'baseball-waiting' g.pk %}" class="btn btn-sm btn-outline-secondary">Waiting for you to join</a>
                {% endif %}
                <form method="post" action="{% url 'baseball-cancel' g.pk %}" class="d-inline">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-sm btn-outline-danger">
                        {% if g.owner == user %}Cancel{% else %}Decline{% endif %}
                    </button>
                </form>
            {% else %}
            <a href="{% url 'baseball-detail' g.pk %}" class="btn btn-sm btn-outline-primary">
                {% if g.status == "finished" %}View{% else %}Resume{% endif %}
            </a>
            {% endif %}
        </td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<p class="text-muted">No games yet. <a href="{% url 'baseball-new' %}">Start one!</a></p>
{% endif %}
{% endblock %}
```

Note the label on Player 2's row deliberately reads "Waiting for you to join" per
the ticket's literal wording, while the *owner's* row for the same game reads
"Waiting for `<player2>` to join" via `baseball-waiting` — same underlying game,
different link/label depending on which role `user` has.

#### 5. `baseball/templates/baseball/game_detail.html` — expose turn info, hide Replay for multiplayer

```html
const CPU_SIDE      = "{{ game.cpu_side|default:'' }}";
const MY_SIDE        = "{{ my_side|default:'' }}";
const OPPONENT_NAME  = "{{ opponent_username|default:'opponent' }}";
```

(added alongside the existing `CPU_SIDE` line)

Wrap the Replay block in the finished-game banner:

```html
        {% if game.mode != "multiplayer" %}
        <div class="mt-2 d-flex align-items-center gap-2">
          <button type="button" id="btn-replay" class="btn btn-outline-primary btn-sm">
            🔁 Replay
          </button>
          <label class="form-check-label small mb-0" for="chk-autoplay">
            <input type="checkbox" id="chk-autoplay" class="form-check-input me-1">
            Autoplay
          </label>
        </div>
        {% endif %}
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0
- [x] `python manage.py shell -c "from django.template.loader import get_template; get_template('baseball/game_waiting.html'); get_template('baseball/game_join.html'); get_template('baseball/game_list.html'); get_template('baseball/game_setup.html'); get_template('baseball/game_detail.html'); print('ok')"`

#### Manual Verification:
- [ ] Page 1: selecting "Multiplayer" reveals the Opponent Player dropdown (and
      hides Opponent Team); other modes hide it
- [ ] Submitting multiplayer setup redirects to the waiting page with correct
      team/innings summary and a working Cancel button
- [ ] Player 2's game list shows "Waiting" badge + "Waiting for you to join" link;
      clicking it lands on the join page with the correct exclusion of Player 1's
      team
- [ ] Player 1's game list shows "Waiting" badge + link to the waiting page +
      Cancel button
- [ ] Finished multiplayer game detail page shows no Replay button

**Implementation Note**: Pause here for manual confirmation before Phase 5.

---

## Phase 5: Gameplay Wiring (`game.js`)

### Overview
Add `initMultiplayer()`: enable the Roll button only during your own half, disable
+ poll otherwise. Skip the Replay UI in the live game-over path for multiplayer.

### Changes Required

#### 1. `baseball/static/baseball/js/game.js` — new mode function

Add alongside `initCpuAuto`/`initAutoPlay`:

```javascript
// --- Mode: multiplayer ------------------------------------------------------

function initMultiplayer() {
    const btn = document.getElementById('btn-roll');
    const half = document.getElementById('diamond').dataset.half;
    const myHalf = MY_SIDE === 'home' ? 'bottom' : 'top';

    if (half !== myHalf) {
        btn.disabled = true;
        btn.textContent = `Waiting for ${OPPONENT_NAME}…`;
        setInterval(() => location.reload(), 4000);
        return;
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

#### 2. `baseball/static/baseball/js/game.js` — wire it into the mode dispatch

```javascript
if (GAME_STATUS === 'active') {
    if (GAME_MODE === 'click_all')   initClickAll();
    if (GAME_MODE === 'cpu_auto')    initCpuAuto();
    if (GAME_MODE === 'auto_play')   initAutoPlay();
    if (GAME_MODE === 'multiplayer') initMultiplayer();
} else {
    wireReplayButton();
}
```

#### 3. `baseball/static/baseball/js/game.js` — skip Replay UI for multiplayer in `showGameOver`

```javascript
    div.appendChild(link);

    if (GAME_MODE !== 'multiplayer') {
        const replayWrap = document.createElement('div');
        replayWrap.className = 'mt-2 d-flex align-items-center gap-2';

        const replayBtn = document.createElement('button');
        replayBtn.type = 'button';
        replayBtn.id = 'btn-replay';
        replayBtn.className = 'btn btn-outline-primary btn-sm';
        replayBtn.textContent = '🔁 Replay';
        replayWrap.appendChild(replayBtn);

        const autoplayLabel = document.createElement('label');
        autoplayLabel.className = 'form-check-label small mb-0';
        autoplayLabel.htmlFor = 'chk-autoplay';
        const autoplayChk = document.createElement('input');
        autoplayChk.type = 'checkbox';
        autoplayChk.id = 'chk-autoplay';
        autoplayChk.className = 'form-check-input me-1';
        autoplayLabel.appendChild(autoplayChk);
        autoplayLabel.appendChild(document.createTextNode('Autoplay'));
        replayWrap.appendChild(autoplayLabel);

        div.appendChild(replayWrap);
    }

    const btnArea = document.getElementById('btn-area');
    btnArea.innerHTML = '';
    btnArea.appendChild(div);

    wireReplayButton();
    playSound('win');
```

(`wireReplayButton()` is already a no-op when `#btn-replay` doesn't exist, so it's
safe to leave the call unconditional.)

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0

#### Manual Verification:
- [ ] Two separate logins (e.g. normal window + incognito), Account A invites
      Account B, B joins: A's Roll button is enabled/disabled correctly per half,
      same for B, and each side's button flips at the right moment after a
      half-inning ends
- [ ] The waiting player's button reads "Waiting for `<name>`…" and the page
      auto-refreshes (no manual reload needed) once it becomes their turn
- [ ] Game finishes correctly with the right winner; no Replay button appears for
      either account
- [ ] A direct POST to `/baseball/<pk>/roll/` during the opponent's half (e.g. via
      browser devtools) returns 403 and does not change game state

---

## Testing Strategy

### Manual Testing Steps (end-to-end):
1. Log in as Account A. `/baseball/new/` → pick side/team/lineup, innings, mode =
   Multiplayer → pick Account B as opponent → Next.
2. Land on the waiting page; confirm the summary text and Cancel button.
3. In a separate (incognito) session, log in as Account B. Game list shows the
   invite as "Waiting" with a "Waiting for you to join" link.
4. Click it → join page excludes A's team from the dropdown → pick team → lineup
   appears pre-filled → drag-reorder → Start Game.
5. Both sessions land on `/baseball/<pk>/`. Confirm only the away-side account's
   Roll button is enabled; the home-side account sees "Waiting for `<name>`…".
6. Roll through a half-inning as the active account; confirm the other account's
   page auto-refreshes into control once the half flips (within ~4s of polling).
7. Play to completion; confirm correct winner banner on both sides, no Replay
   button on either.
8. Start a second multiplayer invite from A to B; from B's session, click Decline
   before joining → confirm it disappears from both game lists.
9. Start a third invite; from A's session, click Cancel before B joins → confirm
   removal from both lists.
10. Confirm `cpu_auto`/`click_all`/`auto_play` games (existing modes) are
    unaffected — create one of each, play through normally.

## Performance Considerations

Polling is a plain `location.reload()` every 4s while waiting — full page render,
no new endpoints, consistent with the existing app's zero-caching, always-hits-DB
style. Given this is a small hobby app with at most a couple of concurrent games,
this is not a concern; a JSON status-polling endpoint would reduce payload size but
isn't justified by current scale and would be the first departure from this
codebase's established "full reload" pattern.

## Migration Notes

`player2`/`owner_side` are both nullable with no default — existing rows get
`NULL`/`NULL`, which is correct (no game before this feature was multiplayer).
`on_delete=models.CASCADE` on `player2` matches the existing behavior of `owner`
(deleting an account deletes their games) rather than introducing a new
`SET_NULL` edge case nobody asked for.

## References

- This session's earlier plan: `thoughts/shared/plans/2026-07-20-two-page-game-setup.md`
  (the `Page1View`/`Page2View`/`SideRosterForm`/`cpu_side` foundation this builds on)
- `baseball/models.py:235-278` — `Game` model
- `baseball/forms.py` — `SideRosterForm`, `Page1Form`
- `baseball/views.py:161-297` — `Page1View`, `Page2View` (patterns being extended)
- `baseball/views.py:345-364` — `RollView`
- `baseball/static/baseball/js/game.js:213-244` — `initCpuAuto` (closest existing
  analog for turn-gated rolling)
- `accounts/models.py` — `Profile` (role field exists but unused by this plan, per
  your answer that all non-self users are invitable)
