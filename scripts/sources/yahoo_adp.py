"""Yahoo ADP — real draft position from Yahoo's public read-only API.

Distinct from sources/yahoo.py, which reads the same endpoint but takes
Yahoo's own editorial rank order. This one reads `draft_analysis.average_pick`
and orders by it, so it is the market rather than the opinion: what Yahoo's
drafters actually did, across the largest single pool of redraft leagues
anywhere.

`average_pick` is the live figure and moves during draft season;
`preseason_average_pick` is frozen and would be the one to use for a
historical backfill, but it is not what a drafter sees today.

Yahoo default leagues are half-PPR, and Yahoo publishes one rank set.
"""
from common import fetch, get_logger, normalize_pos

log = get_logger("yahoo-adp")

URL = ("https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/"
       "players;sort=AR;count={count};start={start}/draft_analysis?format=json")
PAGE = 60
MAX_PLAYERS = 420


def _merge(parts):
    out = {}
    for d in parts:
        if isinstance(d, dict):
            out.update(d)
    return out


def fetch_draft(fmt, sess=None):
    if fmt != "half_ppr":
        return None
    rows = []
    for start in range(0, MAX_PLAYERS, PAGE):
        data = fetch(URL.format(count=PAGE, start=start), sess=sess).json()
        players = data["fantasy_content"]["game"][1]["players"]
        n = int(players.get("count", 0))
        if not n:
            break
        for i in range(n):
            entry = players[str(i)]["player"]
            info = _merge(entry[0])
            name = (info.get("name") or {}).get("full")
            if not name:
                continue
            analysis = _merge((entry[1] or {}).get("draft_analysis") or [])
            try:
                adp = float(analysis.get("average_pick"))
            except (TypeError, ValueError):
                continue          # undrafted players carry no average pick
            rows.append({
                "adp": adp,
                "name": name,
                "team": (info.get("editorial_team_abbr") or "").upper() or None,
                "pos": normalize_pos(info.get("display_position")),
            })
        if n < PAGE:
            break
    rows.sort(key=lambda r: r["adp"])
    out = [{"rank": i, "name": r["name"], "team": r["team"], "pos": r["pos"]}
           for i, r in enumerate(rows, 1)]
    if len(out) < 150:
        raise RuntimeError(f"Yahoo ADP returned only {len(out)} rows — endpoint may have changed")
    log.info("Yahoo ADP: %d players", len(out))
    return {"players": out, "meta": {"field": "draft_analysis.average_pick"}}
