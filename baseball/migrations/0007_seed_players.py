import csv
import os
from django.db import migrations

CSV_PATH = os.path.join(os.path.dirname(__file__), "seed_data", "players.csv")

INT_FIELDS = [
    "jersey_number", "height_inches", "weight_lbs", "season",
    "g", "g_p", "g_sp", "g_rp", "g_c", "g_1b", "g_2b", "g_3b", "g_ss",
    "g_lf", "g_cf", "g_rf", "g_of", "g_dh", "g_ph", "g_pr",
    "first_game", "last_game",
]
STR_FIELDS = [
    "first_name", "last_name", "position", "nationality", "bats", "throws",
    "team_abbrev", "dataid", "status",
]


def _to_int(value):
    value = (value or "").strip()
    return int(value) if value else None


def _to_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def seed_players(apps, schema_editor):
    Player = apps.get_model("baseball", "Player")
    if Player.objects.exists():
        return  # already seeded (or hand-populated) — don't duplicate

    batch = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kwargs = {"player_id": int(row["player_id"])}
            kwargs["team_id"] = _to_int(row["team_id"])
            kwargs["date_of_birth"] = _to_date(row["date_of_birth"])
            kwargs["active"] = (row.get("active") or "").strip().lower() in ("t", "true", "1")
            for field in STR_FIELDS:
                val = (row.get(field) or "").strip()
                kwargs[field] = val or ("available" if field == "status" and not val else (val or None))
            kwargs["status"] = (row.get("status") or "").strip() or "available"
            for field in INT_FIELDS:
                kwargs[field] = _to_int(row.get(field))
            batch.append(Player(**kwargs))

            if len(batch) >= 500:
                Player.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []
    if batch:
        Player.objects.bulk_create(batch, ignore_conflicts=True)


def unseed_players(apps, schema_editor):
    apps.get_model("baseball", "Player").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0006_seed_stadiums_teams"),
    ]

    operations = [
        migrations.RunPython(seed_players, unseed_players),
    ]
