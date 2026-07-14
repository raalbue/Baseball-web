from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from accounts.models import Profile

User = get_user_model()


class AdminUserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email", "is_active", "is_staff"]


class AdminUserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email", "is_active", "is_staff"]


class AdminProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["display_name", "bio", "address"]
