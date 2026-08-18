from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('baseball', '0018_game_weather_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='away_bullpen',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='game',
            name='home_bullpen',
            field=models.JSONField(default=list),
        ),
    ]
