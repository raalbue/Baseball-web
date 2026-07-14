# Multi-User Auth, Profiles & Bootstrap Redesign — Implementation Plan

## Overview

Evolve the single-user, no-auth Django todo app into a multi-user website with:
- User registration / login / logout via Django's built-in auth
- A per-user `Profile` (1:1 with `User`)
- Per-user todo lists & items (data scoped and isolated per user)
- A Bootstrap 5 layout (responsive navbar, cards, styled forms) that can scale to more pages/sections

The two legacy models `Person` and `Account` are removed.

## Current State Analysis

From research (`thoughts/shared/research/2026-06-16-todo-app-architecture-map.md`):

- **Django 6.0.5**, single app `todo_app`; project `todo_project`.
- Models (`todo_app/models.py`): `ToDoList` (`title` globally unique, **no owner**), `ToDoItem` (FK→list), `Account` (plaintext password, unwired), `Person` (unwired to auth).
- Views (`todo_app/views.py`): generic CBVs, **no auth/`LoginRequiredMixin`**, no per-user filtering.
- URLs (`todo_app/urls.py`): list/item CRUD at root; `persons/` CRUD.
- Templates: extend `base.html`, use **CDN Simple.css**, navigation via inline `onclick="location.href=..."`.
- `django.contrib.auth`, `sessions`, `messages` are **already** in `INSTALLED_APPS` (`settings.py:34-39`) and middleware (`settings.py:43-51`).
- DB: PostgreSQL with **hardcoded** credentials; `SECRET_KEY` hardcoded; `DEBUG = True` (`settings.py:23-26,83-92`).
- `TEMPLATES['DIRS']` is empty; `APP_DIRS: True` (`settings.py:55-68`).
- No tests (`todo_app/tests.py` empty). Stray `db.sqlite3` in repo root.

### Key Discoveries
- Auth/session/message infrastructure is already installed — only configuration + views/templates are missing.
- `ToDoList.title = CharField(unique=True)` (`models.py:13`) blocks two users from having a list with the same name — must change to unique-per-owner.
- All todo views must gain `LoginRequiredMixin` and `request.user` scoping, or any logged-in user can read/edit everyone's data.
- A misspelled template exists: `todo_app/templates/todo_app/todoitem_comfirm_delete.html`.

## Desired End State

- Anonymous visitors land on a login page; can sign up.
- A logged-in user sees **only their own** lists/items and can do full CRUD on them.
- Each user has a profile page they can view and edit.
- Every page shares a Bootstrap navbar (Lists · Profile · Logout, or Login/Sign up when anonymous).
- `Person` and `Account` models, views, urls, and templates no longer exist.
- Secrets and DB credentials come from environment variables.

**Verify:** create two users, each creates lists/items, confirm neither can see or reach the other's data (including by guessing URLs); profile edit persists; all pages render with Bootstrap styling.

## What We're NOT Doing

- No REST/JSON API (server-rendered templates only).
- No email verification or email-based password reset flow (can be added later via `django.contrib.auth` password-reset views + SMTP).
- No social / OAuth login.
- No production deployment hardening beyond moving secrets to env vars (no Docker, gunicorn, HTTPS config, static-file CDN).
- No sharing/collaboration of lists between users.
- No data migration/backfill — clean DB reset (per decision).

## Implementation Approach

Build bottom-up: foundation/config first, then auth, then profile, then data ownership, then redesign, then tests. Auth and ownership land before the redesign so the new templates can use real auth-aware navigation from the start. A dedicated `accounts` app keeps auth/profile concerns separate from `todo_app` so the project can scale to more apps/sections.

---

## Phase 1: Foundation & Settings

### Overview
Create the `accounts` app and a project-level `templates/` dir, move secrets to env vars, and add auth-related settings.

### Changes Required

#### 1. Create the accounts app
```
python manage.py startapp accounts
```

#### 2. Dependencies
**File**: `requirements.txt` — add:
```
python-dotenv==1.0.1
django-crispy-forms==2.3
crispy-bootstrap5==2024.10
```
Install: `pip install -r requirements.txt`

#### 3. Settings
**File**: `todo_project/settings.py`
- Load `.env` and read secrets from env:
```python
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-dev-only-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if os.environ.get("DJANGO_ALLOWED_HOSTS") else []
```
- `INSTALLED_APPS` — add `accounts`, `crispy_forms`, `crispy_bootstrap5`:
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "crispy_forms",
    "crispy_bootstrap5",
    "accounts",
    "todo_app",
]
```
- Project-level templates dir:
```python
TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]
```
- Database from env:
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "todo_db"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}
```
- Auth redirects + crispy at end of file:
```python
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "index"
LOGOUT_REDIRECT_URL = "login"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"
```

#### 4. Env files
**File**: `.env` (create, real values; not committed):
```
DJANGO_SECRET_KEY=<generate a new key>
DJANGO_DEBUG=True
DB_NAME=todo_db
DB_USER=postgres
DB_PASSWORD=rdarocks1
DB_HOST=localhost
DB_PORT=5432
```
**File**: `.env.example` (committed template, no secrets).
**File**: `.gitignore` (create) — include `.env`, `db.sqlite3`, `__pycache__/`, `venv/`, `*.pyc`.

#### 5. Remove stray SQLite file
Delete `db.sqlite3` from repo root (DB is PostgreSQL).

### Success Criteria

#### Automated Verification:
- [x] App config loads: `python manage.py check`
- [x] `accounts/` app directory exists with `models.py`, `views.py`, `apps.py`
- [x] Server boots: `python manage.py runserver` starts without errors

#### Manual Verification:
- [ ] Setting `DJANGO_SECRET_KEY`/`DB_PASSWORD` only in `.env` still runs the app
- [ ] No secrets remain hardcoded in `settings.py`

**Implementation Note**: After automated checks pass, pause for confirmation before Phase 2.

---

## Phase 2: Authentication (login / logout / signup)

### Overview
Wire up Django's built-in auth views plus a signup view, with templates, and protect existing todo views.

### Changes Required

#### 1. Accounts URLs
**File**: `accounts/urls.py` (new)
```python
from django.urls import path, include
from . import views

urlpatterns = [
    path("signup/", views.SignUpView.as_view(), name="signup"),
    path("", include("django.contrib.auth.urls")),  # login, logout, password_change, etc.
]
```
**File**: `todo_project/urls.py` — add `path("accounts/", include("accounts.urls"))` above the `todo_app` include.

#### 2. Signup view
**File**: `accounts/views.py`
```python
from django.contrib.auth.forms import UserCreationForm
from django.urls import reverse_lazy
from django.views.generic import CreateView

class SignUpView(CreateView):
    form_class = UserCreationForm
    success_url = reverse_lazy("login")
    template_name = "registration/signup.html"
```

#### 3. Auth templates
**Files** (new, project-level `templates/registration/`):
- `registration/login.html` — renders `{{ form }}` with crispy, CSRF, link to signup.
- `registration/signup.html` — renders `UserCreationForm`, link to login.
- `registration/logged_out.html` — confirmation + link to login (used by `LogoutView`).

(These extend `base.html`; Bootstrap styling applied fully in Phase 5, but they work now.)

#### 4. Protect todo views
**File**: `todo_app/views.py` — add `LoginRequiredMixin` (first base class) to every todo view:
```python
from django.contrib.auth.mixins import LoginRequiredMixin
class ListListView(LoginRequiredMixin, ListView): ...
# ...and all other todo CBVs
```
(Full per-user scoping lands in Phase 4; this phase just requires being logged in.)

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes
- [x] URLs resolve: `python manage.py shell -c "from django.urls import reverse; print(reverse('login'), reverse('signup'), reverse('logout'))"`
- [ ] Anonymous request to `/` redirects to login (test added in Phase 6)

#### Manual Verification:
- [ ] Visiting `/` while logged out redirects to `/accounts/login/`
- [ ] Signup creates a user and redirects to login
- [ ] Login then logout works; logout lands on login page

**Implementation Note**: Pause for confirmation before Phase 3.

---

## Phase 3: User Profile + remove Person/Account

### Overview
Add a `Profile` model auto-created per user, with view/edit pages; delete the legacy `Person` and `Account` models and all their views/urls/templates.

### Changes Required

#### 1. Profile model
**File**: `accounts/models.py`
```python
from django.conf import settings
from django.db import models
from django.urls import reverse

class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)

    def get_absolute_url(self):
        return reverse("profile")

    def __str__(self):
        return self.display_name or self.user.get_username()

    class Meta:
        db_table = "profile"
```

#### 2. Auto-create profile via signal
**File**: `accounts/signals.py` (new)
```python
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Profile

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
```
**File**: `accounts/apps.py` — import signals in `ready()`:
```python
class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    def ready(self):
        from . import signals  # noqa
```

#### 3. Profile views + URLs
**File**: `accounts/views.py` — add:
```python
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, UpdateView
from .models import Profile

class ProfileDetailView(LoginRequiredMixin, DetailView):
    model = Profile
    template_name = "accounts/profile_detail.html"
    def get_object(self): return self.request.user.profile

class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = Profile
    fields = ["display_name", "bio", "address"]
    template_name = "accounts/profile_form.html"
    success_url = reverse_lazy("profile")
    def get_object(self): return self.request.user.profile
```
**File**: `accounts/urls.py` — add `path("profile/", ...)` and `path("profile/edit/", ...)` named `profile` / `profile-edit`.
**Files**: `accounts/templates/accounts/profile_detail.html`, `accounts/templates/accounts/profile_form.html` (new).

#### 4. Remove Person & Account
- `todo_app/models.py` — delete `Account` and `Person` classes.
- `todo_app/views.py` — delete `PersonListView`, `PersonDetailView`, `PersonCreate`, `PersonUpdate`, `PersonDelete`, and the `Person` import.
- `todo_app/urls.py` — delete the five `persons/...` paths.
- Delete templates: `person_list.html`, `person_detail.html`, `person_form.html`, `person_confirm_delete.html`.
- `todo_app/admin.py` — unchanged (never registered them).

#### 5. Migrations
```
python manage.py makemigrations accounts todo_app
python manage.py migrate
```
(Generates `Profile` create + `Person`/`Account` delete. Clean reset DB if convenient: `python manage.py flush` or drop/recreate `todo_db`.)

#### 6. Register Profile in admin (optional, scalability)
**File**: `accounts/admin.py` — `admin.site.register(Profile)`.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py makemigrations --check` shows no missing migrations after applying
- [x] `python manage.py migrate` applies cleanly
- [ ] Signal test: creating a `User` in shell yields `user.profile` (test added in Phase 6)
- [x] `python manage.py check` passes; no import errors referencing `Person`/`Account`

#### Manual Verification:
- [ ] A newly signed-up user has a profile automatically
- [ ] `/accounts/profile/` shows the profile; edit saves changes
- [ ] `persons/` URLs now 404

**Implementation Note**: Pause for confirmation before Phase 4.

---

## Phase 4: Per-User Todo Ownership

### Overview
Make lists belong to users and isolate all CRUD by `request.user`.

### Changes Required

#### 1. Model
**File**: `todo_app/models.py` — `ToDoList`:
```python
from django.conf import settings
from django.db import models

class ToDoList(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="todo_lists")
    title = models.CharField(max_length=100)  # remove unique=True

    class Meta:
        db_table = "todolist"
        constraints = [
            models.UniqueConstraint(fields=["owner", "title"], name="unique_list_title_per_owner")
        ]
    # get_absolute_url / __str__ unchanged
```
`ToDoItem` stays FK→`ToDoList`; ownership flows through the list.

#### 2. Views — scope to user
**File**: `todo_app/views.py`
- `ListListView.get_queryset`: `return ToDoList.objects.filter(owner=self.request.user)`
- `ListCreate`: drop `owner` from form `fields` (stays `["title"]`); set owner in `form_valid`:
```python
def form_valid(self, form):
    form.instance.owner = self.request.user
    return super().form_valid(form)
```
- `ItemListView.get_queryset`: filter `todo_list_id=...` **and** `todo_list__owner=self.request.user`; in `get_context_data` use `get_object_or_404(ToDoList, id=..., owner=request.user)`.
- `ListDelete`/`ItemUpdate`/`ItemDelete`/`ItemCreate`: override `get_queryset` to restrict to the user's objects (e.g. `ToDoItem.objects.filter(todo_list__owner=self.request.user)` and `ToDoList.objects.filter(owner=self.request.user)`), and validate the `list_id` belongs to the user in `ItemCreate.get_initial`/`get_context_data` via `get_object_or_404(..., owner=request.user)`.
- Remove `todo_list` from `ItemCreate`/`ItemUpdate` form `fields` so users can't reassign items to arbitrary lists; set it from URL `list_id` (already pre-filled via `get_initial`) in `form_valid`.

#### 3. Migration
```
python manage.py makemigrations todo_app
python manage.py migrate
```
Adding a non-null `owner` to a table with existing rows requires a clean DB (per decision) or a one-off default; plan assumes clean reset.

### Success Criteria

#### Automated Verification:
- [x] Migrations apply: `python manage.py migrate`
- [ ] Ownership-isolation tests pass (Phase 6): user B gets 404 on user A's list/item URLs
- [x] `python manage.py check` passes

#### Manual Verification:
- [ ] User A creates lists/items; User B (separate login) sees none of them
- [ ] Visiting User A's list URL as User B returns 404, not the data
- [ ] Two users can each have a list titled "Work"

**Implementation Note**: Pause for confirmation before Phase 5.

---

## Phase 5: Bootstrap 5 Redesign

### Overview
Replace Simple.css with a Bootstrap 5 layout: responsive navbar, container, cards/list-groups, crispy-styled forms, and Bootstrap alert rendering for messages. Remove inline `onclick` navigation in favor of links/buttons.

### Changes Required

#### 1. Base layout
**File**: `templates/base.html` (move to project-level `templates/`, replacing `todo_app/templates/base.html`)
- Bootstrap 5 CSS/JS via CDN in `<head>`/end of `<body>`.
- Responsive `<nav class="navbar ...">` with brand → `index`, and links:
  - authenticated: **My Lists** (`index`), **Profile** (`profile`), **Logout** (POST form to `logout`)
  - anonymous: **Login** (`login`), **Sign up** (`signup`)
- `<main class="container py-4">` wrapping `{% block content %}`.
- Messages block rendering Bootstrap alerts:
```django
{% if messages %}{% for m in messages %}
  <div class="alert alert-{{ m.tags }}">{{ m }}</div>
{% endfor %}{% endif %}
```
- Note: Django `LogoutView` requires POST — use a small inline form/button in the navbar, not a link.

#### 2. Convert templates to Bootstrap
**Files**: `todo_app/templates/todo_app/index.html`, `todo_list.html`, `todoitem_form.html`, `todolist_form.html`, `todolist_confirm_delete.html`, and the delete confirm (fix filename `todoitem_comfirm_delete.html` → `todoitem_confirm_delete.html`).
- Lists/items → `list-group` with anchor links (`<a href="{% url ... %}">`), replacing `role="button" onclick=...`.
- Buttons → `<a class="btn btn-primary">` / `<button class="btn ...">`.
- Forms → `{% load crispy_forms_tags %}` + `{{ form|crispy }}` instead of `{{ form.as_table }}`.

#### 3. Auth/profile templates
Apply the same Bootstrap/crispy treatment to `registration/login.html`, `registration/signup.html`, `registration/logged_out.html`, `accounts/profile_detail.html`, `accounts/profile_form.html`.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` passes
- [x] No template references remain to deleted `person`/`Account` URLs: `grep -r "person" todo_app/templates templates` returns nothing
- [ ] Pages return 200 for a logged-in user (smoke tests in Phase 6)

#### Manual Verification:
- [ ] Navbar appears on every page with correct auth-aware links
- [ ] Logout button (POST) logs the user out
- [ ] Forms render as Bootstrap-styled inputs (not a raw table)
- [ ] Layout is responsive (navbar collapses on narrow screens)
- [ ] Success/error messages show as Bootstrap alerts

**Implementation Note**: Pause for confirmation before Phase 6.

---

## Phase 6: Tests

### Overview
Add automated tests covering the new behavior, especially ownership isolation.

### Changes Required

#### 1. Accounts tests
**File**: `accounts/tests.py`
- Signup creates a `User` and an associated `Profile` (signal).
- Login required: `/accounts/profile/` redirects anonymous users to login.
- Profile edit updates fields.

#### 2. Todo tests
**File**: `todo_app/tests.py`
- Anonymous `/` redirects to login.
- `ListCreate` sets `owner = request.user`.
- `ListListView` returns only the requesting user's lists.
- **Isolation**: User B requesting User A's list/item detail/update/delete URLs gets 404.
- Two users can both create a list named "Work" (per-owner uniqueness).

### Success Criteria

#### Automated Verification:
- [x] All tests pass: `python manage.py test`
- [ ] Ownership-isolation tests fail if `LoginRequiredMixin`/queryset scoping is removed (sanity check)

#### Manual Verification:
- [ ] Full flow once end-to-end: signup → login → create list+items → edit profile → logout

---

## Testing Strategy

### Unit Tests
- Profile auto-creation signal.
- `form_valid` owner assignment.
- Per-owner unique constraint (two "Work" lists across users; duplicate within one user rejected).

### Integration Tests
- Ownership isolation across two `Client()` sessions (User A vs User B) for every todo CRUD URL.
- Auth gating: anonymous access to protected URLs redirects to login.

### Manual Testing Steps
1. Sign up as `alice`; confirm redirect to login and that a profile exists.
2. Log in as `alice`; create list "Work" + a few items; edit one; delete one.
3. Edit alice's profile (display name, address); confirm persistence.
4. Open a second browser/incognito; sign up + log in as `bob`; create list "Work".
5. As `bob`, try `alice`'s list URL (`/list/<alice_list_id>/`) → expect 404.
6. Confirm navbar links change between anonymous and authenticated states; logout works.

## Performance Considerations
- Querysets are filtered by `owner` (indexed FK) — fine at this scale. The `UniqueConstraint(owner, title)` adds a supporting index for list lookups.
- No N+1 concerns of note; if list views later show item counts, add `annotate`/`prefetch_related`.

## Migration Notes
- Clean reset chosen: drop & recreate `todo_db` (or `python manage.py flush`) before applying the `owner` and `Profile`/delete migrations, since `owner` is non-null.
- Deleting `Person`/`Account` drops the `person` and `account` tables.

## References
- Research: `thoughts/shared/research/2026-06-16-todo-app-architecture-map.md`
- Models: `todo_app/models.py:12-66`
- Views: `todo_app/views.py:14-136`
- URLs: `todo_app/urls.py:5-35`
- Settings: `todo_project/settings.py:23-92`
- Misspelled template to fix: `todo_app/templates/todo_app/todoitem_comfirm_delete.html`
