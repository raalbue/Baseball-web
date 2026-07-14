from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, DetailView, FormView

from .forms import GameSetupForm, RosterForm, POSITIONS, BATTING_POSITIONS
from .models import Game, Player, Team, GameStat, position_pools, main_position
from .engine import GameState, resolve_dice_roll, apply_in_play

_HIT_STAT   = {"single": "singles", "double": "doubles",
               "triple": "triples", "home_run": "home_runs"}
_OTHER_STAT = {"strikeout": "strikeouts", "walk": "walks", "sacrifice": "sac_hits"}
_AB_OUTCOMES = {"single", "double", "triple", "home_run",
                "strikeout", "groundout", "flyout"}


def _stat_delta(outcome):
    delta = {}
    if outcome in _AB_OUTCOMES:
        delta["ab"] = 1
    col = _HIT_STAT.get(outcome) or _OTHER_STAT.get(outcome)
    if col:
        delta[col] = 1
    return delta


def _pid_for_name(roster, name):
    for e in roster:
        if e.get("name") == name:
            return e.get("player_id")
    return None


def _apply_delta(game, player_id, delta):
    obj, _ = GameStat.objects.get_or_create(game=game, player_id=player_id)
    for col, n in delta.items():
        setattr(obj, col, getattr(obj, col) + n)
    obj.save()
    return obj




def auto_fill_roster(team):
    """Pick one eligible, distinct player per position for the away (CPU) side,
    preferring each player's main position so the lineup is realistic.
    Returns {position_code: player_id}."""
    pools = position_pools(team)
    primary = {p.player_id: main_position(p)
               for p in Player.objects.filter(team=team)}
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
        "batting_team":   gs.batting_team,
        "current_batter": gs.current_batter,
        "game_over":      gs.game_over,
        "away_name":      gs.away_name,
        "home_name":      gs.home_name,
    }


def _advance_game(gs: GameState) -> dict:
    # Capture before any mutation so play-log labels show the inning/half of the play.
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter

    if gs.current_batter == "Tushy Scar":
        d1, d2 = 6, 6
        msg, _ = apply_in_play(gs, "home_run")
        outcome = "home_run"
    else:
        d1, d2, outcome, msg = resolve_dice_roll(gs)
    gs.reset_count()
    gs.advance_lineup()

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    # Walk-off: bottom half of final inning, home leads after the at-bat
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg,
                    play_half=play_half, play_inning=play_inning,
                    batter=batter, half_over=True, game_over=True,
                    state=_state_snapshot(gs))

    if gs.outs >= 3:
        half_over = True
        if gs.half == "top":
            # Home already winning at end of final top half — skip bottom
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
                play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=half_over, game_over=gs.game_over,
                state=_state_snapshot(gs))


class GameListView(LoginRequiredMixin, ListView):
    model         = Game
    template_name = "baseball/game_list.html"

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)


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


class RosterView(LoginRequiredMixin, View):
    template_name = "baseball/game_roster.html"

    def _setup(self, request):
        return request.session.get("bb_setup")

    def _teams(self, setup):
        away = get_object_or_404(Team, pk=setup["away_team_id"])
        home = get_object_or_404(Team, pk=setup["home_team_id"])
        return away, home

    def get(self, request):
        setup = self._setup(request)
        if not setup:
            return redirect("baseball-new")
        away_team, home_team = self._teams(setup)
        initial = {f"away_{code}": pid
                   for code, pid in auto_fill_roster(away_team).items()}
        form = RosterForm(away_team=away_team, home_team=home_team, initial=initial)
        sides = [(setup["away_name"] + " (Away, CPU)", "away"),
                 (setup["home_name"] + " (Home)", "home")]
        return render(request, self.template_name,
                      {"form": form, "setup": setup, "sides": sides})

    def post(self, request):
        setup = self._setup(request)
        if not setup:
            return redirect("baseball-new")
        away_team, home_team = self._teams(setup)
        form = RosterForm(request.POST, away_team=away_team, home_team=home_team)
        sides = [(setup["away_name"] + " (Away, CPU)", "away"),
                 (setup["home_name"] + " (Home)", "home")]
        if not form.is_valid():
            return render(request, self.template_name,
                          {"form": form, "setup": setup, "sides": sides})
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


class GameDetailView(LoginRequiredMixin, DetailView):
    model         = Game
    template_name = "baseball/game_detail.html"

    def get_queryset(self):
        return Game.objects.filter(owner=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        gs = self.object.load_state()
        ctx["current_batter"] = gs.current_batter
        ctx["batting_team"]   = gs.batting_team
        if self.object.status == Game.FINISHED:
            away, home = gs.away_score, gs.home_score
            ctx["winner"] = gs.away_name if away > home else (
                gs.home_name if home > away else None)
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
        return ctx


class RollView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        gs   = game.load_state()
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


class SimulateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        game = get_object_or_404(Game, pk=pk, owner=request.user)
        if game.status == Game.FINISHED:
            return JsonResponse({"error": "game over"}, status=400)
        gs    = game.load_state()
        plays, totals = [], {}
        while not gs.game_over:
            play = _advance_game(gs)
            roster = game.away_roster if play["play_half"] == "top" else game.home_roster
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
