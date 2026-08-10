"""Evaluate every captured ranking against actual fantasy points and build site data.

Outputs docs/data/summary.json (leaderboard + per-week metrics) and
docs/data/predraft.json (side-by-side pre-draft rankings for the site).
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from common import DATA, DOCS, FORMATS, POSITIONS, get_logger, read_json, write_json
import sleeper
import spec_engine

log = get_logger("compute")

# display names for code-adapter sources; spec sources carry their own "label",
# and anything else (e.g. manual inbox boards) gets its slug prettified
CODE_LABELS = {
    "fantasypros": "FantasyPros", "espn": "ESPN", "cbs": "CBS", "nfl": "NFL.com",
    "yahoo": "Yahoo", "pff": "PFF", "mfl": "MyFantasyLeague (ADP)",
    "sharks": "FantasySharks", "fftoday": "FFToday", "walter": "WalterFootball",
    "draftsharks": "Draft Sharks",
}


def source_labels(seen_sources):
    labels = dict(CODE_LABELS)
    for name, spec in spec_engine.load_specs().items():
        if spec.get("label"):
            labels[name] = spec["label"]
    for s in seen_sources:
        if s not in labels:
            labels[s] = s.replace("-", " ").replace("_", " ").title()
    return labels

TOP_N = {"QB": 24, "RB": 36, "WR": 48, "TE": 24}
HIT_N = 12  # top-12 hit rate window

PREDRAFT_TOP_OVERALL = 150


def _avg_rank(values):
    """Ranks (1-based, ties averaged) for a list of values, higher value = better rank."""
    order = sorted(range(len(values)), key=lambda i: -values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(pred_ranks, actual_points):
    """Spearman rho between a predicted rank order and actual points."""
    n = len(pred_ranks)
    if n < 3:
        return None
    actual_ranks = _avg_rank(actual_points)
    mp = sum(pred_ranks) / n
    ma = sum(actual_ranks) / n
    num = sum((p - mp) * (a - ma) for p, a in zip(pred_ranks, actual_ranks))
    dp = sum((p - mp) ** 2 for p in pred_ranks) ** 0.5
    da = sum((a - ma) ** 2 for a in actual_ranks) ** 0.5
    if dp == 0 or da == 0:
        return None
    # both rank sequences use 1 = best, so a perfect prediction gives +1
    return round(num / (dp * da), 4)


def evaluate(players, points_by_pid, top_n, hit_n=HIT_N):
    """players: ordered [{sleeper_id,...}]; points_by_pid: pid -> float."""
    pool = players[:top_n]
    matched = [(i + 1, points_by_pid.get(p.get("sleeper_id"), 0.0) if p.get("sleeper_id") else 0.0)
               for i, p in enumerate(pool)]
    unmatched = sum(1 for p in pool if not p.get("sleeper_id"))
    if len(matched) < 3:
        return None
    pred_ranks = [m[0] for m in matched]
    pts = [m[1] for m in matched]
    rho = spearman(pred_ranks, pts)
    actual_ranks = _avg_rank(pts)
    mae = sum(abs(p - a) for p, a in zip(pred_ranks, actual_ranks)) / len(pred_ranks)
    hits = sum(1 for p, a in zip(pred_ranks, actual_ranks) if p <= hit_n and a <= hit_n)
    return {
        "spearman": rho,
        "rank_mae": round(mae, 2),
        "hit_rate": round(hits / min(hit_n, len(pred_ranks)), 3),
        "n": len(matched),
        "unmatched": unmatched,
    }


def attach_ids(players, matchers):
    for p in players:
        pid = sleeper.match_player(
            matchers, name=p.get("name"), pos=p.get("pos"), espn_id=p.get("espn_id"))
        p["sleeper_id"] = pid
        if pid and not p.get("pos"):
            p["pos"] = matchers["db"][pid]["pos"]
    return players


def pos_lists(players):
    """Split an ordered ranking into per-position ordered lists."""
    out = {pos: [] for pos in POSITIONS}
    for p in sorted(players, key=lambda x: x["rank"]):
        if p.get("pos") in out:
            out[p["pos"]].append(p)
    return out


def load_rankings(season, scope):
    """-> {(source, fmt): payload}"""
    d = DATA / "rankings" / str(season) / scope
    out = {}
    if not d.exists():
        return out
    for f in d.glob("*.json"):
        m = re.match(r"(.+?)_(standard|half_ppr|ppr)\.json$", f.name)
        if m:
            out[(m.group(1), m.group(2))] = read_json(f)
    return out


def main():
    state = sleeper.get_state()
    season = int(state["season"])
    players_db = sleeper.load_players()
    matchers = sleeper.build_matchers(players_db)

    # ---- actual points per completed week
    actual_weeks = {}
    adir = DATA / "actuals" / str(season)
    if adir.exists():
        for f in sorted(adir.glob("week*.json")):
            payload = read_json(f)
            actual_weeks[int(payload["week"])] = payload["points"]
    weeks = sorted(actual_weeks)

    def pts_for(week, fmt):
        return {pid: v.get(fmt, 0.0) for pid, v in actual_weeks[week].items()}

    def cum_pts(through_week, fmt):
        agg = {}
        for w in weeks:
            if w > through_week:
                break
            for pid, v in actual_weeks[w].items():
                agg[pid] = agg.get(pid, 0.0) + v.get(fmt, 0.0)
        return agg

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": season,
        "weeks_evaluated": weeks,
        "weekly": {},     # fmt -> source -> {weeks: {w: {...}}, cumulative: {...}}
        "predraft": {},   # fmt -> source -> {through_week: {...}} evaluated at latest week
        "leaderboard": {"weekly": {}, "predraft": {}},
    }

    # ---- weekly rankings vs weekly points
    for fmt in FORMATS:
        summary["weekly"][fmt] = {}
        for w in weeks:
            rankings = load_rankings(season, f"week{w:02d}")
            for (source, f2), payload in rankings.items():
                if f2 != fmt:
                    continue
                plist = attach_ids(payload["players"], matchers)
                by_pos = pos_lists(plist)
                pts = pts_for(w, fmt)
                pos_metrics = {}
                for pos in POSITIONS:
                    m = evaluate(by_pos[pos], pts, TOP_N[pos])
                    if m:
                        pos_metrics[pos] = m
                if not pos_metrics:
                    continue
                rhos = [m["spearman"] for m in pos_metrics.values() if m["spearman"] is not None]
                entry = summary["weekly"][fmt].setdefault(source, {"weeks": {}})
                entry["weeks"][str(w)] = {
                    "positions": pos_metrics,
                    "avg_spearman": round(sum(rhos) / len(rhos), 4) if rhos else None,
                }
        # cumulative score per source
        board = []
        for source, entry in summary["weekly"][fmt].items():
            scores = [wk["avg_spearman"] for wk in entry["weeks"].values() if wk["avg_spearman"] is not None]
            if scores:
                entry["cumulative"] = {"avg_spearman": round(sum(scores) / len(scores), 4), "weeks": len(scores)}
                board.append({"source": source, "score": entry["cumulative"]["avg_spearman"], "weeks": len(scores)})
        board.sort(key=lambda x: -x["score"])
        summary["leaderboard"]["weekly"][fmt] = board

    # ---- pre-draft rankings vs cumulative season points
    latest = weeks[-1] if weeks else None
    predraft = load_rankings(season, "predraft")
    for fmt in FORMATS:
        summary["predraft"][fmt] = {}
        board = []
        for (source, f2), payload in predraft.items():
            if f2 != fmt:
                continue
            plist = attach_ids(payload["players"], matchers)
            # positional-only boards (e.g. per-position lists) repeat rank 1
            positional_only = sum(1 for p in plist if p["rank"] == 1) > 1
            src_entry = {"captured_at": payload.get("captured_at"), "series": {},
                         "positional_only": positional_only}
            if latest:
                by_pos = pos_lists(plist)
                ordered = None if positional_only else sorted(
                    (p for p in plist if p.get("pos") in POSITIONS), key=lambda x: x["rank"])
                for w in weeks:
                    cpts = cum_pts(w, fmt)
                    pos_rhos = []
                    for pos in POSITIONS:
                        m = evaluate(by_pos[pos], cpts, TOP_N[pos])
                        if m and m["spearman"] is not None:
                            pos_rhos.append(m["spearman"])
                    src_entry["series"][str(w)] = (
                        round(sum(pos_rhos) / len(pos_rhos), 4) if pos_rhos else None)
                cpts = cum_pts(latest, fmt)
                pos_metrics = {}
                for pos in POSITIONS:
                    m = evaluate(by_pos[pos], cpts, TOP_N[pos])
                    if m:
                        pos_metrics[pos] = m
                overall = evaluate(ordered, cpts, PREDRAFT_TOP_OVERALL) if ordered else None
                src_entry["latest"] = {"through_week": latest, "overall": overall, "positions": pos_metrics}
                rhos = [m["spearman"] for m in pos_metrics.values() if m["spearman"] is not None]
                if rhos:
                    board.append({
                        "source": source,
                        "score": round(sum(rhos) / len(rhos), 4),
                        "overall": overall["spearman"] if overall else None,
                        "positions": len(rhos),
                        "through_week": latest,
                    })
            summary["predraft"][fmt][source] = src_entry
        board.sort(key=lambda x: -x["score"])
        summary["leaderboard"]["predraft"][fmt] = board

    seen = set()
    for fmt in FORMATS:
        seen.update(summary["weekly"][fmt])
        seen.update(summary["predraft"][fmt])
    summary["labels"] = source_labels(seen)

    write_json(DOCS / "data" / "summary.json", summary)
    log.info("summary.json written (%d weeks evaluated)", len(weeks))

    # ---- side-by-side predraft comparison for the site
    comparison = {"season": season, "formats": {}}
    for fmt in FORMATS:
        cols = {}
        for (source, f2), payload in predraft.items():
            if f2 != fmt:
                continue
            if sum(1 for p in payload["players"] if p["rank"] == 1) > 1:
                continue  # positional-only board — no overall order to show
            cols[source] = [
                {"rank": p["rank"], "name": p["name"], "pos": p.get("pos"), "team": p.get("team")}
                for p in sorted(payload["players"], key=lambda x: x["rank"])
                if p.get("pos") in ("QB", "RB", "WR", "TE", "K", "DST")
            ][:100]
        comparison["formats"][fmt] = cols
    write_json(DOCS / "data" / "predraft.json", comparison)
    log.info("predraft.json written")


if __name__ == "__main__":
    main()
