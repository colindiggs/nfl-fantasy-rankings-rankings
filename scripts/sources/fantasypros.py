"""FantasyPros expert-consensus rankings (draft cheatsheets + weekly, all formats)."""
import json
import re

from common import fetch, get_logger

log = get_logger("fantasypros")

DRAFT_URLS = {
    "standard": "https://www.fantasypros.com/nfl/rankings/consensus-cheatsheets.php",
    "half_ppr": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php",
    "ppr": "https://www.fantasypros.com/nfl/rankings/ppr-cheatsheets.php",
}

# Weekly per-position pages. QB/K/DST rankings don't vary by scoring format.
WEEKLY_URLS = {
    "standard": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/te.php",
    },
    "half_ppr": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-te.php",
    },
    "ppr": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/ppr-rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/ppr-wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/ppr-te.php",
    },
}


def _parse_ecr(html):
    m = re.search(r"var ecrData = (\{.*?\});", html, re.DOTALL)
    if not m:
        raise RuntimeError("ecrData not found in page")
    return json.loads(m.group(1))


def _players_from_ecr(data):
    out = []
    for p in data.get("players", []):
        out.append({
            "rank": p["rank_ecr"],
            "name": p["player_name"],
            "team": p.get("player_team_id"),
            "pos": (p.get("player_position_id") or "").upper(),
        })
    out.sort(key=lambda x: x["rank"])
    return out


def fetch_draft(fmt, sess=None):
    html = fetch(DRAFT_URLS[fmt], sess=sess).text
    data = _parse_ecr(html)
    return {"players": _players_from_ecr(data), "meta": {"total_experts": data.get("total_experts"), "last_updated": data.get("last_updated")}}


def fetch_weekly(fmt, sess=None):
    """Weekly positional rankings merged into one list (rank = overall order by position groups is meaningless, so positional ranks only)."""
    players = []
    meta = {}
    for pos, url in WEEKLY_URLS[fmt].items():
        html = fetch(url, sess=sess).text
        data = _parse_ecr(html)
        meta[pos] = {"week": data.get("week"), "total_experts": data.get("total_experts")}
        for p in _players_from_ecr(data):
            p["pos"] = pos
            players.append(p)
    return {"players": players, "meta": meta}
