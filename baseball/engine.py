# -*- coding: utf-8 -*-
"""baseball engine: game state and at-bat resolution."""
import random
from typing import Dict, List, Tuple
from .params import (
    LINEUP, STRIKE_PROB, FOUL_PROB, DOUBLE_PLAY_PROB,
    CONTACT_PROB, OUTCOME_WEIGHTS, HIT_BASES, DICE_TABLE, STAT_OUT_SPLIT,
)


class GameState:
    """Holds the full mutable state of a ball game."""

    def __init__(self, away_name: str, home_name: str, total_innings: int,
                 away_lineup=None, home_lineup=None) -> None:
        self.away_name = away_name
        self.home_name = home_name
        self.total_innings = total_innings
        self.away_lineup = list(away_lineup) if away_lineup else list(LINEUP)
        self.home_lineup = list(home_lineup) if home_lineup else list(LINEUP)
        self.inning = 1
        self.half = "top"            # "top" (away bats) or "bottom" (home bats)
        self.outs = 0
        self.balls = 0
        self.strikes = 0
        self.bases = [False, False, False]   # 1B, 2B, 3B
        self.away_score = 0
        self.home_score = 0
        self.away_idx = 0            # lineup rotation index
        self.home_idx = 0
        self.game_over = False

    # -- convenience -----------------------------------------------------------
    @property
    def batting_team(self) -> str:
        return self.away_name if self.half == "top" else self.home_name

    @property
    def current_batter(self) -> str:
        lineup = self.away_lineup if self.half == "top" else self.home_lineup
        idx = self.away_idx if self.half == "top" else self.home_idx
        return lineup[idx % len(lineup)]

    def advance_lineup(self) -> None:
        if self.half == "top":
            self.away_idx += 1
        else:
            self.home_idx += 1

    def add_runs(self, runs: int) -> None:
        if self.half == "top":
            self.away_score += runs
        else:
            self.home_score += runs

    def reset_half(self) -> None:
        self.outs = 0
        self.reset_count()
        self.bases = [False, False, False]

    def reset_count(self) -> None:
        self.balls = 0
        self.strikes = 0

    def runners_on(self) -> int:
        return sum(self.bases)


def weighted_choice(weights: Dict[str, int]) -> str:
    """Pick a key from a {key: weight} mapping."""
    population = list(weights.keys())
    return random.choices(population, weights=[weights[k] for k in population])[0]


def advance_runners(bases: List[bool], n: int) -> Tuple[List[bool], int]:
    """
    Advance all runners (and the batter) by ``n`` bases on a clean hit.

    :param bases: current [1B, 2B, 3B] occupancy
    :param n: number of bases for the hit (1=single .. 4=home run)
    """
    positions = [i + 1 for i in range(3) if bases[i]]
    positions.append(0)  # the batter, starting at home plate
    runs = 0
    new_bases = [False, False, False]
    for pos in positions:
        dest = pos + n
        if dest >= 4:
            runs += 1
        else:
            new_bases[dest - 1] = True
    return new_bases, runs


def walk_runners(bases: List[bool]) -> Tuple[List[bool], int]:
    """Force-advance runners on a walk; returns (new_bases, runs)."""
    new = bases[:]
    runs = 0
    if not new[0]:
        new[0] = True
    elif not new[1]:
        new[1] = True
    elif not new[2]:
        new[2] = True
    else:
        runs = 1  # bases loaded: runner forced home, bases stay loaded
    return new, runs


def pitch_in_zone(strike_prob: float = STRIKE_PROB) -> bool:
    """Return True if the pitch crosses the strike zone."""
    return random.random() < strike_prob


def resolve_swing(swing_type: str, in_zone: bool, contact_mod: float = 0.0) -> Dict:
    """
    Resolve a swing into a play event.

    :param swing_type: "contact", "power" or "bunt"
    :param in_zone: whether the pitch was a strike
    :param contact_mod: pitch-dependent contact adjustment
    """
    location = "zone" if in_zone else "ball"
    contact_chance = CONTACT_PROB[swing_type][location] + contact_mod
    if random.random() > contact_chance:
        return {"type": "swing_strike"}
    if swing_type == "bunt":
        return {"type": "bunt_contact"}
    if random.random() < FOUL_PROB:
        return {"type": "foul"}
    outcome = weighted_choice(OUTCOME_WEIGHTS[swing_type])
    return {"type": "in_play", "outcome": outcome}


# --- Applying events to the game state --------------------------------------

def apply_ball(state: GameState) -> Tuple[str, bool]:
    """Add a ball; returns (message, at_bat_over)."""
    state.balls += 1
    if state.balls >= 4:
        state.bases, runs = walk_runners(state.bases)
        state.add_runs(runs)
        msg = "Ball four! {batter} walks.".format(batter=state.current_batter)
        if runs:
            msg += " A run forces in!"
        return msg, True
    return "Ball. Count {b}-{s}.".format(b=state.balls, s=state.strikes), False


def apply_strike(state: GameState, swinging: bool) -> Tuple[str, bool]:
    """Add a strike; returns (message, at_bat_over)."""
    state.strikes += 1
    label = "Swinging strike" if swinging else "Called strike"
    if state.strikes >= 3:
        state.outs += 1
        return "{label} three! {batter} strikes out.".format(
            label=label, batter=state.current_batter), True
    return "{label}. Count {b}-{s}.".format(
        label=label, b=state.balls, s=state.strikes), False


def apply_foul(state: GameState) -> Tuple[str, bool]:
    """Handle a foul ball; returns (message, at_bat_over)."""
    if state.strikes < 2:
        state.strikes += 1
    return "Foul ball. Count {b}-{s}.".format(b=state.balls, s=state.strikes), False


def apply_in_play(state: GameState, outcome: str) -> Tuple[str, bool]:
    """Resolve a batted ball; returns (message, at_bat_over)."""
    batter = state.current_batter
    if outcome in HIT_BASES:
        n = HIT_BASES[outcome]
        state.bases, runs = advance_runners(state.bases, n)
        state.add_runs(runs)
        names = {1: "singles", 2: "doubles", 3: "triples", 4: "homers"}
        msg = "{batter} {verb}!".format(batter=batter, verb=names[n])
        if outcome == "home_run":
            extra = state.runners_on()  # runners already cleared; recount via runs
            msg = "{batter} crushes a {runs}-run HOME RUN!".format(
                batter=batter, runs=runs) if runs > 1 else \
                "{batter} goes deep, SOLO HOME RUN!".format(batter=batter)
        elif runs:
            msg += " {runs} run{p} score{q}.".format(
                runs=runs, p="s" if runs > 1 else "", q="" if runs > 1 else "s")
        return msg, True

    if outcome == "groundout":
        if state.bases[0] and state.outs < 2 and random.random() < DOUBLE_PLAY_PROB:
            state.outs += 2
            state.bases[0] = False
            return "{batter} grounds into a double play!".format(batter=batter), True
        state.outs += 1
        return "{batter} grounds out.".format(batter=batter), True

    if outcome == "flyout":
        scored = False
        if state.bases[2] and state.outs < 2:
            state.bases[2] = False
            state.add_runs(1)
            scored = True
        state.outs += 1
        if scored:
            return "{batter} lifts a sacrifice fly, a run scores!".format(batter=batter), True
        return "{batter} flies out.".format(batter=batter), True

    state.outs += 1
    return "{batter} is out.".format(batter=batter), True


def apply_bunt(state: GameState) -> Tuple[str, bool]:
    """Resolve a bunt put in play; returns (message, at_bat_over)."""
    batter = state.current_batter
    # 25% beats it out for a single, otherwise a sacrifice that advances runners.
    if random.random() < 0.25:
        state.bases, runs = advance_runners(state.bases, 1)
        state.add_runs(runs)
        msg = "{batter} drops a bunt single!".format(batter=batter)
        if runs:
            msg += " A run scores!"
        return msg, True
    runs = 0
    if any(state.bases):
        # advance lead runners one base (sacrifice).
        new = [False, False, False]
        if state.bases[2]:
            runs += 1
        if state.bases[1]:
            new[2] = True
        if state.bases[0]:
            new[1] = True
        state.bases = new
        state.add_runs(runs)
    state.outs += 1
    msg = "{batter} lays down a sacrifice bunt.".format(batter=batter)
    if runs:
        msg += " A run scores!"
    return msg, True


def roll_dice() -> Tuple[int, int]:
    """Roll two six-sided dice; returns (d1, d2)."""
    return random.randint(1, 6), random.randint(1, 6)


def apply_walk(state: GameState) -> Tuple[str, bool]:
    """Award a direct walk (no count update)."""
    state.bases, runs = walk_runners(state.bases)
    state.add_runs(runs)
    msg = "{batter} draws a walk.".format(batter=state.current_batter)
    if runs:
        msg += " A run forces in!"
    return msg, True


def apply_strikeout(state: GameState) -> Tuple[str, bool]:
    """Record a direct strikeout (no count update)."""
    state.outs += 1
    return "{batter} strikes out.".format(batter=state.current_batter), True


def apply_sacrifice(state: GameState) -> Tuple[str, bool]:
    """Batter is out; all base runners advance one base."""
    batter = state.current_batter
    runs = 0
    if any(state.bases):
        new = [False, False, False]
        if state.bases[2]:
            runs += 1
        if state.bases[1]:
            new[2] = True
        if state.bases[0]:
            new[1] = True
        state.bases = new
        state.add_runs(runs)
    state.outs += 1
    msg = "{batter} hits a sacrifice.".format(batter=batter)
    if runs:
        msg += " A run scores!"
    return msg, True


def stat_based_weights(row: Dict[str, int]) -> Dict[str, int]:
    """
    Build a {outcome: weight} dict from a batter's career counting stats.

    :param row: dict with at_bats, hits, doubles, triples, home_runs,
                walks, strikeouts (extra keys ignored).
    """
    singles = row["hits"] - row["doubles"] - row["triples"] - row["home_runs"]
    in_play_outs = row["at_bats"] - row["hits"] - row["strikeouts"]
    return {
        "walk": row["walks"],
        "strikeout": row["strikeouts"],
        "single": singles,
        "double": row["doubles"],
        "triple": row["triples"],
        "home_run": row["home_runs"],
        "groundout": round(in_play_outs * STAT_OUT_SPLIT["groundout"]),
        "flyout": round(in_play_outs * STAT_OUT_SPLIT["flyout"]),
        "sacrifice": round(in_play_outs * STAT_OUT_SPLIT["sacrifice"]),
    }


def resolve_dice_roll(state: GameState, stat_weights: Dict[str, int] = None) -> Tuple[int, int, str, str]:
    """Roll 2d6 (always, for display), then either look up DICE_TABLE by the
    die pair or -- when stat_weights is given -- draw the outcome from the
    batter's own career-stat weights. Applies the event to state.

    Returns (d1, d2, outcome_key, play_message).
    """
    d1, d2 = roll_dice()
    if stat_weights is not None:
        outcome = weighted_choice(stat_weights)
    else:
        outcome = DICE_TABLE[(min(d1, d2), max(d1, d2))]
    if outcome == "walk":
        msg, _ = apply_walk(state)
    elif outcome == "strikeout":
        msg, _ = apply_strikeout(state)
    elif outcome == "sacrifice":
        msg, _ = apply_sacrifice(state)
    else:
        msg, _ = apply_in_play(state, outcome)
    return d1, d2, outcome, msg


def cpu_batter_action(state: GameState, in_zone: bool) -> str:
    """Decide what the CPU batter does with a pitch."""
    swing_prob = 0.72 if in_zone else 0.40
    if state.strikes == 2:
        swing_prob += 0.15
    if state.balls == 3 and state.strikes < 2:
        swing_prob -= 0.25
    if random.random() < swing_prob:
        return "power" if random.random() < 0.32 else "contact"
    return "take"


def resolve_action(state: GameState, action: str, in_zone: bool,
                   contact_mod: float = 0.0) -> Tuple[str, bool]:
    """
    Resolve a batter's chosen action against a pitch.

    :return: (play-by-play message, at_bat_over)
    """
    if action == "take":
        if in_zone:
            return apply_strike(state, swinging=False)
        return apply_ball(state)

    event = resolve_swing(action, in_zone, contact_mod)
    kind = event["type"]
    if kind == "swing_strike":
        return apply_strike(state, swinging=True)
    if kind == "foul":
        return apply_foul(state)
    if kind == "bunt_contact":
        return apply_bunt(state)
    return apply_in_play(state, event["outcome"])
