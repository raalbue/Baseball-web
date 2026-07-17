from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password

from accounts.models import Profile

User = get_user_model()


class AdminUserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email", "is_active"]


class AdminUserEditForm(forms.ModelForm):
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="Set Password",
        help_text="Leave blank to keep current password. Min 8 characters.",
    )

    class Meta:
        model = User
        fields = ["username", "email", "is_active"]

    def clean_new_password(self):
        value = self.cleaned_data.get("new_password")
        if value:
            validate_password(value, user=self.instance)
        return value


class AdminProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ["display_name", "bio", "address", "role"]
