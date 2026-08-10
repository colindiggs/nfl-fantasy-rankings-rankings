"""The Ringer's fantasy rankings — published Google Sheet CSV (half-PPR, draft only)."""
import csv
import io
import re

from common import fetch, get_logger

log = get_logger("ringer")

CSV_URL = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQ0fHrD0-4mbxkli09g2tHhbFyY"
           "--DpUljDytrCD-B9lcvgkdiCZRWqMjKwUQKwI6guFiypNPb-pXeY/pub"
           "?gid=879540765&single=true&output=csv")

POS_RE = re.compile(r"^(QB|RB|WR|TE|K|DST|DEF)\d*$")


def fetch_draft(fmt, sess=None):
    if fmt != "half_ppr":
        raise RuntimeError("The Ringer's board is half-PPR only")
    text = fetch(CSV_URL, sess=sess).content.decode("utf-8")
    out = []
    for row in csv.reader(io.StringIO(text)):
        # left block: Rk, Player, Team, Pos, Bye, Val
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        rank = int(row[0].strip())
        name, team, pos = row[1].strip(), row[2].strip(), row[3].strip().upper()
        m = POS_RE.match(pos)
        if not (name and m):
            continue
        base = "DST" if m.group(1) in ("DEF", "DST") else m.group(1)
        out.append({"rank": rank, "name": name, "team": team or None, "pos": base})
    seen, deduped = set(), []
    for r in sorted(out, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    if len(deduped) < 50:
        raise RuntimeError(f"Ringer CSV parse yielded only {len(deduped)} players")
    return {"players": deduped, "meta": {"count": len(deduped)}}
