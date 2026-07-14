from django import forms
from .models import Game, Team, Player, position_pools

POSITIONS = [
    ("P",  "Pitcher"),
    ("C",  "Catcher"),
    ("1B", "First Base"),
    ("2B", "Second Base"),
    ("SS", "Shortstop"),
    ("3B", "Third Base"),
    ("LF", "Left Field"),
    ("CF", "Center Field"),
    ("RF", "Right Field"),
    ("DH", "Designated Hitter"),
]
BATTING_POSITIONS = [code for code, _ in POSITIONS if code != "P"]


class GameSetupForm(forms.ModelForm):
    away_team = forms.ModelChoiceField(
        queryset=Team.objects.all(),
        label="Away Team",
        empty_label="— select away team —",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    home_team = forms.ModelChoiceField(
        queryset=Team.objects.all(),
        label="Home Team",
        empty_label="— select home team —",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model  = Game
        fields = ["away_team", "home_team", "total_innings", "mode"]
        widgets = {
            "total_innings": forms.NumberInput(attrs={"min": 1, "max": 9, "class": "form-control"}),
            "mode":          forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["total_innings"].initial = 3

    def clean(self):
        cleaned = super().clean()
        away = cleaned.get("away_team")
        home = cleaned.get("home_team")
        if away and home and away == home:
            raise forms.ValidationError("Away and home teams must be different.")
        return cleaned


class RosterForm(forms.Form):
    """20 player dropdowns: away_<POS> and home_<POS> for each position."""

    def __init__(self, *args, away_team=None, home_team=None, **kwargs):
        super().__init__(*args, **kwargs)
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
        batting_codes = ",".join(BATTING_POSITIONS)
        for side in ("away", "home"):
            self.fields[f"{side}_order"] = forms.CharField(
                required=False,
                initial=batting_codes,
                widget=forms.HiddenInput(),
            )

    def away_fields(self):
        return [self[f"away_{code}"] for code, _ in POSITIONS]

    def home_fields(self):
        return [self[f"home_{code}"] for code, _ in POSITIONS]

    def away_pitcher_field(self):
        return self["away_P"]

    def home_pitcher_field(self):
        return self["home_P"]

    def _batting_fields(self, side):
        return [(code, self[f"{side}_{code}"]) for code in BATTING_POSITIONS]

    def away_batting_fields(self):
        return self._batting_fields("away")

    def home_batting_fields(self):
        return self._batting_fields("home")

    def _clean_side(self, side):
        chosen = {code: self.cleaned_data.get(f"{side}_{code}")
                  for code, _ in POSITIONS}
        ids = [pl.player_id for pl in chosen.values() if pl is not None]
        p_pick, dh_pick = chosen.get("P"), chosen.get("DH")
        if (p_pick is not None and dh_pick is not None
                and p_pick.player_id == dh_pick.player_id):
            ids.remove(dh_pick.player_id)
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(
                f"Each {side} player can only fill one position "
                f"(except a pitcher may also be the DH)."
            )

    def clean(self):
        cleaned = super().clean()
        for side in ("away", "home"):
            self._clean_side(side)
        return cleaned

    def roster_for(self, side):
        """10-slot roster: pitcher first, then 9 batting slots in chosen order."""
        raw = (self.cleaned_data.get(f"{side}_order") or "").split(",")
        order = [c for c in raw if c]
        if sorted(order) != sorted(BATTING_POSITIONS):
            order = list(BATTING_POSITIONS)
        out = []
        for code in ["P"] + order:
            p = self.cleaned_data[f"{side}_{code}"]
            out.append({"position": code, "player_id": p.player_id, "name": str(p)})
        return out
