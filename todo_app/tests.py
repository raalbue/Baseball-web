from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import ToDoItem, ToDoList


def make_user(username, password="Testpass123!"):
    return User.objects.create_user(username=username, password=password)


def make_list(user, title="My List"):
    return ToDoList.objects.create(owner=user, title=title)


def make_item(todo_list, title="An item"):
    return ToDoItem.objects.create(title=title, todo_list=todo_list)


class AnonymousRedirectTest(TestCase):
    def test_index_redirects_anonymous(self):
        response = self.client.get(reverse("index"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('index')}")

    def test_list_add_redirects_anonymous(self):
        response = self.client.get(reverse("list-add"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('list-add')}")


class ListCreateOwnerTest(TestCase):
    def setUp(self):
        self.user = make_user("alice")
        self.client.login(username="alice", password="Testpass123!")

    def test_list_create_sets_owner(self):
        self.client.post(reverse("list-add"), {"title": "Work"})
        todo_list = ToDoList.objects.get(title="Work")
        self.assertEqual(todo_list.owner, self.user)


class ListListViewScopingTest(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.alice_list = make_list(self.alice, "Alice List")
        self.bob_list = make_list(self.bob, "Bob List")

    def test_user_sees_only_own_lists(self):
        self.client.login(username="alice", password="Testpass123!")
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        lists = list(response.context["object_list"])
        self.assertIn(self.alice_list, lists)
        self.assertNotIn(self.bob_list, lists)


class OwnershipIsolationTest(TestCase):
    def setUp(self):
        self.alice = make_user("alice")
        self.bob = make_user("bob")
        self.alice_list = make_list(self.alice, "Alice List")
        self.alice_item = make_item(self.alice_list, "Alice item")
        self.client.login(username="bob", password="Testpass123!")

    def test_bob_gets_404_on_alice_list(self):
        url = reverse("list", args=[self.alice_list.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_bob_gets_404_on_alice_list_delete(self):
        url = reverse("list-delete", args=[self.alice_list.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_bob_gets_404_on_alice_item_add(self):
        url = reverse("item-add", args=[self.alice_list.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_bob_gets_404_on_alice_item_update(self):
        url = reverse("item-update", args=[self.alice_list.id, self.alice_item.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_bob_gets_404_on_alice_item_delete(self):
        url = reverse("item-delete", args=[self.alice_list.id, self.alice_item.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)


class PerOwnerUniquenessTest(TestCase):
    def test_two_users_can_share_list_title(self):
        alice = make_user("alice")
        bob = make_user("bob")
        list_a = make_list(alice, "Work")
        list_b = make_list(bob, "Work")
        self.assertEqual(list_a.title, list_b.title)
        self.assertNotEqual(list_a.owner, list_b.owner)

    def test_duplicate_title_same_user_raises(self):
        from django.db import IntegrityError
        alice = make_user("alice")
        make_list(alice, "Work")
        with self.assertRaises(IntegrityError):
            make_list(alice, "Work")
