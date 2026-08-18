from django.db import migrations

TEAMS_SQL = """
INSERT INTO team (team_id, name, city, abbreviation, conference, division, head_coach, stadium_id, founded_year) VALUES
(31, 'AL All-Stars', '', 'ALAS', 'American League', 'All-Star', NULL, 17, NULL),
(32, 'NL All-Stars', '', 'NLAS', 'National League', 'All-Star', NULL, 17, NULL)
ON CONFLICT (team_id) DO UPDATE SET
    name = EXCLUDED.name,
    city = EXCLUDED.city,
    abbreviation = EXCLUDED.abbreviation,
    conference = EXCLUDED.conference,
    division = EXCLUDED.division,
    stadium_id = EXCLUDED.stadium_id;
"""

# Update rather than delete on reverse too: real Game/SavedRoster rows may
# already reference these team_ids via a plain (non-cascading) FK, so a raw
# DELETE would fail with a ForeignKeyViolation. Reversing just restores the
# placeholder name/city; it does not remove the rows (matches forward's
# upsert semantics — this migration owns team_id 31/32's content, not their
# existence once referenced elsewhere).
REVERSE_SQL = """
UPDATE team SET name = 'All-Stars', city = 'American League' WHERE team_id = 31;
UPDATE team SET name = 'All-Stars', city = 'National League' WHERE team_id = 32;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0016_savedroster"),
    ]
    operations = [
        migrations.RunSQL(sql=TEAMS_SQL, reverse_sql=REVERSE_SQL),
    ]
