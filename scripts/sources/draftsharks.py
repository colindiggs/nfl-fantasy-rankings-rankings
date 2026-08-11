"""DraftSharks redraft rankings — htmx table fragment, all formats, no login."""
import re

from common import fetch, get_logger, normalize_pos

log = get_logger("draftsharks")

SLUGS = {"standard": "", "half_ppr": "half-ppr", "ppr": "ppr"}

URL = ("https://www.draftsharks.com/rankings/load-table"
       "?pprSuperflexSlug={slug}&fantasyPosition=all&researchDepth=simple"
       "&playerGroup=all&sort=&selectedTeam=&playerSearchTerm=")

NAME_RE = re.compile(r'data-player-name="([^"]+)"')
POS_RE = re.compile(r'data-fantasy-position="([^"]+)"')
RANK_RE = re.compile(r'rank-index">\s*<span>(\d+)</span>')
TEAM_RE = re.compile(r'teams/([A-Z]{2,3})\.svg')


def fetch_draft(fmt, sess=None):
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
        p = normalize_pos(raw)
        out.append({"rank": int(rank.group(1)), "name": name.group(1),
                    "team": team.group(1) if team else None, "pos": p,
                    "pos_raw": raw if raw and not p else None})
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"DraftSharks parse yielded only {len(deduped)} players")
    return {"players": deduped, "meta": {"count": len(deduped)}}
