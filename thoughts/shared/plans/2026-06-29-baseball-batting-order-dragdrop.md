# Drag-and-Drop Batting Order Implementation Plan

## Overview

On the roster screen, let the user set each team's **batting order** by dragging the
position dropdowns into the desired sequence. The pitcher is pinned at the top of
each column (defense-only, does not bat under the DH rule); the remaining 9
batting positions form a sortable, numbered list (1–9). The chosen order defaults
to the canonical roster order and becomes the lineup used in play-by-play. Both the
away (CPU) and home columns are reorderable.

## Current State Analysis

- **Roster screen** (`baseball/templates/baseball/game_roster.html`, built this
  session) renders two columns. Each iterates `form.away_fields` / `form.home_fields`
  (`baseball/forms.py`), emitting all 10 position dropdowns in fixed canonical order
  (P, C, 1B, 2B, SS, 3B, LF, CF, RF, DH). No JavaScript on this page.
- **`RosterForm.roster_for(side)`** (`baseball/forms.py`) builds the 10-slot roster
  list by iterating `POSITIONS` in canonical order:
  `[{"position", "player_id", "name"}, …]`.
- **`lineup_from_roster(roster)`** (`baseball/views.py:20`) derives the 9-name batting
  order via `{pos: name}` lookup over the fixed `BATTING_POSITIONS` list — so order is
  always canonical regardless of how the roster list is arranged.
- **`RosterView.post`** (`baseball/views.py`) calls `roster_for` + `lineup_from_roster`,
  bakes the lineups into `GameState` (`away_lineup`/`home_lineup`, serialized into
  `Game.state`), and stores `away_roster`/`home_roster` JSON on the `Game`.
- **Detail page** (`game_detail.html`) "Batting Order" card iterates the stored roster,
  emitting an `<li>` only for non-pitcher entries (`list-group-numbered` auto-numbers
  the emitted items). It therefore already reflects whatever order the roster list is
  stored in.
- **App JS conventions**: no build step; Bootstrap loaded via CDN. `game_detail.html`
  pulls a static `game.js`. Adding a CDN `<script>` is consistent with the existing
  approach.

## Desired End State

- Each roster column shows the pitcher dropdown pinned at top, labeled as not batting,
  followed by a draggable, numbered (1–9) list of the 9 batting-position dropdowns.
- Dragging a row reorders the batting list; the numbers (1–9) update live; the
  player + position selected in each row travel with the row.
- On "Play Ball!", each team's stored roster is `[pitcher, …9 batting entries in the
  chosen order]`; the engine lineup and play-by-play bat in that order; the detail
  "Batting Order" card shows the chosen order.
- Default (no dragging) reproduces today's canonical order exactly.

### Verify by:
- Reordering the home list (e.g. drag DH to slot 1), submitting, then confirming the
  detail "Batting Order" card lists that team in the new order and the first at-bat is
  the slot-1 player.
- Submitting without dragging yields the canonical order (regression check).
- An away (CPU) reorder is honored the same way.

## Key Discoveries
- `lineup_from_roster` (`views.py:20`) is the single choke point that forces canonical
  order; changing it to preserve list order is the core backend change.
- `roster_for` (`forms.py`) controls the stored list order — building it as
  `[P, …chosen 9]` makes both the engine lineup and the detail card correct with **no
  detail-template change**.
- `list-group-numbered` numbers items by DOM order via a CSS counter, so drag reordering
  renumbers automatically — JS only needs to update a hidden order field.
- Old games store rosters as `[P, C, 1B, …]`; order-preserving logic yields the same
  canonical lineup, so the change is backward compatible.

## What We're NOT Doing

- **No DB/model change, no migration.** The chosen order rides inside the existing
  `away_roster`/`home_roster` JSON and the baked `state` lineups.
- **No reordering after the game is created.** Order is fixed at setup, like the roster.
- **No drag-reordering of positions across the pitcher boundary.** Pitcher is pinned;
  it is never a batting slot.
- **No change to the detail page or `game.js`.** The batting-order card already renders
  stored order; play-by-play already reads the baked lineup.
- **No per-row "position vs batting slot" decoupling beyond ordering** — each row keeps
  its position label; only its batting sequence changes.

## Implementation Approach

Two phases. Phase 1 is pure backend (form + helper) and leaves the page working with
canonical order. Phase 2 adds the drag UI that feeds the new order field.

---

## Phase 1: Order-Aware Roster Building

### Overview
Add hidden `away_order`/`home_order` fields to `RosterForm`, expose
`pitcher_field`/`batting_fields` helpers for the template, make `roster_for` honor the
submitted order, and make `lineup_from_roster` preserve list order.

### Changes Required

#### 1. `baseball/forms.py` — order fields, helpers, order-aware `roster_for`

In `RosterForm.__init__`, after building the 20 position fields, add a hidden order
field per side (initial = canonical batting codes):
```python
        batting_codes = ",".join(BATTING_POSITIONS)
        for side in ("away", "home"):
            self.fields[f"{side}_order"] = forms.CharField(
                required=False,
                initial=batting_codes,
                widget=forms.HiddenInput(),
            )
```

Add helper methods (used by the template):
```python
    def pitcher_field(self, side):
        return self[f"{side}_P"]

    def away_pitcher_field(self):
        return self.pitcher_field("away")

    def home_pitcher_field(self):
        return self.pitcher_field("home")

    def _batting_fields(self, side):
        # [(code, bound_field), …] in canonical batting order for initial render.
        return [(code, self[f"{side}_{code}"]) for code in BATTING_POSITIONS]

    def away_batting_fields(self):
        return self._batting_fields("away")

    def home_batting_fields(self):
        return self._batting_fields("home")
```

Rewrite `roster_for` to order the 9 batting slots by the submitted order (pitcher
first), falling back to canonical if the order field is missing/invalid:
```python
    def roster_for(self, side):
        """10-slot roster: pitcher first, then the 9 batting slots in chosen order."""
        raw = (self.cleaned_data.get(f"{side}_order") or "").split(",")
        order = [c for c in raw if c]
        if sorted(order) != sorted(BATTING_POSITIONS):
            order = list(BATTING_POSITIONS)  # fallback: canonical
        out = []
        for code in ["P"] + order:
            p = self.cleaned_data[f"{side}_{code}"]
            out.append({"position": code, "player_id": p.player_id, "name": str(p)})
        return out
```

> Keep the existing `away_fields`/`home_fields` methods or remove them — after Phase 2
> the template uses `*_pitcher_field` / `*_batting_fields` instead. Leaving them is
> harmless; removing them is cleaner. Decide during implementation.

#### 2. `baseball/views.py` — preserve order in `lineup_from_roster`

```python
def lineup_from_roster(roster):
    """9-name batting order from a 10-slot roster, preserving list order
    (pitcher excluded)."""
    return [r["name"] for r in roster if r["position"] != "P"]
```

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] Order fields present + batting helper returns 9:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.forms import RosterForm; from baseball.models import Team; t=list(Team.objects.all()); f=RosterForm(away_team=t[0], home_team=t[1]); assert 'home_order' in f.fields and 'away_order' in f.fields; assert len(f.home_batting_fields())==9; print('ok')"`
- [x] `lineup_from_roster` preserves a custom order and drops the pitcher:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.views import lineup_from_roster; roster=[{'position':'P','player_id':1,'name':'Pitcher'},{'position':'DH','player_id':2,'name':'First'},{'position':'C','player_id':3,'name':'Second'}]; lu=lineup_from_roster(roster); print(lu); assert lu==['First','Second']"`

#### Manual Verification:
- [ ] Roster page still loads and a no-drag submit creates a game with canonical order
      (Phase 2 adds the actual drag UI; this confirms no regression first)

**Implementation Note**: After automated checks pass, pause for manual confirmation
before Phase 2.

---

## Phase 2: Drag-and-Drop Roster UI

### Overview
Restructure `game_roster.html` so each column pins the pitcher and renders the 9
batting dropdowns as a SortableJS-powered numbered list backed by a hidden order
field.

### Changes Required

#### 1. `baseball/templates/baseball/game_roster.html` — per-column structure

Replace each column's `{% for field in form.*_fields %}` block with:
```html
      <div class="col-md-6">
        <h4>{{ setup.away_name }} <small class="text-muted fs-6">Away · CPU</small></h4>

        {# Pitcher — pinned, does not bat #}
        <div class="mb-3">
          <label class="form-label small fw-semibold">
            Pitcher <span class="text-muted">(does not bat)</span>
          </label>
          {{ form.away_pitcher_field }}
          {% if form.away_pitcher_field.errors %}
          <div class="text-danger small">{{ form.away_pitcher_field.errors }}</div>
          {% endif %}
        </div>

        {{ form.away_order }}  {# hidden input, JS-maintained #}
        <label class="form-label small fw-semibold">Batting Order (drag to reorder)</label>
        <ol class="sortable list-group list-group-numbered" id="away-batting">
          {% for code, field in form.away_batting_fields %}
          <li class="list-group-item d-flex align-items-center gap-2" data-pos="{{ code }}">
            <span class="drag-handle" style="cursor:grab">⠿</span>
            <div class="flex-grow-1">
              <div class="small text-muted">{{ field.label }}</div>
              {{ field }}
              {% if field.errors %}<div class="text-danger small">{{ field.errors }}</div>{% endif %}
            </div>
          </li>
          {% endfor %}
        </ol>
      </div>
```
Repeat the identical block for the home column using `form.home_pitcher_field`,
`form.home_order`, `form.home_batting_fields`, `id="home-batting"`, and the
`{{ setup.home_name }}` heading (Home · You).

#### 2. `baseball/templates/baseball/game_roster.html` — SortableJS + init

Before `{% endblock %}`, add:
```html
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script>
function wireSortable(listId, orderInputId) {
  const list  = document.getElementById(listId);
  const order = document.getElementById(orderInputId);
  function sync() {
    order.value = Array.from(list.children)
      .map(li => li.dataset.pos).join(",");
  }
  new Sortable(list, { handle: ".drag-handle", animation: 150, onEnd: sync });
  sync();  // initialize hidden field to the rendered order
}
wireSortable("away-batting", "id_away_order");
wireSortable("home-batting", "id_home_order");
</script>
```
(Django's auto-generated id for `away_order` is `id_away_order`.)

### Success Criteria

#### Automated Verification:
- [x] `./venv/Scripts/python.exe manage.py check` exits 0
- [x] Roster template renders without error (smoke test via test client):
      `./venv/Scripts/python.exe manage.py shell -c "import django; from django.template.loader import get_template; get_template('baseball/game_roster.html'); print('template loads')"`

#### Manual Verification:
- [ ] Each column shows the pitcher pinned at top (labeled "does not bat") and 9
      numbered batting rows below
- [ ] Dragging a row reorders it; the 1–9 numbers update live
- [ ] Selecting a player then dragging its row keeps that selection
- [ ] Submitting with a reordered home list creates the game; the detail "Batting
      Order" card shows the new order; the first home at-bat is the slot-1 player
- [ ] Submitting without dragging yields canonical order (regression)
- [ ] Reordering the away list is likewise honored in play-by-play
- [ ] Same-player-twice validation on a side still errors (drag doesn't bypass it)

---

## Testing Strategy

### Manual Testing Steps:
1. `/baseball/new/` → pick two teams → "Make Roster".
2. On the roster screen, confirm pitcher pinned + 9 numbered draggable rows per column.
3. Drag home "Designated Hitter" to slot 1; confirm numbers renumber 1–9.
4. Pick distinct players for all home slots; "Play Ball!".
5. On detail, confirm the home "Batting Order" card lists DH first; play one at-bat and
   confirm the slot-1 (DH) player bats first.
6. Create another game, don't drag anything; confirm canonical order in the card.
7. Reorder the away column on a third game; play through and confirm away bats in the
   chosen order.
8. Trigger the duplicate-player validation on one side; confirm it still blocks.

## Performance Considerations

SortableJS is ~45 KB from CDN, loaded only on the roster page. Two sortable lists of 9
items each — negligible. No server-side cost change; the order is a short string.

## Migration Notes

None. No schema change. Existing games are unaffected (their rosters were stored
pitcher-first in canonical order, which the new order-preserving logic reproduces).

## References

- Prior plan: `thoughts/shared/plans/2026-06-29-baseball-roster-selection.md`
- Research doc: `thoughts/shared/research/2026-06-25-baseball-web-route.md`
- `baseball/forms.py` — `RosterForm`, `POSITIONS`, `BATTING_POSITIONS`, `roster_for`
- `baseball/views.py:20` — `lineup_from_roster`; `RosterView.post`
- `baseball/templates/baseball/game_roster.html` — roster screen
- `baseball/templates/baseball/game_detail.html` — "Batting Order" card (no change)
- `baseball/engine.py` — `GameState.current_batter` uses the baked lineup order
