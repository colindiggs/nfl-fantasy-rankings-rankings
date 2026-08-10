"""Fantasy Football Calculator ADP — crowd draft data, free JSON API, all formats."""
from common import fetch, get_logger

log = get_logger("ffcalc")

SLUGS = {"standard": "standard", "half_ppr": "half-ppr", "ppr": "ppr"}

URL = "https://fantasyfootballcalculator.com/api/v1/adp/{slug}?teams=12&year={season}"


def fetch_draft(fmt, season, sess=None):
    data = fetch(URL.format(slug=SLUGS[fmt], season=season), sess=sess).json()
    players = data.get("players", [])
    out = []
    for i, p in enumerate(sorted(players, key=lambda x: x["adp"])):
        if p.get("position") in ("DEF", "PK"):
            pos = {"DEF": "DST", "PK": "K"}[p["position"]]
        else:
            pos = p.get("position")
        out.append({"rank": i + 1, "name": p["name"], "team": p.get("team"), "pos": pos})
    if len(out) < 50:
        raise RuntimeError(f"FFC returned only {len(out)} players")
    meta = data.get("meta", {})
    return {"players": out, "meta": {"total_drafts": meta.get("total_drafts"), "end_date": meta.get("end_date")}}
