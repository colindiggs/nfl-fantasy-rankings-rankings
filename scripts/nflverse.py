"""Free historical NFL context data from nflverse-data GitHub releases.

Two datasets, cached under data/nflverse/ and refreshed only when missing:

  roster_{season}.csv    one row per player-team-season: position, birth_date,
                         years_exp, team, and cross-site ids including
                         sleeper_id (exact join to our player space)
  injuries_{season}.csv  one row per player-week on an official injury report:
                         report_status (Out / Doubtful / Questionable),
                         practice_status, gsis_id

Source: https://github.com/nflverse/nflverse-data (public, no key).
"""
import csv
import io
from pathlib import Path

from common import DATA, fetch, get_logger

log = get_logger("nflverse")

CACHE = DATA / "nflverse"
BASE = "https://github.com/nflverse/nflverse-data/releases/download"

URLS = {
    "roster": BASE + "/rosters/roster_{season}.csv",
    "injuries": BASE + "/injuries/injuries_{season}.csv",
    # one file covering every draft class, not per-season
    "draft_picks": BASE + "/draft_picks/draft_picks.csv",
}


def _load_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def get(kind, season=None):
    """Rows for one dataset(-season), downloading on first use. [] if unavailable."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (f"{kind}_{season}.csv" if season else f"{kind}.csv")
    if path.exists():
        return _load_csv(path)
    url = URLS[kind].format(season=season)
    try:
        r = fetch(url, timeout=60)
    except RuntimeError as e:
        log.warning("%s %s unavailable: %s", kind, season, e)
        return []
    # sanity: a real dataset is a header plus hundreds of rows
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if len(rows) < 100:
        log.warning("%s %s looks wrong (%d rows) — not cached", kind, season, len(rows))
        return rows
    path.write_text(r.text, encoding="utf-8")
    log.info("%s %s cached: %d rows", kind, season, len(rows))
    return rows


OFFENSE_POS = {"QB", "RB", "WR", "TE"}


def roster_index(season):
    """-> {sleeper_id: {team, pos, birth_date, years_exp, gsis_id}} for one season.

    A player traded mid-season appears once per team; the LAST row wins, which
    matches "team he ended the season with".
    """
    out = {}
    gsis_to_sleeper = {}
    for row in get("roster", season):
        sid = (row.get("sleeper_id") or "").split(".")[0]  # some exports float-ify ids
        if not sid:
            continue
        out[sid] = {
            "team": row.get("team"),
            "pos": row.get("position"),
            "birth_date": row.get("birth_date") or None,
            "years_exp": row.get("years_exp") or None,
            "gsis_id": row.get("gsis_id") or None,
        }
        if row.get("gsis_id"):
            gsis_to_sleeper[row["gsis_id"]] = sid
    return out, gsis_to_sleeper


def injury_weeks(season, gsis_to_sleeper):
    """-> {sleeper_id: {"out": n, "listed": n}} distinct report weeks in a season."""
    listed, out_wk = {}, {}
    for row in get("injuries", season):
        sid = gsis_to_sleeper.get(row.get("gsis_id") or "")
        if not sid:
            continue
        wk = row.get("week")
        listed.setdefault(sid, set()).add(wk)
        if (row.get("report_status") or "").strip().lower() == "out":
            out_wk.setdefault(sid, set()).add(wk)
    return {sid: {"listed": len(wks), "out": len(out_wk.get(sid, ()))}
            for sid, wks in listed.items()}


def draft_index(gsis_to_sleeper):
    """-> {sleeper_id: {"round": int, "pick": int}} NFL draft capital.

    gsis_to_sleeper should be merged over every season of interest so late-career
    players still resolve. Undrafted players are simply absent.
    """
    out = {}
    for row in get("draft_picks"):
        sid = gsis_to_sleeper.get(row.get("gsis_id") or "")
        if not sid:
            continue
        try:
            out[sid] = {"round": int(row["round"]), "pick": int(row["pick"])}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def team_turnover(season):
    """-> {team: share of this season's offensive skill roster NOT on the same
    team the season before}. A proxy for offensive-composition change."""
    cur, _ = roster_index(season)
    prev, _ = roster_index(season - 1)
    per_team = {}
    for sid, r in cur.items():
        if (r.get("pos") or "") not in OFFENSE_POS or not r.get("team"):
            continue
        stayed = prev.get(sid, {}).get("team") == r["team"]
        n_new, n_all = per_team.get(r["team"], (0, 0))
        per_team[r["team"]] = (n_new + (0 if stayed else 1), n_all + 1)
    return {t: round(n_new / n_all, 3) for t, (n_new, n_all) in per_team.items() if n_all}
