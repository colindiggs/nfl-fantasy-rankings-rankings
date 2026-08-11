"""Draft Sharks redraft rankings — htmx table fragment, no login.

Their default board interleaves IDP (LB/DL/DB) into one overall order, which
crowded offence down to ~83 players inside the top 250 and made the board look
broken. It is not: with IDP removed it is a clean 1QB board.

Only the board as published is captured, tagged roster="idp".

An offence-only view was tried and withdrawn. Stripping the IDP rows and
renumbering does NOT yield a 1QB redraft board, because the underlying order
is value-based across every position: after removing IDP it still reads Gibbs,
Nacua, Bijan, Chase, McCaffrey, Smith-Njigba, Josh Allen (7), Brock Bowers (8),
Trey McBride (9), Lamar Jackson (10), Drake Maye (11), Brandon Aubrey (12).
A kicker twelfth overall is the tell — no 1QB redraft board looks like that.
Peers put QB4 between 36 and 67; this board had it at 28 with TE1 at 8. It is a
legitimate board for the league it targets, and misleading in any other.

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


def fetch_draft(fmt, sess=None):
    rows = _rows(fmt, sess=sess)
    idp_seen = sum(1 for r in rows if (r.get("pos_raw") or "") in IDP_POSITIONS)
    if len(rows) < 50:
        raise RuntimeError(f"DraftSharks parse yielded only {len(rows)} rows")
    return {"players": [dict(r) for r in rows],
            "meta": {"count": len(rows), "idp_rows": idp_seen, "view": "idp"},
            "tags": tags(roster="idp")}
