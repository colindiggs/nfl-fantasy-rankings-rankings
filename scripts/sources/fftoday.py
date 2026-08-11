"""FFToday rankings — plain HTML, all three formats, draft (top 225) + weekly.

Scoring: 1 = non-PPR, 2 = half-PPR, 3 = PPR.
"""
import re

from common import fetch, get_logger, normalize_pos

log = get_logger("fftoday")

SCORING = {"standard": "1", "half_ppr": "2", "ppr": "3"}

DRAFT_URL = "https://www.fftoday.com/rankings/playerrank.php?o=4&Scoring={scoring}"
WEEKLY_URL = ("https://www.fftoday.com/rankings/playerwkrank.php"
              "?Season={season}&GameWeek={week}&PosID={posid}&LeagueID={league}")

POS_IDS = {"QB": 10, "RB": 20, "WR": 30, "TE": 40}
# weekly pages use LeagueID for scoring: 1 = default, 107199 = PPR (site presets);
# fall back to default when a preset is unknown
WEEKLY_LEAGUE = {"standard": "1", "half_ppr": "26955", "ppr": "107644"}

ROW_RE = re.compile(
    r'>(\d+)</TD>\s*<TD[^>]*>((?:QB|RB|WR|TE|K|DEF)\d*)</TD>\s*'
    r'<TD[^>]*><A HREF="/stats/players/\d+/[^"]*">([^<]+)</A>[^<]*</TD>\s*'
    r'<TD[^>]*>([A-Z]{2,3})</TD>',
    re.IGNORECASE,
)
WEEK_ROW_RE = re.compile(
    r'>(\d+)</TD>\s*'
    r'<TD[^>]*><A HREF="/stats/players/\d+/[^"]*">([^<]+)</A>[^<]*</TD>\s*'
    r'<TD[^>]*>([A-Z]{2,3})</TD>',
    re.IGNORECASE,
)


def fetch_draft(fmt, sess=None):
    html = fetch(DRAFT_URL.format(scoring=SCORING[fmt]), sess=sess).text
    out = []
    for m in ROW_RE.finditer(html):
        pos = normalize_pos(re.match(r"[A-Z]+", m.group(2).upper()).group(0))
        out.append({"rank": int(m.group(1)), "name": m.group(3).strip(),
                    "team": m.group(4), "pos": pos})
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"FFToday parse yielded only {len(deduped)} players")
    return {"players": deduped, "meta": {"count": len(deduped)}}


def fetch_weekly(fmt, season, week, sess=None):
    league = WEEKLY_LEAGUE.get(fmt, "1")
    out = []
    for pos, posid in POS_IDS.items():
        html = fetch(WEEKLY_URL.format(season=season, week=week, posid=posid, league=league),
                     sess=sess).text
        rows = []
        for m in WEEK_ROW_RE.finditer(html):
            rows.append({"rank": int(m.group(1)), "name": m.group(2).strip(),
                         "team": m.group(3), "pos": pos})
        seen = set()
        for r in sorted(rows, key=lambda x: x["rank"]):
            if r["rank"] not in seen:
                seen.add(r["rank"])
                out.append(r)
    if len(out) < 40:
        raise RuntimeError(f"FFToday weekly parse yielded only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
