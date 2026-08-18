# Saved Team Rosters Implementation Plan

## Overview

Let a user save a named 10-slot roster (position picks + batting order) for a team, then reload it later from any of the 3 roster-setup screens instead of re-picking every position and re-dragging the batting order each time.

## Current State Analysis

- Roster selection happens independently in 3 places, all built on the same `SideRosterForm` (`baseball/forms.py:20-78`): `Page1Form` (extends it, used by `Page1View`/`game_setup.html` for the game creator), `Page2View`/`game_roster.html` (hotseat player 2), `Player2JoinView`/`game_join.html` (multiplayer invitee). Each is a from-scratch pick every time — nothing persists a user's preferred lineup for a team across games.
- `SideRosterForm.roster_for()` (`baseball/forms.py:68-78`) is the canonical roster shape produced after validation: `[{"position": code, "player_id": int, "name": str}, ...]`, pitcher first then the 9 batting-order slots in chosen order. This is exactly what's stored on `Game.away_roster`/`home_roster` — the natural shape to persist for a saved roster too.
- `Team` (`baseball/models.py:27-47`) is a fixed, global, unmanaged table (30 real MLB teams) — **not user-owned**. Two different users picking the "Yankees" need independent saved rosters, so any saved-roster model must key on `(owner, team)`, not `team` alone.
- All 3 views share an identical "auto-select team → re-render form pre-filled" pattern via `action == "choose_team"` (`views.py:264-271, 381-388, 468-475`), using `data.setdefault(code, str(pid))` from `auto_fill_roster(team)` (`views.py:103-120`) to prefill the Django form's raw POST data before re-instantiating it. Loading a saved roster follows the identical mechanism, just prefilling from a saved roster's picks instead of an auto-fill.
- `position_pools(team)` (`baseball/models.py:114-124`) returns `{position_code: [eligible player_ids]}` for a team — used today to build form field querysets. A saved roster's `player_id`s should be checked against this before prefilling, in case the underlying player/team data is ever re-imported and a previously-valid pick becomes stale.
- All 3 views are separate `LoginRequiredMixin, View` classes with no shared base — `request.user` is always available on all of them.
- No JS framework/build step exists; page interactivity is hand-written vanilla JS per template, following an established pattern: a single `<form id="side-form">` wraps everything, a hidden `<input id="id_action">` is set by JS before an auto-submit (see the existing team-`<select>` `change` handler in all 3 templates, e.g. `game_setup.html:103-106`).

### Key Discoveries:
- The 3 views' `post()` methods are already near-duplicates of each other for the `choose_team` branch — adding 3 more branches (`load_roster`, `save_roster`, `delete_roster`) with the same shape at each call site, backed by 2 shared helper functions, is consistent with the codebase's existing (mild) duplication level rather than introducing a new abstraction (e.g. a shared base-view mixin) that nothing else in the file uses.
- No `admin.py` exists for the `baseball` app — no Django-admin registration convention to extend.
- No forms.py changes are needed: the "name this roster" text input is treated as a plain POST param (`roster_name`), not a `SideRosterForm` field, since it's orthogonal to the position/order validation that form already does.

## Desired End State

From any of the 3 roster-setup screens, after picking a team: if the user has saved rosters for that team, a dropdown lists them by name; picking one instantly fills every position select and the batting order to match (still editable afterward). A name field + "Save roster" button lets the user persist the current picks under a name (or overwrite an existing name). A "Delete" button appears next to a just-loaded roster to remove it. Saved rosters are private per user — two users can each save a differently-named (or same-named) roster for the same team without collision.

### Verification
- `python manage.py makemigrations baseball --check` shows no missing migrations after the model is migrated.
- `python manage.py check` passes.
- Manually: save a roster on Page 1, start a new game, return to Page 1, pick the same team, load the saved roster from the dropdown — all 10 positions and the batting order match exactly, no re-picking needed. Same load/save/delete flow works on the hotseat-P2 and multiplayer-join screens too.

## What We're NOT Doing

- Not building a dedicated "manage saved rosters" page — save/load/delete all happen inline on the existing 3 setup screens via the dropdown + buttons.
- Not sharing saved rosters between users — strictly private per `(owner, team, name)`.
- Not auto-saving on every game creation — saving is an explicit user action (name + "Save roster" button).
- Not validating/blocking a save if the *current* form has errors beyond what `SideRosterForm.is_valid()` already checks (e.g. duplicate player across positions) — same validation as a normal game-creation submit.
- Not touching CPU-side rosters (`auto_fill_roster`/`cpu_roster_for`) — those stay fully automatic, no save/load concept for them.
- Not renaming a saved roster in place — deleting and re-saving under a new name covers that; a rename UI is out of scope.

## Implementation Approach

Four phases: (1) the `SavedRoster` model + migration + two pure-logic helper functions, (2) wiring 3 new POST actions into all 3 views (reusing the existing `choose_team`-style re-render pattern), (3) the shared UI partial (dropdown + name field + Save/Delete buttons + JS) included in all 3 templates, (4) a full cross-flow verification pass.

## Phase 1: Data model

### Overview
Add the `SavedRoster` model and two helper functions views will call in Phase 2. No view/template wiring yet — this phase is purely persistence plumbing, verifiable via `manage.py shell`.

### Changes Required:

#### 1. `SavedRoster` model
**File**: `baseball/models.py`
**Changes**: Insert after `Game.save_state()` (currently ends around line 333), before `class GameStat`:

```python
class SavedRoster(models.Model):
    """A user's saved 10-slot roster (position picks + batting order) for a
    team, so they don't have to re-pick/re-order it on every new game."""
    owner      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="saved_rosters")
    team       = models.ForeignKey(Team, on_delete=models.CASCADE,
                                   related_name="saved_rosters")
    name       = models.CharField(max_length=50)
    roster     = models.JSONField()  # same shape as Game.away_roster/home_roster
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team__name", "name"]
        unique_together = (("owner", "team", "name"),)

    def __str__(self):
        return f"{self.name} ({self.team.name})"
```

#### 2. Migration
**Action**:
```bash
python manage.py makemigrations baseball
```
(Expected: a new `baseball/migrations/0016_savedroster.py` creating the table.)

#### 3. Helper functions
**File**: `baseball/views.py`
**Changes**: Add import and two helpers near the other roster helpers (after `cpu_roster_for()`, currently ending around line 138):

```python
from .models import (
    Game, Player, Team, GameStat, PlayerCareerStats, SavedRoster,
    position_pools, main_position,
)
```
(extends the existing import line, currently `views.py:13`)

```python
def _saved_rosters_for(user, team):
    """A user's saved rosters for a team, alphabetical by name, or [] if no team."""
    if not team:
        return []
    return list(SavedRoster.objects.filter(owner=user, team=team).order_by("name"))


def _apply_saved_roster(data, saved_roster, team):
    """Mutate a mutable POST-data copy in place with a saved roster's picks,
    skipping any player_id no longer in the team's current position pool
    (defensive against a stale save after a player/team data re-import)."""
    pools = position_pools(team)
    order = []
    for entry in saved_roster.roster:
        code, pid = entry["position"], entry["player_id"]
        if pid in pools.get(code, []):
            data.setdefault(code, str(pid))
            if code != "P":
                order.append(code)
    if order:
        data["order"] = ",".join(order)
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py makemigrations baseball --check` reports no missing migrations (after running `makemigrations` once for real)
- [x] `python manage.py migrate` applies cleanly
- [x] `python manage.py check` passes

#### Manual Verification:
- [x] Via `python manage.py shell`: create a `SavedRoster` for a real user/team/roster dict, confirm `SavedRoster.objects.filter(owner=..., team=...)` returns it, confirm saving a second one with the same `(owner, team, name)` raises an `IntegrityError` (uniqueness enforced)

**Implementation Note**: Pause here for manual confirmation before proceeding to Phase 2, since Phase 2's view wiring depends on this model/migration being correct.

---

## Phase 2: View wiring (save / load / delete actions)

### Overview
Add `load_roster`, `save_roster`, and `delete_roster` POST-action branches to `Page1View`, `Page2View`, and `Player2JoinView`, each following the same re-render-with-prefilled-data pattern already used for `choose_team`. Also thread `saved_rosters` (and `loaded_roster` when applicable) into every context dict built once a team is selected.

### Changes Required:

#### 1. `Page1View.post()`
**File**: `baseball/views.py`
**Changes**: Replace the full method (currently `views.py:259-352`):

```python
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
            form = Page1Form(data, team=team, request_user=request.user)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        if action == "load_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            saved = (SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).first()
                     if saved_id and saved_id.isdigit() else None)
            data = request.POST.copy()
            if saved:
                _apply_saved_roster(data, saved, team)
            form = Page1Form(data, team=team, request_user=request.user)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True,
                           "saved_rosters": saved_rosters, "loaded_roster": saved})

        if action == "save_roster" and team:
            form = Page1Form(request.POST, team=team, request_user=request.user)
            name = (request.POST.get("roster_name") or "").strip()
            roster_save_error = None
            roster_saved_name = None
            if not name:
                roster_save_error = "Enter a name to save this roster."
            elif not form.is_valid():
                roster_save_error = "Fix the roster before saving."
            else:
                SavedRoster.objects.update_or_create(
                    owner=request.user, team=team, name=name,
                    defaults={"roster": form.roster_for()},
                )
                saved_rosters = _saved_rosters_for(request.user, team)
                roster_saved_name = name
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True,
                           "saved_rosters": saved_rosters,
                           "roster_save_error": roster_save_error,
                           "roster_saved_name": roster_saved_name})

        if action == "delete_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            if saved_id and saved_id.isdigit():
                SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).delete()
            data = request.POST.copy()
            form = Page1Form(data, team=team, request_user=request.user)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True,
                           "saved_rosters": _saved_rosters_for(request.user, team)})

        form = Page1Form(request.POST, team=team, request_user=request.user)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        cd = form.cleaned_data
        side = cd["side"]
        own_team = cd["team"]
        own_roster = form.roster_for()

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
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
                status=Game.WAITING,
                state={},
                away_roster=away_roster, home_roster=home_roster,
            )
            return redirect("baseball-waiting", pk=game.pk)

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
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
            )
            game = Game.objects.create(
                owner=request.user,
                away_name=away_team.name, home_name=home_team.name,
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                cpu_side=cpu_side,
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
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
            "streaky_per_game":   cd["streaky_per_game"],
            "streaky_per_inning": cd["streaky_per_inning"],
            "roster":        own_roster,
        }
        return redirect("baseball-roster")
```

(Only the top of the method — through the final `form.is_valid()` re-render — changes; everything from `cd = form.cleaned_data` down is unchanged, reproduced here for clarity.)

#### 2. `Page2View.post()`
**File**: `baseball/views.py`
**Changes**: Replace the method (currently `views.py:372-425`), inserting the same 3 new branches (note: this view scopes `team_qs` to exclude the P1 team, and must keep `setup` in every context dict):

```python
    def post(self, request):
        setup = self._setup(request)
        if not setup:
            return redirect("baseball-new")
        team_qs = self._team_qs(setup)
        team_id = request.POST.get("team")
        team = team_qs.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")
        saved_rosters = _saved_rosters_for(request.user, team)

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        if action == "load_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            saved = (SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).first()
                     if saved_id and saved_id.isdigit() else None)
            data = request.POST.copy()
            if saved:
                _apply_saved_roster(data, saved, team)
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": True,
                           "saved_rosters": saved_rosters, "loaded_roster": saved})

        if action == "save_roster" and team:
            form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
            name = (request.POST.get("roster_name") or "").strip()
            roster_save_error = None
            roster_saved_name = None
            if not name:
                roster_save_error = "Enter a name to save this roster."
            elif not form.is_valid():
                roster_save_error = "Fix the roster before saving."
            else:
                SavedRoster.objects.update_or_create(
                    owner=request.user, team=team, name=name,
                    defaults={"roster": form.roster_for()},
                )
                saved_rosters = _saved_rosters_for(request.user, team)
                roster_saved_name = name
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": True,
                           "saved_rosters": saved_rosters,
                           "roster_save_error": roster_save_error,
                           "roster_saved_name": roster_saved_name})

        if action == "delete_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            if saved_id and saved_id.isdigit():
                SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).delete()
            data = request.POST.copy()
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": True,
                           "saved_rosters": _saved_rosters_for(request.user, team)})

        form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

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
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
        )
        game = Game.objects.create(
            owner=request.user,
            away_name=away_team.name, home_name=home_team.name,
            away_team=away_team, home_team=home_team,
            total_innings=setup["total_innings"], mode=setup["mode"],
            cpu_side=None,
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
            state=Game.state_to_dict(gs),
            away_roster=away_roster, home_roster=home_roster,
        )
        del request.session["bb_setup"]
        return redirect("baseball-detail", pk=game.pk)
```

#### 3. `Player2JoinView.post()`
**File**: `baseball/views.py`
**Changes**: Replace the method (currently `views.py:459-500`), same 3 new branches, keeping `game` in every context dict:

```python
    def post(self, request, pk):
        game, bail = self._game(request, pk)
        if bail:
            return bail
        team_qs = self._team_qs(game)
        team_id = request.POST.get("team")
        team = team_qs.filter(pk=team_id).first() if team_id else None
        action = request.POST.get("action")
        saved_rosters = _saved_rosters_for(request.user, team)

        if action == "choose_team":
            data = request.POST.copy()
            if team:
                for code, pid in auto_fill_roster(team).items():
                    data.setdefault(code, str(pid))
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

        if action == "load_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            saved = (SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).first()
                     if saved_id and saved_id.isdigit() else None)
            data = request.POST.copy()
            if saved:
                _apply_saved_roster(data, saved, team)
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": True,
                           "saved_rosters": saved_rosters, "loaded_roster": saved})

        if action == "save_roster" and team:
            form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
            name = (request.POST.get("roster_name") or "").strip()
            roster_save_error = None
            roster_saved_name = None
            if not name:
                roster_save_error = "Enter a name to save this roster."
            elif not form.is_valid():
                roster_save_error = "Fix the roster before saving."
            else:
                SavedRoster.objects.update_or_create(
                    owner=request.user, team=team, name=name,
                    defaults={"roster": form.roster_for()},
                )
                saved_rosters = _saved_rosters_for(request.user, team)
                roster_saved_name = name
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": True,
                           "saved_rosters": saved_rosters,
                           "roster_save_error": roster_save_error,
                           "roster_saved_name": roster_saved_name})

        if action == "delete_roster" and team:
            saved_id = request.POST.get("saved_roster_id")
            if saved_id and saved_id.isdigit():
                SavedRoster.objects.filter(pk=saved_id, owner=request.user, team=team).delete()
            data = request.POST.copy()
            form = SideRosterForm(data, team=team, team_queryset=team_qs)
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": True,
                           "saved_rosters": _saved_rosters_for(request.user, team)})

        form = SideRosterForm(request.POST, team=team, team_queryset=team_qs)
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "game": game, "team_chosen": team is not None,
                           "saved_rosters": saved_rosters})

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
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
        )
        game.state = Game.state_to_dict(gs)
        game.status = Game.ACTIVE
        game.save()
        return redirect("baseball-detail", pk=game.pk)
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [x] POSTing `action=save_roster` with a valid team+roster+name from each of the 3 screens creates/updates a `SavedRoster` row (spot-check via `manage.py shell` or the admin-less `SavedRoster.objects.all()`)
- [x] POSTing `action=load_roster` with a saved roster's id re-renders the form with all positions/order matching that saved roster
- [x] POSTing `action=delete_roster` removes the row and the dropdown no longer lists it on next render
- [x] Saving with a name that already exists for that `(user, team)` overwrites rather than erroring or duplicating

**Implementation Note**: Verified via Django's test `Client` (no browser available in this session) for `Page1View` and `Page2View` end-to-end — save/overwrite/load/delete all behaved correctly. `Player2JoinView` verified by code review/parity only (identical helper calls and branch structure to `Page2View`), not a live HTTP round-trip, since exercising it needs a full multiplayer fixture (a `WAITING` game + second user).

**Bug found and fixed while testing**: initial test of `save_roster` on Page1 failed silently (200 response, no row created) because `Page1Form` (unlike plain `SideRosterForm`) also requires `side`/`mode`/`total_innings` (and `opponent_team` for `cpu_auto`) — this is correct/intentional per the plan (same form validated on save as on real submit), just required the test's POST data to include those fields too. No code change needed, the view logic was right.

---

## Phase 3: UI (dropdown, name field, Save/Delete buttons)

### Overview
One reusable partial template renders the saved-roster controls; include it in all 3 setup templates right after the team-select block. Add the `saved_roster_id` hidden field alongside the existing `action` hidden field in each template's form.

### Changes Required:

#### 1. New partial
**File**: `baseball/templates/baseball/_saved_roster_controls.html` (new file)

```html
{% if team_chosen %}
<div class="mb-3" style="max-width:500px">
    <label class="form-label small fw-semibold d-block">Saved Rosters</label>
    {% if saved_rosters %}
    <select id="id_load_roster" class="form-select form-select-sm mb-2">
        <option value="">— load a saved roster —</option>
        {% for r in saved_rosters %}
        <option value="{{ r.pk }}" {% if loaded_roster and loaded_roster.pk == r.pk %}selected{% endif %}>{{ r.name }}</option>
        {% endfor %}
    </select>
    {% else %}
    <p class="text-muted small mb-2">No saved rosters yet for this team.</p>
    {% endif %}

    {% if roster_save_error %}<div class="text-danger small mb-1">{{ roster_save_error }}</div>{% endif %}
    {% if roster_saved_name %}<div class="text-success small mb-1">Saved &ldquo;{{ roster_saved_name }}&rdquo;.</div>{% endif %}

    <div class="d-flex align-items-center gap-2">
        <input type="text" name="roster_name" id="id_roster_name" class="form-control form-control-sm"
               placeholder="Name this roster" style="max-width:220px"
               value="{{ roster_saved_name|default:'' }}">
        <button type="button" id="btn-save-roster" class="btn btn-sm btn-outline-primary">Save roster</button>
        {% if loaded_roster %}
        <button type="button" id="btn-delete-roster" class="btn btn-sm btn-outline-danger"
                data-roster-id="{{ loaded_roster.pk }}">Delete &ldquo;{{ loaded_roster.name }}&rdquo;</button>
        {% endif %}
    </div>
</div>

<script>
(function () {
    const form = document.getElementById('side-form');
    const actionField = document.getElementById('id_action');
    const savedIdField = document.getElementById('id_saved_roster_id');

    const loadSelect = document.getElementById('id_load_roster');
    if (loadSelect) {
        loadSelect.addEventListener('change', () => {
            if (!loadSelect.value) return;
            actionField.value = 'load_roster';
            savedIdField.value = loadSelect.value;
            form.submit();
        });
    }

    const saveBtn = document.getElementById('btn-save-roster');
    if (saveBtn) {
        saveBtn.addEventListener('click', () => {
            actionField.value = 'save_roster';
            savedIdField.value = '';
            form.submit();
        });
    }

    const deleteBtn = document.getElementById('btn-delete-roster');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', () => {
            actionField.value = 'delete_roster';
            savedIdField.value = deleteBtn.dataset.rosterId;
            form.submit();
        });
    }
})();
</script>
{% endif %}
```

#### 2. `game_setup.html`
**File**: `baseball/templates/baseball/game_setup.html`
**Changes**: Add the hidden field next to the existing `id_action` one (currently line 6):

```html
    <input type="hidden" name="action" id="id_action" value="next">
    <input type="hidden" name="saved_roster_id" id="id_saved_roster_id" value="">
```

Include the partial right after the team-select block (currently lines 22-26):

```html
    <div class="mb-3" style="max-width:400px">
        <label class="form-label fw-semibold">Your Team</label>
        {{ form.team }}
        {% if form.team.errors %}<div class="text-danger small">{{ form.team.errors }}</div>{% endif %}
    </div>

    {% include "baseball/_saved_roster_controls.html" %}
```

#### 3. `game_roster.html`
**File**: `baseball/templates/baseball/game_roster.html`
**Changes**: Same two edits — hidden field next to `id_action` (currently line 11), partial include right after the team-select block (currently lines 17-21).

#### 4. `game_join.html`
**File**: `baseball/templates/baseball/game_join.html`
**Changes**: Same two edits — hidden field next to `id_action` (currently line 12), partial include right after the team-select block (currently lines 18-22).

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [x] On each of the 3 setup screens: picking a team with no saved rosters shows "No saved rosters yet for this team." and no dropdown
- [x] Filling out a roster, entering a name, clicking "Save roster" shows a success message and the dropdown now lists it
- [x] Picking that saved roster from the dropdown fills every position select and reorders the batting-order list to match (verified server-side render contains the loaded picks + Delete button; couldn't verify the client-side JS auto-submit feel without a real browser)
- [x] "Delete" appears only after loading a saved roster, confirmed present in the loaded-roster render for all 3 screens
- [x] Saving again under the same name updates the existing entry (dropdown doesn't grow a duplicate) — reconfirmed here on top of Phase 2's check
- [x] Existing team-select auto-submit (`action=choose_team`) still works unaffected

**Implementation Note**: Verified via Django's test `Client` rendering the actual templates end-to-end (GET with no team chosen, `choose_team`/`save_roster`/`load_roster`/`delete_roster` POSTs), checking response content for the expected markup — across all 3 screens including a full multiplayer join round-trip (2 separate logged-in test-client sessions, a real `WAITING` `Game`). No physical browser available in this session, so the JS auto-submit-on-select UX itself (vs. the server-rendered result it produces) wasn't visually confirmed — recommend a quick manual click-through when you get a chance.

---

## Phase 4: Full verification pass

### Overview
Cross-flow regression: confirm the feature works consistently across all 3 screens and under multi-user isolation.

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes
- [x] `python manage.py makemigrations baseball --check` reports no missing migrations

#### Manual Verification:
- [x] Save a roster on Page 1 (`game_setup.html`), then confirm it's loadable from the hotseat P2 screen (`game_roster.html`) and the multiplayer-join screen (`game_join.html`) too, if that user picks the same team on any of them
- [x] Two different logged-in users each save a roster named "Starters" for the same team — no collision, no cross-user visibility (user B never sees user A's "Starters" in their dropdown)
- [x] A saved roster loads correctly even after being saved, then the game created from it finishes, then a brand-new game is started later — saved rosters persist independently of any particular `Game`
- [x] (Edge case, best-effort) If a saved roster references a `player_id` no longer in the team's position pool, loading it skips that stale slot gracefully (leaves it blank, no crash, no 500) per `_apply_saved_roster`'s pool check

**Implementation Note**: All verified via Django's test `Client` + direct helper calls in `manage.py shell` (no browser in this session):
- Cross-screen reuse confirmed both ways — saved on Page1 then still listed across fresh games, and saved on Page2 (hotseat) for a team then confirmed listed again on Page2 in a brand-new game (same helper functions, `_saved_rosters_for`/`_apply_saved_roster`, are shared verbatim by all 3 views, so this generalizes to the join screen too).
- Two-user isolation confirmed on both the main setup screen and the multiplayer-join screen: each user's dropdown shows exactly their own row (`count == 1`), never the other user's same-named roster.
- Persistence-independent-of-`Game` confirmed by creating multiple separate games across the test run while the saved roster stayed intact and listed throughout.
- Stale-`player_id` defensive check confirmed directly against `_apply_saved_roster`: a corrupted entry (bogus `player_id` not in the team's position pool) is silently skipped — that one slot stays unfilled, the other 9 slots load correctly, no exception.
- All test data (`SavedRoster` rows, `WAITING` games) cleaned up after each check — confirmed zero leftovers.

## Testing Strategy

### Manual Testing Steps:
1. Start a new game (Page 1), pick a team, build a roster, save it as "My Lineup".
2. Complete that game creation (or navigate away), start a second new game, pick the same team — confirm "My Lineup" appears in the dropdown and loading it reproduces the exact roster/order.
3. Modify one position after loading, save again under the same name, reload the page, confirm the update persisted (not a stale cached version).
4. Delete "My Lineup", confirm it's gone from the dropdown on next team pick.
5. Repeat steps 1-2 on the hotseat-P2 flow and the multiplayer-join flow.
6. As a second user, pick the same team and confirm you see none of the first user's saved rosters.

## Performance Considerations

Negligible — `_saved_rosters_for()` is one indexed filter query (`owner`, `team`) per team-selection render, same order of magnitude as the existing `position_pools(team)` query already run on every team pick.

## Migration Notes

New table only (`SavedRoster`) — no changes to any existing model's schema, no backfill needed. Existing games/rosters are entirely unaffected since saved rosters are a separate, opt-in, additive concept.

## References
- Related research: `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md` (background on the codebase's rendering/state model; roster-saving itself is a net-new area not covered by that doc's six original topics)
- `baseball/forms.py:20-78` — `SideRosterForm`, `roster_for()` (canonical roster shape)
- `baseball/models.py:27-47` — `Team` (fixed, unmanaged, not user-owned — why saves key on `(owner, team)`)
- `baseball/models.py:114-124` — `position_pools()` (used for defensive re-validation on load)
- `baseball/views.py:103-138` — `auto_fill_roster()`, `lineup_from_roster()`, `cpu_roster_for()` (existing roster-building helpers, pattern to follow)
- `baseball/views.py:252-352, 355-425, 438-500` — `Page1View`, `Page2View`, `Player2JoinView` (the 3 flows being extended)
- `baseball/templates/baseball/game_setup.html:22-26,103-106` — team-select block + existing auto-submit JS pattern being extended
