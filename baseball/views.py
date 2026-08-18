import json
import random

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, DetailView

from .forms import Page1Form, SideRosterForm, POSITIONS, BATTING_POSITIONS, BULLPEN_MAX
from .models import (
    Game, Player, Team, GameStat, PlayerCareerStats, SavedRoster,
    position_pools, main_position, players_for_team,
)
from .engine import (
    GameState, resolve_dice_roll, apply_in_play, stat_based_weights,
    apply_weather, apply_fatigue,
)
from .params import (
    STAT_BASED_MIN_AB, COMMENTARY_LINES, WEATHER_DEFAULT,
    PITCHER_STAMINA_MAX, STAMINA_DRAIN_PER_BATTER, PITCHER_CHANGE_THRESHOLD,
)
from .stadiums import stadium_context

_HIT_STAT   = {"single": "singles", "double": "doubles",
               "triple": "triples", "home_run": "home_runs"}
_OTHER_STAT = {"strikeout": "strikeouts", "walk": "walks", "sacrifice": "sac_hits"}
_AB_OUTCOMES = {"single", "double", "triple", "home_run",
                "strikeout", "groundout", "flyout", "single_error"}


def _stat_delta(outcome):
    delta = {}
    if outcome in _AB_OUTCOMES:
        delta["ab"] = 1
    col = _HIT_STAT.get(outcome) or _OTHER_STAT.get(outcome)
    if col:
        delta[col] = 1
    return delta


@login_required
def career_stats_api(request, player_id):
    row = PlayerCareerStats.objects.filter(player_id=player_id).order_by("-season").first()
    if not row:
        return JsonResponse({"found": False})
    return JsonResponse({
        "found": True,
        "season": row.season,
        "at_bats": row.at_bats,
        "hits": row.hits,
        "runs": row.runs,
        "rbis": row.rbis,
        "doubles": row.doubles,
        "triples": row.triples,
        "home_runs": row.home_runs,
        "walks": row.walks,
        "strikeouts": row.strikeouts,
        "stolen_bases": row.stolen_bases,
    })


def _pid_for_name(roster, name):
    for e in roster:
        if e.get("name") == name:
            return e.get("player_id")
    return None


def _career_weights_for(player_id, streaky=False, weather=None, stamina=None):
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
    weights = apply_weather(weights, weather or WEATHER_DEFAULT)
    weights = apply_fatigue(weights, PITCHER_STAMINA_MAX if stamina is None else stamina)
    return weights


def _apply_delta(game, player_id, delta):
    obj, _ = GameStat.objects.get_or_create(game=game, player_id=player_id)
    for col, n in delta.items():
        setattr(obj, col, getattr(obj, col) + n)
    obj.save()
    return obj


def _line_cells(line, num_cols, current_inning, is_active_half, runs_this_half):
    """Per-inning board cells: completed innings from `line`, the live partial
    total for the inning in progress, blank for innings not yet reached."""
    cells = []
    for n in range(1, num_cols + 1):
        if n <= len(line):
            cells.append({"n": n, "value": line[n - 1]})
        elif n == current_inning and is_active_half:
            cells.append({"n": n, "value": runs_this_half})
        else:
            cells.append({"n": n, "value": ""})
    return cells




def auto_fill_roster(team):
    """Pick one eligible, distinct player per position for the away (CPU) side,
    preferring each player's main position so the lineup is realistic.
    Returns {position_code: player_id}."""
    pools = position_pools(team)
    primary = {p.player_id: main_position(p)
               for p in players_for_team(team)}
    used, out = set(), {}
    for code, _ in POSITIONS:
        cands = pools.get(code, [])
        pick = next((pid for pid in cands
                     if pid not in used and primary.get(pid) == code), None)
        if pick is None:
            pick = next((pid for pid in cands if pid not in used), None)
        if pick is not None:
            out[code] = pick
            used.add(pick)
    return out


def lineup_from_roster(roster):
    """9-name batting order from a 10-slot roster, preserving list order (pitcher excluded)."""
    return [r["name"] for r in roster if r["position"] != "P"]


def pitcher_from_roster(roster):
    """The starting pitcher's {player_id, name} from a 10-slot roster, or None."""
    entry = next((r for r in roster if r["position"] == "P"), None)
    return {"player_id": entry["player_id"], "name": entry["name"]} if entry else None


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


def auto_fill_bullpen(team, exclude_player_id, n=BULLPEN_MAX):
    """Up to n distinct eligible relievers for a CPU-controlled team's bullpen,
    excluding whichever player was auto-picked as the starter."""
    pool = position_pools(team).get("P", [])
    picks = [pid for pid in pool if pid != exclude_player_id][:n]
    players = {p.player_id: p for p in Player.objects.filter(player_id__in=picks)}
    return [{"player_id": pid, "name": str(players[pid])} for pid in picks if pid in players]


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


def _state_snapshot(gs: GameState) -> dict:
    return {
        "inning":         gs.inning,
        "half":           gs.half,
        "outs":           gs.outs,
        "balls":          gs.balls,
        "strikes":        gs.strikes,
        "bases":          gs.bases,
        "away_score":     gs.away_score,
        "home_score":     gs.home_score,
        "away_line":      gs.away_line,
        "home_line":      gs.home_line,
        "runs_this_half": gs.runs_this_half,
        "away_hits":      gs.away_hits,
        "home_hits":      gs.home_hits,
        "batting_team":   gs.batting_team,
        "current_batter": gs.current_batter,
        "game_over":      gs.game_over,
        "away_name":      gs.away_name,
        "home_name":      gs.home_name,
        "away_pitcher": {"name": gs.away_pitching["current"]["name"] if gs.away_pitching["current"] else None,
                         "stamina": gs.away_pitching["stamina"]},
        "home_pitcher": {"name": gs.home_pitching["current"]["name"] if gs.home_pitching["current"] else None,
                         "stamina": gs.home_pitching["stamina"]},
    }


def _advance_game(gs: GameState, roster) -> dict:
    # Capture before any mutation so play-log labels show the inning/half of the play.
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

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    # Walk-off: bottom half of final inning, home leads after the at-bat
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.close_half()
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg, commentary=commentary,
                    method=method, play_half=play_half, play_inning=play_inning,
                    batter=batter, half_over=True, game_over=True,
                    streaky=streaky, moves=gs.last_moves,
                    pitching_change_available=pitching_change_available,
                    state=_state_snapshot(gs))

    if gs.outs >= 3:
        half_over = True
        gs.close_half()
        if gs.half == "top":
            # Home already winning at end of final top half — skip bottom
            if is_final and gs.home_score > gs.away_score:
                gs.game_over = True
            else:
                gs.half = "bottom"
                gs.reset_half()
                gs.reroll_inning_streaky()
        else:  # bottom
            if is_final and gs.home_score != gs.away_score:
                gs.game_over = True
            else:
                gs.inning += 1
                gs.half = "top"
                gs.reset_half()
                gs.reroll_inning_streaky()

    return dict(d1=d1, d2=d2, outcome=outcome, message=msg, commentary=commentary,
                method=method, play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=half_over, game_over=gs.game_over,
                streaky=streaky, moves=gs.last_moves,
                pitching_change_available=pitching_change_available,
                state=_state_snapshot(gs))


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


class Page1View(LoginRequiredMixin, View):
    template_name = "baseball/game_setup.html"

    def get(self, request):
        return render(request, self.template_name,
                      {"form": Page1Form(request_user=request.user), "team_chosen": False})

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
        own_bullpen = form.bullpen_for()

        if cd["mode"] == Game.MULTIPLAYER:
            opponent_user = cd["opponent_user"]
            if side == "away":
                away_team, home_team = own_team, None
                away_roster, home_roster = own_roster, []
                away_bullpen, home_bullpen = own_bullpen, []
                owner_side = "away"
            else:
                away_team, home_team = None, own_team
                away_roster, home_roster = [], own_roster
                away_bullpen, home_bullpen = [], own_bullpen
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
                weather_temperature_f=cd["weather_temperature_f"],
                weather_wind=cd["weather_wind"],
                weather_sky=cd["weather_sky"],
                away_bullpen=away_bullpen, home_bullpen=home_bullpen,
                status=Game.WAITING,
                state={},
                away_roster=away_roster, home_roster=home_roster,
            )
            return redirect("baseball-waiting", pk=game.pk)

        if cd["mode"] == Game.CPU_AUTO:
            opponent_team = cd["opponent_team"]
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
            game = Game.objects.create(
                owner=request.user,
                away_name=away_team.name, home_name=home_team.name,
                away_team=away_team, home_team=home_team,
                total_innings=cd["total_innings"], mode=cd["mode"],
                cpu_side=cpu_side,
                streaky_per_game=cd["streaky_per_game"],
                streaky_per_inning=cd["streaky_per_inning"],
                weather_temperature_f=cd["weather_temperature_f"],
                weather_wind=cd["weather_wind"],
                weather_sky=cd["weather_sky"],
                away_bullpen=away_bullpen, home_bullpen=home_bullpen,
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
            "weather_temperature_f": cd["weather_temperature_f"],
            "weather_wind":          cd["weather_wind"],
            "weather_sky":           cd["weather_sky"],
            "roster":        own_roster,
            "bullpen":       own_bullpen,
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
        p2_bullpen = form.bullpen_for()
        p1_team = get_object_or_404(Team, pk=setup["team_id"])

        if setup["side"] == "away":
            away_team, home_team = p1_team, p2_team
            away_roster, home_roster = setup["roster"], p2_roster
            away_bullpen, home_bullpen = setup["bullpen"], p2_bullpen
        else:
            away_team, home_team = p2_team, p1_team
            away_roster, home_roster = p2_roster, setup["roster"]
            away_bullpen, home_bullpen = p2_bullpen, setup["bullpen"]

        gs = GameState(
            away_team.name, home_team.name, setup["total_innings"],
            away_lineup=lineup_from_roster(away_roster),
            home_lineup=lineup_from_roster(home_roster),
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
            weather={"temperature_f": setup["weather_temperature_f"],
                     "wind": setup["weather_wind"], "sky": setup["weather_sky"]},
            away_starting_pitcher=pitcher_from_roster(away_roster),
            home_starting_pitcher=pitcher_from_roster(home_roster),
            away_bullpen=away_bullpen, home_bullpen=home_bullpen,
        )
        game = Game.objects.create(
            owner=request.user,
            away_name=away_team.name, home_name=home_team.name,
            away_team=away_team, home_team=home_team,
            total_innings=setup["total_innings"], mode=setup["mode"],
            cpu_side=None,
            streaky_per_game=setup["streaky_per_game"],
            streaky_per_inning=setup["streaky_per_inning"],
            weather_temperature_f=setup["weather_temperature_f"],
            weather_wind=setup["weather_wind"],
            weather_sky=setup["weather_sky"],
            away_bullpen=away_bullpen, home_bullpen=home_bullpen,
            state=Game.state_to_dict(gs),
            away_roster=away_roster, home_roster=home_roster,
        )
        del request.session["bb_setup"]
        return redirect("baseball-detail", pk=game.pk)


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
        p2_bullpen = form.bullpen_for()

        if game.owner_side == "away":
            game.home_team, game.home_roster, game.home_name = p2_team, p2_roster, p2_team.name
            game.home_bullpen = p2_bullpen
        else:
            game.away_team, game.away_roster, game.away_name = p2_team, p2_roster, p2_team.name
            game.away_bullpen = p2_bullpen

        gs = GameState(
            game.away_name, game.home_name, game.total_innings,
            away_lineup=lineup_from_roster(game.away_roster),
            home_lineup=lineup_from_roster(game.home_roster),
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
            weather={"temperature_f": game.weather_temperature_f,
                     "wind": game.weather_wind, "sky": game.weather_sky},
            away_starting_pitcher=pitcher_from_roster(game.away_roster),
            home_starting_pitcher=pitcher_from_roster(game.home_roster),
            away_bullpen=game.away_bullpen, home_bullpen=game.home_bullpen,
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
        ctx["stadium"] = stadium_context(self.object.home_team)
        if self.object.mode == Game.MULTIPLAYER:
            if self.request.user == self.object.owner:
                ctx["my_side"] = self.object.owner_side
                opp = self.object.player2
            else:
                ctx["my_side"] = "home" if self.object.owner_side == "away" else "away"
                opp = self.object.owner
            ctx["opponent_username"] = opp.username if opp else ""
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
        if self.object.away_roster:
            stats = {s.player_id: s.line
                     for s in GameStat.objects.filter(game=self.object)}

            def annotate(roster, streaky_game, streaky_inning):
                return [{**e, "line": stats.get(e["player_id"], "0-0"),
                         "streaky": e["name"] in (streaky_game, streaky_inning)}
                        for e in roster]

            ctx["lineups"] = [
                (annotate(self.object.away_roster,
                          gs.streaky_game_away, gs.streaky_inning_away), self.object.away_name),
                (annotate(self.object.home_roster,
                          gs.streaky_game_home, gs.streaky_inning_home), self.object.home_name),
            ]
            cur_roster = (self.object.away_roster if gs.half == "top"
                          else self.object.home_roster)
            cur_pid = _pid_for_name(cur_roster, gs.current_batter)
            ctx["current_batter_line"] = stats.get(cur_pid, "") if cur_pid else ""

        num_cols = max(self.object.total_innings, gs.inning,
                        len(gs.away_line), len(gs.home_line))
        ctx["away_cells"] = _line_cells(gs.away_line, num_cols, gs.inning,
                                          gs.half == "top", gs.runs_this_half)
        ctx["home_cells"] = _line_cells(gs.home_line, num_cols, gs.inning,
                                          gs.half == "bottom", gs.runs_this_half)
        ctx["away_hits"] = gs.away_hits
        ctx["home_hits"] = gs.home_hits

        # Newest-first display order, with an extra-innings separator flagged on
        # the last (chronologically first) extra-inning play — so it renders
        # immediately after that play once the list is reversed for display.
        seen_extra = False
        annotated = []
        for play in self.object.play_log:
            is_extra = play.get("play_inning", 0) > self.object.total_innings
            annotated.append({**play, "starts_extra": is_extra and not seen_extra})
            seen_extra = seen_extra or is_extra
        ctx["play_log_reversed"] = list(reversed(annotated))
        return ctx


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
        roster = game.away_roster if gs.half == "top" else game.home_roster
        play = _advance_game(gs, roster)
        _maybe_auto_swap_pitcher(game, gs, play)
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


class SimulateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        gs    = game.load_state()
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
        game.status   = Game.FINISHED
        game.save()
        return JsonResponse({"plays": plays})


class ReplayView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.mode == Game.MULTIPLAYER:
            return JsonResponse({"error": "replay not supported for multiplayer games"}, status=400)
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            body = {}
        mode = Game.AUTO_PLAY if body.get("autoplay") else game.mode

        gs = GameState(
            game.away_name, game.home_name, game.total_innings,
            away_lineup=lineup_from_roster(game.away_roster),
            home_lineup=lineup_from_roster(game.home_roster),
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
            weather={"temperature_f": game.weather_temperature_f,
                     "wind": game.weather_wind, "sky": game.weather_sky},
            away_starting_pitcher=pitcher_from_roster(game.away_roster),
            home_starting_pitcher=pitcher_from_roster(game.home_roster),
            away_bullpen=game.away_bullpen, home_bullpen=game.home_bullpen,
        )
        new_game = Game.objects.create(
            owner=request.user,
            away_name=game.away_name, home_name=game.home_name,
            away_team=game.away_team, home_team=game.home_team,
            total_innings=game.total_innings, mode=mode,
            cpu_side=game.cpu_side,
            streaky_per_game=game.streaky_per_game,
            streaky_per_inning=game.streaky_per_inning,
            weather_temperature_f=game.weather_temperature_f,
            weather_wind=game.weather_wind,
            weather_sky=game.weather_sky,
            away_bullpen=game.away_bullpen, home_bullpen=game.home_bullpen,
            state=Game.state_to_dict(gs),
            away_roster=game.away_roster, home_roster=game.home_roster,
        )
        return JsonResponse({"redirect_url": reverse("baseball-detail", args=[new_game.pk])})


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
