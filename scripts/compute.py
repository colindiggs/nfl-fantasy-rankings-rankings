"""Evaluate every captured ranking against actual fantasy points and build site data.

Outputs docs/data/summary.json (leaderboard + per-week metrics) and
docs/data/predraft.json (side-by-side pre-draft rankings for the site).
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from common import (DATA, DOCS, EXTRA_POSITIONS, FORMATS, POSITIONS,
                    SKILL_POSITIONS, get_logger, read_json, write_json)
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

TOP_N = {"QB": 24, "RB": 36, "WR": 48, "TE": 24, "K": 24, "DST": 24}
HIT_N = 12  # top-12 hit rate window


def _scoped(pos_metrics, positions):
    """Average Spearman over a position subset, plus how many positions it used."""
    rhos = [pos_metrics[p]["spearman"] for p in positions
            if p in pos_metrics and pos_metrics[p]["spearman"] is not None]
    if not rhos:
        return None
    return {"avg_spearman": round(sum(rhos) / len(rhos), 4), "positions": len(rhos)}


def scope_scores(pos_metrics):
    """Both leaderboard lenses for one source-week.

    'skill' is QB/RB/WR/TE — every source publishes these, so it stays
    comparable across the whole field and across seasons. 'all' folds in K and
    DST for sources that rank them. Kept separate rather than blended because
    K/DST coverage is patchy and those positions are far more luck-driven;
    the site exposes the choice as a toggle.
    """
    return {"skill": _scoped(pos_metrics, SKILL_POSITIONS),
            "all": _scoped(pos_metrics, POSITIONS)}

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
            matchers, name=p.get("name"), pos=p.get("pos"),
            espn_id=p.get("espn_id"), team=p.get("team"))
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
                scopes = scope_scores(pos_metrics)
                entry = summary["weekly"][fmt].setdefault(source, {"weeks": {}})
                entry["weeks"][str(w)] = {
                    "positions": pos_metrics,
                    "scopes": scopes,
                    # kept for backwards compatibility with the existing site
                    "avg_spearman": scopes["skill"]["avg_spearman"] if scopes["skill"] else None,
                }
        # cumulative score per source, per scope
        summary["leaderboard"]["weekly"][fmt] = {}
        for scope in ("skill", "all"):
            board = []
            for source, entry in summary["weekly"][fmt].items():
                scores = [wk["scopes"][scope]["avg_spearman"] for wk in entry["weeks"].values()
                          if wk["scopes"].get(scope)]
                if not scores:
                    continue
                cum = entry.setdefault("cumulative", {})
                cum[scope] = {"avg_spearman": round(sum(scores) / len(scores), 4),
                              "weeks": len(scores)}
                if scope == "skill":
                    cum["avg_spearman"] = cum[scope]["avg_spearman"]
                    cum["weeks"] = len(scores)
                board.append({"source": source, "score": cum[scope]["avg_spearman"],
                              "weeks": len(scores)})
            board.sort(key=lambda x: -x["score"])
            summary["leaderboard"]["weekly"][fmt][scope] = board

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
                    wk_metrics = {}
                    for pos in POSITIONS:
                        m = evaluate(by_pos[pos], cpts, TOP_N[pos])
                        if m:
                            wk_metrics[pos] = m
                    sc = scope_scores(wk_metrics)
                    src_entry["series"][str(w)] = (
                        sc["skill"]["avg_spearman"] if sc["skill"] else None)
                    src_entry.setdefault("series_all", {})[str(w)] = (
                        sc["all"]["avg_spearman"] if sc["all"] else None)
                cpts = cum_pts(latest, fmt)
                pos_metrics = {}
                for pos in POSITIONS:
                    m = evaluate(by_pos[pos], cpts, TOP_N[pos])
                    if m:
                        pos_metrics[pos] = m
                overall = evaluate(ordered, cpts, PREDRAFT_TOP_OVERALL) if ordered else None
                scopes = scope_scores(pos_metrics)
                src_entry["latest"] = {"through_week": latest, "overall": overall,
                                       "positions": pos_metrics, "scopes": scopes}
                for scope, sc in scopes.items():
                    if sc:
                        board.append({
                            "scope": scope,
                            "source": source,
                            "score": sc["avg_spearman"],
                            "overall": overall["spearman"] if overall else None,
                            "positions": sc["positions"],
                            "through_week": latest,
                        })
            summary["predraft"][fmt][source] = src_entry
        summary["leaderboard"]["predraft"][fmt] = {}
        for scope in ("skill", "all"):
            rows = sorted((r for r in board if r["scope"] == scope), key=lambda x: -x["score"])
            summary["leaderboard"]["predraft"][fmt][scope] = rows

    seen = set()
    for fmt in FORMATS:
        seen.update(summary["weekly"][fmt])
        seen.update(summary["predraft"][fmt])
    summary["labels"] = source_labels(seen)

    write_json(DOCS / "data" / "summary.json", summary)
    log.info("summary.json written (%d weeks evaluated)", len(weeks))

    # ---- consensus pre-draft board for the site (top 200, per-source ranks)
    # Players ranked by some sources but not others: a player's consensus rank is
    # the mean of ranks from the sources that DO rank him, shown with coverage
    # (n of N sources) so thin consensus is visible rather than hidden. Players
    # need >= 2 ranking sources to appear.
    SHOW_POS = ("QB", "RB", "WR", "TE", "K", "DST")
    comparison = {"season": season, "formats": {}}
    for fmt in FORMATS:
        boards = {}
        for (source, f2), payload in predraft.items():
            if f2 != fmt:
                continue
            if sum(1 for p in payload["players"] if p["rank"] == 1) > 1:
                continue  # positional-only board — no overall order
            board = {}
            for p in sorted(payload["players"], key=lambda x: x["rank"]):
                pid = p.get("sleeper_id")
                if pid and p.get("pos") in SHOW_POS and pid not in board:
                    board[pid] = {"rank": len(board) + 1, "p": p}
                if len(board) >= 200:
                    break
            boards[source] = board
        players = {}
        for source, board in boards.items():
            for pid, entry in board.items():
                db = players_db.get(pid, {})
                rec = players.setdefault(pid, {
                    "id": pid,
                    "name": db.get("name") or entry["p"]["name"],
                    "pos": db.get("pos") or entry["p"]["pos"],
                    "team": db.get("team") or entry["p"].get("team"),
                    "ranks": {}})
                rec["ranks"][source] = entry["rank"]
        rows = []
        for rec in players.values():
            ranks = list(rec["ranks"].values())
            if len(ranks) < 2:
                continue
            rec["avg"] = round(sum(ranks) / len(ranks), 1)
            rec["n"] = len(ranks)
            rec["min"] = min(ranks)
            rec["max"] = max(ranks)
            rows.append(rec)
        rows.sort(key=lambda r: (r["avg"], -r["n"]))
        comparison["formats"][fmt] = {
            "sources": sorted(boards, key=lambda s: len(boards[s]), reverse=True),
            "players": rows[:200],
        }
    write_json(DOCS / "data" / "predraft.json", comparison)
    log.info("predraft.json written")


if __name__ == "__main__":
    main()
