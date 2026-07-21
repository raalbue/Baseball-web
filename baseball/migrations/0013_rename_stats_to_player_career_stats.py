from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0012_seed_stats_from_batting"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameModel(old_name="Stats", new_name="PlayerCareerStats"),
                migrations.AlterModelTable(
                    name="PlayerCareerStats", table="player_career_stats"
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE public.stats RENAME TO player_career_stats;",
                    "ALTER TABLE public.player_career_stats RENAME TO stats;",
                ),
            ],
        ),
    ]
