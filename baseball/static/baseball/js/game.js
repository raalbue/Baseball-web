/* Baseball web game — drives all three play modes. */

const CSRF = () =>
    document.querySelector('#csrf-form [name=csrfmiddlewaretoken]').value;

const OUT_FLASH_MS = 500;
const RUNNER_ANIM_MS = 550;

const sfx = {
    play_ball:     new Audio(SOUND_PLAY),
    home_run:      new Audio(SOUND_HR),
    win:           new Audio(SOUND_WIN),
    home_run_wood: new Audio(SOUND_HR_WOOD),
    crowd_cheer:   new Audio(SOUND_CROWD),
    single:        new Audio(SOUND_SINGLE),
    double:        new Audio(SOUND_DOUBLE),
    triple:        new Audio(SOUND_TRIPLE),
    strikeout:     new Audio(SOUND_STRIKEOUT),
};

sfx.strikeout.playbackRate = 3;

function playSound(key) {
    const a = sfx[key];
    if (!a) return;
    a.currentTime = 0;
    a.play().catch(() => {});
}

function playHomeRunSounds() {
    playSound('home_run');
    playSound('home_run_wood');
    playSound('crowd_cheer');
}

// --- DOM helpers -----------------------------------------------------------

function lineCells(line, numCols, currentInning, isActiveHalf, runsThisHalf) {
    const cells = [];
    for (let n = 1; n <= numCols; n++) {
        if (n <= line.length) cells.push(line[n - 1]);
        else if (n === currentInning && isActiveHalf) cells.push(runsThisHalf);
        else cells.push(null);
    }
    return cells;
}

function currentColumnCount() {
    return document.querySelectorAll('#board-away-row .board-cell').length;
}

function ensureColumns(n) {
    const have = currentColumnCount();
    if (n <= have) return;
    const headRow = document.getElementById('board-header-row');
    const awayRow = document.getElementById('board-away-row');
    const homeRow = document.getElementById('board-home-row');
    for (let i = have + 1; i <= n; i++) {
        const th = document.createElement('th');
        th.textContent = i;
        headRow.insertBefore(th, headRow.querySelector('.board-total-col'));

        const tdA = document.createElement('td');
        tdA.className = 'board-cell';
        tdA.id = `board-away-${i}`;
        tdA.innerHTML = '<span class="flip-value"></span>';
        awayRow.insertBefore(tdA, awayRow.querySelector('.board-total-col'));

        const tdH = document.createElement('td');
        tdH.className = 'board-cell';
        tdH.id = `board-home-${i}`;
        tdH.innerHTML = '<span class="flip-value"></span>';
        homeRow.insertBefore(tdH, homeRow.querySelector('.board-total-col'));
    }
}

function setCell(id, value) {
    const cell = document.getElementById(id);
    if (!cell) return;
    const span = cell.querySelector('.flip-value');
    const text = (value === null || value === '') ? '' : String(value);
    if (span.textContent === text) return;
    span.classList.remove('flipping');
    void span.offsetWidth;  // restart animation
    span.textContent = text;
    span.classList.add('flipping');
}

function updateOuts(n) {
    for (let i = 1; i <= 3; i++) {
        document.getElementById(`out-dot-${i}`).classList.toggle('lit', i <= n);
    }
}

function updateBoard(state) {
    const numCols = Math.max(TOTAL_INN, state.inning, state.away_line.length, state.home_line.length);
    ensureColumns(numCols);

    const awayCells = lineCells(state.away_line, numCols, state.inning, state.half === 'top', state.runs_this_half);
    const homeCells = lineCells(state.home_line, numCols, state.inning, state.half === 'bottom', state.runs_this_half);
    awayCells.forEach((v, i) => setCell(`board-away-${i + 1}`, v));
    homeCells.forEach((v, i) => setCell(`board-home-${i + 1}`, v));

    document.getElementById('board-away-r').textContent = state.away_score;
    document.getElementById('board-home-r').textContent = state.home_score;
    document.getElementById('board-away-h').textContent = state.away_hits;
    document.getElementById('board-home-h').textContent = state.home_hits;

    document.getElementById('board-away-bat').textContent = state.half === 'top' ? '▶' : '';
    document.getElementById('board-home-bat').textContent = state.half === 'bottom' ? '▶' : '';

    document.getElementById('board-batter').textContent = state.current_batter;
    const lineEl = document.getElementById('board-batter-line');
    if (lineEl) lineEl.textContent = state.batter_line ? `(${state.batter_line})` : '';

    updateOuts(state.outs);
    updateDiamond(state.bases, RUNNER_ANIM_MS);
    updatePitching(state);
}

function staminaColorClass(stamina) {
    if (stamina <= 25) return 'bg-danger';
    if (stamina <= 50) return 'bg-warning';
    return 'bg-success';
}

function setStaminaBar(id, stamina) {
    const bar = document.getElementById(id);
    if (!bar) return;
    bar.style.width = stamina + '%';
    bar.classList.remove('bg-success', 'bg-warning', 'bg-danger');
    bar.classList.add(staminaColorClass(stamina));
}

function updatePitching(state) {
    if (state.away_pitcher) {
        document.getElementById('away-pitcher-name').textContent = state.away_pitcher.name || '—';
        setStaminaBar('away-pitcher-stamina', state.away_pitcher.stamina);
    }
    if (state.home_pitcher) {
        document.getElementById('home-pitcher-name').textContent = state.home_pitcher.name || '—';
        setStaminaBar('home-pitcher-stamina', state.home_pitcher.stamina);
    }
}

function updateDiamond(bases, delayMs = 0) {
    const apply = () => {
        document.getElementById('base-marker-1').classList.toggle('occupied', !!bases[0]);
        document.getElementById('base-marker-2').classList.toggle('occupied', !!bases[1]);
        document.getElementById('base-marker-3').classList.toggle('occupied', !!bases[2]);
    };
    if (delayMs > 0) setTimeout(apply, delayMs); else apply();
}

function baseCoord(marker) {
    const id = (marker === 'home' || marker === 'batter') ? 'home-plate-marker' : `base-marker-${marker}`;
    const el = document.getElementById(id);
    return el ? { x: +el.getAttribute('cx'), y: +el.getAttribute('cy') } : null;
}

function animateRunners(moves) {
    if (!moves || !moves.length) return;
    const svg = document.querySelector('#diamond svg');
    if (!svg) return;
    moves.forEach((mv) => {
        const from = baseCoord(mv.from);
        if (!from) return;
        const token = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        token.setAttribute('class', 'runner-token');
        token.setAttribute('cx', from.x);
        token.setAttribute('cy', from.y);
        token.setAttribute('r', 5);
        svg.appendChild(token);
        requestAnimationFrame(() => {
            const to = mv.to === 'out' ? from : baseCoord(mv.to);
            if (to) {
                token.setAttribute('cx', to.x);
                token.setAttribute('cy', to.y);
            }
            if (mv.to === 'out' || mv.to === 'home') {
                token.classList.add('runner-token-fade');
            }
        });
        setTimeout(() => token.remove(), RUNNER_ANIM_MS + 350);
    });
}

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

function pulseCrowd() {
    const frame = document.getElementById('crowd-frame');
    if (!frame) return;
    frame.classList.add('cheering');
    setTimeout(() => frame.classList.remove('cheering'), 2400);
}

function methodTag(method) {
    return (method || 'dice') === 'dice' ? '(🎲)' : '(📊)';
}

function streakyTag(streaky) {
    return streaky ? ' 🔥' : '';
}

function showDice(d1, d2, outcome, method) {
    document.getElementById('dice-roll').textContent = `[${d1}]  [${d2}]`;
    document.getElementById('dice-outcome').textContent =
        `${outcome.replace(/_/g, ' ').toUpperCase()} ${methodTag(method)}`;
}

let inExtraInnings = false;

function appendPlay(play) {
    const log = document.getElementById('play-log');
    const empty = document.getElementById('log-empty');
    if (empty) empty.remove();
    if (!inExtraInnings && play.play_inning > TOTAL_INN) {
        inExtraInnings = true;
        const sep = document.createElement('p');
        sep.className = 'text-center fw-bold text-danger my-2';
        sep.textContent = '========= E X T R A   I N N I N G S =========';
        log.prepend(sep);
    }
    const p = document.createElement('p');
    p.className = 'mb-1';
    const half = play.play_half === 'top' ? 'TOP' : 'BOT';
    let html = `[${half} ${play.play_inning}] ⚾ [${play.d1}][${play.d2}] — ${play.message}`;
    if (play.commentary) html += `<br><span class="text-muted fst-italic">${play.commentary}</span>`;
    html += ` ${methodTag(play.method)}${streakyTag(play.streaky)}`;
    p.innerHTML = html;
    log.prepend(p);
    log.scrollTop = 0;
}

function showGameOver(state) {
    const winner = state.away_score > state.home_score
        ? state.away_name
        : (state.home_score > state.away_score ? state.home_name : null);

    const div = document.createElement('div');
    div.className = 'alert alert-success fw-bold fs-5 mb-0';

    const headline = document.createTextNode(winner ? winner + ' win!' : "It's a tie!");
    div.appendChild(headline);

    div.appendChild(document.createElement('br'));

    const small = document.createElement('small');
    small.className = 'fw-normal';
    small.textContent =
        state.away_name + ' ' + state.away_score + ' – ' + state.home_score + ' ' + state.home_name;
    div.appendChild(small);

    div.appendChild(document.createElement('br'));

    const link = document.createElement('a');
    link.href = '/baseball/';
    link.className = 'btn btn-outline-success btn-sm mt-2';
    link.textContent = 'Back to games';
    div.appendChild(link);

    if (SEASON_ID) {
        const seasonWrap = document.createElement('div');
        seasonWrap.className = 'mt-2';
        const seasonLink = document.createElement('a');
        seasonLink.href = SEASON_URL;
        seasonLink.className = 'btn btn-outline-primary btn-sm';
        seasonLink.textContent = 'Continue Season';
        seasonWrap.appendChild(seasonLink);
        div.appendChild(seasonWrap);
    } else if (GAME_MODE !== 'multiplayer') {
        const replayWrap = document.createElement('div');
        replayWrap.className = 'mt-2 d-flex align-items-center gap-2';

        const replayBtn = document.createElement('button');
        replayBtn.type = 'button';
        replayBtn.id = 'btn-replay';
        replayBtn.className = 'btn btn-outline-primary btn-sm';
        replayBtn.textContent = '🔁 Replay';
        replayWrap.appendChild(replayBtn);

        const autoplayLabel = document.createElement('label');
        autoplayLabel.className = 'form-check-label small mb-0';
        autoplayLabel.htmlFor = 'chk-autoplay';
        const autoplayChk = document.createElement('input');
        autoplayChk.type = 'checkbox';
        autoplayChk.id = 'chk-autoplay';
        autoplayChk.className = 'form-check-input me-1';
        autoplayLabel.appendChild(autoplayChk);
        autoplayLabel.appendChild(document.createTextNode('Autoplay'));
        replayWrap.appendChild(autoplayLabel);

        div.appendChild(replayWrap);
    }

    const btnArea = document.getElementById('btn-area');
    btnArea.innerHTML = '';
    btnArea.appendChild(div);

    wireReplayButton();
    playSound('win');
}

// --- Replay ------------------------------------------------------------

async function doReplay(btn, autoplay) {
    btn.disabled = true;
    btn.textContent = 'Starting…';
    const resp = await fetch(REPLAY_URL, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ autoplay }),
    });
    const data = await resp.json();
    if (data.redirect_url) location.href = data.redirect_url;
}

function wireReplayButton() {
    const btn = document.getElementById('btn-replay');
    if (!btn) return;
    const chk = document.getElementById('chk-autoplay');
    btn.addEventListener('click', () => doReplay(btn, !!(chk && chk.checked)));
}

// --- Roll mechanics --------------------------------------------------------

async function doRoll() {
    const resp = await fetch(ROLL_URL, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF(), 'Content-Type': 'application/json' },
    });
    return resp.json();
}

async function doSimulate() {
    const resp = await fetch(SIM_URL, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF(), 'Content-Type': 'application/json' },
    });
    return resp.json();
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function handlePlay(play) {
    showDice(play.d1, play.d2, play.outcome, play.method);
    appendPlay(play);
    maybeShowPitchingPrompt(play);
    if (play.stat_update) {
        const cell = document.getElementById('stat-' + play.stat_update.player_id);
        if (cell) cell.textContent = play.stat_update.line;
    }
    if (play.half_over && !play.game_over) {
        updateOuts(3);
        await sleep(OUT_FLASH_MS);
    }
    animateRunners(play.moves);
    updateBoard(play.state);
    if (play.outcome === 'home_run') {
        playHomeRunSounds();
        launchFireworks();
        pulseCrowd();
    } else if (play.outcome === 'single' || play.outcome === 'double' || play.outcome === 'triple') {
        playSound(play.outcome);
    } else if (play.outcome === 'strikeout') {
        playSound('strikeout');
    }
    const delay = play.outcome === 'home_run' ? 1400 : 900;
    await sleep(delay);
    if (play.half_over && !play.game_over) {
        await sleep(600);
    }
}

// --- Pitching changes --------------------------------------------------

async function postPitcherAction(body) {
    const resp = await fetch(CHANGE_PITCHER_URL, {
        method: 'POST',
        headers: { 'X-CSRFToken': CSRF(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return resp.json();
}

function maybeShowPitchingPrompt(play) {
    const pca = play.pitching_change_available;
    if (!pca) return;
    // Server-rendered banner/button will pick this up on the next reload for
    // most modes; this handles the cpu_auto no-reload CPU-batting stretch,
    // where the fielding (human) side's client won't reload until half_over.
    const banner = document.createElement('div');
    banner.className = 'alert alert-warning py-2 px-3 mb-2';
    banner.innerHTML = `<strong>${pca.pitcher.name}</strong> is tiring (${pca.stamina}% stamina). Change pitchers?`;
    const btnArea = document.getElementById('btn-area');
    btnArea.prepend(banner);
}

document.getElementById('btn-open-pitcher-picker')?.addEventListener('click', () => {
    const picker = document.getElementById('pitcher-picker');
    picker.style.display = picker.style.display === 'none' ? '' : 'none';
});

document.getElementById('btn-dismiss-pitcher-prompt')?.addEventListener('click', async () => {
    await postPitcherAction({ action: 'dismiss' });
    location.reload();
});

document.querySelectorAll('.pitcher-pick-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
        await postPitcherAction({ action: 'change', player_id: parseInt(btn.dataset.playerId, 10) });
        location.reload();
    });
});

// --- Mode: click_all -------------------------------------------------------

function initClickAll() {
    const btn = document.getElementById('btn-roll');
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) {
            showGameOver(play.state);
        } else {
            location.reload();
        }
    });
}

// --- Mode: cpu_auto --------------------------------------------------------

function initCpuAuto() {
    const btn = document.getElementById('btn-roll');
    const initHalf = document.getElementById('diamond').dataset.half;
    const cpuHalf = CPU_SIDE === 'home' ? 'bottom' : 'top';  // default: away is CPU

    async function autoRollCPU() {
        while (true) {
            await sleep(1200);
            const play = await doRoll();
            await handlePlay(play);
            if (play.game_over) { showGameOver(play.state); return; }
            if (play.half_over) {
                location.reload();
                return;
            }
        }
    }

    if (initHalf === cpuHalf) {
        btn.disabled = true;
        btn.textContent = 'CPU batting…';
        autoRollCPU();
    }

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) { showGameOver(play.state); return; }
        location.reload();
    });
}

// --- Mode: auto_play -------------------------------------------------------

function initAutoPlay() {
    const btn = document.getElementById('btn-play');
    btn.addEventListener('click', async () => {
        btn.disabled = true;
        btn.textContent = 'Simulating…';
        playSound('play_ball');
        const data = await doSimulate();
        btn.textContent = 'Replaying…';
        for (const play of data.plays) {
            await handlePlay(play);
        }
        const last = data.plays[data.plays.length - 1];
        if (last) showGameOver(last.state);
    }, { once: true });
}

// --- Mode: multiplayer ------------------------------------------------------

function initMultiplayer() {
    const btn = document.getElementById('btn-roll');
    const half = document.getElementById('diamond').dataset.half;
    const myHalf = MY_SIDE === 'home' ? 'bottom' : 'top';

    if (half !== myHalf) {
        btn.disabled = true;
        btn.textContent = `Waiting for ${OPPONENT_NAME}…`;
        setInterval(() => location.reload(), 4000);
        return;
    }

    btn.addEventListener('click', async () => {
        btn.disabled = true;
        const play = await doRoll();
        await handlePlay(play);
        if (play.game_over) { showGameOver(play.state); return; }
        location.reload();
    });
}

// --- Init ------------------------------------------------------------------

if (GAME_STATUS === 'active') {
    if (GAME_MODE === 'click_all')   initClickAll();
    if (GAME_MODE === 'cpu_auto')    initCpuAuto();
    if (GAME_MODE === 'auto_play')   initAutoPlay();
    if (GAME_MODE === 'multiplayer') initMultiplayer();
} else {
    wireReplayButton();
}

// Render initial diamond from template data attr
const diamondEl = document.getElementById('diamond');
if (diamondEl) {
    const rawBases = diamondEl.dataset.bases;
    if (rawBases) {
        const bases = rawBases.split(',').map(v => v === 'True' || v === '1' || v === 'true');
        updateDiamond(bases);
    }
}

const boardEl = document.getElementById('scoreboard-board');
if (boardEl) {
    updateOuts(parseInt(boardEl.dataset.outs, 10) || 0);
}
