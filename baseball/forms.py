from django import forms
from django.contrib.auth import get_user_model
from .models import Game, Team, Player, position_pools, is_all_star_team

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
BULLPEN_MIN = 2
BULLPEN_MAX = 4


class _TeamLabelMixin:
    """Trailing team abbreviation on player labels, for All-Star pools where
    multiple teams' players are mixed together."""
    def label_from_instance(self, obj):
        return f"{obj} ({obj.team_abbrev})" if obj.team_abbrev else str(obj)


class _PlayerChoiceField(_TeamLabelMixin, forms.ModelChoiceField):
    pass


class _PlayerMultipleChoiceField(_TeamLabelMixin, forms.ModelMultipleChoiceField):
    pass


class SideRosterForm(forms.Form):
    """One side's team pick + 10-slot roster (unprefixed position field names)."""

    def __init__(self, *args, team=None, team_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_star = is_all_star_team(team)
        self.fields["team"] = forms.ModelChoiceField(
            queryset=team_queryset if team_queryset is not None else Team.objects.all(),
            label="Team",
            empty_label="— select team —",
            widget=forms.Select(attrs={"class": "form-select", "id": "id_team"}),
        )
        pools = position_pools(team) if team else {}
        field_cls = _PlayerChoiceField if self.all_star else forms.ModelChoiceField
        for code, label in POSITIONS:
            ids = pools.get(code, [])
            qs = Player.objects.filter(player_id__in=ids) if team else Player.objects.none()
            self.fields[code] = field_cls(
                queryset=qs,
                label=label,
                empty_label=f"— select {label.lower()} —",
                widget=forms.Select(attrs={"class": "form-select"}),
            )
        bullpen_cls = _PlayerMultipleChoiceField if self.all_star else forms.ModelMultipleChoiceField
        self.fields["bullpen"] = bullpen_cls(
            queryset=(Player.objects.filter(player_id__in=pools.get("P", []))
                      if team else Player.objects.none()),
            required=True, label="Bullpen",
            widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
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
        bullpen = cleaned.get("bullpen")
        if bullpen is not None:
            if not (BULLPEN_MIN <= len(bullpen) <= BULLPEN_MAX):
                self.add_error("bullpen", f"Pick {BULLPEN_MIN}-{BULLPEN_MAX} relievers.")
            elif p_pick and any(p.player_id == p_pick.player_id for p in bullpen):
                self.add_error("bullpen", "Your starting pitcher can't also be in the bullpen.")
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

    def bullpen_for(self):
        """List of {player_id, name} for the picked relievers."""
        return [{"player_id": p.player_id, "name": str(p)}
                for p in self.cleaned_data["bullpen"]]


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
        self.fields["streaky_per_game"] = forms.BooleanField(
            required=False, label="Streaky player (per game)",
            widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        )
        self.fields["streaky_per_inning"] = forms.BooleanField(
            required=False, label="Streaky player (per inning)",
            widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        )
        self.fields["weather_temperature_f"] = forms.IntegerField(
            required=False, initial=70, label="Temperature (°F)",
            widget=forms.NumberInput(attrs={"class": "form-control form-control-sm", "style": "max-width:100px"}),
        )
        self.fields["weather_wind"] = forms.ChoiceField(
            choices=Game.WIND_CHOICES, initial="calm", label="Wind",
            widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "max-width:160px"}),
        )
        self.fields["weather_sky"] = forms.ChoiceField(
            choices=Game.SKY_CHOICES, initial="overcast", label="Sky",
            widget=forms.Select(attrs={"class": "form-select form-select-sm", "style": "max-width:160px"}),
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
        if cleaned.get("weather_temperature_f") in (None, ""):
            cleaned["weather_temperature_f"] = 70
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
