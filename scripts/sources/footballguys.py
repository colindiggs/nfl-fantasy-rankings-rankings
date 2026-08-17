"""Footballguys draft rankings.

One of the oldest continuously published fantasy staffs, and a name the
benchmark was conspicuously missing. The board is a staff consensus over ~530
players including kickers and defenses, published with their own tiers.

Only one scoring format is reachable. The site's scoring presets ("Standard
(1 PPR)", "Standard (0 PPR)") are applied per session rather than by URL:
requesting `?league=preset:zero-ppr-standard` returns byte-identical numbers
to the default board, so a "standard" capture would in fact be the PPR board
relabelled. We take the default board as PPR and publish nothing else rather
than invent a second format from the same numbers.

Names come from the player-profile URL, which is stable and unabbreviated;
the visible cell is HTML- and URL-escaped ("Ja%26apos%3BMarr").
"""
import html as html_mod
import re
from urllib.parse import unquote

from common import fetch, get_logger
import teams as teams_mod

log = get_logger("footballguys")

URL = "https://www.footballguys.com/rankings"

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_RANK = re.compile(r'<td[^>]*class="[^"]*\brank\b[^"]*"[^>]*>\s*(\d+)\s*</td>')
_NAME = re.compile(r"/player/([^/\"']+)/")
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
# the position cell reads "RB1", "WR12", "PK3", "Def2"
_POSRANK = re.compile(r"^(QB|RB|WR|TE|PK|K|DEF|DST)\s*\d+$", re.I)
_POS_MAP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
            "PK": "K", "K": "K", "DEF": "DST", "DST": "DST"}
TEAMS = re.compile(r"\b([A-Z]{2,3})\b(?:\s+\d+)?\s*$")


def _text(chunk):
    return re.sub(r"\s+", " ", html_mod.unescape(_TAG.sub(" ", chunk))).strip()


def _clean_name(raw):
    # "Ja%26apos%3BMarr+Chase" -> "Ja'Marr Chase"
    return html_mod.unescape(unquote(raw.replace("+", " "))).strip()


def fetch_draft(fmt, sess=None):
    if fmt != "ppr":
        return None
    resp = fetch(URL, sess=sess)
    body = resp.text
    players = []
    for row in _ROW.findall(body):
        mr = _RANK.search(row)
        mn = _NAME.search(row)
        if not (mr and mn):
            continue
        cells = [_text(c) for c in _CELL.findall(row)]
        pos = None
        for c in cells:
            if _POSRANK.match(c):
                pos = _POS_MAP.get(re.sub(r"\d+$", "", c).strip().upper())
                break
        name = _clean_name(mn.group(1))
        # Defenses carry no position-rank cell, so they arrive unlabelled and
        # would be dropped as unknown. They are recognisable by being a team:
        # resolve through teams.py rather than guessing from the rank range.
        if not pos and teams_mod.resolve_dst(name=name):
            pos = "DST"
        # team and bye trail the name in its own cell: "Jahmyr Gibbs DET 5"
        team = None
        for c in cells:
            if name.split()[-1] in c and "Drafted by" not in c:
                m = TEAMS.search(c)
                if m:
                    team = m.group(1)
                break
        players.append({"rank": int(mr.group(1)), "name": name,
                        "team": team, "pos": pos})
    # one row per rank, first wins
    seen, out = set(), []
    for p in sorted(players, key=lambda x: x["rank"]):
        if p["rank"] in seen:
            continue
        seen.add(p["rank"])
        out.append(p)
    if len(out) < 200:
        raise RuntimeError(f"Footballguys returned only {len(out)} rows — layout may have changed")
    missing = sum(1 for p in out if not p["pos"])
    log.info("Footballguys: %d players (%d without a position)", len(out), missing)
    return {"players": out, "meta": {"source_url": URL}}
