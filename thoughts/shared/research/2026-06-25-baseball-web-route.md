---
date: 2026-06-25
researcher: raalbue
git_commit: n/a (todo_list is not a git repository)
branch: n/a
repository: todo_list
topic: "Adding a /baseball route that plays the console baseball game in the browser"
tags: [research, codebase, baseball, django, routing, game-state]
status: complete
last_updated: 2026-06-25
last_updated_by: raalbue
last_updated_note: "Added As-Built section documenting the implemented baseball app"
---

# Research: Adding a `/baseball` route to play the console baseball game in the browser

**Date**: 2026-06-25
**Researcher**: raalbue
**Repository**: todo_list (Django webapp) + baseball-game (console game source)

## Research Question

Add a route `/baseball` to the `todo_list` Django webapp that serves a page where
the user can play a baseball game. The game logic is to be converted from the
existing console game at `../../baseball-game/`. Document how both codebases work
today so the conversion can be planned, and surface the decisions that must be made.

## Summary

Two independent codebases are involved:

1. **`baseball-game/`** — a self-contained Python package (`baseball/`) with a
   game engine, terminal display, and a CLI loop. It is **turn-based and
   interactive**: the player presses ENTER, two dice are rolled, and the dice sum
   decides the at-bat. All state lives in a single in-memory `GameState` object
   for the duration of one process run; nothing is persisted.

2. **`todo_list/`** — a Django 6 project with three apps (`accounts`, `manage`,
   `todo_app`). All user-facing views require login (`LoginRequiredMixin`), use
   class-based views, Bootstrap 5 templates, and a PostgreSQL database. Routing is
   include-based from `todo_project/urls.py`.

The central architectural fact for the conversion: **the console game is stateful
across turns, but HTTP is stateless.** Each dice roll in the console game mutates a
live `GameState`. On the web, that state must be stored somewhere between requests
(Django session, a DB model, or entirely client-side in JavaScript). This is the
main decision the conversion hinges on.

A second important fact: **the `baseball` package contains two separate gameplay
systems, but only one is actually wired into play.**

## Detailed Findings

### The console baseball game (`baseball-game/baseball/`)

Package layout (only 6 source files):

- `__main__.py` / `__init__.py` — entry points (`python -m baseball`)
- `params.py` — all constants, probability tables, dice table, lineup, text
- `engine.py` — game state + at-bat resolution logic (pure-ish, no I/O)
- `display.py` — terminal rendering (uses `art`, `colorama`)
- `game.py` — the CLI game loop + argument parsing + sound playback

**Two gameplay engines exist in the code:**

1. **Dice-roll system (THIS is what is actually played).**
   `game.py:play_at_bat` calls `engine.resolve_dice_roll(state)`
   (`engine.py:279`). It rolls 2d6, looks the pair up in `DICE_TABLE`
   (`params.py:75`), and applies the outcome. The full table:

   | Roll (sorted pair) | Outcome     |
   |--------------------|-------------|
   | (1,1),(1,2)        | walk        |
   | (1,3),(2,2),(2,3)  | single      |
   | (3,3),(5,6)        | double      |
   | (4,4)              | triple      |
   | (5,5),(6,6)        | home run    |
   | (1,6),(2,5),(3,4),(4,5) | strikeout |
   | (1,5),(2,4),(2,6)  | groundout   |
   | (1,4),(3,5),(4,6)  | flyout      |
   | (3,6)              | sacrifice   |

   Note: the public-facing `BASEBALL.md` rule table (keyed on the dice *sum* 2–12)
   does **not** match the actual `DICE_TABLE` (keyed on the sorted die pair). The
   code is the source of truth.

2. **Swing/pitch-selection system (CODED BUT DORMANT — never called by the loop).**
   `engine.py:resolve_action` (`engine.py:309`), `resolve_swing` (`engine.py:111`),
   `cpu_batter_action` (`engine.py:297`), plus `CONTACT_PROB`, `OUTCOME_WEIGHTS`,
   `PITCH_TYPES`, `SWING_MENU` in `params.py`. This is a richer model where the
   batter chooses take/contact/power/bunt and the pitcher chooses a pitch type,
   with ball/strike counts and fouls. **`game.py` never invokes any of it** — the
   played game is purely the dice roll. This system would have to be deliberately
   chosen and wired up if the web version is meant to be more interactive.

**`GameState` (`engine.py:11`)** holds everything: inning, half (top/bottom), outs,
balls, strikes, `bases = [1B, 2B, 3B]` booleans, scores, lineup rotation indices,
`game_over`. Helper functions advance runners (`advance_runners`, `walk_runners`),
add runs, reset the half, etc. All outcome appliers return `(message, at_bat_over)`.

**Game flow (`game.py:play_game`, line 77):**
- 3 innings by default (`DEFAULT_INNINGS = 3`).
- Away ("Robots") bats top, home ("You") bats bottom.
- 3 outs end a half-inning; walk-off win logic in the final inning; extra innings on
  a tie.
- It is **single-player vs CPU** in practice, though the human only presses ENTER —
  there are no real player decisions in the dice-roll loop. (`--auto` runs a no-input
  demo; the only difference is whether ENTER is required.)

**Side effects to note for a web port:**
- `display.py` uses `colorama`/`art` and `os.system("cls"/"clear")` — terminal only,
  must be replaced with HTML.
- `game.py:play_sound` plays `.wav` files from `mytimer/sounds/` via `nava` — desktop
  audio, would become browser audio or be dropped.
- `time.sleep` pacing between plays (`game.py:pause`) — has no web equivalent unless
  reproduced client-side.
- `random` is module-global; seeding is via `--seed`.

The **portable core** (no terminal/audio dependencies) is `engine.py` + the data in
`params.py`. That is what cleanly transfers to the web.

### The Django webapp (`todo_list/`)

**Project config (`todo_project/settings.py`):**
- Django apps installed: `accounts`, `manage`, `todo_app`, plus `crispy_forms` /
  `crispy_bootstrap5`.
- Database: PostgreSQL (`settings.py:55`).
- Templates: project-level dir `templates/` plus per-app `templates/` (`APP_DIRS=True`).
- Static: `STATIC_URL = "static/"`, `STATICFILES_DIRS = [BASE_DIR / "static"]`.
- Auth: `LOGIN_URL = "login"`, `LOGIN_REDIRECT_URL = "index"`.

**Routing (`todo_project/urls.py`):**
```
admin/            -> admin
accounts/         -> include("accounts.urls")
manage/           -> include("manage.urls")
""  (root)        -> include("todo_app.urls")
```
A new `/baseball` route can be added either by `path("baseball/", include("baseball.urls"))`
in the project urls (a new `baseball` Django app), or as a single path inside an
existing app's `urls.py`.

**View conventions (`todo_app/views.py`):**
- All views are class-based and inherit `LoginRequiredMixin` — every page currently
  requires authentication.
- Querysets are always filtered by `owner=self.request.user` (per-user data isolation).
- `accounts/mixins.py` adds a `StaffRequiredMixin` for admin-only pages.

**Templates:**
- Two different base templates exist:
  - `templates/base.html` — **Bootstrap 5**, full navbar (My Lists / Profile / Admin /
    Logout), Django messages framework. This is the main app shell.
  - `todo_app/templates/base.html` — an older **Simple.css** base, minimal.
  - A new baseball page would most naturally extend `templates/base.html` to match the
    current Bootstrap look and navbar.
- No existing JavaScript beyond the Bootstrap bundle CDN; no build step, no SPA
  framework.

### How the two connect (conversion surface)

- The Django side has no game code today. The conversion adds either (a) a Python
  port/import of `baseball/engine.py` with state held server-side, or (b) a
  JavaScript reimplementation of the dice engine running in the browser.
- `baseball/display.py` and the terminal/audio parts of `baseball/game.py` do **not**
  transfer; they are replaced by an HTML template (+ optional JS/CSS).
- The 3-inning, top/bottom, walk-off game-flow logic in `game.py:play_game` is engine
  orchestration that must be re-expressed in whichever architecture is chosen, since
  it currently assumes a blocking `while` loop with `input()`.

## Code References

- `baseball-game/baseball/engine.py:11` — `GameState` (all game state)
- `baseball-game/baseball/engine.py:279` — `resolve_dice_roll` (the played engine)
- `baseball-game/baseball/engine.py:309` — `resolve_action` (dormant swing/pitch engine)
- `baseball-game/baseball/params.py:75` — `DICE_TABLE` (real outcome mapping)
- `baseball-game/baseball/params.py:19` — defaults (3 innings, Robots vs You)
- `baseball-game/baseball/game.py:77` — `play_game` (inning/walk-off orchestration)
- `baseball-game/baseball/game.py:21` — `play_sound` (wav playback, desktop only)
- `baseball-game/baseball/display.py` — terminal rendering (not portable)
- `todo_list/todo_project/urls.py:20` — project URL include table
- `todo_list/todo_app/views.py:9` — CBV + `LoginRequiredMixin` pattern
- `todo_list/templates/base.html` — Bootstrap 5 app shell + navbar
- `todo_list/todo_project/settings.py:12` — INSTALLED_APPS

## Architecture Documentation

- **Django app pattern**: each feature is a separate app with its own `urls.py`,
  `views.py`, `templates/<app>/`, included from `todo_project/urls.py`. A `baseball`
  app would follow this convention.
- **Auth pattern**: `LoginRequiredMixin` on every view; per-user querysets.
- **Styling pattern**: Bootstrap 5 via CDN, extend `templates/base.html`,
  crispy-forms for forms.
- **Console game pattern**: pure engine (`engine.py`) + data (`params.py`) cleanly
  separated from I/O (`display.py`, `game.py`). The engine is the reusable asset.

## Open Questions (decisions required before building — see questions to user)

1. **Where does game state live between turns?** Server-side (Django session or a DB
   model) vs entirely client-side (port engine to JS).
2. **Which gameplay model?** The simple dice-roll the console actually plays, or wire
   up the richer dormant swing/pitch-selection engine for real player choices.
3. **Auth**: require login like every other page, or make `/baseball` public?
4. **Persistence/history**: store finished-game results per user in the DB, or
   ephemeral only?
5. **Sound & pacing**: reproduce sound effects / between-play delays in the browser, or
   drop them?
6. **Visual style**: HTML scoreboard matching Bootstrap shell; how faithful to the
   ASCII diamond/scoreboard layout?

## Conversion Decisions (from user Q&A, 2026-06-25)

These resolve the open questions above and define the target architecture:

1. **State model: Server + DB model.** A new `baseball` Django app with a `Game`
   model (owner FK to the user, game state persisted — e.g. a JSON field plus
   discrete columns for inning/half/outs/scores/bases). Games are resumable across
   sessions. Reuses the Python `engine.py` logic server-side.
   - Likely routes: `GET /baseball/` (list/new game), `POST /baseball/new`,
     `GET /baseball/<id>/`, `POST /baseball/<id>/roll`.
   - The `engine.py` `GameState` should be (de)serialized to/from the model on each
     request rather than kept in memory. `params.py` constants come along unchanged.

2. **Gameplay: dice-roll first, swing/pitch documented for future.** Ship the
   dice-roll engine (`resolve_dice_roll` / `DICE_TABLE`) that the console actually
   plays. The richer swing/pitch system (`resolve_action`, `CONTACT_PROB`,
   `PITCH_TYPES`, `SWING_MENU`) is **explicitly deferred** — keep the code reachable
   and note it as a planned enhancement (batter chooses take/contact/power/bunt,
   pitcher picks pitch type, full ball-strike counts).

3. **Auth: require login.** `/baseball` views use `LoginRequiredMixin` like the rest
   of the app; games are owned by `request.user` and querysets filtered by owner
   (consistent with `todo_app` pattern).

4. **Extras: all kept.**
   - **Choose team names / innings** — a setup form before a game starts, exposing the
     console's `--home` / `--away` / `--innings` options (defaults: You vs Robots, 3
     innings).
   - **Play-by-play pacing** — animate/delay between play-by-play lines client-side
     (JS), since `time.sleep` has no server equivalent.
   - **Sound effects** — reproduce the wav cues (home run, win, play ball) as browser
     audio; the source files live in `baseball-game/mytimer/sounds/` (`1.wav`,
     `5.wav`, `10.wav` per `SOUND_MAP`).
   - **Save game results** — finished games persist in the DB model (already implied
     by decision #1); enables per-user history.

### Implied build outline (for the planning step, not yet implemented)

- New Django app `baseball` registered in `INSTALLED_APPS` and included in
  `todo_project/urls.py`.
- Port `engine.py` + `params.py` into the app (or import them) as the pure logic core;
  drop `display.py` and the terminal/audio/`input()` parts of `game.py`.
- `Game` model + migration; serialize/deserialize `GameState`.
- Views (CBV, `LoginRequiredMixin`): game list/new, setup form, detail, roll (POST).
- Templates extending `templates/base.html` (Bootstrap 5): HTML scoreboard + diamond,
  roll button, play-by-play log, final screen; add a navbar link.
- Static JS/CSS for pacing animation + audio playback; copy the 3 wav files into the
  app's `static/`.
- Re-express the inning / top-bottom / 3-outs / walk-off / extra-innings flow from
  `game.py:play_game` as server-side turn logic driven by the roll endpoint.

---

## Implementation As-Built (2026-06-25)

The `baseball` Django app described above was built and now exists in `todo_list/`.
This section documents the implemented system as it stands today. Implemented per
plan `thoughts/shared/plans/2026-06-25-baseball-web-game.md` (Phases 1–5).

### App layout

```
todo_list/baseball/
  __init__.py
  apps.py                  # BaseballConfig, name = "baseball"
  engine.py                # copied from console; import changed to `from .params import (...)`
  params.py                # copied verbatim from console package
  models.py                # Game model + GameState (de)serialization
  forms.py                 # GameSetupForm (ModelForm)
  views.py                 # 5 CBVs + 2 module helpers
  urls.py                  # 5 named routes
  migrations/0001_initial.py
  templates/baseball/
    game_list.html
    game_setup.html
    game_detail.html
  static/baseball/
    js/game.js
    sounds/{1,5,10}.wav
```

### Registration & routing

- `todo_project/settings.py:24` — `"baseball"` in `INSTALLED_APPS`.
- `todo_project/urls.py:24` — `path("baseball/", include("baseball.urls"))`, placed
  before the root `""` include.
- `todo_project/settings.py:80` — `STATIC_ROOT = BASE_DIR / "staticfiles"` was added
  during Phase 5 so `collectstatic` runs (it was previously absent).
- `templates/base.html:27` — "Baseball" navbar link inside the
  `{% if user.is_authenticated %}` block, after "My Lists".

### Routes (`baseball/urls.py`)

| Name | Path | View | Method |
|------|------|------|--------|
| `baseball-list` | `/baseball/` | `GameListView` | GET |
| `baseball-new` | `/baseball/new/` | `GameCreateView` | GET/POST |
| `baseball-detail` | `/baseball/<int:pk>/` | `GameDetailView` | GET |
| `baseball-roll` | `/baseball/<int:pk>/roll/` | `RollView` | POST (JSON) |
| `baseball-simulate` | `/baseball/<int:pk>/simulate/` | `SimulateView` | POST (JSON) |

### `Game` model (`baseball/models.py:6`)

Fields (migration `0001_initial`): `owner` (FK → AUTH_USER_MODEL,
`related_name="baseball_games"`, CASCADE), `away_name`/`home_name` (CharField 50),
`total_innings` (PositiveSmallInteger, default 3), `mode` (CharField, choices
`cpu_auto`/`click_all`/`auto_play`), `state` (JSONField — serialized GameState),
`play_log` (JSONField, default list), `status` (CharField, choices
`active`/`finished`, default `active`), `created_at`/`updated_at`. `Meta.ordering =
["-created_at"]`.

Serialization helpers on the model:
- `state_to_dict(GameState)` / `state_from_dict(dict)` — round-trip the 13 GameState
  attrs (`models.py:37`, `models.py:50`). Note: `batting_team`/`current_batter` are
  GameState **properties**, not serialized; they are recomputed on load.
- `load_state()` / `save_state(gs)` — instance wrappers (`models.py:66`).

### Three gameplay modes

Selected at creation in `GameSetupForm` (`forms.py:5`, `mode` rendered as
`RadioSelect`, Bootstrap widget classes on text/number fields, initial values
Robots / You / 3 innings). All driven by the same per-at-bat engine; the mode only
changes which side the browser auto-rolls and when it waits for a click:

- **`click_all`** — user clicks "Roll Dice" for every at-bat (both teams).
- **`cpu_auto`** — away (CPU) half auto-rolls at ~1.2 s pace; the button enables for
  the home half; alternates each inning.
- **`auto_play`** — one click POSTs to `SimulateView`, server sims the whole game,
  browser replays all plays with pacing + sound.

### Turn orchestration (server)

The console's blocking `play_game`/`play_half` `while` loop is re-expressed as a
single stateless helper:

- `_advance_game(gs)` (`views.py:30`) — runs one at-bat via `resolve_dice_roll(gs)`,
  then `reset_count()` + `advance_lineup()`, then applies half/inning transition,
  walk-off, and game-over logic. Returns a JSON-ready dict.
- `_state_snapshot(gs)` (`views.py:12`) — the minimal dict the JS scoreboard reads
  (inning, half, outs, balls, strikes, bases, scores, `batting_team`,
  `current_batter`, `game_over`, team names).
- Each play dict carries `play_half` + `play_inning`, captured **before** the
  transition mutates state, so play-log labels show the inning/half the play
  occurred in (deviation from the original plan, which read these post-mutation).
- `RollView` (`views.py:114`) appends one play to `play_log`, persists state, flips
  `status` to `finished` on game over. `SimulateView` (`views.py:129`) loops
  `_advance_game` to completion, replaces `play_log` with the full list, sets
  `finished`. Both 400 if already finished. All four CBVs use `LoginRequiredMixin`;
  list/detail querysets filter by `owner=request.user`.
- `GameDetailView.get_context_data` (`views.py:102`) injects `current_batter`,
  `batting_team`, and (when finished) `winner` — values not present in the
  serialized `state` dict.

### Engine

`baseball/engine.py` is the console `engine.py` copied verbatim except line 5,
`from .params import (...)`. `resolve_dice_roll` (`engine.py:279`) is the played
engine; the dormant swing/pitch system (`resolve_action` etc.) came along in the
copy but remains uncalled, as planned. `params.py` copied verbatim.

### Templates

- `game_list.html` — table of the user's games (away/home/innings/mode badge/status
  badge/score) with Resume (active) or View (finished) links; empty state.
- `game_setup.html` — the `GameSetupForm` with per-field error blocks; mode as radio
  list; "Play Ball!" submit.
- `game_detail.html` — scoreboard card (inning label, both teams with `← batting`
  marker, outs, ASCII diamond, current batter), dice-result card, action area
  (Play Ball button for `auto_play`, Roll Dice otherwise, or final banner when
  finished), and a play-by-play log. Injects JS config consts (`GAME_MODE`,
  `GAME_STATUS`, `ROLL_URL`, `SIM_URL`, sound URLs, `TOTAL_INN`). The `#diamond`
  div carries `data-half` and `data-bases` for JS init. CSRF token lives in a hidden
  `#csrf-form` for fetch POSTs.

### Client JS (`static/baseball/js/game.js`)

- Reads injected consts; wires one of `initClickAll` / `initCpuAuto` / `initAutoPlay`
  by `GAME_MODE` when `GAME_STATUS === 'active'`.
- `doRoll()` / `doSimulate()` POST with `X-CSRFToken`; `handlePlay()` shows dice,
  appends to log, updates scoreboard, plays the home-run cue, paces with `sleep`
  (1400 ms HR / 900 ms otherwise, +600 ms on half change).
- `updateScoreboard` updates `#sb-half` and `#sb-inning` spans **individually**.
  `updateDiamond` renders the ASCII diamond from the `bases` array.
- `showGameOver` builds the final banner with `document.createElement` +
  `textContent` (no innerHTML interpolation of team names) — XSS-safe.
- Sound via `Audio`: `5.wav` home run, `10.wav` win, `1.wav` play ball. Files copied
  from `baseball-game/mytimer/sounds/` into `static/baseball/sounds/`.

### Bugs fixed during/after implementation

1. **Phase 5 — static config.** `STATIC_ROOT` was unset; `collectstatic` failed with
   `ImproperlyConfigured`. Added `STATIC_ROOT = BASE_DIR / "staticfiles"`.
2. **Post-implementation — scoreboard crash every 2 rolls.** `updateScoreboard`
   originally set `.textContent` on the `#sb-inning-label` card header, which
   destroyed its child `<span id="sb-inning">`. The next roll's
   `getElementById('sb-inning')` returned `null` and threw, leaving the Roll button
   disabled (user had to refresh). Fixed by wrapping the half word in
   `<span id="sb-half">` and updating `#sb-half` + `#sb-inning` independently rather
   than rewriting the parent. This also unblocked the `cpu_auto` auto-roll loop.
3. **Post-implementation — XSS hardening.** `showGameOver` originally interpolated
   team names into `innerHTML`; rewritten to use DOM nodes + `textContent`.

### As-built code references

- `todo_list/baseball/models.py:6` — `Game` model
- `todo_list/baseball/views.py:30` — `_advance_game` (turn orchestration)
- `todo_list/baseball/views.py:114` — `RollView`; `:129` — `SimulateView`
- `todo_list/baseball/urls.py:4` — route table
- `todo_list/baseball/static/baseball/js/game.js` — client driver for all 3 modes
- `todo_list/baseball/templates/baseball/game_detail.html` — scoreboard + log DOM
- `todo_list/todo_project/settings.py:80` — `STATIC_ROOT`
- `todo_list/templates/base.html:27` — navbar link

### Status

Automated success criteria pass: `manage.py check`, `makemigrations --check`,
engine import smoke test, `Game._meta.fields`, `collectstatic`. Manual playthrough
verification (all three modes to completion, sound, persistence, XSS, multi-user
isolation) is the remaining open item.
