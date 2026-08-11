"""The Ringer's published rankings sheet.

Their site renders a JS table, but the underlying data is a Google Sheet they
publish themselves — same title, same update date as the web page. It is the
real source, not a workaround.

One CSV carries FOUR complete boards, each with its own TOP 200 / DEFENSES /
KICKERS sections:

    The Ringer's Half-PPR ...      -> half_ppr
    The Ringer's Zero-PPR ...      -> standard
    The Ringer's PPR ...           -> ppr
    The Ringer's Superflex ...     -> captured as source "ringer-superflex"

The superflex board is kept deliberately. It is the same analysts, the same
week, differing only in format — which makes it a labelled control for format
detection, and the only ground truth we have for what a superflex board looks
like. It is tagged qb=superflex so it never enters a 1QB consensus.

Quirk: in the DEFENSES sections the Team column is NOT the defense's own team
(e.g. "Seattle Seahawks" against "PIT"), so the name is authoritative. Handled
centrally in teams.resolve_dst; we simply drop the team column for DST rows.
"""
import csv
import io
import re

from common import fetch, get_logger, normalize_pos, tags

log = get_logger("ringer")

URL = ("https://docs.google.com/spreadsheets/d/e/2PACX-1vQ0fHrD0-4mbxkli09g2t"
       "HhbFyY--DpUljDytrCD-B9lcvgkdiCZRWqMjKwUQKwI6guFiypNPb-pXeY/pub"
       "?gid=879540765&single=true&output=csv")

# board title fragment -> our format key
BOARD_FORMATS = {
    "half-ppr": "half_ppr",
    "zero-ppr": "standard",
    "ppr": "ppr",
    "superflex": "superflex",
}

TITLE_RE = re.compile(r"the ringer'?s\s+(.+?)\s+fantasy football rankings", re.I)

_cache = {}


def _split_boards(rows):
    """-> {format_key: [rows]} by scanning for the per-board title rows."""
    boards, current = {}, None
    for row in rows:
        head = (row[0] if row else "").strip()
        m = TITLE_RE.search(head) if head else None
        if m:
            label = m.group(1).strip().lower()
            # "ppr" is a substring of "half-ppr"/"zero-ppr", so match longest first
            key = next((v for k, v in sorted(BOARD_FORMATS.items(),
                                             key=lambda kv: -len(kv[0]))
                        if k in label), None)
            current = key
            if key:
                boards[key] = []
            continue
        if current and current in boards:
            boards[current].append(row)
    return boards


def _parse_board(rows):
    out = []
    for row in rows:
        if len(row) < 4 or not row[0].strip().isdigit():
            continue
        rank = int(row[0].strip())
        name = (row[1] or "").strip()
        team = (row[2] or "").strip().upper() or None
        # Pos column carries the positional rank too: "RB1", "DST3", "K12"
        pos = normalize_pos(row[3])
        if not name or not pos:
            continue
        if pos == "DST":
            team = None  # their team column is unreliable for defenses
        out.append({"rank": rank, "name": name, "team": team, "pos": pos})
    out.sort(key=lambda x: x["rank"])
    return out


def _load(sess=None):
    if "rows" not in _cache:
        text = fetch(URL, sess=sess, timeout=45).content.decode("utf-8", "replace")
        _cache["rows"] = list(csv.reader(io.StringIO(text)))
    return _cache["rows"]


def clear_cache():
    _cache.clear()


def fetch_draft(fmt, sess=None, board=None):
    """board=None uses fmt; board='superflex' pulls the superflex control."""
    want = board or fmt
    boards = _split_boards(_load(sess))
    if want not in boards:
        raise RuntimeError(
            f"Ringer sheet has no {want} board (found: {sorted(boards)})")
    players = _parse_board(boards[want])
    if len(players) < 100:
        raise RuntimeError(f"Ringer {want}: only {len(players)} rows parsed")
    updated = None
    for row in _load(sess)[:3]:
        if row and row[0].strip().lower().startswith("updated"):
            updated = row[0].split(":", 1)[-1].strip()
    return {
        "players": players,
        "meta": {"count": len(players), "board": want, "updated": updated},
        "tags": tags(qb="superflex") if want == "superflex" else tags(),
    }
