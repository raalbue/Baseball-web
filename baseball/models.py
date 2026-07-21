from django.conf import settings
from django.db import models
from .engine import GameState


# ---------------------------------------------------------------------------
# Unmanaged models — raw Postgres tables; Django does not manage DDL.
# ---------------------------------------------------------------------------

class Stadium(models.Model):
    stadium_id = models.AutoField(primary_key=True)
    name       = models.CharField(max_length=100)
    city       = models.CharField(max_length=50)
    state      = models.CharField(max_length=50, blank=True, null=True)
    country    = models.CharField(max_length=50, default='USA')
    capacity   = models.IntegerField(null=True, blank=True)

    class Meta:
        managed  = False
        db_table = 'stadium'
        ordering = ['name']

    def __str__(self):
        return self.name


class Team(models.Model):
    team_id      = models.AutoField(primary_key=True)
    name         = models.CharField(max_length=100)
    city         = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=5, blank=True, null=True)
    conference   = models.CharField(max_length=50, blank=True, null=True)
    division     = models.CharField(max_length=50, blank=True, null=True)
    head_coach   = models.CharField(max_length=50, blank=True, null=True)
    stadium      = models.ForeignKey(
        Stadium, db_column='stadium_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )
    founded_year = models.IntegerField(null=True, blank=True)

    class Meta:
        managed  = False
        db_table = 'team'
        ordering = ['name']

    def __str__(self):
        return f"{self.city} {self.name}"


class Player(models.Model):
    player_id     = models.AutoField(primary_key=True)
    first_name    = models.CharField(max_length=50)
    last_name     = models.CharField(max_length=50)
    team          = models.ForeignKey(
        Team, db_column='team_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )
    position      = models.CharField(max_length=30, blank=True, null=True)
    jersey_number = models.IntegerField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    height_inches = models.IntegerField(null=True, blank=True)
    weight_lbs    = models.IntegerField(null=True, blank=True)
    nationality   = models.CharField(max_length=50, blank=True, null=True)
    bats          = models.CharField(max_length=1, blank=True, null=True)
    throws        = models.CharField(max_length=1, blank=True, null=True)
    team_abbrev   = models.CharField(max_length=10, blank=True, null=True)
    season        = models.IntegerField(null=True, blank=True)
    g    = models.IntegerField(null=True, blank=True)
    g_p  = models.IntegerField(null=True, blank=True)
    g_sp = models.IntegerField(null=True, blank=True)
    g_rp = models.IntegerField(null=True, blank=True)
    g_c  = models.IntegerField(null=True, blank=True)
    g_1b = models.IntegerField(null=True, blank=True)
    g_2b = models.IntegerField(null=True, blank=True)
    g_3b = models.IntegerField(null=True, blank=True)
    g_ss = models.IntegerField(null=True, blank=True)
    g_lf = models.IntegerField(null=True, blank=True)
    g_cf = models.IntegerField(null=True, blank=True)
    g_rf = models.IntegerField(null=True, blank=True)
    g_of = models.IntegerField(null=True, blank=True)
    g_dh = models.IntegerField(null=True, blank=True)
    g_ph = models.IntegerField(null=True, blank=True)
    g_pr = models.IntegerField(null=True, blank=True)
    first_game  = models.IntegerField(null=True, blank=True)
    last_game   = models.IntegerField(null=True, blank=True)
    dataid      = models.CharField(max_length=255, blank=True, null=True)
    status      = models.CharField(max_length=50, default='available')
    active      = models.BooleanField(default=True)

    class Meta:
        managed  = False
        db_table = 'player'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


FIELDING_COLS = {
    "P": "g_p", "C": "g_c", "1B": "g_1b", "2B": "g_2b", "3B": "g_3b",
    "SS": "g_ss", "LF": "g_lf", "CF": "g_cf", "RF": "g_rf",
}


def main_position(player) -> str | None:
    best, code = 0, None
    for c, col in FIELDING_COLS.items():
        v = getattr(player, col) or 0
        if v > best:
            best, code = v, c
    return code


def position_pools(team) -> dict:
    pools = {c: [] for c in FIELDING_COLS}
    pools["DH"] = []
    for p in Player.objects.filter(team=team):
        for code, col in FIELDING_COLS.items():
            if (getattr(p, col) or 0) > 0:
                pools[code].append(p.player_id)
        is_pitcher = (p.g_sp or 0) > 0 or (p.g_rp or 0) > 0
        if not is_pitcher or (p.g_dh or 0) > 0:
            pools["DH"].append(p.player_id)
    return pools


class MLBSchedule(models.Model):
    """Maps to the raw `schedule` table (distinct from baseball.Game)."""
    game_id    = models.AutoField(primary_key=True)
    home_team  = models.ForeignKey(
        Team, db_column='home_team_id',
        on_delete=models.DO_NOTHING, related_name='schedule_home',
    )
    away_team  = models.ForeignKey(
        Team, db_column='away_team_id',
        on_delete=models.DO_NOTHING, related_name='schedule_away',
    )
    stadium    = models.ForeignKey(
        Stadium, db_column='stadium_id', on_delete=models.DO_NOTHING,
    )
    game_date  = models.DateField()
    game_time  = models.TimeField(null=True, blank=True)
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)
    status     = models.CharField(max_length=20, default='Scheduled')

    class Meta:
        managed  = False
        db_table = 'schedule'


class MLBGame(models.Model):
    """Maps to the raw `game` table (distinct from baseball.Game web-app model)."""
    game_id    = models.AutoField(primary_key=True)
    status     = models.CharField(max_length=20, default='Pending')
    start_time = models.DateTimeField()
    end_time   = models.DateTimeField()
    home_score = models.IntegerField(default=0)
    away_score = models.IntegerField(default=0)
    stadium    = models.ForeignKey(
        Stadium, db_column='stadium_id',
        on_delete=models.DO_NOTHING, null=True, blank=True,
    )

    class Meta:
        managed  = False
        db_table = 'game'


class PlayerCareerStats(models.Model):
    stat_id           = models.AutoField(primary_key=True)
    player            = models.ForeignKey(
        Player, db_column='player_id', on_delete=models.DO_NOTHING,
    )
    season            = models.IntegerField()
    at_bats           = models.IntegerField(default=0)
    hits              = models.IntegerField(default=0)
    runs              = models.IntegerField(default=0)
    rbis              = models.IntegerField(default=0)
    doubles           = models.IntegerField(default=0)
    triples           = models.IntegerField(default=0)
    home_runs         = models.IntegerField(default=0)
    walks             = models.IntegerField(default=0)
    strikeouts        = models.IntegerField(default=0)
    stolen_bases      = models.IntegerField(default=0)
    innings_pitched   = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pitches_thrown    = models.IntegerField(null=True, blank=True)
    hits_allowed      = models.IntegerField(default=0)
    runs_allowed      = models.IntegerField(default=0)
    earned_runs       = models.IntegerField(default=0)
    walks_allowed     = models.IntegerField(default=0)
    ks_pitched        = models.IntegerField(default=0)
    home_runs_allowed = models.IntegerField(default=0)

    class Meta:
        managed  = False
        db_table = 'player_career_stats'
        unique_together = (('player', 'season'),)


class GameParticipant(models.Model):
    participant_id  = models.AutoField(primary_key=True)
    game            = models.ForeignKey(
        MLBGame, db_column='game_id', on_delete=models.DO_NOTHING,
    )
    player_sequence = models.IntegerField(default=1)
    user_id         = models.IntegerField()
    team            = models.ForeignKey(
        Team, db_column='team_id', on_delete=models.DO_NOTHING,
    )

    class Meta:
        managed  = False
        db_table = 'game_participant'


class Lineup(models.Model):
    lineup_id     = models.AutoField(primary_key=True)
    participant   = models.ForeignKey(
        GameParticipant, db_column='participant_id', on_delete=models.DO_NOTHING,
    )
    player        = models.ForeignKey(
        Player, db_column='player_id', on_delete=models.DO_NOTHING,
    )
    batting_order = models.IntegerField()

    class Meta:
        managed  = False
        db_table = 'lineup'


# ---------------------------------------------------------------------------

class Game(models.Model):
    CPU_AUTO    = "cpu_auto"
    CLICK_ALL   = "click_all"
    AUTO_PLAY   = "auto_play"
    MULTIPLAYER = "multiplayer"
    MODE_CHOICES = [
        (CPU_AUTO,    "CPU auto, you click"),
        (CLICK_ALL,   "Click every at-bat"),
        (AUTO_PLAY,   "Auto-play whole game"),
        (MULTIPLAYER, "Multiplayer (invite a player)"),
    ]

    ACTIVE   = "active"
    WAITING  = "waiting"
    FINISHED = "finished"
    STATUS_CHOICES = [
        (ACTIVE, "Active"), (WAITING, "Waiting for player"), (FINISHED, "Finished"),
    ]

    CPU_SIDE_CHOICES = [("away", "Away"), ("home", "Home")]

    owner         = models.ForeignKey(settings.AUTH_USER_MODEL,
                                      on_delete=models.CASCADE,
                                      related_name="baseball_games")
    player2       = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.CASCADE,
                                      related_name="baseball_games_as_player2")
    away_name     = models.CharField(max_length=50)
    home_name     = models.CharField(max_length=50)
    away_team     = models.ForeignKey(
        'Team', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='away_games',
    )
    home_team     = models.ForeignKey(
        'Team', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='home_games',
    )
    away_roster   = models.JSONField(default=list)
    home_roster   = models.JSONField(default=list)
    total_innings = models.PositiveSmallIntegerField(default=3)
    mode          = models.CharField(max_length=20, choices=MODE_CHOICES)
    cpu_side      = models.CharField(max_length=4, choices=CPU_SIDE_CHOICES,
                                     null=True, blank=True)
    owner_side    = models.CharField(max_length=4, choices=CPU_SIDE_CHOICES,
                                     null=True, blank=True)
    state         = models.JSONField()
    play_log      = models.JSONField(default=list)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default=ACTIVE)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @staticmethod
    def state_to_dict(s: GameState) -> dict:
        return {
            "away_name": s.away_name, "home_name": s.home_name,
            "total_innings": s.total_innings,
            "inning": s.inning, "half": s.half,
            "outs": s.outs, "balls": s.balls, "strikes": s.strikes,
            "bases": s.bases,
            "away_score": s.away_score, "home_score": s.home_score,
            "away_idx": s.away_idx, "home_idx": s.home_idx,
            "game_over": s.game_over,
            "away_lineup": s.away_lineup, "home_lineup": s.home_lineup,
        }

    @staticmethod
    def state_from_dict(d: dict) -> GameState:
        gs = GameState(d["away_name"], d["home_name"], d["total_innings"],
                       away_lineup=d.get("away_lineup"),
                       home_lineup=d.get("home_lineup"))
        gs.inning      = d["inning"]
        gs.half        = d["half"]
        gs.outs        = d["outs"]
        gs.balls       = d["balls"]
        gs.strikes     = d["strikes"]
        gs.bases       = d["bases"]
        gs.away_score  = d["away_score"]
        gs.home_score  = d["home_score"]
        gs.away_idx    = d["away_idx"]
        gs.home_idx    = d["home_idx"]
        gs.game_over   = d["game_over"]
        return gs

    def load_state(self) -> GameState:
        return self.state_from_dict(self.state)

    def save_state(self, gs: GameState) -> None:
        self.state = self.state_to_dict(gs)


class GameStat(models.Model):
    game       = models.ForeignKey(Game, db_column="game_id",
                                   on_delete=models.DO_NOTHING,
                                   related_name="game_stats")
    player     = models.ForeignKey(Player, db_column="player_id",
                                   on_delete=models.DO_NOTHING)
    ab         = models.SmallIntegerField(default=0)
    singles    = models.SmallIntegerField(default=0)
    doubles    = models.SmallIntegerField(default=0)
    triples    = models.SmallIntegerField(default=0)
    home_runs  = models.SmallIntegerField(default=0)
    strikeouts = models.SmallIntegerField(default=0)
    walks      = models.SmallIntegerField(default=0)
    sac_hits   = models.SmallIntegerField(default=0)

    class Meta:
        managed  = False
        db_table = "game_stat"

    @property
    def hits(self) -> int:
        return self.singles + self.doubles + self.triples + self.home_runs

    @property
    def line(self) -> str:
        return f"{self.hits}-{self.ab}"
