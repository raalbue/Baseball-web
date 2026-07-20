import json
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "data" / "stadiums.json"
_STADIUMS = json.loads(_DATA_PATH.read_text())

TEAM_SLUGS = {
    "Angels": "angels", "Astros": "astros", "Athletics": "athletics",
    "Blue Jays": "blue_jays", "Braves": "braves", "Brewers": "brewers",
    "Cardinals": "cardinals", "Cubs": "cubs", "Diamondbacks": "diamondbacks",
    "Dodgers": "dodgers", "Giants": "giants", "Guardians": "indians",
    "Mariners": "mariners", "Marlins": "marlins", "Mets": "mets",
    "Nationals": "nationals", "Orioles": "orioles", "Padres": "padres",
    "Phillies": "phillies", "Pirates": "pirates", "Rangers": "rangers",
    "Rays": "rays", "Red Sox": "red_sox", "Reds": "reds",
    "Rockies": "rockies", "Royals": "royals", "Tigers": "tigers",
    "Twins": "twins", "White Sox": "white_sox", "Yankees": "yankees",
}


def stadium_context(team):
    """Return template-ready stadium data for the given Team (or None)."""
    slug = TEAM_SLUGS.get(team.name) if team else None
    data = _STADIUMS.get(slug) or _STADIUMS["generic"]
    minx, miny, w, h = data["viewbox"]
    return {
        "name": data["name"] or "Generic Ballpark",
        "viewbox": f"{minx} {miny} {w} {h}",
        "marker_radius": data["marker_radius"],
        "segments": {
            seg: " ".join(f"{x},{y}" for x, y in points)
            for seg, points in data["segments"].items()
        },
        "bases": data["bases"],
    }
