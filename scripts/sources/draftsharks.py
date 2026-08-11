"""Draft Sharks redraft rankings — htmx table fragment, no login.

Their default board interleaves IDP (LB/DL/DB) into one overall order, which
crowded offence down to ~83 players inside the top 250 and made the board look
broken. It is not: with IDP removed it is a clean 1QB board.

Two views are captured, because both are real leagues someone plays:

  draftsharks       offence + K/DST, IDP rows dropped, re-ranked 1..N
  draftsharks-idp   the board exactly as published, IDP included

The published order is preserved in both; the offence view only removes rows
and renumbers, so a player's position relative to other offensive players is
untouched.

pprSuperflexSlug also accepts superflex variants ("superflex",
"half-ppr-superflex", "ppr-superflex"). We deliberately use the 1QB slugs —
verified against their superflex boards, which put Josh Allen first.
"""
import re

from common import fetch, get_logger, normalize_pos, tags

log = get_logger("draftsharks")

SLUGS = {"standard": "", "half_ppr": "half-ppr", "ppr": "ppr"}

URL = ("https://www.draftsharks.com/rankings/load-table"
       "?pprSuperflexSlug={slug}&fantasyPosition=all&researchDepth=simple"
       "&playerGroup=all&sort=&selectedTeam=&playerSearchTerm=")

NAME_RE = re.compile(r'data-player-name="([^"]+)"')
POS_RE = re.compile(r'data-fantasy-position="([^"]+)"')
RANK_RE = re.compile(r'rank-index">\s*<span>(\d+)</span>')
TEAM_RE = re.compile(r'teams/([A-Z]{2,3})\.svg')

IDP_POSITIONS = {"LB", "DL", "DB", "DE", "DT", "CB", "S", "EDGE"}

_cache = {}


def _rows(fmt, sess=None):
    if fmt not in _cache:
        html = fetch(URL.format(slug=SLUGS[fmt]), sess=sess,
                     headers={"HX-Request": "true"}).text
        out = []
        for block in re.split(r"<tbody\s+data-player-row", html)[1:]:
            name = NAME_RE.search(block)
            rank = RANK_RE.search(block)
            if not (name and rank):
                continue
            pos = POS_RE.search(block)
            team = TEAM_RE.search(block)
            raw = (pos.group(1).upper() if pos else None)
            out.append({"rank": int(rank.group(1)), "name": name.group(1),
                        "team": team.group(1) if team else None,
                        "pos": normalize_pos(raw), "pos_raw": raw})
        seen, deduped = set(), []
        for r in sorted(out, key=lambda x: x["rank"]):
            if r["rank"] not in seen:
                seen.add(r["rank"])
                deduped.append(r)
        _cache[fmt] = deduped
    return _cache[fmt]


def clear_cache():
    _cache.clear()


def fetch_draft(fmt, sess=None, include_idp=False):
    rows = _rows(fmt, sess=sess)
    idp_seen = sum(1 for r in rows if (r.get("pos_raw") or "") in IDP_POSITIONS)
    if include_idp:
        players = [dict(r) for r in rows]
        meta = {"count": len(players), "idp_rows": idp_seen, "view": "idp"}
        return {"players": players, "meta": meta, "tags": tags(roster="idp")}
    players = []
    for r in rows:
        if not r.get("pos") or (r.get("pos_raw") or "") in IDP_POSITIONS:
            continue
        p = {k: v for k, v in r.items() if k != "pos_raw"}
        p["rank"] = len(players) + 1        # renumber over offence only
        p["published_rank"] = r["rank"]     # keep what they actually printed
        players.append(p)
    if len(players) < 50:
        raise RuntimeError(f"DraftSharks parse yielded only {len(players)} rows")
    return {"players": players,
            "meta": {"count": len(players), "idp_rows_dropped": idp_seen,
                     "view": "offense"},
            "tags": tags()}
