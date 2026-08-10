"""Underdog Fantasy best-ball ADP via the public BestBallTeamBuilder data feed.

Underdog best ball is half-PPR. Third-party mirror updated daily; validate freshness.
"""
from common import fetch, get_logger

log = get_logger("underdog")

URL = "https://fantasy-slice-data.web.app/player_stacker_data.json"


def fetch_draft(fmt, sess=None):
    if fmt != "half_ppr":
        raise RuntimeError("Underdog best ball is half-PPR only")
    data = fetch(URL, sess=sess, timeout=60).json()
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = [r for r in data
            if isinstance(r, dict) and _num(r.get("adp")) is not None and r.get("overall")]
    out = []
    for r in sorted(rows, key=lambda x: float(x["adp"])):
        pos = (r.get("position") or "").upper() or None
        if pos == "DEF":
            pos = "DST"
        out.append({"rank": len(out) + 1, "name": r.get("player"),
                    "team": r.get("team"), "pos": pos})
        if len(out) >= 350:
            break
    if len(out) < 50:
        raise RuntimeError(f"Underdog feed yielded only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
