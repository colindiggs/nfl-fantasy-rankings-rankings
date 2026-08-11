"""MyFantasyLeague ADP — real-league draft data via free JSON export API.

Formats: standard (IS_PPR=0) and PPR (IS_PPR=1); MFL has no half-PPR split.
"""
from common import fetch, get_logger, normalize_pos

log = get_logger("mfl")

PPR_FLAG = {"standard": "0", "ppr": "1"}

ADP_URL = "https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1&IS_PPR={flag}"
PLAYERS_URL = "https://api.myfantasyleague.com/{season}/export?TYPE=players&JSON=1"

KEEP_POS = {"QB", "RB", "WR", "TE", "PK", "Def"}

_players_cache = {}


def _players(season, sess=None):
    if season not in _players_cache:
        data = fetch(PLAYERS_URL.format(season=season), sess=sess, timeout=60).json()
        m = {}
        for p in data.get("players", {}).get("player", []):
            if p.get("position") not in KEEP_POS:
                continue
            name = p.get("name", "")
            if "," in name:  # "Last, First" -> "First Last"
                last, first = [x.strip() for x in name.split(",", 1)]
                name = f"{first} {last}"
            pos = normalize_pos(p["position"])
            m[p["id"]] = {"name": name, "pos": pos, "team": p.get("team")}
        _players_cache[season] = m
    return _players_cache[season]


def fetch_draft(fmt, season, sess=None):
    if fmt not in PPR_FLAG:
        raise RuntimeError(f"MFL has no ADP for format {fmt}")
    pmap = _players(season, sess)
    data = fetch(ADP_URL.format(season=season, flag=PPR_FLAG[fmt]), sess=sess).json()
    rows = data.get("adp", {}).get("player", [])
    out = []
    for r in sorted(rows, key=lambda x: float(x["averagePick"])):
        info = pmap.get(r["id"])
        if not info:
            continue
        out.append({"rank": len(out) + 1, "name": info["name"], "team": info["team"], "pos": info["pos"]})
    if len(out) < 150:
        raise RuntimeError(
            f"MFL returned only {len(out)} matched players — too few drafts of this type yet")
    return {"players": out, "meta": {"rows": len(rows)}}
