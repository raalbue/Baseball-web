# -*- coding: utf-8 -*-
"""baseball params."""

BASEBALL_VERSION = "1.0"

BASEBALL_OVERVIEW = '''
Console Baseball is a terminal play-ball game for geeks.
You manage a team: swing at the plate on offense and pick your pitches on
defense, while a big ASCII scoreboard keeps the count, the bases and the runs.
Built on top of the mytimer toolbox (art + colorama + nava).
'''

BASEBALL_REPO = "Have fun out there!"

EXIT_MESSAGE = "Game called. See you at the ballpark!"
INPUT_ERROR_MESSAGE = "[Error] Please pick one of the listed options."
SOUND_ERROR_MESSAGE = "[Error] Unable to play sound"

DEFAULT_INNINGS = 3
DEFAULT_AWAY_NAME = "Robots"
DEFAULT_HOME_NAME = "You"

# Lineup names used for the play-by-play.
LINEUP = [
    "Diaz", "Okafor", "Tanaka", "Smith", "Rossi",
    "Khan", "Muller", "Santos", "Park",
]

# --- Probability knobs -------------------------------------------------------
STRIKE_PROB = 0.50          # chance a CPU pitch is in the zone
FOUL_PROB = 0.24            # chance a contact ball is fouled off
DOUBLE_PLAY_PROB = 0.45     # chance a groundout becomes a double play (runner on 1st)

# Contact chance per swing type, split by pitch location.
CONTACT_PROB = {
    "contact": {"zone": 0.82, "ball": 0.55},
    "power": {"zone": 0.58, "ball": 0.30},
    "bunt": {"zone": 0.85, "ball": 0.45},
}

# In-play outcome weights once solid contact is made.
OUTCOME_WEIGHTS = {
    "contact": {
        "single": 38, "double": 12, "triple": 3, "home_run": 4,
        "groundout": 23, "flyout": 20,
    },
    "power": {
        "single": 18, "double": 18, "triple": 5, "home_run": 18,
        "groundout": 19, "flyout": 22,
    },
}

# Pitch types the player can throw on defense: (strike-zone prob, hittability).
PITCH_TYPES = {
    "1": {"name": "Fastball", "strike_prob": 0.60, "contact_mod": 0.05},
    "2": {"name": "Curveball", "strike_prob": 0.45, "contact_mod": -0.08},
    "3": {"name": "Changeup", "strike_prob": 0.50, "contact_mod": -0.04},
    "4": {"name": "Intentional ball", "strike_prob": 0.00, "contact_mod": 0.00},
}

# Batter menu (offense).
SWING_MENU = {
    "1": ("take", "Take the pitch"),
    "2": ("contact", "Contact swing (meet the ball)"),
    "3": ("power", "Power swing (go deep)"),
    "4": ("bunt", "Bunt (advance runners)"),
}

HIT_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4, "single_error": 1}

# 2d6 dice table: keyed on (min_die, max_die) so (3,5) and (5,3) are the same roll.
# Doubles each appear 1/36; mixed pairs each appear 2/36.
# Doubles (6 combos, 1/36 each) — special rolls, all positive outcomes.
# Mixed pairs (15 combos, 2/36 each) — mostly outs with a few hits/walks.
DICE_TABLE = {
    # --- doubles ---
    (1, 1): "walk",
    (2, 2): "single",
    (3, 3): "double",
    (4, 4): "triple",
    (5, 5): "home_run",
    (6, 6): "home_run",
    # --- mixed pairs ---
    (1, 2): "walk",
    (1, 3): "single",
    (1, 4): "flyout",
    (1, 5): "groundout",
    (1, 6): "strikeout",
    (2, 3): "single",
    (2, 4): "groundout",
    (2, 5): "strikeout",
    (2, 6): "groundout",
    (3, 4): "strikeout",
    (3, 5): "flyout",
    (3, 6): "sacrifice",
    (4, 5): "strikeout",
    (4, 6): "flyout",
    (5, 6): "double",
}

# Streaky-batter variant of the dice table: 2 of the 3 groundout rolls become
# "reaches on an error" singles (still an at-bat, not a hit) when the current
# batter is that half-inning's/game's streaky pick. (1,5) stays a groundout so
# streaky dice-table batters still have some groundout risk.
DICE_TABLE_STREAKY = {
    **DICE_TABLE,
    (2, 4): "single_error",
    (2, 6): "single_error",
}

DICE_EVENT_LABELS = {
    "home_run":  "HOME RUN",
    "triple":    "TRIPLE",
    "double":    "DOUBLE",
    "single":    "SINGLE",
    "walk":      "WALK",
    "strikeout": "STRIKE OUT",
    "groundout": "GROUND OUT",
    "flyout":    "FLY OUT",
    "sacrifice": "SACRIFICE",
}

# Minimum career at-bats before stat-based outcome resolution kicks in;
# below this, the fixed dice table is used (small-sample fallback).
STAT_BASED_MIN_AB = 200

# No per-batter groundout/flyout/sacrifice split exists in the imported data
# (Retrosheet b_sh/b_sf were never loaded); split each batter's leftover
# in-play outs by this fixed ratio instead.
STAT_OUT_SPLIT = {"groundout": 0.55, "flyout": 0.43, "sacrifice": 0.02}

# --- Weather -------------------------------------------------------------------
# Neutral baseline: a 70F, calm, overcast day. Games left at this exact
# weather must behave identically to before weather existed.
WEATHER_DEFAULT = {"temperature_f": 70, "wind": "calm", "sky": "overcast"}
COLD_THRESHOLD_F = 60        # below this, cold-weather hit penalty applies
WIND_OUT_HR_MULT = 1.3       # blowing out: home runs more likely
WIND_IN_HR_MULT = 0.75       # blowing in: home runs less likely
COLD_RAIN_HIT_MULT = 0.9     # rain, or temperature below COLD_THRESHOLD_F: hits less likely

# --- Pitcher stamina -------------------------------------------------------------
PITCHER_STAMINA_MAX = 100
STAMINA_DRAIN_PER_BATTER = 4   # -> ~25 batters faced before a pitcher is fully spent
FATIGUE_WALK_MULT = 0.5        # at zero stamina, walk weight is *1.5
FATIGUE_HIT_MULT = 0.4         # at zero stamina, single/double/triple/home_run weights are *1.4
PITCHER_CHANGE_THRESHOLD = 30  # stamina at/below this triggers the change-pitcher prompt

# --- Announcer commentary -----------------------------------------------------
# A second, randomized flavor line shown alongside the mechanical play message.
COMMENTARY_LINES = {
    "home_run": [
        "Get up, get up, get outta here! {batter} goes deep!",
        "Absolutely crushed — {batter} sends one a long way!",
        "That ball is gone — {batter} with the moonshot!",
        "{batter} takes a well-earned curtain call!",
        "No doubt about that one off the bat of {batter}!",
    ],
    "triple": [
        "{batter} legs it out for a stand-up triple!",
        "Into the gap and {batter} is rolling — triple!",
        "Off the wall and {batter} cruises into third!",
        "{batter} never stops running — three-bagger!",
        "{batter} makes that look easy — triple!",
    ],
    "double": [
        "{batter} rips one into the corner for a double!",
        "Line drive into the gap — {batter} stands on second!",
        "Base hit, and {batter} stretches it into two!",
        "That's got extra bases written all over it, {batter} doubles!",
        "{batter} carves out a two-bagger!",
    ],
    "single": [
        "{batter} slaps one through the infield for a base hit!",
        "Clean single up the middle for {batter}!",
        "{batter} finds a hole for a base hit!",
        "{batter} pokes one the other way for a single!",
        "Ground ball finds the outfield grass — single for {batter}!",
    ],
    "walk": [
        "{batter} works the count and draws a walk!",
        "Ball four — {batter} takes the free pass!",
        "Patient at-bat there, {batter} strolls to first!",
        "{batter} wasn't giving in — walk!",
        "Four wide ones, {batter} jogs down to first!",
    ],
    "strikeout": [
        "{batter} is caught looking — strike three!",
        "Swing and a miss — {batter} strikes out!",
        "{batter} couldn't catch up to that one!",
        "Down goes {batter} on strikes!",
        "{batter} fans — back to the dugout!",
    ],
    "groundout": [
        "{batter} beats it into the dirt — routine groundout.",
        "Chopper to the infield, {batter} is out at first.",
        "{batter} rolls one over — can't beat the throw.",
        "Ground ball, {batter} hustles but comes up short.",
        "Easy play on that grounder from {batter}.",
    ],
    "flyout": [
        "{batter} skies one — caught in the outfield.",
        "Lazy fly ball, {batter} is retired.",
        "{batter} gets under it — routine out.",
        "Deep, but not deep enough — {batter} flies out.",
        "{batter} pops it up, easy out.",
    ],
    "sacrifice": [
        "{batter} gives himself up to move the runner along.",
        "Smart at-bat — {batter} sacrifices for the team.",
        "{batter} puts the ball in play just to advance the runner.",
        "That's a professional at-bat from {batter}.",
        "{batter} trades an out to push the runner up a base.",
    ],
    "single_error": [
        "{batter} reaches on a wild throw — error on the play!",
        "The defense boots it — {batter} is aboard on the error!",
        "{batter} beats it out after a bobble in the infield!",
        "Miscue on defense lets {batter} reach base!",
        "{batter} reaches after the defense couldn't handle it!",
    ],
}

# --- Sound effects (reuse mytimer's wav library) -----------------------------
SOUND_MAP = {
    "play_ball": "1.wav",
    "home_run": "5.wav",
    "win": "10.wav",
}

# --- Display -----------------------------------------------------------------
BANNER_FONT = "standard"
PLAY_BALL_TEXT = "PLAY BALL"
HOME_RUN_TEXT = "HOME RUN!"
GAME_OVER_TEXT = "GAME OVER"
