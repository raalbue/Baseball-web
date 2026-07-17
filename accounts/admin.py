from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Profile

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ["display_name", "bio", "address", "role"]


class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ["username", "email", "get_display_name", "is_staff", "is_active",
                    "date_joined"]
    list_filter = ["is_staff", "is_active", "date_joined"]
    search_fields = ["username", "email", "profile__display_name"]

    @admin.display(description="Display name")
    def get_display_name(self, obj):
        return obj.profile.display_name if hasattr(obj, "profile") else ""


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.register(Profile)
