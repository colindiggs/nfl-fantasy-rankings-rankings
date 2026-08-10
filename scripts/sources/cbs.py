"""CBS Sports fantasy rankings (draft top-200 + weekly positional pages).

CBS publishes standard and PPR (no half-PPR top-200).
Player names come from the profile-URL slug (display name is abbreviated).
"""
import re

from bs4 import BeautifulSoup

from common import fetch, get_logger

log = get_logger("cbs")

DRAFT_URLS = {
    "standard": "https://www.cbssports.com/fantasy/football/rankings/standard/top200/",
    "ppr": "https://www.cbssports.com/fantasy/football/rankings/ppr/top200/",
}

WEEKLY_URLS = {
    "standard": "https://www.cbssports.com/fantasy/football/rankings/standard/{pos}/",
    "ppr": "https://www.cbssports.com/fantasy/football/rankings/ppr/{pos}/",
}

_SLUG_RE = re.compile(r"/nfl/players/\d+/([a-z0-9-]+)/")


def _name_from_slug(href):
    m = _SLUG_RE.search(href or "")
    if not m:
        return None
    return m.group(1).replace("-", " ").title()


def _parse_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.select("div.player-row"):
        rank_el = row.select_one("div.rank")
        link = row.select_one("div.player a[href*='/nfl/players/']")
        pos_el = row.select_one("span.team.position, span.position")
        if not rank_el or not link:
            continue
        try:
            rank = int(rank_el.get_text(strip=True))
        except ValueError:
            continue
        name = _name_from_slug(link.get("href")) or link.get_text(strip=True)
        pos = None
        if pos_el:
            toks = pos_el.get_text(" ", strip=True).split()
            for t in toks:
                if t in ("QB", "RB", "WR", "TE", "K", "DST"):
                    pos = t
                    break
        out.append({"rank": rank, "name": name, "team": None, "pos": pos})
    # the page repeats the list for responsive layouts — keep first row per rank
    seen = set()
    deduped = []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    return deduped


def fetch_draft(fmt, sess=None):
    if fmt not in DRAFT_URLS:
        raise RuntimeError(f"CBS has no draft rankings for format {fmt}")
    html = fetch(DRAFT_URLS[fmt], sess=sess).text
    players = _parse_rows(html)
    if len(players) < 50:
        raise RuntimeError(f"CBS parse yielded only {len(players)} players — page layout may have changed")
    return {"players": players, "meta": {"count": len(players)}}


def fetch_weekly(fmt, sess=None):
    if fmt not in WEEKLY_URLS:
        raise RuntimeError(f"CBS has no weekly rankings for format {fmt}")
    players = []
    for pos in ("qb", "rb", "wr", "te"):
        url = WEEKLY_URLS[fmt].format(pos=pos)
        html = fetch(url, sess=sess).text
        rows = _parse_rows(html)
        for r in rows:
            r["pos"] = pos.upper()
        players.extend(rows)
    if len(players) < 40:
        raise RuntimeError(f"CBS weekly parse yielded only {len(players)} players")
    return {"players": players, "meta": {"count": len(players)}}
