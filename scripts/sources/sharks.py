"""FantasySharks ADP.

Previously this pulled their projections.php table, which is ordered by RAW
PROJECTED POINTS pooled across positions — so ~25 QBs led the board, because a
QB scores ~350 points a season and an RB ~250. That is a projections table, not
a draft board, and it made the source look like a superflex ranker when it was
neither.

adp.php is their actual draft-order data (Gibbs #1, not Josh Allen #1), so the
source is now tagged basis="adp" — market behaviour rather than expert opinion.

Position codes: 97 = QB/RB/WR/TE, 99 = all w/DST, 98 = all w/IDP.
Scoring: 1 = non-PPR, 18 = half-PPR, 2 = PPR.
Segment selects the season; only the current one returns data (the archive
dropdown lists back to 2012 but serves empty pages).
"""
import re

from common import fetch, get_logger, normalize_pos

log = get_logger("sharks")

SCORING = {"standard": "1", "half_ppr": "18", "ppr": "2"}

URL = ("https://www.fantasysharks.com/apps/bert/forecasts/adp.php"
       "?League=-1&Position={pos}&scoring={scoring}&Segment={segment}&uid=4")

POSITION_ALL_DST = "99"
CURRENT_SEGMENT = "874"  # 2026; steps by 32 per season

ROW_RE = re.compile(
    r"<b>(\d+)</b>\s*</div>\s*"
    r'<TD class="playerLink"[^>]*>\s*<a[^>]*>([^<]+)</a>.*?'
    r'<td align="center">([A-Za-z/]+)</td>\s*'
    r'<td align="center">([A-Z]{2,3})</td>',
    re.DOTALL | re.IGNORECASE,
)


def fetch_draft(fmt, sess=None, segment=None):
    url = URL.format(pos=POSITION_ALL_DST, scoring=SCORING[fmt],
                     segment=segment or CURRENT_SEGMENT)
    html = fetch(url, sess=sess, timeout=60).text
    out = []
    for m in ROW_RE.finditer(html):
        rank, raw_name, pos, team = (m.group(1), m.group(2).strip(),
                                     m.group(3), m.group(4))
        name = raw_name
        if "," in raw_name:  # "Gibbs, Jahmyr" -> "Jahmyr Gibbs"
            last, first = [x.strip() for x in raw_name.split(",", 1)]
            name = f"{first} {last}"
        out.append({"rank": int(rank), "name": name, "team": team,
                    "pos": normalize_pos(pos)})
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"Sharks ADP parse yielded only {len(deduped)} rows")
    # the scoring param is accepted but ignored — all three settings return the
    # same board. It still competes in every format's leaderboard (it is a real
    # prediction either way), but the caveat belongs in the data.
    return {"players": deduped,
            "meta": {"count": len(deduped), "format_agnostic": True}}
