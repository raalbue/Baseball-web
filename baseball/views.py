import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView, DetailView

from .forms import Page1Form, SideRosterForm, POSITIONS, BATTING_POSITIONS
from .models import Game, Player, Team, GameStat, PlayerCareerStats, position_pools, main_position
from .engine import GameState, resolve_dice_roll, apply_in_play, stat_based_weights
from .params import STAT_BASED_MIN_AB
from .stadiums import stadium_context

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


def _career_weights_for(player_id):
    """Stat-based outcome weights for a batter, or None to use the dice table."""
    if not player_id:
        return None
    row = PlayerCareerStats.objects.filter(player_id=player_id).values(
        "at_bats", "hits", "doubles", "triples", "home_runs", "walks", "strikeouts",
    ).first()
    if not row or row["at_bats"] < STAT_BASED_MIN_AB:
        return None
    return stat_based_weights(row)


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


def _advance_game(gs: GameState, roster) -> dict:
    # Capture before any mutation so play-log labels show the inning/half of the play.
    play_half   = gs.half
    play_inning = gs.inning
    batter      = gs.current_batter

    if batter == "Tushy Scar":
        d1, d2 = 6, 6
        msg, _ = apply_in_play(gs, "home_run")
        outcome = "home_run"
        method = "dice"
    else:
        pid = _pid_for_name(roster, batter)
        weights = _career_weights_for(pid)
        d1, d2, outcome, msg = resolve_dice_roll(gs, stat_weights=weights)
        method = "stat" if weights is not None else "dice"
    gs.reset_count()
    gs.advance_lineup()

    half_over = False
    is_final  = gs.inning >= gs.total_innings

    # Walk-off: bottom half of final inning, home leads after the at-bat
    if gs.half == "bottom" and is_final and gs.home_score > gs.away_score:
        gs.game_over = True
        return dict(d1=d1, d2=d2, outcome=outcome, message=msg, method=method,
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

    return dict(d1=d1, d2=d2, outcome=outcome, message=msg, method=method,
                play_half=play_half, play_inning=play_inning,
                batter=batter, half_over=half_over, game_over=gs.game_over,
                state=_state_snapshot(gs))


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
        )
        new_game = Game.objects.create(
            owner=request.user,
            away_name=game.away_name, home_name=game.home_name,
            away_team=game.away_team, home_team=game.home_team,
            total_innings=game.total_innings, mode=mode,
            cpu_side=game.cpu_side,
            state=Game.state_to_dict(gs),
            away_roster=game.away_roster, home_roster=game.home_roster,
        )
        return JsonResponse({"redirect_url": reverse("baseball-detail", args=[new_game.pk])})
