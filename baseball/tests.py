from datetime import date

from django.test import TestCase

from .models import Season, Team
from .season import (
    build_regular_season_schedule,
    build_round_entries,
    compute_standings,
    next_entry_id,
    pick_league,
)


class PickLeagueTests(TestCase):
    def test_size_and_composition(self):
        player_team = Team.objects.exclude(division="All-Star").first()
        for size in (8, 16):
            team_ids = pick_league(player_team, size)
            self.assertEqual(len(team_ids), size)
            self.assertEqual(len(set(team_ids)), size)
            self.assertIn(player_team.team_id, team_ids)

    def test_excludes_all_star_teams(self):
        player_team = Team.objects.exclude(division="All-Star").first()
        all_star_ids = set(Team.objects.filter(division="All-Star")
                            .values_list("team_id", flat=True))
        team_ids = pick_league(player_team, 16)
        self.assertFalse(set(team_ids) & all_star_ids)


class BuildRegularSeasonScheduleTests(TestCase):
    def test_round_robin_shape_8_teams(self):
        team_ids = list(range(1, 9))
        schedule = build_regular_season_schedule(team_ids, date(2026, 4, 1))
        num_pairs = 8 * 7 // 2  # C(8,2) = 28
        self.assertEqual(len(schedule), num_pairs * 3)

        pairs_seen = set()
        for series_id in {e["series_id"] for e in schedule}:
            games = [e for e in schedule if e["series_id"] == series_id]
            self.assertEqual(len(games), 3)
            teams = {games[0]["away_team_id"], games[0]["home_team_id"]}
            self.assertEqual(len(teams), 2)
            for g in games:
                self.assertEqual({g["away_team_id"], g["home_team_id"]}, teams)
            pairs_seen.add(frozenset(teams))
        self.assertEqual(len(pairs_seen), num_pairs)

    def test_round_robin_shape_16_teams(self):
        team_ids = list(range(1, 17))
        schedule = build_regular_season_schedule(team_ids, date(2026, 4, 1))
        num_pairs = 16 * 15 // 2  # C(16,2) = 120
        self.assertEqual(len(schedule), num_pairs * 3)

    def test_dates_strictly_increasing(self):
        team_ids = list(range(1, 9))
        schedule = build_regular_season_schedule(team_ids, date(2026, 4, 1))
        dates = [date.fromisoformat(e["date"]) for e in schedule]
        self.assertEqual(dates, sorted(dates))
        self.assertTrue(all(b > a for a, b in zip(dates, dates[1:])))

    def test_entry_ids_sequential(self):
        team_ids = list(range(1, 9))
        schedule = build_regular_season_schedule(team_ids, date(2026, 4, 1))
        self.assertEqual([e["id"] for e in schedule], list(range(len(schedule))))


class BuildRoundEntriesTests(TestCase):
    def test_best_of_3_entry_count_and_home_split(self):
        schedule = []
        matchups = [(4, 1), (3, 2)]  # (away, home) per series
        build_round_entries(schedule, matchups, "semifinal_first", 3, date(2026, 10, 1))
        self.assertEqual(len(schedule), 2 * 3)
        # Game 1/2 hosted by the designated home seed, game 3 by the away seed.
        g1 = next(e for e in schedule if e["series_id"] == "semifinal_first-0" and e["game_number"] == 1)
        g2 = next(e for e in schedule if e["series_id"] == "semifinal_first-0" and e["game_number"] == 2)
        g3 = next(e for e in schedule if e["series_id"] == "semifinal_first-0" and e["game_number"] == 3)
        self.assertEqual(g1["home_team_id"], 1)
        self.assertEqual(g2["home_team_id"], 1)
        self.assertEqual(g3["home_team_id"], 4)

    def test_best_of_5_entry_count_and_home_split(self):
        schedule = []
        matchups = [(8, 1)]
        build_round_entries(schedule, matchups, "quarterfinal", 5, date(2026, 10, 1))
        self.assertEqual(len(schedule), 5)
        games = {e["game_number"]: e for e in schedule}
        self.assertEqual(games[1]["home_team_id"], 1)
        self.assertEqual(games[2]["home_team_id"], 1)
        self.assertEqual(games[3]["home_team_id"], 8)
        self.assertEqual(games[4]["home_team_id"], 8)
        self.assertEqual(games[5]["home_team_id"], 1)

    def test_appends_to_existing_schedule_with_continued_ids(self):
        schedule = [{"id": 0}, {"id": 1}, {"id": 5}]
        self.assertEqual(next_entry_id(schedule), 6)
        build_round_entries(schedule, [(2, 1)], "final", 3, date(2026, 10, 1))
        new_ids = [e["id"] for e in schedule[3:]]
        self.assertEqual(new_ids, [6, 7, 8])


def _entry(entry_id, away, home, away_score, home_score, innings=9, phase="regular", status="final"):
    return {
        "id": entry_id, "phase": phase, "round": phase, "series_id": entry_id,
        "game_number": 1, "away_team_id": away, "home_team_id": home,
        "date": "2026-04-01", "time": "7:05 PM", "status": status,
        "game_id": None, "away_score": away_score, "home_score": home_score,
        "innings": innings,
    }


class ComputeStandingsTests(TestCase):
    def setUp(self):
        self.team_ids = list(
            Team.objects.exclude(division="All-Star").values_list("team_id", flat=True)[:4]
        )
        self.a, self.b, self.c, self.d = self.team_ids

    def test_known_scores(self):
        schedule = [
            _entry(0, self.a, self.b, 5, 2),   # a wins (away)
            _entry(1, self.a, self.b, 3, 4),   # b wins (home)
            _entry(2, self.a, self.b, 6, 1),   # a wins (away)
        ]
        season = Season(team_ids=self.team_ids, schedule=schedule)
        rows = {r["team"].team_id: r for r in compute_standings(season)}

        self.assertEqual(rows[self.a]["wins"], 2)
        self.assertEqual(rows[self.a]["losses"], 1)
        self.assertEqual(rows[self.a]["runs_for"], 14)
        self.assertEqual(rows[self.a]["runs_against"], 7)
        self.assertAlmostEqual(rows[self.a]["win_pct"], 2 / 3)
        self.assertAlmostEqual(rows[self.a]["era"], 7 / 27 * 9)
        self.assertAlmostEqual(rows[self.a]["era"], rows[self.a]["runs_against_per9"])

        self.assertEqual(rows[self.b]["wins"], 1)
        self.assertEqual(rows[self.b]["losses"], 2)
        self.assertEqual(rows[self.b]["runs_for"], 7)
        self.assertEqual(rows[self.b]["runs_against"], 14)

    def test_zero_games_team_has_no_division_by_zero(self):
        schedule = [_entry(0, self.a, self.b, 5, 2)]
        season = Season(team_ids=self.team_ids, schedule=schedule)
        rows = {r["team"].team_id: r for r in compute_standings(season)}
        self.assertEqual(rows[self.c]["wins"], 0)
        self.assertEqual(rows[self.c]["losses"], 0)
        self.assertEqual(rows[self.c]["win_pct"], 0.0)
        self.assertEqual(rows[self.c]["era"], 0.0)
        self.assertEqual(rows[self.c]["avg"], 0.0)

    def test_tiebreak_by_run_differential_then_runs_for(self):
        # a and c both go 1-0 (win_pct tied); a's win is by more runs.
        schedule = [
            _entry(0, self.a, self.b, 10, 0),
            _entry(1, self.c, self.d, 2, 1),
        ]
        season = Season(team_ids=self.team_ids, schedule=schedule)
        standings = compute_standings(season)
        leaders = [r["team"].team_id for r in standings if r["wins"] == 1]
        self.assertEqual(leaders[0], self.a)
        self.assertEqual(leaders[1], self.c)

    def test_playoff_entries_excluded_from_standings(self):
        schedule = [
            _entry(0, self.a, self.b, 5, 2, phase="regular"),
            _entry(1, self.a, self.b, 1, 9, phase="playoffs"),
        ]
        season = Season(team_ids=self.team_ids, schedule=schedule)
        rows = {r["team"].team_id: r for r in compute_standings(season)}
        self.assertEqual(rows[self.a]["wins"], 1)
        self.assertEqual(rows[self.a]["losses"], 0)

    def test_scheduled_entries_excluded_from_standings(self):
        schedule = [
            _entry(0, self.a, self.b, 5, 2),
            _entry(1, self.a, self.b, None, None, innings=None, status="scheduled"),
        ]
        season = Season(team_ids=self.team_ids, schedule=schedule)
        rows = {r["team"].team_id: r for r in compute_standings(season)}
        self.assertEqual(rows[self.a]["wins"], 1)
        self.assertEqual(rows[self.a]["losses"], 0)
