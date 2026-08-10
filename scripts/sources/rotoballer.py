"""RotoBaller expert consensus rankings — clean WordPress JSON API, all formats."""
from common import fetch, get_logger

log = get_logger("rotoballer")

SLUGS = {"standard": "standard", "half_ppr": "half-ppr", "ppr": "ppr"}

URL = ("https://www.rotoballer.com/wp-json/rb/v1/rankings"
       "?league=Overall&perPage=600&spreadsheet={slug}")


def fetch_draft(fmt, sess=None):
    data = fetch(URL.format(slug=SLUGS[fmt]), sess=sess).json()
    rows = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for r in rows:
        player = r.get("player") or {}
        name = player.get("name") or r.get("name")
        rank = r.get("rank")
        if not name or rank is None:
            continue
        pos = (r.get("position") or "").upper() or None
        if pos == "DEF":
            pos = "DST"
        out.append({"rank": int(rank), "name": name, "team": r.get("team"), "pos": pos})
    out.sort(key=lambda x: x["rank"])
    if len(out) < 50:
        raise RuntimeError(f"RotoBaller returned only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
