# Test Vulnerabilities

Local-only endpoints added to the `manage` app for hands-on security learning.
Remove before any real deployment.

---

## SQL Injection Demo

### Endpoints

| URL | Description |
|-----|-------------|
| `/manage/demo/sqli/vulnerable/` | Builds the query via Python string interpolation — injectable |
| `/manage/demo/sqli/safe/` | Uses a parameterized query — protected |

Both endpoints accept a `?username=` query parameter, display the raw SQL sent to the
database, and return a results table. You must be logged in as a staff user to access them.

### Relevant files

- `manage/views.py` — `sqli_vulnerable` and `sqli_safe` function views
- `manage/urls.py` — routes `demo/sqli/vulnerable/` and `demo/sqli/safe/`
- `manage/templates/manage/sqli_demo.html` — shared template with payload reference table

### How it works

**Vulnerable path** — the username value is interpolated directly into the query string.
The database engine receives and parses whatever string the user submits, including SQL syntax:

```python
query = f"SELECT id, username, email, is_staff FROM auth_user WHERE username = '{username}'"
cursor.execute(query)
```

**Safe path** — the value is passed separately as a parameter. The driver escapes it before
the database sees it, so the query structure can never be altered by user input:

```python
query = "SELECT id, username, email, is_staff FROM auth_user WHERE username = %s"
cursor.execute(query, [username])
```

### Payloads to try (vulnerable endpoint only)

| Input | Effect |
|-------|--------|
| `raalbue` | Normal lookup — one row returned |
| `' OR '1'='1` | Always-true condition — all users returned |
| `' OR '1'='1'--` | Same; `--` comments out anything after the injection point |
| `' UNION SELECT id, password, email, is_staff FROM auth_user--` | Leaks hashed passwords via a second SELECT appended to the original query |
| `' AND '1'='2` | Always-false — zero rows; used for blind probing |

The same payloads on the safe endpoint return no rows and produce no errors — the input is
treated as a literal string value, not SQL.

### Why the Django ORM is safe by default

`User.objects.filter(username=username)` translates to a parameterized query internally.
You are only vulnerable when you write raw SQL with string formatting (`f"..."`, `%` operator,
or `.format()`). The fix is always to pass values as parameters, never to concatenate them.
