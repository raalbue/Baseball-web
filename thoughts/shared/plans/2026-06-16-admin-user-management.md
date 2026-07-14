# Admin User Management — Implementation Plan

## Overview

Add an admin role to the existing multi-user Django todo app. Admins can view and fully
manage all users, their profiles, and their to-do data through a custom in-app management
area (`/manage/`) as well as an enhanced Django `/admin/` site. The admin role is expressed
via Django's built-in `is_staff` flag — no new model or migration needed to represent the
role itself.

## Current State Analysis

From reading the live codebase (June 2026):

- **Auth**: Django's built-in `auth.User`. Every todo view is behind `LoginRequiredMixin`
  and filters querysets to `request.user`. `accounts` app provides signup, login/logout,
  and a `Profile` (1:1 to User, auto-created by signal).
- **Role flags**: `User.is_staff` and `User.is_superuser` exist on every user but are
  unused by the app. Only the Django `/admin/` site checks `is_staff`.
- **No management UI**: There is no in-app way to list, create, edit, or delete other
  users. Profile views (`accounts/views.py:15-31`) always return `request.user.profile`.
- **Django admin** (`/admin/`): registers `ToDoItem`, `ToDoList` (`todo_app/admin.py`),
  and `Profile` (`accounts/admin.py`) with default display only. User management is
  available via the built-in `UserAdmin` but unenhanced.
- **Nav** (`templates/base.html`): shows My Lists / Profile / Logout for authenticated
  users. No admin link.

### Key Discoveries

- `accounts/views.py:19,29` — both profile views hard-code `self.request.user.profile`;
  admin views must use a different lookup (`get_object_or_404(Profile, user=user)` or
  `user.profile`).
- `todo_app/views.py:22` — `ItemListView` uses `get_object_or_404(ToDoList, id=...,
  owner=self.request.user)`. Admin views must drop the `owner` filter.
- `todo_app/views.py:50` — `ItemCreate.get_todo_list` also filters by
  `owner=self.request.user`; admin item-create must not.
- `templates/base.html:18-39` — nav is a simple `{% if user.is_authenticated %}` block
  with hard-coded items. Adding an `{% if user.is_staff %}` branch is straightforward.
- No `accounts/forms.py` exists yet; admin user-create/edit forms will be new.

## Desired End State

- A staff user sees an **"Admin"** link in the navbar.
- `/manage/users/` lists all users; staff can create, view, edit (username/email/
  is_active/is_staff + profile fields), and delete any user.
- `/manage/users/<pk>/lists/` lists a target user's todo lists; from there, staff
  can drill into list items, edit any item, and delete any list or item.
- Non-staff users who request any `/manage/` URL receive a 403.
- Anonymous users who request any `/manage/` URL are redirected to login.
- Django `/admin/` has a `ProfileInline` on `UserAdmin`, richer `list_display`, and
  list/item admin improvements.

**Verify:** Log in as a staff user → Admin link appears → manage any user's profile and
lists → non-staff user gets 403 on `/manage/` URLs.

## What We're NOT Doing

- No custom `AUTH_USER_MODEL` — we stay with `auth.User`.
- No permission-based access control beyond `is_staff` (no per-object or per-action
  granularity).
- No audit log of admin actions.
- No admin-initiated password reset email flow (staff can set a new password via a form,
  not an email link).
- No pagination on management list views (add later if user counts grow).
- No bulk-action UI (select multiple users and delete; out of scope).

---

## Phase 1: Admin Access Control Foundation

### Overview

Introduce a `StaffRequiredMixin`, add the Admin nav link for staff users, and create the
`manage` URL namespace — all gating infrastructure that the subsequent phases build on.

### Changes Required

#### 1. StaffRequiredMixin
**File**: `accounts/mixins.py` (new)
```python
from django.contrib.auth.mixins import UserPassesTestMixin


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff
```
`UserPassesTestMixin` redirects anonymous users to `LOGIN_URL` and raises
`PermissionDenied` (→ 403) for authenticated non-staff users. Both behaviors are correct.

#### 2. Admin nav link
**File**: `templates/base.html`

Inside the `{% if user.is_authenticated %}` block, add after the Profile `<li>`:
```html
{% if user.is_staff %}
<li class="nav-item">
    <a class="nav-link" href="{% url 'manage:user-list' %}">Admin</a>
</li>
{% endif %}
```

#### 3. Manage URL namespace placeholder
**File**: `manage/__init__.py` (new empty file — creates the `manage` Python package)
**File**: `manage/urls.py` (new)
```python
from django.urls import path
from . import views

app_name = "manage"

urlpatterns = []  # populated in Phase 2 and 3
```

**File**: `todo_project/urls.py` — add include before the `todo_app` include:
```python
path("manage/", include("manage.urls")),
```

**File**: `todo_project/settings.py` — add `"manage"` to `INSTALLED_APPS` (needed so
Django finds the app config and templates):
```python
INSTALLED_APPS = [
    ...
    "manage",
    "todo_app",
]
```

**File**: `manage/apps.py` (new)
```python
from django.apps import AppConfig

class ManageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "manage"
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes with no errors
- [ ] Staff user sees "Admin" link: verify `{% if user.is_staff %}` renders in a
  logged-in staff session (manual check sufficient; covered by Phase 2 tests)

#### Manual Verification:
- [ ] Log in as a staff user → "Admin" nav link appears
- [ ] Log in as a normal user → "Admin" nav link is absent

---

## Phase 2: User & Profile Management

### Overview

Full CRUD for users and their profiles at `/manage/users/`. Staff can list all users,
create new ones, view detail, edit (account fields + profile fields in one form), and
delete any user (with self-delete protection).

### Changes Required

#### 1. Forms
**File**: `manage/forms.py` (new)
```python
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
```

These are two separate forms rendered together on the create/edit pages (user fields +
profile fields in one `<form>` tag, one submit).

#### 2. Views
**File**: `manage/views.py` (new)
```python
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DeleteView, ListView

from accounts.mixins import StaffRequiredMixin
from accounts.models import Profile
from .forms import AdminUserCreateForm, AdminUserEditForm, AdminProfileForm

User = get_user_model()


class UserListView(StaffRequiredMixin, ListView):
    model = User
    template_name = "manage/user_list.html"
    context_object_name = "users"
    queryset = User.objects.select_related("profile").order_by("username")


class UserCreateView(StaffRequiredMixin, View):
    template_name = "manage/user_form.html"

    def get(self, request):
        return render(request, self.template_name, {
            "user_form": AdminUserCreateForm(),
            "profile_form": AdminProfileForm(),
            "action": "Create",
        })

    def post(self, request):
        user_form = AdminUserCreateForm(request.POST)
        profile_form = AdminProfileForm(request.POST)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            profile = user.profile          # created by signal
            profile_form = AdminProfileForm(request.POST, instance=profile)
            profile_form.save()
            messages.success(request, f"User '{user.username}' created.")
            return redirect("manage:user-list")
        return render(request, self.template_name, {
            "user_form": user_form,
            "profile_form": profile_form,
            "action": "Create",
        })


class UserEditView(StaffRequiredMixin, View):
    template_name = "manage/user_form.html"

    def get_user(self, pk):
        return get_object_or_404(User.objects.select_related("profile"), pk=pk)

    def get(self, request, pk):
        target = self.get_user(pk)
        return render(request, self.template_name, {
            "user_form": AdminUserEditForm(instance=target),
            "profile_form": AdminProfileForm(instance=target.profile),
            "target_user": target,
            "action": "Edit",
        })

    def post(self, request, pk):
        target = self.get_user(pk)
        user_form = AdminUserEditForm(request.POST, instance=target)
        profile_form = AdminProfileForm(request.POST, instance=target.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, f"User '{target.username}' updated.")
            return redirect("manage:user-list")
        return render(request, self.template_name, {
            "user_form": user_form,
            "profile_form": profile_form,
            "target_user": target,
            "action": "Edit",
        })


class UserDeleteView(StaffRequiredMixin, DeleteView):
    model = User
    template_name = "manage/user_confirm_delete.html"
    success_url = reverse_lazy("manage:user-list")
    context_object_name = "target_user"

    def post(self, request, *args, **kwargs):
        if self.get_object().pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
            return redirect("manage:user-list")
        return super().post(request, *args, **kwargs)
```

#### 3. URLs
**File**: `manage/urls.py` — add user paths:
```python
from django.urls import path
from . import views

app_name = "manage"

urlpatterns = [
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/add/", views.UserCreateView.as_view(), name="user-add"),
    path("users/<int:pk>/edit/", views.UserEditView.as_view(), name="user-edit"),
    path("users/<int:pk>/delete/", views.UserDeleteView.as_view(), name="user-delete"),
]
```

#### 4. Templates
All extend `base.html` and use Bootstrap 5 / crispy conventions consistent with existing
templates.

**File**: `manage/templates/manage/user_list.html`
```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Users</h2>
    <a class="btn btn-primary" href="{% url 'manage:user-add' %}">Add user</a>
</div>
<table class="table table-hover">
    <thead>
        <tr>
            <th>Username</th><th>Email</th><th>Display name</th>
            <th>Staff</th><th>Active</th><th></th>
        </tr>
    </thead>
    <tbody>
    {% for u in users %}
        <tr>
            <td>{{ u.username }}</td>
            <td>{{ u.email|default:"—" }}</td>
            <td>{{ u.profile.display_name|default:"—" }}</td>
            <td>{% if u.is_staff %}Yes{% else %}No{% endif %}</td>
            <td>{% if u.is_active %}Yes{% else %}No{% endif %}</td>
            <td>
                <a class="btn btn-sm btn-outline-secondary"
                   href="{% url 'manage:user-edit' u.pk %}">Edit</a>
                <a class="btn btn-sm btn-outline-primary"
                   href="{% url 'manage:user-lists' u.pk %}">Lists</a>
                {% if u.pk != request.user.pk %}
                <a class="btn btn-sm btn-outline-danger"
                   href="{% url 'manage:user-delete' u.pk %}">Delete</a>
                {% endif %}
            </td>
        </tr>
    {% endfor %}
    </tbody>
</table>
{% endblock %}
```

**File**: `manage/templates/manage/user_form.html`
```html
{% extends "base.html" %}
{% load crispy_forms_tags %}
{% block content %}
<h2>{{ action }} User</h2>
<div class="row">
    <div class="col-md-6">
        <form method="post">
            {% csrf_token %}
            <h5 class="mb-3">Account</h5>
            {{ user_form|crispy }}
            <h5 class="mt-4 mb-3">Profile</h5>
            {{ profile_form|crispy }}
            <button type="submit" class="btn btn-primary">Save</button>
            <a class="btn btn-secondary" href="{% url 'manage:user-list' %}">Cancel</a>
        </form>
    </div>
</div>
{% endblock %}
```

**File**: `manage/templates/manage/user_confirm_delete.html`
```html
{% extends "base.html" %}
{% block content %}
<h2>Delete user</h2>
<p>Delete <strong>{{ target_user.username }}</strong>? This will also delete all their
lists, items, and profile. This cannot be undone.</p>
<form method="post">
    {% csrf_token %}
    <button type="submit" class="btn btn-danger">Delete</button>
    <a class="btn btn-secondary" href="{% url 'manage:user-list' %}">Cancel</a>
</form>
{% endblock %}
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes
- [ ] Staff can access `/manage/users/` — returns 200
- [ ] Non-staff gets 403 on `/manage/users/`
- [ ] Anonymous gets redirect to login on `/manage/users/`

#### Manual Verification:
- [ ] User list shows all users with Staff/Active columns
- [ ] Create user populates profile via signal; form errors surface on both form sections
- [ ] Edit saves user + profile fields together
- [ ] Delete removes user (and cascades to profile + lists/items via Django cascade)
- [ ] Attempting to delete yourself redirects with an error message
- [ ] Deactivating a user (`is_active=False`) prevents that user from logging in

---

## Phase 3: Cross-User To-Do Data Management

### Overview

Staff can browse any user's todo lists and items from `/manage/users/<pk>/lists/`, and
can edit or delete any list or item. Reuses `ToDoList`/`ToDoItem` models and the existing
Bootstrap template style. These views drop the per-user `owner` filter.

### Changes Required

#### 1. Views
**File**: `manage/views.py` — add to existing file:
```python
from todo_app.models import ToDoList, ToDoItem


class ManagedListView(StaffRequiredMixin, ListView):
    model = ToDoList
    template_name = "manage/todolist_list.html"
    context_object_name = "todo_lists"

    def get_target_user(self):
        return get_object_or_404(User, pk=self.kwargs["pk"])

    def get_queryset(self):
        return ToDoList.objects.filter(owner=self.get_target_user())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["target_user"] = self.get_target_user()
        return context


class ManagedItemListView(StaffRequiredMixin, ListView):
    model = ToDoItem
    template_name = "manage/todoitem_list.html"
    context_object_name = "items"

    def get_todo_list(self):
        return get_object_or_404(ToDoList, pk=self.kwargs["list_pk"])

    def get_queryset(self):
        return ToDoItem.objects.filter(todo_list=self.get_todo_list())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["todo_list"] = self.get_todo_list()
        return context


class ManagedListDeleteView(StaffRequiredMixin, DeleteView):
    model = ToDoList
    template_name = "manage/todolist_confirm_delete.html"
    context_object_name = "todo_list"

    def get_success_url(self):
        return reverse_lazy("manage:user-lists", kwargs={"pk": self.object.owner_id})


class ManagedItemUpdateView(StaffRequiredMixin, View):
    template_name = "manage/todoitem_form.html"

    def get_item(self, list_pk, item_pk):
        return get_object_or_404(ToDoItem, pk=item_pk, todo_list_id=list_pk)

    def get(self, request, list_pk, item_pk):
        item = self.get_item(list_pk, item_pk)
        from todo_app.views import ItemUpdate
        form = ItemUpdate.form_class(instance=item) if hasattr(ItemUpdate, 'form_class') \
            else forms.modelform_factory(ToDoItem, fields=["title", "description", "due_date"])(instance=item)
        return render(request, self.template_name, {"form": form, "object": item,
                                                    "todo_list": item.todo_list})

    def post(self, request, list_pk, item_pk):
        item = self.get_item(list_pk, item_pk)
        from django.forms import modelform_factory
        Form = modelform_factory(ToDoItem, fields=["title", "description", "due_date"])
        form = Form(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "Item updated.")
            return redirect("manage:user-list-items",
                            list_pk=item.todo_list_id)
        return render(request, self.template_name, {"form": form, "object": item,
                                                    "todo_list": item.todo_list})


class ManagedItemDeleteView(StaffRequiredMixin, DeleteView):
    model = ToDoItem
    template_name = "manage/todoitem_confirm_delete.html"
    context_object_name = "item"

    def get_success_url(self):
        return reverse_lazy("manage:user-list-items",
                            kwargs={"list_pk": self.object.todo_list_id})
```

**Note on `ManagedItemUpdateView`:** Simplify by using a `modelform_factory` directly
(avoids importing and coupling to the todo_app view class). Write the Form inline as a
named class at top of file:

```python
from django import forms as dj_forms
from django.forms import modelform_factory
from todo_app.models import ToDoList, ToDoItem

TodoItemEditForm = modelform_factory(ToDoItem, fields=["title", "description", "due_date"])
```

Then `ManagedItemUpdateView` uses `TodoItemEditForm(instance=item)` / `TodoItemEditForm(request.POST, instance=item)` — no import from `todo_app.views`.

#### 2. URLs
**File**: `manage/urls.py` — add:
```python
path("users/<int:pk>/lists/", views.ManagedListView.as_view(), name="user-lists"),
path("users/<int:pk>/lists/<int:list_pk>/delete/",
     views.ManagedListDeleteView.as_view(), name="user-list-delete"),
path("lists/<int:list_pk>/items/",
     views.ManagedItemListView.as_view(), name="user-list-items"),
path("lists/<int:list_pk>/items/<int:item_pk>/edit/",
     views.ManagedItemUpdateView.as_view(), name="user-item-edit"),
path("lists/<int:list_pk>/items/<int:item_pk>/delete/",
     views.ManagedItemDeleteView.as_view(), name="user-item-delete"),
```

#### 3. Templates

**File**: `manage/templates/manage/todolist_list.html`
```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>{{ target_user.username }}'s Lists</h2>
    <a class="btn btn-secondary" href="{% url 'manage:user-list' %}">Back to users</a>
</div>
{% if todo_lists %}
<ul class="list-group">
    {% for lst in todo_lists %}
    <li class="list-group-item d-flex justify-content-between align-items-center">
        <a href="{% url 'manage:user-list-items' lst.id %}"
           class="text-decoration-none">{{ lst.title }}</a>
        <div>
            <a class="btn btn-sm btn-outline-danger"
               href="{% url 'manage:user-list-delete' target_user.pk lst.id %}">Delete</a>
        </div>
    </li>
    {% endfor %}
</ul>
{% else %}
<p class="text-muted">This user has no lists.</p>
{% endif %}
{% endblock %}
```

**File**: `manage/templates/manage/todoitem_list.html`
```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Items in "{{ todo_list.title }}"</h2>
    <a class="btn btn-secondary"
       href="{% url 'manage:user-lists' todo_list.owner_id %}">Back to lists</a>
</div>
{% if items %}
<ul class="list-group">
    {% for item in items %}
    <li class="list-group-item d-flex justify-content-between align-items-center">
        <span>{{ item.title }}</span>
        <div class="d-flex gap-2 align-items-center">
            <span class="text-muted small">Due {{ item.due_date|date:"l, F j" }}</span>
            <a class="btn btn-sm btn-outline-secondary"
               href="{% url 'manage:user-item-edit' todo_list.id item.id %}">Edit</a>
            <a class="btn btn-sm btn-outline-danger"
               href="{% url 'manage:user-item-delete' todo_list.id item.id %}">Delete</a>
        </div>
    </li>
    {% endfor %}
</ul>
{% else %}
<p class="text-muted">This list has no items.</p>
{% endif %}
{% endblock %}
```

**File**: `manage/templates/manage/todoitem_form.html`
```html
{% extends "base.html" %}
{% load crispy_forms_tags %}
{% block content %}
<h2>Edit Item</h2>
<div class="row">
    <div class="col-md-6">
        <form method="post">
            {% csrf_token %}
            {{ form|crispy }}
            <button type="submit" class="btn btn-primary">Save</button>
            <a class="btn btn-secondary"
               href="{% url 'manage:user-list-items' todo_list.id %}">Cancel</a>
        </form>
    </div>
</div>
{% endblock %}
```

**File**: `manage/templates/manage/todolist_confirm_delete.html`
```html
{% extends "base.html" %}
{% block content %}
<h2>Delete list</h2>
<p>Delete list <strong>"{{ todo_list.title }}"</strong> and all its items?
   This cannot be undone.</p>
<form method="post">
    {% csrf_token %}
    <button type="submit" class="btn btn-danger">Delete</button>
    <a class="btn btn-secondary"
       href="{% url 'manage:user-lists' todo_list.owner_id %}">Cancel</a>
</form>
{% endblock %}
```

**File**: `manage/templates/manage/todoitem_confirm_delete.html`
```html
{% extends "base.html" %}
{% block content %}
<h2>Delete item</h2>
<p>Delete item <strong>"{{ item.title }}"</strong>? This cannot be undone.</p>
<form method="post">
    {% csrf_token %}
    <button type="submit" class="btn btn-danger">Delete</button>
    <a class="btn btn-secondary"
       href="{% url 'manage:user-list-items' item.todo_list_id %}">Cancel</a>
</form>
{% endblock %}
```

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes
- [ ] Staff can access `/manage/users/<pk>/lists/` — returns 200
- [ ] Non-staff gets 403

#### Manual Verification:
- [ ] Admin drills: user list → user's lists → list's items → edit/delete item
- [ ] Deleting a list from the manage area removes it and its items
- [ ] "Back" links navigate correctly up the hierarchy
- [ ] Normal user's own todo views are unaffected (still scoped to `request.user`)

---

## Phase 4: Enhanced Django `/admin/`

### Overview

Add a `ProfileInline` to `UserAdmin` so profile fields are editable alongside the user.
Improve `list_display` and search for users. Add `list_display` improvements to
`ToDoListAdmin` and `ToDoItemAdmin`.

### Changes Required

#### 1. Enhanced UserAdmin with ProfileInline
**File**: `accounts/admin.py`
```python
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Profile

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = ["display_name", "bio", "address"]


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
```

#### 2. Enhanced ToDoList and ToDoItem admin
**File**: `todo_app/admin.py`
```python
from django.contrib import admin
from .models import ToDoList, ToDoItem


class ToDoItemInline(admin.TabularInline):
    model = ToDoItem
    extra = 0
    fields = ["title", "due_date"]
    readonly_fields = ["created_date"]


@admin.register(ToDoList)
class ToDoListAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "item_count"]
    list_filter = ["owner"]
    search_fields = ["title", "owner__username"]
    inlines = [ToDoItemInline]

    @admin.display(description="Items")
    def item_count(self, obj):
        return obj.todoitem_set.count()


@admin.register(ToDoItem)
class ToDoItemAdmin(admin.ModelAdmin):
    list_display = ["title", "todo_list", "due_date", "created_date"]
    list_filter = ["todo_list__owner", "due_date"]
    search_fields = ["title", "todo_list__title", "todo_list__owner__username"]
    readonly_fields = ["created_date"]
```

Note: remove the old `admin.site.register(ToDoItem)` and `admin.site.register(ToDoList)`
bare registrations (replacing with `@admin.register` decorator form).

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes
- [x] No `AlreadyRegistered` errors on server start

#### Manual Verification:
- [ ] `/admin/auth/user/` shows Display name column and has Profile inline on detail page
- [ ] `/admin/todo_app/todolist/` shows owner column and item count; inline shows items
- [ ] Search in user admin works by username, email, and display name

---

## Testing Strategy

### Unit Tests
**File**: `manage/tests.py` (new)

- `StaffRequiredMixin`: anonymous → redirect to login; non-staff → 403; staff → 200.
- `UserCreateView`: creates user and profile; form errors keep page.
- `UserEditView`: updates user and profile fields.
- `UserDeleteView`: self-delete returns error + redirect, not deletion.

**File**: `accounts/tests.py` (add)
- `StaffRequiredMixin` import test (covered above in manage tests).

### Integration Tests
**File**: `manage/tests.py`

- Staff can access full CRUD on users; changes visible in DB.
- Staff sees another user's todo lists/items; can delete them.
- Normal user's own todo views still return only their data after manage routes added.

### Manual Testing Steps

1. Create a staff user: `python manage.py createsuperuser` (or set `is_staff=True` via shell).
2. Log in as staff → confirm "Admin" appears in navbar.
3. Go to `/manage/users/` → user list shows all users.
4. Create a new user via Admin panel; confirm profile auto-created.
5. Edit the new user's profile fields; confirm changes persist.
6. Create some lists as the new user, then as staff browse `/manage/users/<pk>/lists/` → see them.
7. Edit an item, delete a list — confirm cascade removes items.
8. Attempt to delete yourself as staff → confirm error message, no deletion.
9. Log in as a normal user → no "Admin" nav link; `/manage/users/` returns 403.
10. Visit `/admin/` as staff → Profile inline on user detail; list admin shows owner + count.

## Migration Notes

No new models are introduced in this plan. The `manage` app has no models, so no
migration is needed. Phases 1–4 are all view/template/admin changes only.

## References

- Prior plan (implemented): `thoughts/shared/plans/2026-06-16-multi-user-auth-and-redesign.md`
- Research doc (partially stale): `thoughts/shared/research/2026-06-16-todo-app-architecture-map.md`
- `accounts/models.py` — `Profile` model
- `accounts/views.py:15-31` — current profile views (always `request.user.profile`)
- `accounts/signals.py:7-10` — profile auto-creation signal
- `todo_app/views.py:22,50` — per-user queryset filters to bypass in manage views
- `templates/base.html:18-39` — navbar to add Admin link to
- `todo_app/admin.py` — existing bare admin registrations to replace
