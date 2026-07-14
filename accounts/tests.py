from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile


class SignupCreatesProfileTest(TestCase):
    def test_signup_creates_user_and_profile(self):
        response = self.client.post(reverse("signup"), {
            "username": "alice",
            "password1": "Testpass123!",
            "password2": "Testpass123!",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="alice")
        self.assertTrue(hasattr(user, "profile"))
        self.assertIsInstance(user.profile, Profile)

    def test_signal_creates_profile_on_user_create(self):
        user = User.objects.create_user(username="bob", password="Testpass123!")
        self.assertTrue(Profile.objects.filter(user=user).exists())


class ProfileLoginRequiredTest(TestCase):
    def test_profile_redirects_anonymous(self):
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")

    def test_profile_edit_redirects_anonymous(self):
        response = self.client.get(reverse("profile-edit"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile-edit')}")


class ProfileEditTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="Testpass123!")
        self.client.login(username="alice", password="Testpass123!")

    def test_profile_detail_accessible(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)

    def test_profile_edit_saves_fields(self):
        response = self.client.post(reverse("profile-edit"), {
            "display_name": "Alice Smith",
            "bio": "Hello world",
            "address": "123 Main St",
        })
        self.assertRedirects(response, reverse("profile"))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.display_name, "Alice Smith")
        self.assertEqual(self.user.profile.bio, "Hello world")
        self.assertEqual(self.user.profile.address, "123 Main St")
