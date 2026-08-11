"""Rank-value curves: what a positional rank slot has historically been worth.

FantasyPros scores experts in POINTS space rather than rank space. Each rank is
assigned the fantasy points that rank slot has historically produced, and the
error is |points implied by the expert's rank - points actually scored|. That
weights a miss at RB2 far more heavily than one at RB45, which rank correlation
treats identically.

This builds those curves from our own backfilled actuals:

    curve[fmt][pos][rank] = mean points scored by the player who FINISHED at
                            that positional rank, averaged over the seasons in
                            the window

FantasyPros use a rolling 3-year average. We keep several windows so the
tradeoff stays visible — 3 years tracks the current scoring environment,
all-history is smoother but drags in older, lower-scoring seasons.

Weekly and season-long curves are separate: a weekly RB1 scores ~25 points, a
season-long RB1 ~300. They are not interchangeable.
"""
import sys
from collections import defaultdict

from common import DATA, DOCS, FORMATS, POSITIONS, get_logger, read_json, write_json
import sleeper

log = get_logger("rankvalue")

WINDOWS = {"3yr": 3, "5yr": 5, "all": None}

MAX_RANK = {"QB": 40, "RB": 70, "WR": 90, "TE": 40, "K": 36, "DST": 36}


def season_dirs():
    d = DATA / "actuals"
    if not d.exists():
        return []
    return sorted(int(p.name) for p in d.iterdir() if p.is_dir() and p.name.isdigit())


def load_actuals(season):
    """-> {week: {pid: {fmt: pts}}}"""
    out = {}
    d = DATA / "actuals" / str(season)
    if not d.exists():
        return out
    for f in sorted(d.glob("week*.json")):
        payload = read_json(f)
        out[int(payload["week"])] = payload["points"]
    return out


def _ranked_points(points_by_pid, pos_of, pos, fmt):
    """Points scored by players at this position, best first."""
    vals = [v.get(fmt, 0.0) or 0.0 for pid, v in points_by_pid.items()
            if pos_of.get(pid) == pos]
    vals.sort(reverse=True)
    return vals


def build(seasons, pos_of):
    """-> {"weekly": {fmt: {pos: {rank: [pts per season-week]}}}, "season": ...}"""
    weekly = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    seasonal = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for season in seasons:
        weeks = load_actuals(season)
        if not weeks:
            continue
        totals = defaultdict(lambda: defaultdict(float))
        for _w, pts in weeks.items():
            for pid, v in pts.items():
                for fmt in FORMATS:
                    totals[fmt][pid] += v.get(fmt, 0.0) or 0.0
        for fmt in FORMATS:
            for pos in POSITIONS:
                cap = MAX_RANK[pos]
                for _w, pts in weeks.items():
                    vals = _ranked_points(pts, pos_of, pos, fmt)
                    for i, v in enumerate(vals[:cap]):
                        weekly[fmt][pos][i + 1].append(v)
                svals = sorted((v for pid, v in totals[fmt].items()
                                if pos_of.get(pid) == pos), reverse=True)
                for i, v in enumerate(svals[:cap]):
                    seasonal[fmt][pos][i + 1].append(v)
    return {"weekly": weekly, "season": seasonal}


def _mean(xs):
    return round(sum(xs) / len(xs), 2) if xs else None


def curves_for(seasons, pos_of):
    raw = build(seasons, pos_of)
    out = {}
    for kind in ("weekly", "season"):
        out[kind] = {}
        for fmt in FORMATS:
            out[kind][fmt] = {}
            for pos in POSITIONS:
                per_rank = raw[kind][fmt][pos]
                if not per_rank:
                    continue
                out[kind][fmt][pos] = {str(r): _mean(v)
                                       for r, v in sorted(per_rank.items())}
    return out


def points_for_rank(curve, kind, fmt, pos, rank):
    """Value of a rank slot, flat-extrapolating past the end of the curve."""
    table = ((curve.get(kind) or {}).get(fmt) or {}).get(pos)
    if not table:
        return None
    if str(rank) in table:
        return table[str(rank)]
    ranks = sorted(int(r) for r in table)
    if not ranks:
        return None
    return table[str(ranks[-1] if rank > ranks[-1] else ranks[0])]


def main():
    players_db = sleeper.load_players()
    pos_of = {pid: p["pos"] for pid, p in players_db.items() if p.get("pos")}
    seasons = season_dirs()
    if not seasons:
        print("no actuals captured yet")
        return
    latest = seasons[-1]
    payload = {"seasons_available": seasons, "windows": {}}
    for name, n in WINDOWS.items():
        window = seasons if n is None else [s for s in seasons if s > latest - n]
        payload["windows"][name] = {
            "seasons": window,
            "curves": curves_for(window, pos_of),
        }
        log.info("curve %-4s built from %d seasons: %s", name, len(window), window)
    payload["default_window"] = "3yr"   # FantasyPros' choice
    write_json(DOCS / "data" / "rankvalue.json", payload)
    write_json(DATA / "rankvalue.json", payload)
    log.info("rankvalue.json written (%d seasons available)", len(seasons))


if __name__ == "__main__":
    main()
