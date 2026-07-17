from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=Profile)
def sync_role_to_staff(sender, instance, **kwargs):
    desired = instance.role == Profile.ROLE_ADMIN
    if instance.user.is_staff != desired:
        instance.user.is_staff = desired
        instance.user.save(update_fields=["is_staff"])
