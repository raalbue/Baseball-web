from django.conf import settings
from django.db import models
from django.urls import reverse


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)

    def get_absolute_url(self):
        return reverse("profile")

    def __str__(self):
        return self.display_name or self.user.get_username()

    class Meta:
        db_table = "profile"
