"""NFFC / NFC high-stakes ADP (nfc.shgn.com).

Real draft position from the National Fantasy Football Championship — entry
fees run from a few hundred dollars into five figures, so this is the sharpest
market board the project captures. Every other ADP source here is either free
mock drafts (FF Calculator), a host's aggregate (MyFantasyLeague,
FantasySharks) or best ball (Underdog); none of them cost the drafter anything
to be wrong.

The page renders client-side; the table body comes from a POST to
/adp.data.php returning HTML rows. robots.txt allows all crawling.

Scoring: NFFC is full PPR, but with 6-point passing touchdowns and 0.05 per
passing yard, which is richer for quarterbacks than our PPR baseline. That
would normally be a reason to hold the board at arm's length — except the
board itself says otherwise. Sharp high-stakes drafters wait on quarterbacks
harder than the field does, and the premium does not show up where the scoring
predicts:

    QB1..QB4 overall pick     NFFC 28, 58, 59, 61
                              our PPR consensus 26, 39, 42, 47

QB4 at 61 sits inside the 36-67 range the peer boards occupy, so the board is
comparable as a 1QB PPR ADP. Recorded here because the next person to look at
the scoring rules will have the same doubt.
"""
import re

from common import fetch, get_logger

log = get_logger("nffc")

URL = "https://nfc.shgn.com/adp.data.php"
PAGE = "https://nfc.shgn.com/adp/football"

# draft_type -1 = all non-superflex drafts; num_teams 12 = the common size
FORM = {
    "team_id": "0", "time_period": "", "from_date": "", "to_date": "",
    "num_teams": "12", "draft_type": "-1", "sport": "football",
    "position": "", "league_teams": "0", "as_board": "",
}

# NFFC's own position codes
POS_MAP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
           "TK": "K", "TDSP": "DST", "K": "K", "DEF": "DST"}

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _text(html):
    return re.sub(r"\s+", " ", _TAG.sub("", html)).strip()


def fetch_draft(fmt, sess=None):
    if fmt != "ppr":
        return None
    resp = fetch(URL, sess=sess, method="POST", data=FORM,
                 headers={"X-Requested-With": "XMLHttpRequest", "Referer": PAGE})
    html = resp.text
    players, skipped, dropped_k = [], 0, []
    for row in _ROW.findall(html):
        cells = [_text(c) for c in _CELL.findall(row)]
        # rank | name | team | position | ADP | min | max | ... | picks
        if len(cells) < 5 or not cells[0].isdigit():
            continue
        pos = POS_MAP.get(cells[3].split("/")[0].strip().upper())
        if not pos:
            skipped += 1
            continue
        # NFFC names kickers after their team ("San Francisco 49ers", TK) —
        # the same string it uses for that team's defense. Defences resolve by
        # name here (see teams.py), so keeping these rows would file every
        # kicker as a defense and score it against the wrong player entirely.
        # The feed carries no kicker identity to recover, so drop them.
        if pos == "K":
            dropped_k.append(cells[1])
            continue
        players.append({"rank": int(cells[0]), "name": cells[1],
                        "team": cells[2] or None, "pos": pos})
    players.sort(key=lambda p: p["rank"])
    if len(players) < 150:
        raise RuntimeError(f"NFFC ADP returned only {len(players)} rows — layout may have changed")
    log.info("NFFC ADP: %d players (%d unknown position, %d team-named kickers dropped)",
             len(players), skipped, len(dropped_k))
    return {"players": players, "meta": {"source_url": PAGE, "num_teams": 12,
                                         "draft_type": "all non-superflex"}}
