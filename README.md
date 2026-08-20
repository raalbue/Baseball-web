# Baseball Web

A Django web game where you manage a real MLB team through single games or a
full simulated season — pick your lineup, swing at the plate, and watch a
scoreboard, an animated field, and dice-based play-by-play resolve every
at-bat.

Started life as a Django "todo app" course project; the `todo_app`/`manage`
apps are the original scaffold (kept as an admin CRUD + SQL-injection demo for
security teaching), and `baseball` is the game built on top of it.

## Features

### Core gameplay (`baseball/engine.py`)
- At-bat resolution by **2d6 dice roll** against a fixed outcome table, or by
  **real career stat weights** pulled from each player's Retrosheet data once
  they have 200+ career at-bats (`STAT_BASED_MIN_AB`) — small-sample players
  fall back to the dice table.
- Batter actions: take, contact swing, power swing, bunt — each with its own
  contact/outcome odds; pitcher pitch types (fastball/curveball/changeup/
  intentional ball) shift the zone probability and hittability.
- Full base/out/count state machine: walks, strikeouts, singles/doubles/
  triples/homers, sacrifice flies, double plays, bunts (beat-out vs.
  sacrifice).
- **Streaky batters** — an optional per-game or per-inning "hot hand" pick
  per team that swaps some groundouts for reached-on-error singles.
- **Weather** — temperature, wind (blowing out/in), and sky (rain/overcast)
  multiplicatively nudge home-run and hit odds.
- **Pitcher stamina & bullpen** — stamina drains per batter faced, fatigue
  raises walk/hit odds, and the game prompts a pitching change below a
  stamina threshold (manual or auto-swap).
- Announcer **commentary lines** — randomized flavor text layered on top of
  the mechanical play-by-play for every outcome type.

### Game setup & modes (`baseball/views.py`)
- Two-page setup flow: pick teams/stadium/weather, then build a 10-slot
  roster (starting pitcher + 8 fielders + DH) with position-eligible
  dropdowns and drag-and-drop batting order.
- **All-Star mode** — league-wide pseudo-teams (AL/NL All-Stars) pooling
  every player in a conference, plus a player search/autocomplete for
  building custom rosters.
- **Saved rosters** — store a named roster per team so you don't re-pick it
  every game.
- Four play modes: CPU auto (you click, CPU plays itself), click every
  at-bat, full auto-simulate, and **multiplayer** (invite a second user via
  a join link; game sits in a "waiting" state until they join).
- Live **career stats popup** per player (`/api/career-stats/<id>/`).
- Per-player in-game box score tracking (`GameStat`: AB, hits by type, K,
  BB, sacrifices) written back to the DB after each game.

### Season mode (`baseball/season.py`, `season_views.py`)
- Pick an 8- or 16-team league (your team + randomly drawn opponents),
  auto-generates a full **round-robin regular season** (3-game series,
  randomized home/away and scheduling).
- **Advance** button auto-simulates every CPU-vs-CPU game up to your next
  matchup, so you only play your own team's games.
- Live **standings** (W/L, run differential, ERA, AVG) computed from
  finished games.
- **Playoff bracket** generated automatically once the regular season ends
  (best-of-3/best-of-5 depending on league size and round), reseeded each
  round until a champion is crowned.

### Presentation
- Old-fashioned line-score **scoreboard** (innings, R/H/E) and animated
  base/runner diagram driven by the engine's per-play "moves."
- **Stadium outline rendering** — real ballpark shape/segments/base
  coordinates per team, loaded from `baseball/data/stadiums.json` and drawn
  as an SVG field.
- Sound effects and fireworks/crowd flourishes on big plays (home runs,
  wins).
- **Replay** view to step back through a finished game's play log.

### Accounts & admin
- Custom `accounts` app: signup, login, profile (with an admin-role flag),
  built on Django auth.
- `manage` app: staff-only admin dashboard for managing users and their
  (legacy) todo lists.
- Deliberate **SQL-injection teaching demo** (`manage/demo/sqli/vulnerable/`
  vs. `.../safe/`) — side-by-side raw string-interpolated query vs.
  parameterized query, staff-only, documented in `test-vulnerabilities.md`.
  Not for production use.

## Stack

- Django 6.0, PostgreSQL (via `dj-database-url` / `psycopg2`)
- `django-crispy-forms` + `crispy-bootstrap5` for forms
- `whitenoise` for static files, `gunicorn` for serving (see `Procfile`)
- Player/team/schedule data imported from real MLB rosters and stats
  (`Player`, `Team`, `Stadium`, `PlayerCareerStats` are unmanaged tables
  backed by a separately-loaded Postgres dataset)

## Layout

| App | Purpose |
|---|---|
| `baseball/` | The game itself — engine, single-game views, season mode, stadium rendering |
| `accounts/` | Signup/login/profile |
| `manage/` | Staff admin dashboard + SQL-injection demo |
| `todo_app/` | Legacy scaffold from the original course project |
| `baseball_project/` | Django project settings/URLs |
| `thoughts/shared/plans/` | Design docs for every feature, in build order |

## Running locally

```bash
cp .env.example .env   # fill in DB credentials
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```
