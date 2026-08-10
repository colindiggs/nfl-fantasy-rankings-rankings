"""PFF fantasy draft rankings via their public consumer API.

The api-key is PFF's own public client credential shipped in their JS bundle;
it may rotate — if this starts 403ing, re-extract CONSUMER_API_KEY from the bundle.
Single board with PPR-flavored ADP; mapped to ppr.
"""
from common import fetch, get_logger

log = get_logger("pff")

URL = "https://consumer-api.pff.com/football/v1/fantasy/rankings"
API_KEY = "0f6ca1f4-79d4-11ee-b962-0242ac120002"


def fetch_draft(fmt, sess=None):
    if fmt != "ppr":
        raise RuntimeError("PFF publishes one draft board (PPR-flavored) — ppr only")
    data = fetch(URL, sess=sess, headers={"api-key": API_KEY}).json()
    out = []
    for r in data.get("rankings", []):
        rank = (r.get("rank") or {}).get("current")
        if rank is None:
            continue
        out.append({
            "rank": rank,
            "name": f"{r.get('firstName', '')} {r.get('lastName', '')}".strip(),
            "team": r.get("teamAbbreviation"),
            "pos": r.get("position"),
        })
    out.sort(key=lambda x: x["rank"])
    if len(out) < 50:
        raise RuntimeError(f"PFF returned only {len(out)} players — api-key may have rotated")
    return {"players": out, "meta": {"count": len(out)}}
