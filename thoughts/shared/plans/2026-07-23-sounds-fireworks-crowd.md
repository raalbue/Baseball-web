# Home-Run Fireworks, Layered Hit/Strikeout Sounds, and Crowd Imagery Implementation Plan

## Overview

Add richer audio-visual feedback to the live game view (`baseball/templates/baseball/game_detail.html`): distinct sounds for singles/doubles/triples, a crowd-cheer layered on top of the existing home-run crack, a CSS/JS particle fireworks burst on home runs, a "ring him up"-slot buzzer sound on strikeouts, and a procedurally-drawn crowd frame around the field that briefly brightens on home runs.

## Current State Analysis

- Sound system: three `.wav` files (`baseball/static/baseball/sounds/{1,5,10}.wav` = play-ball/home-run/win), loaded as `Audio` objects in a `sfx` map (`baseball/static/baseball/js/game.js:6-17`), triggered via `playSound(key)`. Only `home_run`, `win`, and `play_ball` (autoplay-start only) currently fire — no sound plays for singles/doubles/triples/strikeouts today.
- Visual effects: zero CSS `@keyframes`/`transition`/`animation` exist anywhere in the baseball app (confirmed in `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`). The stadium is flat-color inline SVG built server-side from `baseball/data/stadiums.json` (`baseball/stadiums.py:21-35`, rendered `game_detail.html:37-65`). No crowd/photo imagery exists anywhere in the repo.
- `handlePlay(play)` (`baseball/static/baseball/js/game.js:178-192`) is the single chokepoint every game mode routes through per at-bat (`click_all`, `cpu_auto`, `auto_play`'s loop, `multiplayer`) — it already special-cases `play.outcome === 'home_run'` for the existing crack sound. New sound/fireworks/crowd triggers hook into this same function so all four modes get them for free.
- `play.outcome` values already match the strings we need for dispatch: `"single"`, `"double"`, `"triple"`, `"home_run"`, `"strikeout"` (from `DICE_TABLE`/`apply_in_play` in `baseball/engine.py`) — no new backend data is needed, this is a frontend-only change.

### Key Discoveries:

- **Static-file hazard**: `baseball_project/settings.py:86-93` configures `STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedManifestStaticFilesStorage"`, a manifest-strict storage. `{% static %}` tags for a file **not yet in `staticfiles/staticfiles.json`** raise a hard `ValueError` at template-render time — this applies locally under `runserver`/DEBUG too, not just in production, because this project has no DEBUG-conditional storage swap. This means: new sound files must physically exist **and** `python manage.py collectstatic` must be re-run **before** any `{% static %}` tag referencing them is added to a template, or the entire game page 500s.
- **No `ffmpeg` available** in this environment (confirmed via `which ffmpeg` — not found), so the one sound sourced by direct download (`single.ogg`, Ogg Vorbis) cannot be transcoded to `.wav`/`.mp3` here. Ogg Vorbis is unsupported in Safari; `playSound()`'s existing `a.play().catch(() => {})` (`game.js:12-17`) already swallows playback failures silently, so this degrades gracefully (no crack sound in Safari for singles) rather than breaking anything — documented as a known limitation, not fixed.
- Asset sourcing research (web search) found exactly one directly-curlable CC0 file (`single.ogg`); everything else needs a manual browser download because Mixkit's download buttons are JS-gated (no login required, just not scriptable) and no free clip of the literal phrase "ring him up" exists anywhere. Per user decision, the plan uses a generic buzzer as the strikeout sound placeholder (swappable later) and treats the other 3 files as a manual one-time download step.

## Desired End State

On the live game page, home runs trigger the existing crack sound plus a crowd-cheer sound, a canvas-free CSS particle fireworks burst over the field, and a brief brightness pulse on a new procedural crowd frame around the stadium card. Singles, doubles, and triples each play a distinct, escalating bat-crack sound. Strikeouts play a buzzer sound. All of this fires identically across all four game modes (`click_all`, `cpu_auto`, `auto_play`, `multiplayer`) since it hooks into the shared `handlePlay()` function.

### Verification
- `python manage.py check` passes.
- `python manage.py collectstatic --noinput` succeeds and `staticfiles/staticfiles.json` contains entries for all 5 new/reused sound keys.
- Manually playing a game in each of the 4 modes shows: distinct sound per single/double/triple, home run plays crack+cheer+fireworks+crowd-pulse together, strikeout plays the buzzer, crowd frame renders on page load, no browser console errors, no 500s.

## What We're NOT Doing

- Not sourcing or including an actual "ring him up" voice clip — none exists freely; a generic buzzer placeholder is used instead (user's explicit choice), swappable later by replacing one file.
- Not adding sound for walks, groundouts, flyouts, sacrifices, or the game-start/win sounds — out of scope, unchanged.
- Not touching the dead `SOUND_MAP` constant in `baseball/params.py:123-127` — confirmed unreferenced, not part of this feature.
- Not building a per-stadium-accurate crowd (e.g. seat-by-seat SVG tied to `stadiums.json` geometry) — a single reusable CSS pattern frames every stadium identically, regardless of park.
- Not transcoding `single.ogg` to a Safari-compatible format — no `ffmpeg` available in this environment; documented as a known gap.
- Not adding server-side/backend changes — this entire feature is static assets + template + `game.js`.

## Implementation Approach

Four phases, each independently testable in the browser: (1) gather/place the 5 sound files and get them into the manifest, (2) wire up the 4 new sound triggers, (3) fireworks particle effect, (4) procedural crowd frame + reactive pulse. Phase 1 is a hard prerequisite gate for Phase 2 because of the manifest-strict static storage — its manual-verification step must pass before any `{% static %}` reference to the new files is added.

## Phase 1: Sound asset acquisition

### Overview
Get all 5 sound files (1 auto-downloaded, 4 manual) onto disk at `baseball/static/baseball/sounds/`, then run `collectstatic` so the manifest knows about them.

### Changes Required:

#### 1. Auto-downloadable file
**Action**: Download the one verified CC0, no-login-required direct file.

```bash
curl -L -o baseball/static/baseball/sounds/single.ogg \
  https://opengameart.org/sites/default/files/baseballbat_1.ogg
```
(License: CC0 / public domain, OpenGameArt.org "RPG Sound Effect Pack" by Delta12 Studio.)

#### 2. Manual downloads (user action required)
**Action**: Visit each page in a browser, download, and save to the exact target path/filename below. All are free/no-login-required per the source sites' stated policy; licenses noted for reference.

| Target file | Source | What to grab | License |
|---|---|---|---|
| `baseball/static/baseball/sounds/crowd_cheer.mp3` | https://mixkit.co/free-sound-effects/crowd/ | A short (~2-4s) stadium crowd cheer/roar clip (e.g. "Male crowd cheering short") | Mixkit License (free commercial use, no attribution) |
| `baseball/static/baseball/sounds/strikeout_buzzer.mp3` | https://mixkit.co/free-sound-effects/buzzer/ | A short (~1-2s) negative-tone buzzer (e.g. "Wrong answer bass buzzer") | Mixkit License |
| `baseball/static/baseball/sounds/double.wav` | https://opengameart.org/sites/default/files/100-CC0-wood-metal-SFX.zip | From the extracted zip, pick a wood-crack sample louder/sharper than `single.ogg` | CC0 |
| `baseball/static/baseball/sounds/triple.wav` | (same zip as above) | Pick a second wood-crack sample, louder again than the one chosen for `double.wav`, but still distinguishable from the existing home-run crack (`5.wav`) | CC0 |

#### 3. Refresh the static manifest
**File**: n/a (build step)
**Changes**: Re-run collectstatic so `staticfiles/staticfiles.json` picks up the 5 new/changed files.

```bash
python manage.py collectstatic --noinput
```
(Use `.\venv\Scripts\python.exe manage.py collectstatic --noinput` if `python` isn't on PATH.)

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py collectstatic --noinput` exits 0
- [x] `staticfiles/staticfiles.json` contains keys for the new sound files (see note on actual filenames below)

#### Manual Verification:
- [ ] All 7 files exist under `baseball/static/baseball/sounds/` and are non-empty, playable audio files
- [ ] `double.ogg` and `triple.ogg` sound progressively louder/bigger than `single.ogg`, and `triple.ogg`/`home_run_wood.ogg` are still distinguishable from each other

**Implementation Note**: This phase must fully complete (files present + collectstatic succeeded) before Phase 2 adds any `{% static %}` reference to these files — the manifest-strict storage will otherwise 500 the entire game page.

**Deviation from original plan (user-supplied files, not the sourced CC0/Mixkit ones listed above)**:
- `single.ogg` — auto-downloaded as planned (OpenGameArt CC0 baseball bat crack)
- `double.ogg`, `triple.ogg` — user's own `wood_slam_01.ogg`/`wood_slam_04.ogg` from a local `100-CC0-wood-metal-SFX` download (not `.wav` as originally planned)
- `home_run_wood.ogg` — **new file, not in original plan** — user's `wood_slam_02.ogg`, layered under the existing `5.wav` crack on home runs
- `crowd_cheer.wav` — user's `mixkit-huge-crowd-cheering-victory-462.wav` (not `.mp3`); per user instruction, plays **after** the wood-slam sound finishes, not overlapping as originally planned — Phase 2 must sequence this (e.g. wait for the wood sound's `ended` event or a fixed delay) rather than firing both immediately
- `strikeout_trombone.wav` — user's `mixkit-slow-sad-trombone-fail-472.wav` in place of the generic buzzer placeholder (not `.mp3`)

Phase 2's `{% static %}` const list and `sfx` map must reference these actual filenames/extensions, and the home-run branch needs sequential (not simultaneous) playback for the wood-slam → crowd-cheer pair.

---

## Phase 2: Sound triggers

### Overview
Wire the 5 sound files into `game_detail.html`'s JS-config block and `game.js`'s `sfx` map, and dispatch on `play.outcome` inside `handlePlay()`.

### Changes Required:

#### 1. New static URL globals
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Extend the existing JS config `<script>` block (currently lines 19-32) with 5 new `const` lines, right after the existing `SOUND_*` lines (28-30):

```html
const SOUND_CROWD     = "{% static 'baseball/sounds/crowd_cheer.mp3' %}";
const SOUND_SINGLE    = "{% static 'baseball/sounds/single.ogg' %}";
const SOUND_DOUBLE    = "{% static 'baseball/sounds/double.wav' %}";
const SOUND_TRIPLE    = "{% static 'baseball/sounds/triple.wav' %}";
const SOUND_STRIKEOUT = "{% static 'baseball/sounds/strikeout_buzzer.mp3' %}";
```

#### 2. Extend `sfx` map
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Replace the current `sfx` object (`game.js:6-10`):

```js
const sfx = {
    play_ball: new Audio(SOUND_PLAY),
    home_run:  new Audio(SOUND_HR),
    win:       new Audio(SOUND_WIN),
};
```

with:

```js
const sfx = {
    play_ball:   new Audio(SOUND_PLAY),
    home_run:    new Audio(SOUND_HR),
    win:         new Audio(SOUND_WIN),
    crowd_cheer: new Audio(SOUND_CROWD),
    single:      new Audio(SOUND_SINGLE),
    double:      new Audio(SOUND_DOUBLE),
    triple:      new Audio(SOUND_TRIPLE),
    strikeout:   new Audio(SOUND_STRIKEOUT),
};
```

#### 3. Dispatch in `handlePlay`
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Replace the single home-run check (`game.js:186`):

```js
if (play.outcome === 'home_run') playSound('home_run');
```

with:

```js
if (play.outcome === 'home_run') {
    playSound('home_run');
    playSound('crowd_cheer');
} else if (play.outcome === 'single' || play.outcome === 'double' || play.outcome === 'triple') {
    playSound(play.outcome);
} else if (play.outcome === 'strikeout') {
    playSound('strikeout');
}
```

(Phases 3 and 4 will each add one more line inside the `home_run` branch — `launchFireworks();` and `pulseCrowd();` respectively — rather than redoing this block.)

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] Play a `click_all` game: singles, doubles, triples each produce an audibly distinct crack sound
- [ ] A home run plays crack + wood-slam together, then crowd cheer fires once the wood-slam sound ends (sequential, per user's explicit instruction — deviates from original plan's "overlapping" spec)
- [ ] A strikeout plays the sad-trombone sound
- [ ] Walks/groundouts/flyouts/sacrifices remain silent (unchanged)
- [ ] No browser console errors on any play

**Deviation from original plan**: implemented with user-supplied files (see Phase 1 note) and an additional `home_run_wood` sfx key layered under the existing crack; crowd cheer is sequenced via the wood-slam `Audio`'s `ended` event rather than firing simultaneously.

---

## Phase 3: Fireworks on home runs

### Overview
A CSS-keyframe particle burst rendered over the stadium SVG, triggered alongside the existing home-run sound.

### Changes Required:

#### 1. Overlay container + CSS keyframes
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Give the stadium `card-body` a positioning context and add an overlay div. Current (lines 40-63):

```html
      <div class="card-body">
        <div id="diamond"
             data-half="{{ game.state.half }}"
             data-bases="{{ game.state.bases|join:',' }}">
```

becomes:

```html
      <div class="card-body" style="position:relative;">
        <div id="fireworks-overlay"></div>
        <div id="diamond"
             data-half="{{ game.state.half }}"
             data-bases="{{ game.state.bases|join:',' }}">
```

Extend the existing `<style>` block (`game_detail.html:5-13`) with:

```css
#fireworks-overlay {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 5;
}
.firework-particle {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  pointer-events: none;
  animation: firework-burst 900ms ease-out forwards;
}
@keyframes firework-burst {
  0%   { transform: translate(0, 0) scale(1);              opacity: 1; }
  100% { transform: translate(var(--dx), var(--dy)) scale(.3); opacity: 0; }
}
```

#### 2. Particle-spawning JS
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Add near the other DOM-helper functions (after `updateDiamond`, `game.js:44`):

```js
const FIREWORK_COLORS = ['#ffd400', '#ff4d4d', '#4dc3ff', '#7cfc00', '#ffffff', '#ff8fd8'];

function launchFireworks() {
    const overlay = document.getElementById('fireworks-overlay');
    if (!overlay) return;
    for (let burst = 0; burst < 3; burst++) {
        setTimeout(() => {
            const originX = 30 + Math.random() * 40;
            const originY = 15 + Math.random() * 25;
            for (let i = 0; i < 24; i++) {
                const angle = (Math.PI * 2 * i) / 24;
                const dist = 60 + Math.random() * 60;
                const p = document.createElement('span');
                p.className = 'firework-particle';
                p.style.left = originX + '%';
                p.style.top = originY + '%';
                p.style.setProperty('--dx', Math.cos(angle) * dist + 'px');
                p.style.setProperty('--dy', Math.sin(angle) * dist + 'px');
                p.style.background = FIREWORK_COLORS[Math.floor(Math.random() * FIREWORK_COLORS.length)];
                overlay.appendChild(p);
                setTimeout(() => p.remove(), 950);
            }
        }, burst * 300);
    }
}
```

Then update the `home_run` branch added in Phase 2 (`handlePlay`) to:

```js
if (play.outcome === 'home_run') {
    playSound('home_run');
    playSound('crowd_cheer');
    launchFireworks();
}
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] A home run triggers a visible multi-colored particle burst over the field that fades out within ~1s
- [ ] Particles don't block clicks on anything underneath (`pointer-events: none` confirmed by clicking through the overlay area)
- [ ] No leftover particle DOM nodes accumulate after several home runs (spot-check via browser dev tools element count)

---

## Phase 4: Crowd imagery

### Overview
A procedural CSS dot-pattern "stands" frame wrapping the stadium card, with a brightness pulse on home runs.

### Changes Required:

#### 1. Wrap the stadium card
**File**: `baseball/templates/baseball/game_detail.html`
**Changes**: Current (lines 37-65, abbreviated):

```html
  <div class="col-md-6">
    <div class="card mb-3">
      <div class="card-header fw-bold text-center">{{ stadium.name }}</div>
      <div class="card-body" style="position:relative;">
        ...
      </div>
    </div>
  </div>
```

becomes:

```html
  <div class="col-md-6">
    <div class="crowd-frame" id="crowd-frame">
      <div class="card mb-3">
        <div class="card-header fw-bold text-center">{{ stadium.name }}</div>
        <div class="card-body" style="position:relative;">
          ...
        </div>
      </div>
    </div>
  </div>
```

Extend the `<style>` block with:

```css
.crowd-frame {
  padding: 20px 14px 4px;
  border-radius: 10px 10px 0 0;
  background-color: #5b4636;
  background-image:
    radial-gradient(circle, #e8b86d 35%, transparent 36%),
    radial-gradient(circle, #c97b63 35%, transparent 36%),
    radial-gradient(circle, #7a8f9e 35%, transparent 36%),
    radial-gradient(circle, #d9c27e 35%, transparent 36%);
  background-size: 16px 16px;
  background-position: 0 0, 8px 4px, 4px 10px, 12px 12px;
  filter: brightness(1);
  transition: filter .5s ease;
}
.crowd-frame.cheering {
  filter: brightness(1.7);
}
```

#### 2. Reactive pulse JS
**File**: `baseball/static/baseball/js/game.js`
**Changes**: Add near `launchFireworks()`:

```js
function pulseCrowd() {
    const frame = document.getElementById('crowd-frame');
    if (!frame) return;
    frame.classList.add('cheering');
    setTimeout(() => frame.classList.remove('cheering'), 1200);
}
```

Update the `home_run` branch in `handlePlay` (final form):

```js
if (play.outcome === 'home_run') {
    playSound('home_run');
    playSound('crowd_cheer');
    launchFireworks();
    pulseCrowd();
}
```

### Success Criteria:

#### Automated Verification:
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] The stadium card now sits inside a visible multi-colored dotted "stands" frame on page load, for every stadium
- [ ] A home run briefly brightens the crowd frame (~1.2s) and it settles back to normal
- [ ] Frame doesn't visually clip or overlap the field SVG/scoreboard content at common browser widths (desktop + narrow window)

---

## Testing Strategy

### Manual Testing Steps:
1. Start a `click_all` game, manually trigger at-bats until you see a single, a double, a triple, a strikeout, and a home run — confirm each has its expected sound, and the home run also fires fireworks + crowd pulse.
2. Start an `auto_play` game and let it simulate/replay a full game client-side (no page reloads mid-game) — confirm sounds/fireworks/crowd-pulse still fire correctly across the tight replay loop, and no particle DOM buildup after many home runs.
3. Start a `cpu_auto` game, let the CPU bat — confirm sounds fire during the CPU's automated turns, not just the human's.
4. Start (or join) a `multiplayer` game — confirm sounds/effects fire on both the acting player's turn and reflect correctly after their opponent's reload-polled turn.
5. Check the browser console throughout for any errors (missing file 404s should silently no-op per `playSound`'s existing `.catch()`, not throw).

## Performance Considerations

Fireworks spawn up to 3 × 24 = 72 short-lived DOM nodes per home run, each self-removing via `setTimeout` after ~950ms — negligible for a turn-based game with one home run at a time; no cleanup beyond the existing per-particle `setTimeout` removal is needed.

## Migration Notes

None — this is a static-asset and frontend-only change; no database/model changes.

## References
- Related research: `thoughts/shared/research/2026-07-23-game-effects-scoreboard-streaky-player.md`
- `baseball/static/baseball/js/game.js:6-17` — existing `sfx`/`playSound()`
- `baseball/static/baseball/js/game.js:178-192` — `handlePlay()`, the shared per-play hook used by all 4 modes
- `baseball/templates/baseball/game_detail.html:5-13,19-32,37-65` — existing style block, JS config globals, stadium card markup
- `baseball_project/settings.py:86-93` — manifest-strict static storage (the ordering hazard this plan's Phase 1 works around)
