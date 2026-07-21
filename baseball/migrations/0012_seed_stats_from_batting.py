import csv
import os
from django.db import migrations

CSV_PATH = os.path.join(os.path.dirname(__file__), "seed_data", "totalbattingstats.csv")

# stats column -> totalbattingstats.csv column
COL_MAP = {
    "at_bats": "b_ab",
    "hits": "b_h",
    "runs": "b_r",
    "rbis": "b_rbi",
    "doubles": "b_d",
    "triples": "b_t",
    "home_runs": "b_hr",
    "walks": "b_w",
    "strikeouts": "b_k",
    "stolen_bases": "b_sb",
}


def _int(value):
    value = (value or "").strip()
    return int(value) if value else 0


def seed_stats(apps, schema_editor):
    Stats = apps.get_model("baseball", "Stats")
    Player = apps.get_model("baseball", "Player")
    if Stats.objects.exists():
        return  # already seeded (or hand-populated) — don't duplicate

    dataid_to_pid = dict(
        Player.objects.exclude(dataid__isnull=True)
        .exclude(dataid="")
        .values_list("dataid", "player_id")
    )

    batch = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dataid = (row.get("dataid") or "").strip().lower()
            player_id = dataid_to_pid.get(dataid)
            if not player_id:
                continue  # not one of our rostered players

            season = _int(row.get("last_season"))
            if not season:
                continue

            kwargs = {"player_id": player_id, "season": season}
            for field, col in COL_MAP.items():
                kwargs[field] = _int(row.get(col))
            batch.append(Stats(**kwargs))

            if len(batch) >= 500:
                Stats.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []
    if batch:
        Stats.objects.bulk_create(batch, ignore_conflicts=True)


def unseed_stats(apps, schema_editor):
    apps.get_model("baseball", "Stats").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0011_stats_drop_game_add_season"),
    ]

    operations = [
        migrations.RunPython(seed_stats, unseed_stats),
    ]
