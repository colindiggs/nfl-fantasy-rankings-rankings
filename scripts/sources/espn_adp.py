"""ESPN ADP — average draft position across ESPN's own leagues.

Distinct from sources/espn.py, which reads `draftRanksByRankType` (ESPN's
editorial board). This reads `ownership.averageDraftPosition`, which is what
ESPN's drafters did rather than what ESPN's analysts said.

Published for PPR only, and deliberately not per format: the figure is
identical when requested through the standard (leaguedefaults/1) and PPR
(leaguedefaults/3) endpoints, so it is one pooled number across ESPN's league
types rather than a scoring-specific board. Emitting it three times under
three format labels would manufacture three sources out of one.

That pooling is the same class of problem that got MyFantasyLeague
reclassified, but a much milder one: pooling scoring formats shifts the
RB/WR balance a little, where MFL was pooling dynasty drafts and moving
rookies 192 ranks. The QB4 slot and peer agreement are checked by
scripts/validate.py and sit in the normal redraft range.
"""
import json

from common import fetch, get_logger, normalize_pos

log = get_logger("espn-adp")

URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}"
       "/segments/0/leaguedefaults/3?view=kona_player_info")

POS_BY_ID = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}


def fetch_draft(fmt, season, sess=None):
    if fmt != "ppr":
        return None
    flt = {"players": {"limit": 450,
                       "sortDraftRanks": {"sortPriority": 1, "sortAsc": True,
                                          "value": "PPR"}}}
    data = fetch(URL.format(season=season), sess=sess, timeout=60,
                 headers={"x-fantasy-filter": json.dumps(flt)}).json()
    rows = []
    for item in data.get("players", []):
        p = item.get("player") or {}
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        # 0 means "never drafted in our leagues", which is missing data rather
        # than a first-overall pick — the sort would otherwise put them on top
        if not adp or adp <= 0:
            continue
        name = p.get("fullName")
        if not name:
            continue
        rows.append({
            "adp": float(adp), "name": name,
            "pos": POS_BY_ID.get(p.get("defaultPositionId")) or
                   normalize_pos(str(p.get("defaultPositionId"))),
            "espn_id": p.get("id"),
        })
    rows.sort(key=lambda r: r["adp"])
    # The decimal ADP is carried alongside the rank because the draft room
    # shows the decimal, not the ordinal: two players can sit one rank apart
    # and four picks apart, and that gap is the whole arbitrage signal.
    out = [{"rank": i, "name": r["name"], "team": None, "pos": r["pos"],
            "espn_id": r["espn_id"], "adp": round(r["adp"], 1)}
           for i, r in enumerate(rows, 1)]
    if len(out) < 150:
        raise RuntimeError(f"ESPN ADP returned only {len(out)} rows — API may have changed")
    log.info("ESPN ADP: %d players", len(out))
    return {"players": out, "meta": {"field": "ownership.averageDraftPosition"}}
