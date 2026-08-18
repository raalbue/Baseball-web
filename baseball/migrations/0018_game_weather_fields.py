from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('baseball', '0017_seed_all_star_teams'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='weather_temperature_f',
            field=models.IntegerField(default=70),
        ),
        migrations.AddField(
            model_name='game',
            name='weather_wind',
            field=models.CharField(choices=[('calm', 'Calm'), ('blowing_out', 'Blowing Out'), ('blowing_in', 'Blowing In')], default='calm', max_length=12),
        ),
        migrations.AddField(
            model_name='game',
            name='weather_sky',
            field=models.CharField(choices=[('overcast', 'Overcast'), ('rain', 'Rain')], default='overcast', max_length=12),
        ),
    ]
