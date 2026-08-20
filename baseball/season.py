import itertools
import random
from datetime import date, timedelta

from django.db.models import Sum

from .engine import GameState
from .models import Game, GameStat, Season, Team
from .views import (
    auto_fill_bullpen, cpu_roster_for, lineup_from_roster,
    pitcher_from_roster, simulate_full_game,
)

ROUND_BEST_OF = {
    "semifinal_first": 3,   # 8-team bracket's only pre-final round
    "quarterfinal":    3,   # 16-team bracket's first round
    "semifinal":       5,   # 16-team bracket's second round
    "final":           5,
}

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
    with the second element of each pair treated as the higher (home-favored) seed."""
    entry_id = next_entry_id(schedule)
    day = start_date
    for series_id, (away_id, home_id) in enumerate(matchups):
        for game_number in range(1, best_of + 1):
            # Standard 2-1 (best_of=3) / 2-2-1 (best_of=5) home split favoring the
            # higher (second-listed / "home_id") seed, purely cosmetic scheduling.
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
        # All runs allowed are treated as earned (the engine has no unearned-run
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
    is_away = entry["away_team_id"] == season.player_team_id
    is_home = entry["home_team_id"] == season.player_team_id

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


def _rounds_for(size):
    """Ordered playoff round names for this league size."""
    return ["semifinal_first", "final"] if size == 8 else \
           ["quarterfinal", "semifinal", "final"]


def _last_schedule_date(schedule):
    return max(date.fromisoformat(e["date"]) for e in schedule)


def _round_entries(schedule, round_name):
    return [e for e in schedule if e.get("round") == round_name]


def _series_index(series_id):
    """The numeric suffix of a playoff series_id (e.g. 'quarterfinal-2' -> 2),
    used to keep bracket-order-sensitive pairing correct regardless of string
    sort order once a round has 10+ series."""
    return int(str(series_id).rsplit("-", 1)[1])


def _series_winner(season, series_id):
    games = _series_entries(season, series_id)
    wins = {}
    for g in games:
        if g["status"] != "final":
            continue
        w = g["away_team_id"] if g["away_score"] > g["home_score"] else g["home_team_id"]
        wins[w] = wins.get(w, 0) + 1
    return max(wins, key=wins.get)


def _bracket_pairs(seeds):
    """#1 vs #N, #2 vs #(N-1), ... as (away, home) pairs with the better seed
    hosting — `seeds` ordered best-to-worst."""
    return [(seeds[-(i + 1)], seeds[i]) for i in range(len(seeds) // 2)]


def _maybe_advance_stage(season):
    """Generate the next playoff round (or crown a champion) once every entry
    in the current stage/round is final or skipped. A no-op otherwise."""
    if season.stage == Season.REGULAR:
        regular = [e for e in season.schedule if e["phase"] == "regular"]
        if not all(e["status"] in ("final", "skipped") for e in regular):
            return
        standings = compute_standings(season)
        n = 4 if season.size == 8 else 8
        seeds = [row["team"].team_id for row in standings[:n]]
        round_name = _rounds_for(season.size)[0]
        start = _last_schedule_date(season.schedule) + timedelta(days=3)
        build_round_entries(season.schedule, _bracket_pairs(seeds), round_name,
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
        series_ids = sorted({e["series_id"] for e in current_entries}, key=_series_index)
        winners = [_series_winner(season, sid) for sid in series_ids]
        if current_round == rounds[-1]:
            season.stage = Season.FINISHED
            season.bracket.append({"round": "champion", "team_id": winners[0]})
            return
        next_round = rounds[rounds.index(current_round) + 1]
        start = _last_schedule_date(season.schedule) + timedelta(days=3)
        build_round_entries(season.schedule, _bracket_pairs(winners), next_round,
                             ROUND_BEST_OF[next_round], start)
        season.bracket.append({"round": next_round, "seeds": winners})


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
