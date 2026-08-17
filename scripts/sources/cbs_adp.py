"""CBS ADP — average draft position across CBS Sports leagues.

Distinct from sources/cbs.py, which is CBS's editorial top-200. This is the
draft-averages table: what CBS's players actually did.

CBS publish one pooled ADP rather than one per scoring format, so it is
captured under PPR only. Names come from the profile-URL slug for the same
reason as the editorial board — the visible cell carries an abbreviated name
("J. Gibbs") in one span and the full name in another, and which one a naive
text parse picks up depends on the responsive layout markup.
"""
import re

from bs4 import BeautifulSoup

from common import fetch, get_logger, normalize_pos
import teams as teams_mod

log = get_logger("cbs-adp")

URL = "https://www.cbssports.com/fantasy/football/draft/averages/"

_SLUG = re.compile(r"/nfl/players/\d+/([a-z0-9-]+)/")


def _name_from_slug(href):
    m = _SLUG.search(href or "")
    return m.group(1).replace("-", " ").title() if m else None


def fetch_draft(fmt, sess=None):
    if fmt != "ppr":
        return None
    soup = BeautifulSoup(fetch(URL, sess=sess).text, "html.parser")
    rows = []
    for tr in soup.select("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        rank_txt = tds[0].get_text(strip=True)
        if not rank_txt.isdigit():
            continue
        link = tds[1].select_one("a[href*='/nfl/players/']")
        if not link:
            continue
        name = _name_from_slug(link.get("href")) or link.get_text(strip=True)
        cell = tds[1]
        pos_el = cell.select_one(".CellPlayerName-position")
        team_el = cell.select_one(".CellPlayerName-team")
        pos = normalize_pos(pos_el.get_text(strip=True)) if pos_el else None
        team = team_el.get_text(strip=True).upper() if team_el else None
        # CBS lists defenses without a position marker
        if not pos and teams_mod.resolve_dst(name=name, team=team):
            pos = "DST"
        try:
            adp = float(tds[3].get_text(strip=True))
        except ValueError:
            continue
        rows.append({"adp": adp, "name": name, "team": team, "pos": pos})
    rows.sort(key=lambda r: r["adp"])
    out = [{"rank": i, "name": r["name"], "team": r["team"], "pos": r["pos"]}
           for i, r in enumerate(rows, 1)]
    if len(out) < 100:
        raise RuntimeError(f"CBS ADP returned only {len(out)} rows — layout may have changed")
    log.info("CBS ADP: %d players", len(out))
    return {"players": out, "meta": {"source_url": URL}}
