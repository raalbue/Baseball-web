from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView

from .forms import SeasonCreateForm
from .models import GameStat, SavedRoster, Season, Team
from .season import advance_season, build_regular_season_schedule, compute_standings, pick_league
from .views import _apply_saved_roster, _saved_rosters_for, auto_fill_bullpen, auto_fill_roster


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

        if action == "save_roster" and team:
            form = SeasonCreateForm(request.POST, team=team)
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
            form = SeasonCreateForm(data, team=team)
            return render(request, self.template_name,
                          {"form": form, "team_chosen": True,
                           "saved_rosters": _saved_rosters_for(request.user, team)})

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
        # GameStat.game has no DB-level cascade (on_delete=DO_NOTHING against an
        # external FK constraint), so any completed season game's box-score rows
        # must be cleared explicitly before the Game rows can be deleted.
        GameStat.objects.filter(game__season=season).delete()
        season.delete()
        return redirect("season-list")


def _team_name(teams, team_id):
    t = teams.get(team_id)
    return t.name if t else "?"


class SeasonDetailView(LoginRequiredMixin, View):
    template_name = "baseball/season_detail.html"

    def get(self, request, pk):
        season = get_object_or_404(Season, pk=pk, owner=request.user)
        standings = compute_standings(season)
        teams = {t.team_id: t for t in Team.objects.filter(team_id__in=season.team_ids)}

        next_entry = None
        if season.current_index < len(season.schedule):
            next_entry = dict(season.schedule[season.current_index])
            next_entry["away_team_name"] = _team_name(teams, next_entry["away_team_id"])
            next_entry["home_team_name"] = _team_name(teams, next_entry["home_team_id"])

        series = {}
        for e in season.schedule:
            entry = dict(e)
            entry["away_team_name"] = _team_name(teams, e["away_team_id"])
            entry["home_team_name"] = _team_name(teams, e["home_team_id"])
            series.setdefault(e["series_id"], []).append(entry)
        series_list = list(series.values())

        bracket = []
        for round_info in season.bracket:
            if round_info["round"] == "champion":
                bracket.append({"round": "Champion",
                                 "team_name": _team_name(teams, round_info["team_id"])})
            else:
                bracket.append({"round": round_info["round"],
                                 "seed_names": [_team_name(teams, tid) for tid in round_info["seeds"]]})

        champion = None
        if season.stage == Season.FINISHED and season.bracket:
            champion = teams.get(season.bracket[-1].get("team_id"))

        return render(request, self.template_name, {
            "season": season, "standings": standings,
            "next_entry": next_entry, "series_list": series_list,
            "bracket": bracket, "champion": champion,
        })


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
