from django import forms
from django.contrib.auth import get_user_model
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


class SideRosterForm(forms.Form):
    """One side's team pick + 10-slot roster (unprefixed position field names)."""

    def __init__(self, *args, team=None, team_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team"] = forms.ModelChoiceField(
            queryset=team_queryset if team_queryset is not None else Team.objects.all(),
            label="Team",
            empty_label="— select team —",
            widget=forms.Select(attrs={"class": "form-select", "id": "id_team"}),
        )
        pools = position_pools(team) if team else {}
        for code, label in POSITIONS:
            ids = pools.get(code, [])
            qs = Player.objects.filter(player_id__in=ids) if team else Player.objects.none()
            self.fields[code] = forms.ModelChoiceField(
                queryset=qs,
                label=label,
                empty_label=f"— select {label.lower()} —",
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        self.fields["order"] = forms.CharField(
            required=False,
            initial=",".join(BATTING_POSITIONS),
            widget=forms.HiddenInput(),
        )

    def pitcher_field(self):
        return self["P"]

    def batting_fields(self):
        return [(code, self[code]) for code in BATTING_POSITIONS]

    def clean(self):
        cleaned = super().clean()
        chosen = {code: cleaned.get(code) for code, _ in POSITIONS}
        ids = [pl.player_id for pl in chosen.values() if pl is not None]
        p_pick, dh_pick = chosen.get("P"), chosen.get("DH")
        if (p_pick is not None and dh_pick is not None
                and p_pick.player_id == dh_pick.player_id):
            ids.remove(dh_pick.player_id)
        if len(ids) != len(set(ids)):
            raise forms.ValidationError(
                "Each player can only fill one position "
                "(except a pitcher may also be the DH)."
            )
        return cleaned

    def roster_for(self):
        """10-slot roster: pitcher first, then 9 batting slots in chosen order."""
        raw = (self.cleaned_data.get("order") or "").split(",")
        order = [c for c in raw if c]
        if sorted(order) != sorted(BATTING_POSITIONS):
            order = list(BATTING_POSITIONS)
        out = []
        for code in ["P"] + order:
            p = self.cleaned_data[code]
            out.append({"position": code, "player_id": p.player_id, "name": str(p)})
        return out


class Page1Form(SideRosterForm):
    """Page 1: side + team + roster + mode + innings (+ opponent team if cpu_auto)."""

    SIDE_CHOICES = [("away", "Away"), ("home", "Home")]
    INNINGS_CHOICES = [(3, "3"), (6, "6"), (9, "9")]

    def __init__(self, *args, request_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["side"] = forms.ChoiceField(
            choices=self.SIDE_CHOICES, widget=forms.RadioSelect, initial="away",
        )
        self.fields["mode"] = forms.ChoiceField(
            choices=Game.MODE_CHOICES, widget=forms.RadioSelect,
            initial=Game.CPU_AUTO,
        )
        self.fields["total_innings"] = forms.TypedChoiceField(
            choices=self.INNINGS_CHOICES, coerce=int, initial=3,
            widget=forms.RadioSelect,
        )
        self.fields["opponent_team"] = forms.ModelChoiceField(
            queryset=Team.objects.all(), required=False,
            label="Opponent Team (CPU)",
            empty_label="— select opponent team —",
            widget=forms.Select(attrs={"class": "form-select"}),
        )
        User = get_user_model()
        opp_qs = (User.objects.exclude(pk=request_user.pk)
                  if request_user else User.objects.all())
        self.fields["opponent_user"] = forms.ModelChoiceField(
            queryset=opp_qs, required=False,
            label="Opponent Player",
            empty_label="— select opponent —",
            widget=forms.Select(attrs={"class": "form-select"}),
        )

    def clean(self):
        cleaned = super().clean()
        team = cleaned.get("team")
        opp  = cleaned.get("opponent_team")
        mode = cleaned.get("mode")
        if mode == Game.CPU_AUTO:
            if not opp:
                self.add_error("opponent_team", "Pick the CPU's team.")
            elif team and team.team_id == opp.team_id:
                self.add_error("opponent_team", "Opponent team must differ from your team.")
        if mode == Game.MULTIPLAYER and not cleaned.get("opponent_user"):
            self.add_error("opponent_user", "Pick an opponent to invite.")
        return cleaned
