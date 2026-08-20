---
date: 2026-08-18T17:00:01-04:00
researcher: Claude
git_commit: 87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e
branch: main
repository: Baseball-web
topic: "Season mode: existing building blocks and gaps in the codebase"
tags: [research, codebase, season-mode, baseball, game-model, engine, simulate]
status: complete
last_updated: 2026-08-18
last_updated_by: Claude
---

# Research: Season mode — existing building blocks and gaps

**Date**: 2026-08-18T17:00:01-04:00
**Researcher**: Claude
**Git Commit**: 87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e
**Branch**: main
**Repository**: Baseball-web

## Research Question

User wants a season mode: 8- or 16-team league drawn from real MLB teams (excluding the AL/NL All-Star pseudo-teams), a fixed schedule of 3-game CPU series with randomly matched opponents, one team picked by the player for the whole season, CPU-vs-CPU games auto-played, progress saved after every game so a season resumes where it left off, a season hub page (list in-progress seasons, create, delete), standings (W/L, RS/RA normalized to 9-inning games, ERA, team AVG, win%), a playoff bracket (top 4 of 8 or top 8 of 16, best-of-3 first round then best-of-5 thereafter, #1 vs #4 / #2 vs #3 seeding), and a cosmetic-only artificial calendar/schedule of dates and times generated from the season's creation date. What already exists in the codebase to build this on top of, and what's missing?

## Summary

The app has no season, schedule, standings, or playoff concept anywhere — confirmed by a full model/migration audit (`baseball/models.py`, all 19 migrations) and a full view/engine audit. What it does have are strong, directly-reusable building blocks for the pieces season mode needs most:

- **Full-game CPU-vs-CPU auto-simulation already exists and works exactly as season mode needs it**: `SimulateView` (`baseball/views.py:935-964`) loops `_advance_game` until `gs.game_over`, batches all stat updates, and marks the `Game` `FINISHED` in one DB write. `ReplayView`'s `{"autoplay": true}` body flag (`baseball/views.py:970-976`) is the existing precedent for forcing a game into this auto-play path.
- **Full roster auto-fill for CPU (or a lazy human) teams already exists**: `cpu_roster_for(team)` / `auto_fill_roster(team)` / `auto_fill_bullpen(team, exclude_player_id)` (`baseball/views.py:115-165`) pick a complete, position-legal 10-slot roster + bullpen for any `Team` with no human input, and are already wired to a "Player 1 auto-fill" button in `game_setup.html`.
- **Per-game resume already exists**: `Game.state` (JSONField) + `Game.state_to_dict`/`state_from_dict`/`load_state`/`save_state` (`baseball/models.py:246-375`) fully round-trip a live `GameState` (inning/outs/bases/score/lineup position/pitching staff/bullpen/streaky picks) — this is precisely the "save after each game... resume where you left off" mechanism, just scoped to one game rather than a season.
- **The AL/NL All-Star exclusion rule already exists as a queryable flag**: `Team.division == "All-Star"` (seeded onto team_id 31/32 in migration `0017_seed_all_star_teams.py`), checked via `is_all_star_team(team)` (`baseball/models.py:114-115`). A season's random-team pool is simply `Team.objects.exclude(division="All-Star")` — 30 real teams available.
- **Nothing exists for**: grouping multiple `Game` rows into a season/league, a schedule/series/matchup model, a season-scoped standings/record model, a playoff bracket model, or any artificial-calendar/date-generation logic. `Game` has no FK back to any season-like parent at all — this was explicitly severed for `PlayerCareerStats` (formerly `Stats`) in migration `0011_stats_drop_game_add_season.py`, which removed a `game_id` FK in favor of a bare `season` integer year column, so there is *no* precedent in this codebase for a `Game`↔season link to copy from; it would need to be added fresh.
- The unmanaged `MLBSchedule` model (`baseball/models.py:139-161`, raw `schedule` table with `game_date`/`game_time`/`home_score`/`away_score`/`status`) looks schedule-shaped but is a pre-existing external table with no seed data and no app code reading/writing it (confirmed empty of app-side usage) — it is not the same thing as the app's own `Game` model and isn't wired into any view.

## Detailed Findings

### Team pool and All-Star exclusion

- `Team` model — `baseball/models.py:27-47` (unmanaged, `db_table='team'`, ordered by `name`). Fields: `team_id`, `name`, `city`, `abbreviation`, `conference`, `division`, `head_coach`, `stadium` (FK), `founded_year`.
- 30 real MLB teams seeded with fixed `team_id` 1-30 in `baseball/migrations/0006_seed_stadiums_teams.py`.
- Two All-Star pseudo-teams seeded in `baseball/migrations/0017_seed_all_star_teams.py`: `team_id=31` "AL All-Stars", `team_id=32` "NL All-Stars", both with `division='All-Star'`.
- `is_all_star_team(team)` — `baseball/models.py:114-115` — `bool(team) and team.division == "All-Star"`. This is the exact predicate to filter out when building a season's random team pool: `Team.objects.exclude(division="All-Star")` yields the 30 real teams (enough for both an 8-team and a 16-team season).
- `players_for_team(team)` (`baseball/models.py:118-123`) and `position_pools(team)` (`126-136`) already branch on `is_all_star_team` (pooling players by `conference` for All-Star teams vs. by `team` otherwise) — irrelevant to season mode directly since All-Star teams are excluded, but confirms the flag is the canonical way this codebase distinguishes "real team" from "special pseudo-team."
- `baseball/stadiums.py:7-20` `TEAM_SLUGS` dict is effectively a second canonical list of the 30 team names (used only for stadium-diagram rendering), confirming no separate "list of season-eligible teams" exists elsewhere.

### CPU-vs-CPU full-game auto-simulation (directly reusable)

- `SimulateView` — `baseball/views.py:935-964`. Owner-only (`get_object_or_404(Game, pk=pk, owner=request.user)`, no `player2`/multiplayer check), 400s if already `Game.FINISHED`. Loads `GameState` via `game.load_state()`, then `while not gs.game_over:` repeatedly calls `_advance_game(gs, roster)` (the same per-at-bat resolver `RollView` uses for one manual click, `baseball/views.py:218-297`) with no per-play DB write. Player stat deltas are accumulated in memory (`totals` dict) and flushed once per player at the end via `_apply_delta` (`baseball/views.py:91-96`), rather than once per at-bat. After the loop: `game.save_state(gs)`, `game.play_log = plays` (full replace), `game.status = Game.FINISHED`, `game.save()`.
- `_maybe_auto_swap_pitcher` (`baseball/views.py:300-321`, called every play inside `SimulateView`'s loop) treats a side as CPU-controlled if `game.mode == Game.AUTO_PLAY or game.cpu_side == side` — in `AUTO_PLAY` mode *both* sides auto-swap tiring pitchers with no human prompt, which is exactly the behavior a season's CPU-vs-CPU game needs.
- `ReplayView` (`baseball/views.py:967-1005`) is the existing precedent for *triggering* the auto-play path programmatically: it creates a fresh `Game` reusing the source game's rosters/settings, and if the request body has `{"autoplay": true}` it force-sets `mode = Game.AUTO_PLAY` (line 976) regardless of the original mode, then returns `{"redirect_url": ...}` for the client to follow. A season scheduler generating a CPU-vs-CPU `Game` could reuse this exact "build the Game with `mode=AUTO_PLAY` then call `SimulateView`'s logic" pattern (either by hitting `SimulateView` server-side/programmatically, or refactoring `SimulateView`'s loop body into a plain function callable from a season-day-advance view).
- Games created directly with `mode=Game.CPU_AUTO` already build a full `GameState` synchronously at creation via `cpu_roster_for(opponent_team)` (`Page1View.post`, `baseball/views.py:473-516`) — the same helper season mode would use to give every non-player team a legal CPU roster without any per-game human setup.

### Roster auto-fill for teams the player doesn't control

- `auto_fill_roster(team)` — `baseball/views.py:115-132` — picks one eligible, distinct player per position (preferring each player's primary position via `main_position`), returns `{position_code: player_id}` for all 10 slots including pitcher.
- `auto_fill_bullpen(team, exclude_player_id, n=BULLPEN_MAX)` — `baseball/views.py:159-165` — picks up to `n` (default `BULLPEN_MAX=4`) distinct relievers from the team's pitcher pool, excluding the already-picked starter.
- `cpu_roster_for(team)` — `baseball/views.py:146-156` — combines the above into the full 10-slot roster shape (`[{"position","player_id","name"}, ...]`) matching `Game.away_roster`/`home_roster`'s JSON shape, ready to hand straight to `GameState`.
- These three functions are the complete "give this team a legal roster with zero human input" toolkit a season needs for every team other than the one the player picked, and (per this session's own recent change, see `baseball/views.py`'s `auto_roster` POST-action branch in `Page1View`, added same day as this research) are already exposed to a human player too, via a button — so the exact same call can seed either a CPU team's season roster or let the player one-click their own team's opening-day lineup.

### Game state persistence / resume (per-game, not yet per-season)

- `Game.state` — `baseball/models.py:303` — single `JSONField`, no default, required. Holds the complete serialized `GameState`.
- `Game.state_to_dict(s)` / `Game.state_from_dict(d)` — `baseball/models.py:313-369` — full round-trip serializer covering inning/half/outs/balls/strikes/bases/scores/line-scores/hits/lineup-rotation-indices/`game_over`/lineups/streaky picks/weather/both sides' full pitching-staff dicts (current pitcher, stamina, bullpen, prompted/dismissed flags).
- `Game.load_state()` / `Game.save_state(gs)` — `baseball/models.py:371-375` — thin wrappers every view uses to deserialize/reserialize; `save_state` does not itself call `.save()`, callers must.
- `Game.status` — `active` / `waiting` / `finished` (`Game.STATUS_CHOICES`, `baseball/models.py:258-263`) — the only "is this game done" signal that exists today, per individual `Game` row.
- **Gap**: there is no field or model tying a finished/in-progress `Game` back to a season, no "which game/series are we currently on" pointer, and no season-level status. A season implementation would need a new model (e.g. holding `owner`, chosen team, list/schedule of `Game` FKs or a season-scoped schedule table, current position in the schedule, and status) — none of this exists to extend; it's fresh design.

### Standings — no existing model, but the raw ingredients are present

- Final score per game: `GameState.away_score`/`home_score`, persisted inside `Game.state` (via `state_to_dict`); only reliably final once `Game.status == Game.FINISHED`.
- Per-player, per-game batting box score: `GameStat` — `baseball/models.py:398-423` — unmanaged `game_stat` table, FK to `Game` and `Player`, tracks `ab`, `singles`, `doubles`, `triples`, `home_runs`, `strikeouts`, `walks`, `sac_hits`, with computed `hits`/`line` properties. This is per-`Game`-per-`Player`, not per-team-per-season — a team/season standings aggregate (W/L, RS/RA, ERA, team AVG) would need to be computed either on the fly from all of a season's `Game`+`GameStat` rows, or maintained as a separate rolling aggregate model updated after each game.
- `PlayerCareerStats` — `baseball/models.py:182-210` — is a *different* axis entirely: per-`Player`-per-`season`-integer aggregate (batting + pitching), unrelated to any specific `Game` or to team win/loss records (its `game_id` FK was explicitly dropped in migration `0011_stats_drop_game_add_season.py` in favor of a bare year). Not usable as-is for team standings; it's real-world historical career-stat data (seeded from CSV in `0007`/`0012`), not season-mode gameplay data.
- No pitching-decision (W/L/ERA-by-team) tracking exists anywhere — `GameStat` only has batting columns. ERA and pitching-side standings would need new fields/tracking (there's no `earned_runs`/`innings_pitched` recorded per `Game` today outside of `PlayerCareerStats`' historical/real-world columns).
- "Based on 9-inning increments" (user's normalization ask for RS/RA) has no existing helper — `Game.total_innings` (`baseball/models.py:290`, default 3, chosen per game from `Page1Form.INNINGS_CHOICES` = 3/6/9) is the only inning-count field available to normalize by.

### Playoffs — no existing bracket/seeding concept

Nothing in `models.py`, `views.py`, or `engine.py` represents a bracket, seed, or best-of-N series. `Game` is strictly one played game; there is no "series" grouping of multiple `Game`s with a running series score, which the user's regular-season 3-game series and playoff best-of-3/best-of-5 rounds both need. This is a clean-slate addition.

### Artificial calendar — no scheduling/date system to reuse

- `Game.created_at`/`updated_at` (`baseball/models.py:307-308`) are real `auto_now_add`/`auto_now` timestamps — actual wall-clock time of creation/last edit, not a fabricated in-league calendar.
- `MLBSchedule` (`baseball/models.py:139-161`, unmanaged `db_table='schedule'`) has `game_date`, `game_time`, `home_team`/`away_team`/`stadium` FKs, `home_score`/`away_score`, `status` (default `'Scheduled'`) — structurally close to what a schedule table needs, but it's a **separate, pre-existing external raw table** with no migration that seeds it and no view/form anywhere that reads or writes it. It predates and is unrelated to the app's own `Game` model (in fact `PlayerCareerStats`/`Stats` originally FK'd to this `schedule` table via `game_id` before migration `0011` deleted that FK). Reusing it would mean adopting an existing but currently-dormant/unmanaged table shape rather than a proven in-app pattern; there's no code precedent showing it actually works end-to-end in this app today.
- No date-generation/faking utility exists anywhere in the codebase (no `datetime` arithmetic helpers for schedules found in `params.py`, `stadiums.py`, or elsewhere).

### Season "page" — closest existing UI/URL precedent

- `GameListView` (`baseball/views.py:323-347`, URL `""` → `baseball-list`) is the closest existing analog to "a page listing your seasons": a `ListView` filtered to `request.user`'s own games (`owner=request.user | player2=request.user`), each row annotated with computed display info.
- Creation flow precedent: `Page1View` (`baseball/views.py:350-533`, URL `new/` → `baseball-new`) — multi-action `POST` handler (`choose_team`, `load_roster`, `auto_roster`, `save_roster`, `delete_roster`, plain-submit-creates-and-redirects) is the established pattern this app uses for "a form-heavy creation page with several sub-actions," which a "create new season" page (team pick, season size 8 or 16) would naturally follow.
- Deletion precedent: `CancelWaitingView` (`baseball/views.py:798-805`) — `POST`-only, ownership-scoped `get_object_or_404`, then a hard `.delete()`, then redirect — the pattern a "delete season" action would follow.
- All of the above inherit `LoginRequiredMixin` and scope querysets to the requesting user (`owner=request.user` and/or `player2=request.user`), which is the existing convention for season ownership/visibility too.

### Existing "season" fields (unrelated to season mode)

Two unrelated fields already use the word "season" in this codebase — neither is a season-mode gameplay concept and neither should be confused with a new season-mode model:
1. `Player.season` (`baseball/models.py:67`) — a per-player-record vintage/year snapshot from the CSV seed data (`baseball/migrations/0007_seed_players.py`), not a link to any played season.
2. `PlayerCareerStats.season` (`baseball/models.py:187`, with `unique_together` on `(player, season)`) — real-world historical per-player-per-year aggregate stats, seeded from `totalbattingstats.csv` in migration `0012`. Unrelated to any in-app schedule or standings.

## Code References

- [`baseball/models.py:27-47`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L27-L47) — `Team` model
- [`baseball/models.py:50-96`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L50-L96) — `Player` model (including `Player.season`)
- [`baseball/models.py:114-115`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L114-L115) — `is_all_star_team(team)`
- [`baseball/models.py:118-136`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L118-L136) — `players_for_team`, `position_pools`
- [`baseball/models.py:139-161`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L139-L161) — `MLBSchedule` (unmanaged, dormant, schedule-shaped table)
- [`baseball/models.py:182-210`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L182-L210) — `PlayerCareerStats` (per-player-per-year, unrelated to Game)
- [`baseball/models.py:246-375`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L246-L375) — `Game` model: choices, all fields, `state_to_dict`/`state_from_dict`/`load_state`/`save_state`
- [`baseball/models.py:378-395`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L378-L395) — `SavedRoster` model
- [`baseball/models.py:398-423`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/models.py#L398-L423) — `GameStat` model (per-game per-player batting box score)
- [`baseball/migrations/0006_seed_stadiums_teams.py`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/migrations/0006_seed_stadiums_teams.py) — seeds the 30 real teams (team_id 1-30)
- [`baseball/migrations/0011_stats_drop_game_add_season.py`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/migrations/0011_stats_drop_game_add_season.py) — historical precedent of *removing* a `Game`-like FK in favor of a bare season year (cautionary, not a pattern to copy)
- [`baseball/migrations/0017_seed_all_star_teams.py`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/migrations/0017_seed_all_star_teams.py) — seeds team_id 31/32 as `division='All-Star'`
- [`baseball/views.py:115-165`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L115-L165) — `auto_fill_roster`, `cpu_roster_for`, `auto_fill_bullpen`
- [`baseball/views.py:191-215`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L191-L215) — `_state_snapshot` (response-only partial state, not persistence)
- [`baseball/views.py:218-297`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L218-L297) — `_advance_game` (single at-bat resolver + inning/game-over state machine)
- [`baseball/views.py:300-321`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L300-L321) — `_maybe_auto_swap_pitcher`
- [`baseball/views.py:323-347`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L323-L347) — `GameListView` (season-hub-page precedent)
- [`baseball/views.py:350-533`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L350-L533) — `Page1View` (multi-action creation-page precedent)
- [`baseball/views.py:668-675`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L668-L675), [`678-795`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L678-L795), [`798-805`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L798-L805) — multiplayer waiting/join/cancel flow (ownership-scoped access-control precedent)
- [`baseball/views.py:935-964`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L935-L964) — `SimulateView` (full CPU-vs-CPU auto-play loop — directly reusable)
- [`baseball/views.py:967-1005`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/views.py#L967-L1005) — `ReplayView` (precedent for force-setting `mode=Game.AUTO_PLAY` programmatically)
- [`baseball/forms.py:5-19`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/forms.py#L5-L19) — `POSITIONS`, `BULLPEN_MIN`/`BULLPEN_MAX`
- [`baseball/forms.py:37-115`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/forms.py#L37-L115) — `SideRosterForm` (team+roster+bullpen form, reusable shape for a season's per-team setup)
- [`baseball/forms.py:118-188`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/forms.py#L118-L188) — `Page1Form` (mode/innings/weather/streaky/opponent fields)
- [`baseball/stadiums.py:7-20`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/stadiums.py#L7-L20) — `TEAM_SLUGS` (secondary canonical team-name list, display-only)
- [`baseball/params.py:125`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/params.py#L125) — `STAT_BASED_MIN_AB`
- [`baseball/urls.py:5-16`](https://github.com/raalbue/Baseball-web/blob/87c8f567cbc4f271c8f1a4f27489fae3f61c1e0e/baseball/urls.py#L5-L16) — full URL map

## Architecture Documentation

- **Single-game-centric design**: every model and view in `baseball/` is built around one `Game` row being the unit of play, persistence, and resume. There is no grouping/parent concept above `Game` anywhere in the schema.
- **JSON-blob state pattern**: rather than normalizing live game state into relational columns, the app stores the entire mutable game state as one `JSONField` (`Game.state`) and rehydrates it into a plain Python object (`GameState`) on each request. Season mode's "resume where you left off" would likely want an analogous top-level JSON/relational hybrid: durable relational fields for season metadata (teams, standings, schedule position) plus reuse of the existing per-`Game` JSON state for whichever game is currently in progress.
- **Ownership scoping convention**: every view scopes its queryset to `request.user` via `owner`/`player2` FK checks plus `LoginRequiredMixin` — no season-mode addition would need to invent a new access-control pattern.
- **Multi-action POST-on-one-URL convention**: `Page1View`, `Page2View`, `Player2JoinView` all multiplex several form actions (`choose_team`, `load_roster`, `auto_roster`, `save_roster`, `delete_roster`, final-submit) behind one URL via a `request.POST["action"]` switch — the established idiom for a "create season" page's team-pick + roster-setup flow.
- **CPU-side detection convention**: `is_cpu = game.mode == Game.AUTO_PLAY or game.cpu_side == side` (`baseball/views.py:308`, inside `_maybe_auto_swap_pitcher`) is the existing per-side "does a human control this side" check; a season's CPU-vs-CPU games would set `mode=Game.AUTO_PLAY` to get this for free, while the player's own games would use `mode=Game.CPU_AUTO` with `cpu_side` set to the opponent.

## Historical Context (from thoughts/)

No existing plan or research document in `thoughts/` addresses season mode, schedules, standings, playoffs, or league structure — confirmed by a full locator sweep of all 24 documents in `thoughts/shared/`. The closest precedents:
- `thoughts/shared/plans/2026-07-20-multiplayer-mode.md` — how multi-participant game state and turn-taking were designed; relevant to how a season's ownership/turn model might extend to CPU-vs-CPU auto-play.
- `thoughts/shared/plans/2026-08-17-all-star-mode-player-search-announcer-commentary.md` — the most directly analogous prior "special mode" addition (alternate team assembly + new page), useful as a template for how a new mode has been bolted onto this codebase before.
- `thoughts/shared/plans/2026-07-23-saved-team-rosters.md` — `SavedRoster` design; relevant since a season needs a roster that persists across many games rather than one-off per-game setup.
- `thoughts/shared/plans/2026-07-21-stat-based-at-bat-outcomes.md` and `thoughts/shared/research/2026-08-17-outcome-probability-dice-vs-array.md` — relevant to how CPU-vs-CPU games would resolve outcomes at higher volume (many auto-played games per season) than the current one-off game usage.
- `thoughts/shared/plans/2026-06-25-baseball-web-game.md` — original foundational plan; establishes the base engine/data model season mode would sit on top of.

Full file-by-file relevance list is in the sub-agent finding above; nothing further to add — no document even mentions the words "season" (as a gameplay concept), "schedule," "standings," "playoffs," or "league."

## Related Research

None — this is the first research document touching season mode specifically.

## Open Questions

These are things the existing codebase doesn't answer and would need to be decided when a plan is written (not answered here, per this command's scope):
- Where would season-level models live — a new `season` field/app, or new models inside `baseball/models.py` alongside `Game`?
- Should regular-season and playoff games reuse the existing `Game` model as-is (one `Game` row per game in the season, linked via a new FK), or would some games need new fields `Game` doesn't have (e.g., which series/round they belong to, game number within a series)?
- How would a CPU-vs-CPU game in a season actually get simulated — by directly invoking `SimulateView`'s loop logic (refactored into a callable), or by having the season "advance a day" action programmatically POST to `SimulateView` per game?
- How would ERA and team batting average be computed given `GameStat` currently has no pitching columns (earned runs, innings pitched) at all — would `GameStat` need new columns, or would a season need a separate pitching-stat-per-game model?
- Since `MLBSchedule` is a dormant, unmanaged, unseeded table structurally similar to what a "real" schedule would need — is it in scope to start using it, or should a season's schedule be a new app-owned (managed) model instead, consistent with how `Game`/`SavedRoster` (the only two managed models in `baseball/`) were added?
