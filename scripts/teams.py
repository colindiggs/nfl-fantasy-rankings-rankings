"""NFL team table and resolver — the backbone of DST matching.

Sleeper keys defenses by team code ("PHI"), so resolving any of the forms sites
publish ("Philadelphia Eagles", "Eagles D/ST", "Philadelphia", "PHI") down to a
code is all that DST player-matching needs.
"""
import re

# code -> (city, nickname)
TEAMS = {
    "ARI": ("Arizona", "Cardinals"), "ATL": ("Atlanta", "Falcons"),
    "BAL": ("Baltimore", "Ravens"), "BUF": ("Buffalo", "Bills"),
    "CAR": ("Carolina", "Panthers"), "CHI": ("Chicago", "Bears"),
    "CIN": ("Cincinnati", "Bengals"), "CLE": ("Cleveland", "Browns"),
    "DAL": ("Dallas", "Cowboys"), "DEN": ("Denver", "Broncos"),
    "DET": ("Detroit", "Lions"), "GB": ("Green Bay", "Packers"),
    "HOU": ("Houston", "Texans"), "IND": ("Indianapolis", "Colts"),
    "JAX": ("Jacksonville", "Jaguars"), "KC": ("Kansas City", "Chiefs"),
    "LAC": ("Los Angeles", "Chargers"), "LAR": ("Los Angeles", "Rams"),
    "LV": ("Las Vegas", "Raiders"), "MIA": ("Miami", "Dolphins"),
    "MIN": ("Minnesota", "Vikings"), "NE": ("New England", "Patriots"),
    "NO": ("New Orleans", "Saints"), "NYG": ("New York", "Giants"),
    "NYJ": ("New York", "Jets"), "PHI": ("Philadelphia", "Eagles"),
    "PIT": ("Pittsburgh", "Steelers"), "SEA": ("Seattle", "Seahawks"),
    "SF": ("San Francisco", "49ers"), "TB": ("Tampa Bay", "Buccaneers"),
    "TEN": ("Tennessee", "Titans"), "WAS": ("Washington", "Commanders"),
}

# Alternate codes sites use for the same franchise -> Sleeper code.
CODE_ALIASES = {
    "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "GBP": "GB", "HST": "HOU",
    "JAC": "JAX", "KAN": "KC", "KCC": "KC", "LA": "LAR", "LVR": "LV",
    "NEP": "NE", "NOR": "NO", "NOS": "NO", "NWE": "NE", "OAK": "LV",
    "SD": "LAC", "SDG": "LAC", "SFO": "SF", "STL": "LAR", "TAM": "TB",
    "TBB": "TB", "WSH": "WAS", "WFT": "WAS",
}

# Nicknames that have moved or been renamed — map to the current franchise.
NICKNAME_ALIASES = {
    "redskins": "WAS", "washington football team": "WAS",
    "football team": "WAS", "oilers": "TEN",
}

# Words sites tack onto a defense's name.
_DST_WORDS = re.compile(
    r"\b(d/?st|dst|defense|defence|def|special\s*teams|st)\b", re.IGNORECASE)


def _norm(s):
    s = (s or "").lower().replace(".", " ").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


_BY_NICKNAME = {_norm(nick): code for code, (_, nick) in TEAMS.items()}
_BY_CITY = {}
for _code, (_city, _nick) in TEAMS.items():
    # New York and Los Angeles are ambiguous by city alone — leave them out
    _BY_CITY.setdefault(_norm(_city), []).append(_code)
_BY_CITY = {c: v[0] for c, v in _BY_CITY.items() if len(v) == 1}
_BY_FULL = {_norm(f"{city} {nick}"): code for code, (city, nick) in TEAMS.items()}


def normalize_code(code):
    """Map any team abbreviation variant to the Sleeper code, or None."""
    if not code:
        return None
    c = str(code).strip().upper()
    c = CODE_ALIASES.get(c, c)
    return c if c in TEAMS else None


def resolve_dst(name=None, team=None):
    """Resolve a defense row to its Sleeper team code.

    Accepts any of: "Philadelphia Eagles", "Eagles D/ST", "Eagles",
    "Philadelphia", "PHI" — plus an optional team column, which wins when valid.
    """
    code = normalize_code(team)
    if code:
        return code
    n = _norm(name)
    if not n:
        return None
    code = normalize_code(n.upper())        # name column holding a bare code
    if code:
        return code
    n = _norm(_DST_WORDS.sub(" ", n))       # drop "D/ST", "Defense", ...
    if not n:
        return None
    for table in (_BY_FULL, _BY_NICKNAME, NICKNAME_ALIASES, _BY_CITY):
        if n in table:
            return table[n]
    # last resort: a known nickname appearing anywhere in the string, so
    # "Washington Redskins" and "Green Bay Packers Defense" both land
    for table in (_BY_NICKNAME, NICKNAME_ALIASES):
        for nick, code in table.items():
            if re.search(rf"\b{re.escape(nick)}\b", n):
                return code
    return None
