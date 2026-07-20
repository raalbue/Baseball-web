/* Baseball web game — drives all three play modes. */

const CSRF = () =>
    document.querySelector('#csrf-form [name=csrfmiddlewaretoken]').value;

const sfx = {
    play_ball: new Audio(SOUND_PLAY),
    home_run:  new Audio(SOUND_HR),
    win:       new Audio(SOUND_WIN),
};

function playSound(key) {
    const a = sfx[key];
    if (!a) return;
    a.currentTime = 0;
    a.play().catch(() => {});
}

// --- DOM helpers -----------------------------------------------------------

function updateScoreboard(state) {
    document.getElementById('sb-half').textContent = state.half === 'top' ? 'Top' : 'Bottom';
    document.getElementById('sb-inning').textContent = state.inning;
    document.getElementById('sb-away-score').textContent = state.away_score;
    document.getElementById('sb-home-score').textContent = state.home_score;
    document.getElementById('sb-outs').textContent = state.outs;
    document.getElementById('sb-batter').textContent = state.current_batter;
    const lineEl = document.getElementById('sb-batter-line');
    if (lineEl) lineEl.textContent = state.batter_line ? `(${state.batter_line})` : '';
    document.getElementById('sb-team').textContent = state.batting_team;

    document.getElementById('sb-away-bat').textContent =
        state.half === 'top' ? '← batting' : '';
    document.getElementById('sb-home-bat').textContent =
        state.half === 'bottom' ? '← batting' : '';

    updateDiamond(state.bases);
}

function updateDiamond(bases) {
    document.getElementById('base-marker-1').classList.toggle('occupied', !!bases[0]);
    document.getElementById('base-marker-2').classList.toggle('occupied', !!bases[1]);
    document.getElementById('base-marker-3').classList.toggle('occupied', !!bases[2]);
}

function showDice(d1, d2, outcome) {
    document.getElementById('dice-roll').textContent = `[${d1}]  [${d2}]`;
    document.getElementById('dice-outcome').textContent =
        outcome.replace(/_/g, ' ').toUpperCase();
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
    p.textContent = `[${half} ${play.play_inning}] 🎲 [${play.d1}][${play.d2}] — ${play.message}`;
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

    if (GAME_MODE !== 'multiplayer') {
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
    showDice(play.d1, play.d2, play.outcome);
    appendPlay(play);
    updateScoreboard(play.state);
    if (play.stat_update) {
        const cell = document.getElementById('stat-' + play.stat_update.player_id);
        if (cell) cell.textContent = play.stat_update.line;
    }
    if (play.outcome === 'home_run') playSound('home_run');
    const delay = play.outcome === 'home_run' ? 1400 : 900;
    await sleep(delay);
    if (play.half_over && !play.game_over) {
        await sleep(600);
    }
}

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
