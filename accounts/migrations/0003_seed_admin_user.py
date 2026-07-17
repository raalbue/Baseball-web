from django.contrib.auth import get_user_model
from django.db import migrations


def seed_admin(apps, schema_editor):
    User = get_user_model()
    Profile = apps.get_model("accounts", "Profile")

    user, created = User.objects.get_or_create(
        username="Admin",
        defaults={"is_staff": True, "is_superuser": True, "is_active": True},
    )
    user.set_password("Admin")
    user.is_staff = True
    user.is_superuser = True
    user.save()

    profile, _ = Profile.objects.get_or_create(user_id=user.pk)
    profile.role = 1
    profile.save()


def unseed_admin(apps, schema_editor):
    get_user_model().objects.filter(username="Admin").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_profile_role"),
    ]

    operations = [
        migrations.RunPython(seed_admin, unseed_admin),
    ]
