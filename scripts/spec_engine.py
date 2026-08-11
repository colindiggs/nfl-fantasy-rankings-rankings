"""Declarative source engine: fetch + parse a ranking source from a JSON spec.

A spec file in scripts/sources/specs/*.json describes how to pull one source —
no Python required. Schema:

{
  "source": "myranker",                      // unique key
  "label": "My Ranker",                      // optional display name for the site
  "draft": {                                 // and/or "weekly"
    "type": "json" | "csv" | "regex",
    "url": "https://... {season} {week} {param}",
    "params_by_format": {                    // which formats exist + URL params
      "standard": {"param": "std"},
      "half_ppr": {"param": "half"},
      "ppr": {"param": "ppr"}
    },
    "headers": {"api-key": "..."},           // optional extra request headers

    // type json:
    "items": "data.players",                 // dot path to the list
    "fields": {"rank": "rank", "name": "player.name",
               "pos": "position", "team": "team"},   // rank optional if sort_by
    "sort_by": "adp",                        // optional: order by this numeric field
                                             // and assign rank 1..N

    // type csv:
    "columns": {"rank": 0, "name": 1, "team": 2, "pos": 3},  // -1 = absent

    // type regex:
    "pattern": "...",                        // finditer over the page
    "groups": {"rank": 1, "name": 2, "pos": 3, "team": 4},

    "min_players": 50                        // optional validation floor
  }
}
"""
import csv
import html as htmllib
import io
import json
import re
from pathlib import Path

from common import VALID_POS, fetch, get_logger, normalize_pos

log = get_logger("spec_engine")

SPEC_DIR = Path(__file__).resolve().parent / "sources" / "specs"


def load_specs():
    specs = {}
    if not SPEC_DIR.exists():
        return specs
    for f in sorted(SPEC_DIR.glob("*.json")):
        try:
            spec = json.loads(f.read_text(encoding="utf-8"))
            specs[spec["source"]] = spec
        except Exception as e:
            log.warning("bad spec %s: %s", f.name, e)
    return specs


def _dig(obj, path):
    if path is None:
        return None
    if path == "":  # root
        return obj
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)]
        else:
            return None
    return obj


def _clean(row):
    name = (row.get("name") or "").strip()
    if not name:
        return None
    raw = (row.get("pos") or "").strip().upper() or None
    pos = normalize_pos(raw)
    team = (row.get("team") or "").strip().upper() or None
    out = {"rank": row["rank"], "name": htmllib.unescape(name), "team": team, "pos": pos}
    if raw and not pos:
        # e.g. IDP labels (LB/DL/DB) — kept so we can tell an IDP board apart
        # from a board that simply failed to report positions
        out["pos_raw"] = raw
    return out


def _parse_json(cfg, resp):
    items = _dig(resp.json(), cfg["items"]) or []
    fields = cfg["fields"]
    rows = []
    for it in items:
        row = {k: _dig(it, v) for k, v in fields.items()}
        if cfg.get("sort_by"):
            try:
                row["_sort"] = float(_dig(it, cfg["sort_by"]))
            except (TypeError, ValueError):
                continue
        rows.append(row)
    if cfg.get("sort_by"):
        rows.sort(key=lambda r: r["_sort"])
        for i, r in enumerate(rows):
            r["rank"] = i + 1
    out = []
    for r in rows:
        try:
            r["rank"] = int(r["rank"])
        except (TypeError, ValueError):
            continue
        c = _clean(r)
        if c:
            out.append(c)
    return out


def _parse_csv(cfg, resp):
    cols = cfg["columns"]
    out = []
    text = resp.content.decode(cfg.get("encoding", "utf-8"), errors="replace")
    for row in csv.reader(io.StringIO(text)):
        try:
            rank = int(row[cols["rank"]].strip())
        except (ValueError, IndexError):
            continue
        def col(key):
            i = cols.get(key, -1)
            return row[i] if 0 <= i < len(row) else None
        c = _clean({"rank": rank, "name": col("name"), "team": col("team"), "pos": col("pos")})
        if c:
            out.append(c)
    return out


def _parse_regex(cfg, resp):
    g = cfg["groups"]
    out = []
    for m in re.finditer(cfg["pattern"], resp.text, re.DOTALL | re.IGNORECASE):
        def grp(key):
            i = g.get(key, 0)
            return m.group(i) if i else None
        try:
            rank = int(grp("rank"))
        except (TypeError, ValueError):
            continue
        c = _clean({"rank": rank, "name": grp("name"), "team": grp("team"), "pos": grp("pos")})
        if c:
            out.append(c)
    return out


PARSERS = {"json": _parse_json, "csv": _parse_csv, "regex": _parse_regex}


def run(spec, kind, fmt, season=None, week=None, sess=None):
    """Execute spec section ('draft' or 'weekly') for one format."""
    cfg = spec.get(kind)
    if not cfg:
        raise RuntimeError(f"{spec['source']} has no {kind} section")
    params = cfg.get("params_by_format", {})
    if params and fmt not in params:
        raise RuntimeError(f"{spec['source']} does not publish {fmt}")
    subst = dict(params.get(fmt, {}))
    subst.update({"season": season, "week": week, "fmt": fmt})
    url = cfg["url"].format(**subst)
    resp = fetch(url, sess=sess, headers=cfg.get("headers"), timeout=60)
    players = PARSERS[cfg["type"]](cfg, resp)
    # de-dup by rank, keep first
    seen, deduped = set(), []
    for r in sorted(players, key=lambda x: x["rank"]):
        if r["rank"] not in seen:
            seen.add(r["rank"])
            deduped.append(r)
    floor = cfg.get("min_players", 50)
    if len(deduped) < floor:
        raise RuntimeError(
            f"{spec['source']}/{fmt}: only {len(deduped)} players parsed (floor {floor})")
    return {"players": deduped, "meta": {"count": len(deduped), "spec": True}}


def formats_for(spec, kind):
    cfg = spec.get(kind) or {}
    params = cfg.get("params_by_format")
    return list(params) if params else []
