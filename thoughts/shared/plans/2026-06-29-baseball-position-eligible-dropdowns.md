# Position-Eligible Roster Dropdowns Implementation Plan

## Overview

Today every roster dropdown lists the selected team's entire ~56–65-player roster
(the `player.position` column is null, so no filtering was possible). Change each of
the 9 fielding-position dropdowns to list **every player who has played games at that
position** (`g_<slot> > 0`), so a player who has appeared at multiple positions shows
up in each of those dropdowns. The Designated Hitter dropdown lists all **non-pitchers**
**plus any two-way player who has DH'd** (`g_dh > 0`), so a player like Shohei Ohtani
stays in the DH list even though he pitches. Finally, a pitcher may **DH for himself**:
the same player may be chosen at both P and DH on one side. The away (CPU) auto-fill
must pick position-eligible, distinct players so its pre-filled selections are valid in
the filtered dropdowns.

## Current State Analysis

- **`RosterForm.__init__`** (`baseball/forms.py:57`) builds 20 `ModelChoiceField`s with
  `queryset = Player.objects.filter(team=team)` — every position dropdown shows the
  whole team roster.
- **`RosterForm._clean_side`** (`baseball/forms.py:98`) rejects the same player at two
  slots with no exceptions.
- **`RosterForm.roster_for`** (`baseball/forms.py:113`) builds `["P"] + batting order`;
  `lineup_from_roster` (`baseball/views.py:20`) drops the `"P"` slot. So if the same
  player fills P and DH, the DH entry (same name) lands in the batting order — i.e. the
  pitcher bats in the DH slot. No change needed there for self-DH to work.
- **`auto_fill_roster(team)`** (`baseball/views.py:12`) picks the first 10 distinct
  players (`Player.objects.filter(team=team)[:10]`) for the away side — ignores positions.
- **`Player`** (`baseball/models.py:50`, unmanaged) has per-position games columns:
  `g_p, g_sp, g_rp, g_c, g_1b, g_2b, g_3b, g_ss, g_lf, g_cf, g_rf, g_of, g_dh, g_ph,
  g_pr`. `Player.position` is null for all rows. Default ordering = `last_name,
  first_name`.
- **`POSITIONS`** (`baseball/forms.py:4`) = `[(P,…),(C,…),(1B,…),(2B,…),(SS,…),(3B,…),
  (LF,…),(CF,…),(RF,…),(DH,…)]`. The roster template iterates `pitcher_field` +
  `batting_fields`, rendering each field's queryset — no template change is needed when
  the querysets change.

### Key Discoveries (verified against the live DB, all 30 teams)
- **Multi-position pools are non-empty everywhere**: 0 empty fielding pools across all
  30 teams, so every required dropdown always has ≥1 option.
- **Pools now overlap** (this is intended): utility players appear in several dropdowns.
  Sample team multi-position sizes →
  `{P:41, C:4, 1B:8, 2B:8, 3B:8, SS:8, LF:8, CF:8, RF:9}` (vs. the disjoint
  main-position buckets of the prior design). The 9 fielding pools are **no longer
  disjoint**.
- **Two-way players exist**: 42 players league-wide have `g_p>0`/`g_sp>0`/`g_rp>0`
  **and** `g_dh>0`. These must appear in both the P pool and the DH pool (Ohtani case).
- **`g_of` stays unused**: outfield handled via `g_lf/g_cf/g_rf`; `g_of/g_dh/g_ph/g_pr`
  are not fielding slots in the dropdowns (`g_dh` only gates DH eligibility).

## Desired End State

- On the roster screen, the Pitcher dropdown lists every player with pitching games, and
  each fielding dropdown lists every player with games at that slot (utility players
  appear in multiple dropdowns). The DH dropdown lists every non-pitcher **and** every
  two-way player who has DH'd.
- A pitcher may be selected at both P and DH on the same side (self-DH); duplicate
  validation permits exactly that one pairing and nothing else.
- The away (CPU) roster is auto-filled with distinct, eligible players (each pre-selected
  player is present in its dropdown's filtered list).
- A game can be created end-to-end with these filtered dropdowns.

### Verify by:
- Open `/baseball/roster/`: a utility player appears in each position he's played; the
  DH dropdown shows no pitcher **except** two-way players; the away side is pre-filled
  and every selection is in-range.
- On a team with a two-way player, pick him at P and DH → form submits (no duplicate
  error) and he bats in the DH slot.
- Create a game successfully and confirm play-by-play uses the chosen players.

## What We're NOT Doing

- **No `player.position` backfill.** Eligibility is computed on the fly from the games
  columns; the null `position` column is untouched.
- **No model/schema change, no migration.** Uses existing columns.
- **No template change.** Dropdowns already render `field.queryset`.
- **No general multi-player-per-slot.** Beyond the explicit P+DH self-DH exception, a
  player still fills only one slot on a side.
- **No change to the drag-and-drop batting order, the engine, or the detail page.**

## Implementation Approach

Single coherent phase. Add pool-computation helpers to `models.py`, consume them in
`RosterForm.__init__` (per-field querysets), relax `RosterForm._clean_side` for the
P+DH self-DH case, and make `auto_fill_roster` pick distinct eligible players (preferring
each player's main position so the CPU lineup is realistic). Form filtering and auto-fill
must land together: if dropdowns were filtered but auto-fill still picked arbitrary
players, the away pre-fill would select players absent from their dropdowns.

---

## Phase 1: Position Pools + Filtered Dropdowns + Self-DH + Eligible Auto-Fill

### Overview
Compute each team's per-position eligible-player pools (multi-position membership), wire
them into the form querysets, allow a pitcher to DH for himself, and pick eligible away
auto-fill.

### Changes Required

#### 1. `baseball/models.py` — pool helpers

Add at module level (after the `Player` model):
```python
# Roster code -> games-played column that makes a player eligible at that slot.
FIELDING_COLS = {
    "P": "g_p", "C": "g_c", "1B": "g_1b", "2B": "g_2b", "3B": "g_3b",
    "SS": "g_ss", "LF": "g_lf", "CF": "g_cf", "RF": "g_rf",
}


def main_position(player) -> str | None:
    """The fielding code the player has the most games at (None if all zero).
    Ties resolve to FIELDING_COLS insertion order (P..RF). Used to make the
    CPU auto-fill pick a player's primary slot first."""
    best, code = 0, None
    for c, col in FIELDING_COLS.items():
        v = getattr(player, col) or 0
        if v > best:
            best, code = v, c
    return code


def position_pools(team) -> dict[str, list[int]]:
    """For a team: {roster_code: [eligible player_ids]}.
    A player is eligible at EVERY fielding slot he has games at (g_<slot> > 0),
    so the 9 fielding pools overlap for utility players.
    'DH' = every non-pitcher PLUS any player who has DH'd (g_dh > 0), so a
    two-way player (e.g. Ohtani) stays selectable at DH even while pitching."""
    pools = {c: [] for c in FIELDING_COLS}
    pools["DH"] = []
    for p in Player.objects.filter(team=team):
        for code, col in FIELDING_COLS.items():
            if (getattr(p, col) or 0) > 0:
                pools[code].append(p.player_id)
        is_pitcher = (p.g_sp or 0) > 0 or (p.g_rp or 0) > 0
        if not is_pitcher or (p.g_dh or 0) > 0:
            pools["DH"].append(p.player_id)
    return pools
```

#### 2. `baseball/forms.py` — filter each dropdown + allow self-DH

Import the helper:
```python
from .models import Game, Team, Player, position_pools
```

In `RosterForm.__init__`, replace the queryset construction:
```python
        self._sides = {"away": away_team, "home": home_team}
        for side, team in self._sides.items():
            pools = position_pools(team) if team else {}
            for code, label in POSITIONS:
                ids = pools.get(code, [])
                qs = (Player.objects.filter(player_id__in=ids)
                      if team else Player.objects.none())
                self.fields[f"{side}_{code}"] = forms.ModelChoiceField(
                    queryset=qs,
                    label=label,
                    empty_label=f"— select {label.lower()} —",
                    widget=forms.Select(attrs={"class": "form-select"}),
                )
```
(`Player`'s default ordering `last_name, first_name` keeps options alphabetized.)

Relax `_clean_side` so a pitcher may DH for himself (P and DH may be the same player),
while still rejecting every other duplicate:
```python
    def _clean_side(self, side):
        chosen = {code: self.cleaned_data.get(f"{side}_{code}")
                  for code, _ in POSITIONS}
        ids = [pl.player_id for pl in chosen.values() if pl is not None]
        # A pitcher may DH for himself: drop one allowed P/DH duplicate.
        p_pick, dh_pick = chosen.get("P"), chosen.get("DH")
        if (p_pick is not None and dh_pick is not None
                and p_pick.player_id == dh_pick.player_id):
            ids.remove(dh_pick.player_id)
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(
                f"Each {side} player can only fill one position "
                f"(except a pitcher may also be the DH)."
            )
```
`roster_for` is unchanged: when P and DH are the same player, the DH entry carries that
player's name into the batting order (`lineup_from_roster` drops only the `"P"` slot),
so the pitcher bats in the DH slot — exactly the self-DH behavior.

#### 3. `baseball/views.py` — eligible auto-fill (prefer main position)

Import the helpers:
```python
from .models import Game, Player, Team, position_pools, main_position
```

Replace `auto_fill_roster`:
```python
def auto_fill_roster(team):
    """Pick one eligible, distinct player per position for the away (CPU) side,
    preferring each player's main position so the lineup is realistic.
    Returns {position_code: player_id}."""
    pools = position_pools(team)
    primary = {p.player_id: main_position(p)
               for p in Player.objects.filter(team=team)}
    used, out = set(), {}
    for code, _ in POSITIONS:
        cands = pools.get(code, [])
        pick = next((pid for pid in cands
                     if pid not in used and primary.get(pid) == code), None)
        if pick is None:
            pick = next((pid for pid in cands if pid not in used), None)
        if pick is not None:
            out[code] = pick
            used.add(pick)
    return out
```
(Auto-fill keeps the CPU side's slots distinct — no CPU self-DH — and every pick is in
its slot's pool, so it renders validly in the filtered dropdown. `POSITIONS` orders
P..DH, so DH is filled last from a player the fielding picks didn't use.)

### Success Criteria

#### Automated Verification:
- [ ] `./venv/Scripts/python.exe manage.py check` exits 0
- [ ] Multi-position pools match `g_<col> > 0`, DH excludes pitchers-without-DH but keeps
      two-way players, no empty fielding pool:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.models import position_pools, Team, Player, FIELDING_COLS; t=Team.objects.first(); pl=position_pools(t); P=list(Player.objects.filter(team=t)); assert all(set(pl[c])==set(p.player_id for p in P if (getattr(p,col) or 0)>0) for c,col in FIELDING_COLS.items()), 'fielding pool mismatch'; assert all(len(pl[c])>0 for c in FIELDING_COLS), 'empty fielding pool'; assert all((p.g_dh or 0)>0 or ((p.g_sp or 0)==0 and (p.g_rp or 0)==0) for p in P if p.player_id in pl['DH']), 'bad DH member'; tw=[p for p in P if ((p.g_sp or 0)>0 or (p.g_rp or 0)>0) and (p.g_dh or 0)>0]; assert all(p.player_id in pl['DH'] and p.player_id in pl['P'] for p in tw), 'two-way not in P and DH'; print('pools ok', {c:len(pl[c]) for c in pl})"`
- [ ] Form querysets match pools; a two-way player appears in both P and DH dropdowns:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.forms import RosterForm; from baseball.models import Team, position_pools; ts=list(Team.objects.all()); t=next(x for x in ts if [i for i in position_pools(x)['P'] if i in position_pools(x)['DH']]); f=RosterForm(away_team=ts[0], home_team=t); pl=position_pools(t); assert f.fields['home_C'].queryset.count()==len(pl['C']); assert f.fields['home_DH'].queryset.count()==len(pl['DH']); tw=[i for i in pl['P'] if i in pl['DH']][0]; assert f.fields['home_P'].queryset.filter(player_id=tw).exists() and f.fields['home_DH'].queryset.filter(player_id=tw).exists(); print('form ok', f.fields['home_C'].queryset.count(), f.fields['home_DH'].queryset.count())"`
- [ ] Self-DH allowed at P+DH, other duplicates still rejected:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.forms import RosterForm, POSITIONS; from baseball.models import Team, Player, position_pools; from django.forms import ValidationError; ts=list(Team.objects.all()); t=next(x for x in ts if [i for i in position_pools(x)['P'] if i in position_pools(x)['DH']]); f=RosterForm(away_team=ts[0], home_team=t); pl=position_pools(t); tw=Player.objects.get(pk=[i for i in pl['P'] if i in pl['DH']][0]); base={f'home_{c}':None for c,_ in POSITIONS}; cd=dict(base); cd['home_P']=tw; cd['home_DH']=tw; f.cleaned_data=cd; f._clean_side('home'); print('self-DH allowed'); c1=Player.objects.get(pk=pl['C'][0]); cd2=dict(base); cd2['home_C']=c1; cd2['home_1B']=c1; f.cleaned_data=cd2;\nimport sys\ntry:\n    f._clean_side('home'); print('FAIL: dup not caught'); sys.exit(1)\nexcept ValidationError:\n    print('dup rejected ok')"`
- [ ] Auto-fill returns 10 distinct, position-eligible ids:
      `./venv/Scripts/python.exe manage.py shell -c "from baseball.views import auto_fill_roster; from baseball.models import Team, position_pools; t=Team.objects.first(); r=auto_fill_roster(t); pl=position_pools(t); assert len(r)==10 and len(set(r.values()))==10; assert all(pid in pl[code] for code,pid in r.items()); print('autofill ok')"`

#### Manual Verification:
- [ ] `/baseball/roster/` — a utility player (e.g. one with 2B and SS games) appears in
      both the 2B and SS dropdowns; the Pitcher dropdown lists pitchers
- [ ] DH dropdown contains no pitchers **except** two-way players who have DH'd
      (cross-check a known two-way name)
- [ ] Away side is pre-filled and every pre-selected player appears in its own dropdown
      (no blank/orphan selection)
- [ ] On a team with a two-way player: pick him at P and DH, fill the rest, "Play Ball!"
      → game creates, and he appears in the batting order at the DH slot
- [ ] Duplicate-player validation still fires for any non-(P,DH) duplicate (e.g. the same
      catcher picked at C and at 2B)

**Implementation Note**: After automated checks pass, pause for manual confirmation.

---

## Testing Strategy

### Manual Testing Steps:
1. `/baseball/new/` → pick two teams → "Make Roster".
2. Open several home fielding dropdowns; confirm a utility player shows up in each slot
   he's played, and the Pitcher list is pitchers.
3. Confirm the DH dropdown excludes pure pitchers but keeps two-way players.
4. Confirm the away column is pre-filled and each selection is visibly chosen (not reset
   to the empty label).
5. On a two-way team, set P and DH to the same player, fill the rest, "Play Ball!" →
   game plays and he bats at DH.
6. Re-pick the same catcher at C and 2B → submit → duplicate validation error.

## Performance Considerations

`position_pools(team)` runs one query (the team's ~56–65 players) and buckets in Python.
`RosterForm.__init__` calls it twice (once per team) → 2 queries; each filtered field
queryset re-queries on render/validation (~20 small `IN`-list queries on the roster
page). Negligible. `auto_fill_roster` adds one `position_pools` call plus one player
fetch on the roster GET.

## Migration Notes

None. No schema change; computation reads existing games columns.

## References

- Prior plans: `thoughts/shared/plans/2026-06-29-baseball-roster-selection.md`,
  `thoughts/shared/plans/2026-06-29-baseball-batting-order-dragdrop.md`
- `baseball/models.py:50` — `Player` (per-position games columns, incl. `g_dh`)
- `baseball/forms.py:57,98,113` — `RosterForm.__init__`, `_clean_side`, `roster_for`
- `baseball/views.py:12,20` — `auto_fill_roster`, `lineup_from_roster`
- `baseball/templates/baseball/game_roster.html` — dropdowns (no change)
