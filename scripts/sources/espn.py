"""ESPN fantasy draft rankings via the public league-defaults API.

ESPN publishes draft ranks for STANDARD and PPR only (no half-PPR).
Matching downstream uses espn_id -> Sleeper ID, so it's exact.
"""
import json

from common import fetch, get_logger

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
    return {"players": out, "meta": {"count": len(out)}}
