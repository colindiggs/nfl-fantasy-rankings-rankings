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

# Weekly per-position pages. QB/K/DST rankings don't vary by scoring format, so
# all three formats point at the same page for those.
WEEKLY_URLS = {
    "standard": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/te.php",
        "K": "https://www.fantasypros.com/nfl/rankings/k.php",
        "DST": "https://www.fantasypros.com/nfl/rankings/dst.php",
    },
    "half_ppr": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/half-point-ppr-te.php",
        "K": "https://www.fantasypros.com/nfl/rankings/k.php",
        "DST": "https://www.fantasypros.com/nfl/rankings/dst.php",
    },
    "ppr": {
        "QB": "https://www.fantasypros.com/nfl/rankings/qb.php",
        "RB": "https://www.fantasypros.com/nfl/rankings/ppr-rb.php",
        "WR": "https://www.fantasypros.com/nfl/rankings/ppr-wr.php",
        "TE": "https://www.fantasypros.com/nfl/rankings/ppr-te.php",
        "K": "https://www.fantasypros.com/nfl/rankings/k.php",
        "DST": "https://www.fantasypros.com/nfl/rankings/dst.php",
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


def _archived(url, season=None, week=None):
    """FantasyPros serves historical ECR from the same pages via ?year=&week=."""
    params = []
    if week is not None:
        params.append(f"week={week}")
    if season is not None:
        params.append(f"year={season}")
    return f"{url}?{'&'.join(params)}" if params else url


def fetch_draft(fmt, sess=None, season=None):
    """Pre-draft board. Passing season pulls that year's frozen preseason ECR."""
    html = fetch(_archived(DRAFT_URLS[fmt], season=season), sess=sess).text
    data = _parse_ecr(html)
    if season and str(data.get("year")) != str(season):
        raise RuntimeError(
            f"asked for {season} draft board, page returned {data.get('year')}")
    return {"players": _players_from_ecr(data),
            "meta": {"total_experts": data.get("total_experts"),
                     "last_updated": data.get("last_updated"),
                     "year": data.get("year")}}


def fetch_weekly(fmt, sess=None, season=None, week=None):
    """Weekly positional rankings merged into one list.

    Ranks restart at 1 per position — there is no meaningful cross-position
    order in a weekly board. Passing season/week pulls the archived ECR as it
    stood that week, which is what makes historical backfill possible.
    """
    players = []
    meta = {}
    for pos, url in WEEKLY_URLS[fmt].items():
        html = fetch(_archived(url, season=season, week=week), sess=sess).text
        data = _parse_ecr(html)
        # guard against the site quietly serving the current week instead
        if week is not None and str(data.get("week")) != str(week):
            raise RuntimeError(
                f"{pos}: asked for week {week}, page returned {data.get('week')}")
        if season is not None and str(data.get("year")) != str(season):
            raise RuntimeError(
                f"{pos}: asked for {season}, page returned {data.get('year')}")
        meta[pos] = {"week": data.get("week"), "year": data.get("year"),
                     "total_experts": data.get("total_experts")}
        for p in _players_from_ecr(data):
            p["pos"] = pos
            players.append(p)
    return {"players": players, "meta": meta}
