"""FantasySharks projections-based rankings (all formats, plain HTML table).

scoring: 1 = default standard, 18 = default half-PPR, 2 = default PPR.
Position=99 = all positions, ranked by projected points. Segment=0 = full season.
"""
import re

from common import fetch, get_logger

log = get_logger("sharks")

SCORING = {"standard": "1", "half_ppr": "18", "ppr": "2"}

TEAM_NICKNAMES = {
    "Cardinals", "Falcons", "Ravens", "Bills", "Panthers", "Bears", "Bengals",
    "Browns", "Cowboys", "Broncos", "Lions", "Packers", "Texans", "Colts",
    "Jaguars", "Chiefs", "Raiders", "Chargers", "Rams", "Dolphins", "Vikings",
    "Patriots", "Saints", "Giants", "Jets", "Eagles", "Steelers", "49ers",
    "Seahawks", "Buccaneers", "Titans", "Commanders",
}

URL = ("https://www.fantasysharks.com/apps/bert/forecasts/projections.php"
       "?League=-1&Position=99&scoring={scoring}&Segment=0&uid=4")

ROW_RE = re.compile(
    r'<tr><td[^>]*>(\d+)</td><td class="playerLink"[^>]*>'
    r'<a[^>]*playerpage\.php\?id=\d+[^>]*>([^<]+)</a>.*?'
    r'<td[^>]*>([A-Z]{2,3})</td>',
    re.DOTALL,
)


def fetch_draft(fmt, sess=None):
    html = fetch(URL.format(scoring=SCORING[fmt]), sess=sess, timeout=60).text
    out = []
    for m in ROW_RE.finditer(html):
        rank, name, team = int(m.group(1)), m.group(2).strip(), m.group(3)
        if "," not in name:
            continue
        last, first = [x.strip() for x in name.split(",", 1)]
        name = f"{first} {last}"
        if last in TEAM_NICKNAMES:
            continue  # team defense rows are "Seahawks, Seattle" etc.
        out.append({"rank": rank, "name": name, "team": team, "pos": None})
    # de-dup ranks (page can repeat header blocks), keep first
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"Sharks parse yielded only {len(deduped)} players")
    return {"players": deduped, "meta": {"count": len(deduped)}}
