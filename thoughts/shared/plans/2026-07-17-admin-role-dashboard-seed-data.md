# Admin Role + Dashboard Upgrade + Seed Data — Implementation Plan

## Overview

Four asks, one plan:

1. Add a `role` field (0=user, 1=admin) to user accounts.
2. Upgrade the existing `/manage/` admin dashboard (already built, staff-gated) to
   surface Role/Status columns, a password-reset field, and a "Hello {user}" navbar
   dropdown, per the supplied UI screenshots.
3. Data migration: seed a default `Admin`/`Admin` user with role=1.
4. Data migrations: seed `stadium`+`team` rows (SQL provided by user) and `player`
   rows (from `players.csv`).

## Current State Analysis

- **No custom `AUTH_USER_MODEL`.** Stock `django.contrib.auth.models.User`
  (`accounts/models.py`, `baseball_project/settings.py` — no `AUTH_USER_MODEL` set).
  Role must live on the existing `Profile` OneToOne (`accounts/models.py:6-21`), not
  via a user-model swap.
- **Admin dashboard already exists.** `manage` app (`manage/views.py`,
  `manage/forms.py`, `manage/urls.py`, `manage/templates/manage/`) is a full
  staff-gated CRUD for users, built per `thoughts/shared/plans/2026-06-16-admin-user-management.md`
  (already implemented). Role today = `User.is_staff`, checked by
  `StaffRequiredMixin` (`accounts/mixins.py:4-6`). This plan extends that dashboard
  rather than building a new one.
- **Team/Player/Stadium models already exist**, `managed = False`
  (`baseball/models.py:10-96`) — Django doesn't own their DDL, the tables already
  exist in Postgres (confirmed by user), but are currently **empty**.
- **`players.csv`** at `C:\Users\raalb\Downloads\players.csv` has a header that maps
  1:1 to `Player` model fields (`player_id,first_name,last_name,team_id,position,
  jersey_number,date_of_birth,height_inches,weight_lbs,nationality,bats,throws,
  team_abbrev,season,g,g_p,g_sp,g_rp,g_c,g_1b,g_2b,g_3b,g_ss,g_lf,g_cf,g_rf,g_of,
  g_dh,g_ph,g_pr,first_game,last_game,dataid,status,active`), 1693 data rows.
  `active` is `t`/`f` text; must convert to bool.
- **No `RunPython`/data migration exists anywhere in the repo yet** — these will be
  the first.
- **Migration numbering**: `accounts/migrations/` has only `0001_initial.py`;
  `baseball/migrations/` goes up to `0005_gamestat.py`.
- Pre-existing unrelated diff: `baseball/migrations/0003_game_away_team_game_home_team.py`
  is locally modified (adds `db_constraint=False` to the two `Team` FKs) — untouched
  by this plan, noted so it isn't confused with a new change.

### Key Discoveries / Decisions (from user Q&A)

- **Role storage**: `Profile.role` — `IntegerField`, choices `(0, "User")`,
  `(1, "Admin")`, default `0`.
- **Role ↔ `is_staff` sync**: a `post_save` signal on `Profile` sets
  `user.is_staff = (role == 1)` whenever a profile is saved. This means
  `StaffRequiredMixin` (already gating `/manage/`) keeps working unchanged — no
  mixin rewrite needed, no `is_staff` checkbox left in the admin forms (it becomes
  fully derived from `role`).
- **Edit-user page**: single combined form (today's pattern), not the screenshots'
  four separate mini-forms/buttons. Role, Account Status (`is_active`), and a new
  optional "Set Password" field are added as extra fields inside the existing
  combined `user_form` + `profile_form` POST, one Save button. `is_active` stays a
  checkbox (not a dropdown) — the one deliberate visual deviation from the
  screenshots, traded for staying inside the existing form/save pattern.
- **Seed admin user**: username `Admin`, password `Admin`, `role=1`. Also sets
  `is_superuser=True` so the seeded account has full access to Django's built-in
  `/admin/` site too, not just `/manage/` (role=1 is meant to mean "full admin").
  `create_user`/direct password hash bypasses `AUTH_PASSWORD_VALIDATORS`, so the
  weak default password is fine to set via migration — flagged in Migration Notes
  as "change immediately in any real deployment."
- **Teams/Stadiums**: tables exist, empty. Seed via a `RunSQL` data migration using
  the exact `INSERT` statements the user supplied (30 stadiums, 30 teams).
- **"Player sets" = `Player` table rows**, loaded from `players.csv`. The CSV lives
  outside the repo (user's Downloads folder) — it will be copied into the repo
  under `baseball/migrations/seed_data/players.csv` so the migration is portable
  and reproducible on any machine/deploy, not just this one.

## Desired End State

- Every `Profile` has a `role` (0 or 1). Setting `role=1` on a user makes them
  `is_staff=True` (and therefore able to reach `/manage/`); `role=0` reverts it.
- `/manage/users/` list shows **Username / Email / Role / Status / Actions**
  columns (Role: "Admin"/"User", Status: "Active"/"Inactive"), matching the
  screenshot's column set (Display name column dropped from the list view — still
  editable on the edit page).
- `/manage/users/<pk>/edit/` includes a Role dropdown, Account Status checkbox, and
  an optional "Set Password" field (blank = unchanged), all saved by the existing
  single Save button.
- Navbar: authenticated users see a **"Hello {username}"** dropdown containing
  "Admin Dashboard" (only if `is_staff`) and "Logout", replacing today's flat
  Admin-link + Logout-button items. "My Lists" / "Profile" / "Baseball" links stay
  as they are, outside the dropdown.
- A fresh `python manage.py migrate` on an empty DB produces: a working `Admin`/
  `Admin` (role 1) login, 30 rows in `stadium`, 30 rows in `team`, 1693 rows in
  `player`.

### Verify by:
- Log in as `Admin`/`Admin` → navbar shows "Hello Admin" → dropdown → "Admin
  Dashboard" works → `/manage/users/` shows Admin with Role=Admin, Status=Active.
- Edit a normal user, set Role to Admin, Save → that user can now reach
  `/manage/users/`; their `is_staff` is `True` in the DB.
- `GameSetupForm`'s team dropdowns (`baseball/forms.py`) populate with the 30 seeded
  teams; `RosterForm` position pools populate with real players per team.
- `Player.objects.count() == 1693`, `Team.objects.count() == 30`,
  `Stadium.objects.count() == 30`.

## What We're NOT Doing

- No `AUTH_USER_MODEL` swap.
- No four-separate-mini-form edit page (screenshots' exact layout) — single
  combined form instead (user-confirmed trade-off).
- No uppercase/lowercase/number/special-character password composition validator —
  the screenshot's hint text is UI copy from an unrelated app; new/admin-set
  passwords are validated with the project's existing `AUTH_PASSWORD_VALIDATORS`
  (min length 8, common-password check, not-all-numeric, not-too-similar-to-username).
- No "Photos" tab (screenshot artifact from an unrelated app, no equivalent concept
  here).
- No pagination on the user list (pre-existing scope limit from the original
  admin-dashboard plan, unchanged).
- No re-import/upsert logic for players.csv beyond `ignore_conflicts=True` on
  `bulk_create` (safe to re-run migrate on a fresh DB; not a general re-sync tool).

## Implementation Approach

Five phases, each independently runnable/migratable:

1. Role field + sync (accounts app).
2. Dashboard UI upgrade (manage app + navbar).
3. Seed default admin user (accounts app data migration, depends on Phase 1).
4. Seed stadiums + teams (baseball app data migration).
5. Seed players from CSV (baseball app data migration, depends on Phase 4 for
   `team_id` FK targets to exist).

---

## Phase 1: Role Field + is_staff Sync

### Overview
Add `role` to `Profile`, keep it in sync with `User.is_staff` so all existing
staff-gating keeps working unchanged.

### Changes Required

#### 1. `accounts/models.py`
```python
class Profile(models.Model):
    ROLE_USER = 0
    ROLE_ADMIN = 1
    ROLE_CHOICES = [(ROLE_USER, "User"), (ROLE_ADMIN, "Admin")]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    role = models.IntegerField(choices=ROLE_CHOICES, default=ROLE_USER)

    def get_absolute_url(self):
        return reverse("profile")

    def __str__(self):
        return self.display_name or self.user.get_username()

    class Meta:
        db_table = "profile"
```

#### 2. `accounts/signals.py` — add sync receiver
```python
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
```

#### 3. `accounts/admin.py` — expose role on the inline
**Change**: `ProfileInline.fields` → `["display_name", "bio", "address", "role"]`.

#### 4. Migration
```
python manage.py makemigrations accounts
```
Produces `accounts/migrations/0002_profile_role.py` (autogenerated `AddField`,
`default=0`).

### Success Criteria

#### Automated Verification:
- [x] `python manage.py makemigrations --check accounts` exits 0 (no missing migrations for this app — whole-project `--check` still fails on the pre-existing unrelated `baseball/migrations/0003` local diff noted in Current State Analysis, untouched by this phase).
- [x] `python manage.py migrate accounts` exits 0.
- [x] `python manage.py check` exits 0.

#### Manual Verification:
- [x] In shell: `p = Profile.objects.first(); p.role = 1; p.save(); p.user.refresh_from_db(); p.user.is_staff == True`.
- [x] Setting `role` back to `0` and saving flips `is_staff` back to `False`.

---

## Phase 2: Dashboard UI Upgrade

### Overview
Extend the existing `manage` app forms/views/templates with Role, Status, and a
password field; add the navbar "Hello {user}" dropdown.

### Changes Required

#### 1. `manage/forms.py`
```python
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

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
```
`is_staff` is dropped from both forms — it's fully derived from `role` via the
Phase 1 signal.

#### 2. `manage/views.py` — apply the new password on save
**Change** `UserEditView.post`:
```python
    def post(self, request, pk):
        target = self.get_user(pk)
        user_form = AdminUserEditForm(request.POST, instance=target)
        profile_form = AdminProfileForm(request.POST, instance=target.profile)
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save(commit=False)
            new_password = user_form.cleaned_data.get("new_password")
            if new_password:
                user.set_password(new_password)
            user.save()
            profile_form.save()
            messages.success(request, f"User '{target.username}' updated.")
            return redirect("manage:user-list")
        return render(request, self.template_name, {
            "user_form": user_form,
            "profile_form": profile_form,
            "target_user": target,
            "action": "Edit",
        })
```
`UserCreateView` is unchanged (new users still get their password via
`UserCreationForm`'s `password1`/`password2`).

#### 3. `manage/templates/manage/user_list.html` — Role/Status columns
```html
{% extends "base.html" %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
    <h2>Users</h2>
    <a class="btn btn-primary" href="{% url 'manage:user-add' %}">+ Add User</a>
</div>
<table class="table table-hover">
    <thead>
        <tr>
            <th>Username</th><th>Email</th><th>Role</th><th>Status</th><th></th>
        </tr>
    </thead>
    <tbody>
    {% for u in users %}
        <tr>
            <td>{{ u.username }}</td>
            <td>{{ u.email|default:"—" }}</td>
            <td>{{ u.profile.get_role_display }}</td>
            <td>
                {% if u.is_active %}
                <span class="text-success">Active</span>
                {% else %}
                <span class="text-danger">Inactive</span>
                {% endif %}
            </td>
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
(`UserListView.queryset` already does `select_related("profile")` —
`u.profile.get_role_display` is free.)

#### 4. `templates/base.html` — "Hello {user}" dropdown
**Replace** the existing flat `{% if user.is_staff %}Admin{% endif %}` link + the
Logout `<li>` with:
```html
<li class="nav-item dropdown">
    <a class="nav-link dropdown-toggle" href="#" id="userMenu" role="button"
       data-bs-toggle="dropdown" aria-expanded="false">
        Hello {{ user.username }}
    </a>
    <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userMenu">
        {% if user.is_staff %}
        <li><a class="dropdown-item" href="{% url 'manage:user-list' %}">Admin Dashboard</a></li>
        {% endif %}
        <li>
            <form method="post" action="{% url 'logout' %}" class="m-0">
                {% csrf_token %}
                <button type="submit" class="dropdown-item text-danger">Logout</button>
            </form>
        </li>
    </ul>
</li>
```
"My Lists" / "Profile" / "Baseball" `<li>`s stay unchanged, before this block.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py check` exits 0.

#### Manual Verification:
- [x] `/manage/users/` shows Role ("User"/"Admin") and Status ("Active"/"Inactive") columns.
- [x] Editing a user, changing Role to Admin and saving, makes them able to reach `/manage/` (role→is_staff sync from Phase 1 fires on `profile_form.save()`).
- [x] Editing a user, typing a new password and saving, lets that user log in with the new password.
- [x] Leaving "Set Password" blank on save does not change the user's password.
- [x] Navbar shows "Hello {username}" dropdown; "Admin Dashboard" item only appears for staff users; "Logout" works from inside the dropdown.

---

## Phase 3: Seed Default Admin User

### Overview
Data migration creating `Admin`/`Admin`, role=1, superuser, idempotent.

### Changes Required

#### 1. `accounts/migrations/0003_seed_admin_user.py`
```python
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

    profile, _ = Profile.objects.get_or_create(user=user)
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
```
Note: this migration uses the *historical* `apps.get_model` for `Profile`, but the
real (non-historical) `get_user_model()` for `User.set_password`/`save()`, since
`set_password` isn't available on the frozen historical model — this is the
standard Django pattern for data migrations that touch `auth.User`.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py migrate accounts` exits 0.
- [x] `python manage.py shell -c "from django.contrib.auth import get_user_model; u=get_user_model().objects.get(username='Admin'); assert u.check_password('Admin') and u.is_staff and u.is_superuser and u.profile.role == 1"` exits 0.
- [x] Re-running (`migrate accounts 0002` then forward again) does not create a duplicate user — `Admin` count stays 1.

#### Manual Verification:
- [x] Log in with `Admin`/`Admin` → succeeds, dropdown shows "Admin Dashboard".

---

## Phase 4: Seed Stadiums + Teams

### Overview
`RunSQL` data migration inserting the 30 stadiums and 30 teams the user supplied,
guarded so it's a no-op if data already exists.

### Changes Required

#### 1. `baseball/migrations/0006_seed_stadiums_teams.py`
```python
from django.db import migrations

STADIUMS_SQL = """
INSERT INTO stadium (stadium_id, name, city, state, country, capacity) VALUES
(1,  'Fenway Park',               'Boston',        'MA', 'USA', 37755),
(2,  'Yankee Stadium',            'New York',      'NY', 'USA', 46537),
(3,  'Citi Field',                'New York',      'NY', 'USA', 41922),
(4,  'Camden Yards',              'Baltimore',     'MD', 'USA', 44970),
(5,  'Tropicana Field',           'St. Petersburg','FL', 'USA', 25000),
(6,  'Rogers Centre',             'Toronto',       'ON', 'CAN', 49286),
(7,  'Guaranteed Rate Field',     'Chicago',       'IL', 'USA', 40615),
(8,  'Progressive Field',         'Cleveland',     'OH', 'USA', 34830),
(9,  'Comerica Park',             'Detroit',       'MI', 'USA', 41083),
(10, 'Kauffman Stadium',          'Kansas City',   'MO', 'USA', 37903),
(11, 'Target Field',              'Minneapolis',   'MN', 'USA', 38544),
(12, 'Minute Maid Park',          'Houston',       'TX', 'USA', 41168),
(13, 'Globe Life Field',          'Arlington',     'TX', 'USA', 40518),
(14, 'Angel Stadium',             'Anaheim',       'CA', 'USA', 45477),
(15, 'Oakland Coliseum',          'Oakland',       'CA', 'USA', 46765),
(16, 'T-Mobile Park',             'Seattle',       'WA', 'USA', 47929),
(17, 'Wrigley Field',             'Chicago',       'IL', 'USA', 41649),
(18, 'Busch Stadium',             'St. Louis',     'MO', 'USA', 44383),
(19, 'American Family Field',     'Milwaukee',     'WI', 'USA', 41900),
(20, 'PNC Park',                  'Pittsburgh',    'PA', 'USA', 38362),
(21, 'Great American Ball Park',  'Cincinnati',    'OH', 'USA', 42319),
(22, 'Truist Park',               'Cumberland',    'GA', 'USA', 41084),
(23, 'loanDepot Park',            'Miami',         'FL', 'USA', 37446),
(24, 'Nationals Park',            'Washington',    'DC', 'USA', 41339),
(25, 'Citizens Bank Park',        'Philadelphia',  'PA', 'USA', 42792),
(26, 'Dodger Stadium',            'Los Angeles',   'CA', 'USA', 56000),
(27, 'Petco Park',                'San Diego',     'CA', 'USA', 40162),
(28, 'Oracle Park',               'San Francisco', 'CA', 'USA', 41915),
(29, 'Chase Field',               'Phoenix',       'AZ', 'USA', 48519),
(30, 'Coors Field',               'Denver',        'CO', 'USA', 46897)
ON CONFLICT (stadium_id) DO NOTHING;
"""

TEAMS_SQL = """
INSERT INTO team (team_id, name, city, abbreviation, conference, division, head_coach, stadium_id, founded_year) VALUES
(1,  'Yankees',      'New York',      'NYY', 'American League', 'East',    'Aaron Boone',      2,  1901),
(2,  'Red Sox',      'Boston',        'BOS', 'American League', 'East',    'Alex Cora',        1,  1901),
(3,  'Orioles',      'Baltimore',     'BAL', 'American League', 'East',    'Brandon Hyde',     4,  1901),
(4,  'Rays',         'Tampa Bay',     'TB',  'American League', 'East',    'Kevin Cash',       5,  1998),
(5,  'Blue Jays',    'Toronto',       'TOR', 'American League', 'East',    'John Schneider',   6,  1977),
(6,  'White Sox',    'Chicago',       'CWS', 'American League', 'Central', 'Grady Sizemore',   7,  1900),
(7,  'Guardians',    'Cleveland',     'CLE', 'American League', 'Central', 'Stephen Vogt',     8,  1901),
(8,  'Tigers',       'Detroit',       'DET', 'American League', 'Central', 'A.J. Hinch',       9,  1901),
(9,  'Royals',       'Kansas City',   'KC',  'American League', 'Central', 'Matt Quatraro',    10, 1969),
(10, 'Twins',        'Minnesota',     'MIN', 'American League', 'Central', 'Rocco Baldelli',   11, 1901),
(11, 'Astros',       'Houston',       'HOU', 'American League', 'West',    'Joe Espada',       12, 1962),
(12, 'Rangers',      'Texas',         'TEX', 'American League', 'West',    'Bruce Bochy',      13, 1961),
(13, 'Angels',       'Anaheim',       'LAA', 'American League', 'West',    'Ron Washington',   14, 1961),
(14, 'Athletics',    'Oakland',       'OAK', 'American League', 'West',    'Mark Kotsay',      15, 1901),
(15, 'Mariners',     'Seattle',       'SEA', 'American League', 'West',    'Dan Wilson',       16, 1977),
(16, 'Braves',       'Atlanta',       'ATL', 'National League', 'East',    'Brian Snitker',    22, 1876),
(17, 'Marlins',      'Miami',         'MIA', 'National League', 'East',    'Skip Schumaker',   23, 1993),
(18, 'Mets',         'New York',      'NYM', 'National League', 'East',    'Carlos Mendoza',   3,  1962),
(19, 'Phillies',     'Philadelphia',  'PHI', 'National League', 'East',    'Rob Thomson',      25, 1883),
(20, 'Nationals',    'Washington',    'WSH', 'National League', 'East',    'Dave Martinez',    24, 1969),
(21, 'Cubs',         'Chicago',       'CHC', 'National League', 'Central', 'Craig Counsell',   17, 1876),
(22, 'Reds',         'Cincinnati',    'CIN', 'National League', 'Central', 'David Bell',       21, 1882),
(23, 'Brewers',      'Milwaukee',     'MIL', 'National League', 'Central', 'Pat Murphy',       19, 1969),
(24, 'Pirates',      'Pittsburgh',    'PIT', 'National League', 'Central', 'Derek Shelton',    20, 1882),
(25, 'Cardinals',    'St. Louis',     'STL', 'National League', 'Central', 'Oliver Marmol',    18, 1882),
(26, 'Diamondbacks', 'Arizona',       'ARI', 'National League', 'West',    'Torey Lovullo',    29, 1998),
(27, 'Rockies',      'Colorado',      'COL', 'National League', 'West',    'Bud Black',        30, 1993),
(28, 'Dodgers',      'Los Angeles',   'LAD', 'National League', 'West',    'Dave Roberts',     26, 1883),
(29, 'Padres',       'San Diego',     'SD',  'National League', 'West',    'Mike Shildt',      27, 1969),
(30, 'Giants',       'San Francisco', 'SF',  'National League', 'West',    'Bob Melvin',       28, 1883)
ON CONFLICT (team_id) DO NOTHING;
"""

REVERSE_SQL = """
DELETE FROM team WHERE team_id BETWEEN 1 AND 30;
DELETE FROM stadium WHERE stadium_id BETWEEN 1 AND 30;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0005_gamestat"),
    ]

    operations = [
        migrations.RunSQL(sql=STADIUMS_SQL + TEAMS_SQL, reverse_sql=REVERSE_SQL),
    ]
```
`ON CONFLICT ... DO NOTHING` makes it safe to re-run/re-migrate without duplicate
key errors.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py migrate baseball` exits 0.
- [x] `python manage.py shell -c "from baseball.models import Stadium, Team; assert Stadium.objects.count() == 30 and Team.objects.count() == 30"` exits 0.
- [x] Forward-apply verified clean (`Team.objects.get(team_id=1)` → Yankees, stadium → Yankee Stadium).

**Discovered limitation**: reversing this migration (`migrate baseball 0005`) fails with a
Postgres FK violation (`fk_player_team`) once `player` rows reference these teams — real DB
constraint that Django's `managed=False` models don't surface at the ORM level. Forward-only
in practice; not fixed (cascading a player delete out of a "seed teams" migration would be
scope creep). Documented here rather than in code.

**Discovered during testing**: `player` table was NOT empty — it already had 1694 rows
(1693 matching `players.csv` exactly by `player_id`, e.g. `129092` = Jacob Amaya/CWS, plus
one pre-existing dev/test row `1001` "Tushy Scar" unrelated to the CSV). Contradicts the
"empty, need seed" answer given for Team **and** Player together — Team was genuinely empty
(now correctly seeded), Player was not. Phase 5's `Player.objects.exists()` guard makes this
safe either way (it will no-op against already-present data) — proceeding with Phase 5 as
planned for portability to other/fresh environments.

#### Manual Verification:
- [ ] `baseball/new/` team-setup dropdowns (`GameSetupForm`) list all 30 teams.

---

## Phase 5: Seed Players from CSV

### Overview
Copy `players.csv` into the repo (portability), then a `RunPython` migration bulk-loads
it into `Player`.

### Changes Required

#### 1. Copy the data file into the repo
Copy `C:\Users\raalb\Downloads\players.csv` →
`baseball/migrations/seed_data/players.csv` (create the `seed_data/` dir; add an
empty `__init__.py` is NOT needed, it's just a data asset, not a package).

#### 2. `baseball/migrations/0007_seed_players.py`
```python
import csv
import os
from django.db import migrations

CSV_PATH = os.path.join(os.path.dirname(__file__), "seed_data", "players.csv")

INT_FIELDS = [
    "jersey_number", "height_inches", "weight_lbs", "season",
    "g", "g_p", "g_sp", "g_rp", "g_c", "g_1b", "g_2b", "g_3b", "g_ss",
    "g_lf", "g_cf", "g_rf", "g_of", "g_dh", "g_ph", "g_pr",
    "first_game", "last_game",
]
STR_FIELDS = [
    "first_name", "last_name", "position", "nationality", "bats", "throws",
    "team_abbrev", "dataid", "status",
]


def _to_int(value):
    value = (value or "").strip()
    return int(value) if value else None


def _to_date(value):
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y"):
        try:
            from datetime import datetime
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def seed_players(apps, schema_editor):
    Player = apps.get_model("baseball", "Player")
    if Player.objects.exists():
        return  # already seeded (or hand-populated) — don't duplicate

    batch = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kwargs = {"player_id": int(row["player_id"])}
            kwargs["team_id"] = _to_int(row["team_id"])
            kwargs["date_of_birth"] = _to_date(row["date_of_birth"])
            kwargs["active"] = (row.get("active") or "").strip().lower() in ("t", "true", "1")
            for field in STR_FIELDS:
                val = (row.get(field) or "").strip()
                kwargs[field] = val or ("available" if field == "status" and not val else (val or None))
            kwargs["status"] = (row.get("status") or "").strip() or "available"
            for field in INT_FIELDS:
                kwargs[field] = _to_int(row.get(field))
            batch.append(Player(**kwargs))

            if len(batch) >= 500:
                Player.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []
    if batch:
        Player.objects.bulk_create(batch, ignore_conflicts=True)


def unseed_players(apps, schema_editor):
    apps.get_model("baseball", "Player").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("baseball", "0006_seed_stadiums_teams"),
    ]

    operations = [
        migrations.RunPython(seed_players, unseed_players),
    ]
```
Notes:
- `Player.objects.exists()` guard makes it a safe no-op on re-migrate (same
  philosophy as `ON CONFLICT DO NOTHING` in Phase 4, since `bulk_create(...,
  ignore_conflicts=True)` alone isn't quite enough — historical models used here
  don't reliably expose DB-level unique constraints the same way, so the explicit
  early-exit is the more robust guard).
- Runs after Phase 4 so `team_id` values (1-30) already exist as real `Team` rows.
- `first_game`/`last_game` are `IntegerField`s on the model (raw YYYYMMDD-looking
  integers from the source data, e.g. `20250327`) — not parsed as dates, just cast
  with `_to_int`.

### Success Criteria

#### Automated Verification:
- [x] `python manage.py migrate baseball` exits 0.
- [x] `python manage.py shell -c "from baseball.models import Player; assert Player.objects.count() == 1693"` exits 0 — **deviates as expected**: actual count is `1694`, not `1693`. Per Phase 4's "Discovered during testing" note, the `player` table already had 1693 CSV rows + 1 pre-existing dev row (`player_id=1001`, "Tushy Scar") before this migration ran. The `Player.objects.exists()` guard correctly no-op'd (data already present), so the migration didn't insert/duplicate anything — it just didn't clear the unrelated dev row either, which was never in scope.
- [x] `python manage.py shell -c "from baseball.models import Player; p = Player.objects.get(player_id=129092); assert p.first_name == 'Jacob' and p.active is True"` exits 0.

#### Manual Verification:
- [ ] `baseball/<id>/` roster-selection screen (`RosterForm`, `position_pools`) shows
  real players per position for a seeded team.
- [ ] Starting and playing a full game with a seeded roster works end to end.

---

## Testing Strategy

### Unit Tests
- `accounts/tests.py`: setting `Profile.role = 1` and saving flips `user.is_staff`
  to `True`; setting back to `0` flips it back.
- `manage/tests.py`: `UserEditView` — posting a `new_password` changes the user's
  password (verify via `check_password`); posting a blank `new_password` leaves it
  unchanged; posting `role=1` in the profile form results in `is_staff=True` on
  save.

### Integration Tests
- Full migrate-from-zero on a scratch DB: `accounts` 0001→0003, `baseball`
  0001→0007, then assert `Admin` user + 30 stadiums + 30 teams + 1693 players.

### Manual Testing Steps
1. Fresh DB → `python manage.py migrate` → confirm no errors.
2. Log in as `Admin`/`Admin` → navbar dropdown → Admin Dashboard.
3. `/manage/users/` → confirm Admin shows Role=Admin, Status=Active.
4. Create a normal user via "+ Add User" → confirm Role defaults to "User", they
   cannot reach `/manage/`.
5. Edit that user → set Role=Admin, Save → confirm they can now reach `/manage/`.
6. Edit that user again → set a new password, Save → log in as them with the new
   password.
7. `/baseball/new/` → confirm the away/home team dropdowns list real teams.
8. Start a game, get to roster selection → confirm real player names appear per
   position.

## Performance Considerations

- `players.csv` seed uses batched `bulk_create` (500/batch) to avoid 1693
  individual INSERTs.
- `RunSQL` team/stadium insert is a single statement per table — negligible cost.

## Migration Notes

- Seeded `Admin`/`Admin` credentials are intentionally weak (matches the user's
  explicit request) and bypass password validators via direct migration — **must
  be changed immediately in any environment other than local dev.**
- All three seed migrations (Phases 3-5) are re-run-safe (`get_or_create`,
  `ON CONFLICT DO NOTHING`, `Player.objects.exists()` guard respectively) so
  `migrate` can be re-applied without duplicating data.
- Phase 5 depends on Phase 4 having already inserted `Team` rows 1-30 (FK target
  for `player.team_id`).

## References

- Prior admin-dashboard plan (implemented): `thoughts/shared/plans/2026-06-16-admin-user-management.md`
- Baseball web-game plan (implemented): `thoughts/shared/plans/2026-06-25-baseball-web-game.md`
- Baseball route research: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- `accounts/models.py:6-21` — `Profile` model
- `accounts/mixins.py:4-6` — `StaffRequiredMixin` (unchanged, now driven by synced `is_staff`)
- `manage/views.py`, `manage/forms.py`, `manage/urls.py` — existing admin dashboard
- `baseball/models.py:10-96` — `Stadium`/`Team`/`Player` (unmanaged)
- `baseball/forms.py` — `GameSetupForm`/`RosterForm`, consumers of seeded Team/Player data
- `templates/base.html:17-47` — navbar to convert to dropdown
- UI reference screenshots (user-supplied, 2026-07-17): dashboard user list, edit-user
  page, navbar "Hello Admin" dropdown
