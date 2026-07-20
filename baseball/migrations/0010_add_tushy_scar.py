from django.db import migrations

# `Player` is an unmanaged model (raw `player` table) and its FK to `team`
# was never captured in the migration graph's historical state (only
# `team_abbrev` shows up there) — so this uses raw SQL against the known
# physical columns instead of `apps.get_model()`/the ORM.

PLAYER_ID = 999999
CUBS_TEAM_ID = 21

migrations_sql = """
DELETE FROM player WHERE player_id = %s;
INSERT INTO player (player_id, first_name, last_name, team_id, team_abbrev,
                     g, g_c, status, active)
VALUES (%s, 'Tushy', 'Scar', %s, 'CHC', 1, 1, 'available', true);
""" % (PLAYER_ID, PLAYER_ID, CUBS_TEAM_ID)

reverse_sql = "DELETE FROM player WHERE player_id = %s;" % PLAYER_ID


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0009_game_owner_side_game_player2_alter_game_away_team_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=migrations_sql, reverse_sql=reverse_sql),
    ]
