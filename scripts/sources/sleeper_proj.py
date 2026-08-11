"""Sleeper's own weekly projections, turned into positional rankings.

Sleeper publishes a projection for every player, every week, at
/projections/nfl/{season}/{week}. Ordering those by projected points gives a
genuine weekly ranking from a source that is not FantasyPros — which for
historical seasons is otherwise the only weekly board that survives.

Two properties make this the most reliable source in the project:

  * it is keyed by Sleeper player_id, the same id space our actuals use, so
    matching is exact rather than name-based
  * it goes back to 2018 (2017 and earlier return rows with no points)

It is a projection, not an expert opinion, so it is tagged basis="projection".
That matters: a projection ordered by points is a legitimate ranking, but it
answers "who scores most" rather than "who should you start", and those come
apart at positions where usage is volatile.
"""
from common import fetch, get_logger, normalize_pos

log = get_logger("sleeper_proj")

URL = ("https://api.sleeper.app/projections/nfl/{season}/{week}"
       "?season_type=regular&position[]=QB&position[]=RB&position[]=WR"
       "&position[]=TE&position[]=K&position[]=DEF&order_by=pts_half_ppr")

PTS_KEY = {"standard": "pts_std", "half_ppr": "pts_half_ppr", "ppr": "pts_ppr"}

FIRST_SEASON = 2018   # earlier seasons return rows with no projected points

_cache = {}


def clear_cache():
    _cache.clear()


def _rows(season, week, sess=None):
    key = (season, week)
    if key not in _cache:
        _cache[key] = fetch(URL.format(season=season, week=week),
                            sess=sess, timeout=60).json()
    return _cache[key]


def fetch_weekly(fmt, sess=None, season=None, week=None):
    if season is None or week is None:
        raise RuntimeError("sleeper projections need an explicit season and week")
    if int(season) < FIRST_SEASON:
        raise RuntimeError(
            f"Sleeper projections start in {FIRST_SEASON}; asked for {season}")
    stat = PTS_KEY[fmt]
    rows = _rows(season, week, sess=sess)

    by_pos = {}
    for r in rows:
        stats = r.get("stats") or {}
        pts = stats.get(stat)
        if pts is None:
            continue
        info = r.get("player") or {}
        pos = normalize_pos(info.get("position"))
        if not pos:
            continue
        pid = str(r.get("player_id"))
        name = (f"{info.get('first_name', '')} {info.get('last_name', '')}".strip()
                or pid)
        by_pos.setdefault(pos, []).append({
            "name": name,
            "team": info.get("team") or r.get("team"),
            "pos": pos,
            "sleeper_id": pid,       # exact match, no name lookup needed
            "_pts": float(pts),
        })

    players = []
    for pos, group in by_pos.items():
        group.sort(key=lambda p: -p["_pts"])
        for i, p in enumerate(group):
            p["rank"] = i + 1
            p["projected"] = round(p.pop("_pts"), 2)
            players.append(p)

    if len(players) < 40:
        raise RuntimeError(
            f"Sleeper projections {season} wk{week}: only {len(players)} rows")
    return {"players": players,
            "meta": {"count": len(players),
                     "positions": {k: len(v) for k, v in sorted(by_pos.items())}}}
