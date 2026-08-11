"""ESPN fantasy draft rankings via the public league-defaults API.

ESPN publishes draft ranks for STANDARD and PPR only (no half-PPR).
Matching downstream uses espn_id -> Sleeper ID, so it's exact.
"""
import json

from common import fetch, get_logger, tags

log = get_logger("espn")

POS_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

RANK_TYPE = {"standard": "STANDARD", "ppr": "PPR"}

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3?view=kona_player_info"


def fetch_draft(fmt, season, sess=None):
    if fmt not in RANK_TYPE:
        raise RuntimeError(f"ESPN has no draft ranks for format {fmt}")
    rank_type = RANK_TYPE[fmt]
    flt = {
        "players": {
            "limit": 400,
            "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": rank_type},
        }
    }
    r = fetch(URL.format(season=season), sess=sess,
              headers={"x-fantasy-filter": json.dumps(flt)})
    data = r.json()
    out = []
    for entry in data.get("players", []):
        pl = entry.get("player") or {}
        ranks = pl.get("draftRanksByRankType") or {}
        rk = (ranks.get(rank_type) or {}).get("rank")
        if rk is None:
            continue
        pos = POS_MAP.get(pl.get("defaultPositionId"))
        if pos is None:
            continue
        out.append({
            "rank": rk,
            "name": pl.get("fullName"),
            "team": None,
            "pos": pos,
            "espn_id": pl.get("id"),
        })
    out.sort(key=lambda x: x["rank"])
    if len(out) < 50:
        raise RuntimeError(f"ESPN returned only {len(out)} ranked players — API shape may have changed")
    # a human-curated draft board, unlike their weekly projections below
    return {"players": out, "meta": {"count": len(out)}, "tags": tags()}


# ---------------------------------------------------------------- weekly
#
# ESPN publish a projection for every player every week, addressable by
# scoringPeriodId, and the season lives in the URL path — so unlike almost
# every other site, past weeks are still retrievable.
#
# 2021 and 2022 respond, and are deliberately NOT used. The player set they
# return for those seasons skews toward players prominent today rather than
# then: 12 of the top-24 projected QBs in 2022 week 3 never took the field that
# week. What survives is a small, survivorship-biased pool of players who were
# good in that era, which inflated weekly Spearman to 0.43 against 0.26 for
# every other source on the same weeks. 2023 onward returns dnp counts of ~0
# and tracks the field normally.
#
# leaguedefaults/1 scores standard, /3 scores PPR. Half-PPR is exactly the
# midpoint: half = std + 0.5*rec and ppr = std + 1.0*rec, so (std + ppr) / 2
# lands on half to the cent. That is arithmetic on ESPN's own projection, not
# an invented third board — and it is the only way this project gets ESPN into
# half-PPR at all, since they publish no half-PPR ranks.
WEEK_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
            "{season}/segments/0/leaguedefaults/{ld}")

LEAGUE_DEFAULT = {"standard": 1, "ppr": 3}

WEEKLY_FIRST_SEASON = 2023

# any valid sort works; this shape is the one ESPN accepts (limit alone 400s)
_WEEK_FILTER = {"players": {"limit": 500,
                            "sortDraftRanks": {"sortPriority": 100,
                                               "sortAsc": True, "value": "PPR"}}}

_week_cache = {}


def clear_cache():
    _week_cache.clear()


def _week_points(season, week, ld, sess=None):
    """-> {espn_id: (name, pos, projected_points)} for one scoring system."""
    key = (season, week, ld)
    if key in _week_cache:
        return _week_cache[key]
    r = fetch(WEEK_URL.format(season=season, ld=ld), sess=sess, timeout=60,
              params={"view": "kona_player_info", "scoringPeriodId": week},
              headers={"x-fantasy-filter": json.dumps(_WEEK_FILTER)})
    out = {}
    for entry in r.json().get("players", []):
        pl = entry.get("player") or {}
        pos = POS_MAP.get(pl.get("defaultPositionId"))
        if not pos:
            continue
        for st in pl.get("stats", []):
            if st.get("statSourceId") == 1 and st.get("scoringPeriodId") == week:
                out[pl.get("id")] = (pl.get("fullName"), pos,
                                     float(st.get("appliedTotal") or 0.0))
                break
    _week_cache[key] = out
    return out


def fetch_weekly(fmt, season, week, sess=None):
    if int(season) < WEEKLY_FIRST_SEASON:
        raise RuntimeError(
            f"ESPN weekly projections start in {WEEKLY_FIRST_SEASON}; asked {season}")
    std = _week_points(season, week, LEAGUE_DEFAULT["standard"], sess=sess)
    ppr = _week_points(season, week, LEAGUE_DEFAULT["ppr"], sess=sess)
    if not std or not ppr:
        raise RuntimeError(f"ESPN weekly {season} wk{week}: empty projection set")

    combined = {}
    for eid, (name, pos, s) in std.items():
        p = ppr.get(eid)
        if not p:
            continue
        pts = {"standard": s, "ppr": p[2], "half_ppr": (s + p[2]) / 2.0}[fmt]
        combined[eid] = (name, pos, pts)

    by_pos = {}
    for eid, (name, pos, pts) in combined.items():
        by_pos.setdefault(pos, []).append(
            {"name": name, "pos": pos, "team": None, "espn_id": eid,
             "_pts": pts})
    players = []
    for pos, group in by_pos.items():
        group.sort(key=lambda x: -x["_pts"])
        for i, p in enumerate(group):
            p["rank"] = i + 1
            p["projected"] = round(p.pop("_pts"), 2)
            players.append(p)
    if len(players) < 40:
        raise RuntimeError(f"ESPN weekly {season} wk{week}: only {len(players)} rows")
    return {"players": players,
            "meta": {"count": len(players),
                     "positions": {k: len(v) for k, v in sorted(by_pos.items())},
                     "half_ppr_derived": fmt == "half_ppr"},
            "tags": tags(basis="projection")}
