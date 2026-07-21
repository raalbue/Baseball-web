from django.db import migrations, models

FORWARD_SQL = """
ALTER TABLE public.stats DROP CONSTRAINT fk_stats_game;
ALTER TABLE public.stats DROP COLUMN game_id;
ALTER TABLE public.stats ADD COLUMN season integer NOT NULL DEFAULT 0;
ALTER TABLE public.stats ALTER COLUMN season DROP DEFAULT;
ALTER TABLE public.stats ADD CONSTRAINT uq_stats_player_season UNIQUE (player_id, season);
"""

REVERSE_SQL = """
ALTER TABLE public.stats DROP CONSTRAINT uq_stats_player_season;
ALTER TABLE public.stats DROP COLUMN season;
ALTER TABLE public.stats ADD COLUMN game_id integer NOT NULL;
ALTER TABLE public.stats ADD CONSTRAINT fk_stats_game FOREIGN KEY (game_id)
    REFERENCES public.schedule (game_id) MATCH SIMPLE
    ON UPDATE NO ACTION ON DELETE NO ACTION;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0010_add_tushy_scar"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="stats",
                    name="player",
                    field=models.ForeignKey(
                        db_column="player_id",
                        on_delete=models.DO_NOTHING,
                        to="baseball.player",
                    ),
                    preserve_default=False,
                ),
                migrations.AddField(
                    model_name="stats",
                    name="season",
                    field=models.IntegerField(default=0),
                    preserve_default=False,
                ),
            ],
            database_operations=[
                migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
            ],
        ),
    ]
