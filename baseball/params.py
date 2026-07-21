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

HIT_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4}

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
