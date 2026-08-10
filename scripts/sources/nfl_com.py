"""NFL.com editorial draft rankings (server-rendered HTML, one set — NFL default scoring).

Weekly in-season: statType=weekStats&week=N on the same page.
"""
import re

from common import fetch, get_logger

log = get_logger("nfl_com")

URL = "https://fantasy.nfl.com/research/rankings?leagueId=0&statType=draftStats&offset={offset}"
WEEK_URL = "https://fantasy.nfl.com/research/rankings?leagueId=0&statType=weekStats&week={week}&position={pos}&offset={offset}"

ROW_RE = re.compile(
    r'class="editorDraftRankRank first">(\d+)</td>.*?'
    r'what-playerCard">([^<]+)</a> <em>(\w+) - (\w+)</em>',
    re.DOTALL,
)
WEEK_ROW_RE = re.compile(
    r'class="editorWeekRankRank first">(\d+)</td>.*?'
    r'what-playerCard">([^<]+)</a> <em>(\w+)(?: - (\w+))?</em>',
    re.DOTALL,
)


def _rows(html, rx):
    out = []
    for chunk in html.split('<tr class="player-')[1:]:
        m = rx.search(chunk)
        if m:
            rank, name, pos, team = m.group(1), m.group(2), m.group(3), m.group(4)
            out.append({"rank": int(rank), "name": name, "team": team, "pos": pos})
    return out


def fetch_draft(fmt, sess=None):
    if fmt != "standard":
        raise RuntimeError("NFL.com publishes one editorial board (default scoring) — standard only")
    out = []
    for offset in (1, 101, 201):
        html = fetch(URL.format(offset=offset), sess=sess).text
        rows = _rows(html, ROW_RE)
        if not rows:
            break
        out.extend(rows)
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"NFL.com parse yielded only {len(deduped)} players")
    return {"players": deduped, "meta": {"count": len(deduped)}}


def fetch_weekly(fmt, week, sess=None):
    if fmt != "standard":
        raise RuntimeError("NFL.com weekly rankings are default scoring — standard only")
    out = []
    for pos in ("QB", "RB", "WR", "TE"):
        rows = []
        for offset in (1, 26):
            html = fetch(WEEK_URL.format(week=week, pos=pos, offset=offset), sess=sess).text
            got = _rows(html, WEEK_ROW_RE)
            if not got:
                break
            rows.extend(got)
        seen = set()
        for r in sorted(rows, key=lambda x: x["rank"]):
            if r["rank"] not in seen:
                seen.add(r["rank"])
                r["pos"] = pos
                out.append(r)
    if len(out) < 40:
        raise RuntimeError(f"NFL.com weekly parse yielded only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
