"""Yahoo fantasy draft rankings via the public read-only API (no OAuth).

Yahoo default leagues are half-PPR, and there is a single rank/ADP set.
"""
from common import fetch, get_logger

log = get_logger("yahoo")

URL = ("https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/"
       "players;sort=AR;count=60;start={start}/draft_analysis?format=json")


def _merge(list_of_dicts):
    out = {}
    for d in list_of_dicts:
        if isinstance(d, dict):
            out.update(d)
    return out


def fetch_draft(fmt, sess=None):
    if fmt != "half_ppr":
        raise RuntimeError("Yahoo publishes one rank set (default half-PPR) — half_ppr only")
    out = []
    for start in range(0, 300, 60):
        data = fetch(URL.format(start=start), sess=sess).json()
        players = data["fantasy_content"]["game"][1]["players"]
        n = int(players.get("count", 0))
        if n == 0:
            break
        for i in range(n):
            entry = players[str(i)]["player"]
            info = _merge(entry[0])
            name = (info.get("name") or {}).get("full")
            if not name:
                continue
            out.append({
                "rank": len(out) + 1,
                "name": name,
                "team": (info.get("editorial_team_abbr") or "").upper() or None,
                "pos": info.get("display_position"),
            })
        if n < 60:
            break
    if len(out) < 50:
        raise RuntimeError(f"Yahoo returned only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
