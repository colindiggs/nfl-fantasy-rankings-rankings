"""Evaluate every captured ranking against actual fantasy points and build site data.

Outputs docs/data/summary.json (leaderboard + per-week metrics) and
docs/data/predraft.json (side-by-side pre-draft rankings for the site).
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from common import (DATA, DEFAULT_TAGS, DOCS, EXTRA_POSITIONS, FORMATS,
                    POSITIONS, SKILL_POSITIONS, get_logger, matches_baseline,
                    read_json, write_json)
import rankvalue
import sleeper
import spec_engine

log = get_logger("compute")

# display names for code-adapter sources; spec sources carry their own "label",
# and anything else (e.g. manual inbox boards) gets its slug prettified
CODE_LABELS = {
    "fantasypros": "FantasyPros", "espn": "ESPN", "cbs": "CBS", "nfl": "NFL.com",
    "yahoo": "Yahoo", "pff": "PFF", "mfl": "MyFantasyLeague (ADP)",
    "sharks": "FantasySharks (ADP)", "fftoday": "FFToday",
    "walter": "WalterFootball", "draftsharks": "Draft Sharks",
    "draftsharks-idp": "Draft Sharks (IDP)", "ringer": "The Ringer",
    "ringer-superflex": "The Ringer (Superflex)",
    "ffcalc": "FF Calculator (ADP)", "underdog": "Underdog (Best Ball ADP)",
    "rotoballer": "RotoBaller", "sleeper": "Sleeper (projections)",
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

# sleeper_id -> position, needed to build the "top N by actual points" half of
# each evaluation pool. Populated once from the player DB in main().
POS_OF = {}


# Rank-value curves, loaded once per run. Lets us score in POINTS space the way
# FantasyPros do, not just rank-correlation space.
CURVE = {}


def load_curve():
    CURVE.clear()
    payload = read_json(DATA / "rankvalue.json") or {}
    win = (payload.get("windows") or {}).get(payload.get("default_window", "3yr")) or {}
    CURVE.update(win.get("curves") or {})
    return CURVE


NAME_OF = {}


def load_positions(players_db):
    POS_OF.clear()
    POS_OF.update({pid: p["pos"] for pid, p in players_db.items() if p.get("pos")})
    NAME_OF.clear()
    NAME_OF.update({pid: p.get("name") for pid, p in players_db.items() if p.get("name")})


def short_name(name):
    """'Jahmyr Gibbs' -> 'J. Gibbs'; single-word and team names pass through."""
    if not name:
        return None
    parts = name.split()
    if len(parts) < 2:
        return name
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


MIN_POOL = 8   # a Spearman over fewer players than this is mostly noise


def _scoped(pos_metrics, positions):
    """Average Spearman and Accuracy Gap over a position subset.

    Positions whose scoreable pool fell below MIN_POOL are reported per
    position but left out of the average — a rho computed over five players
    swings wildly and would dominate a six-position mean.
    """
    usable = [p for p in positions
              if p in pos_metrics and pos_metrics[p].get("n", 0) >= MIN_POOL]
    rhos = [pos_metrics[p]["spearman"] for p in usable
            if pos_metrics[p]["spearman"] is not None]
    if not rhos:
        return None
    gaps = [pos_metrics[p]["accuracy_gap"] for p in usable
            if pos_metrics[p].get("accuracy_gap") is not None]
    out = {"avg_spearman": round(sum(rhos) / len(rhos), 4), "positions": len(rhos)}
    if gaps:
        out["accuracy_gap"] = round(sum(gaps) / len(gaps), 2)
    return out


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


def evaluate(players, points_by_pid, top_n, hit_n=HIT_N, pos=None, kind=None, fmt=None):
    """Score one positional ranking against actual points.

    players: ordered [{sleeper_id,...}]; points_by_pid: pid -> float.

    The evaluation pool is the UNION of the source's top N and the top N by
    actual points, following FantasyPros' methodology. Slicing only the top N
    by prediction makes a breakout invisible: if nobody ranked a player who
    finished RB12, every source silently escapes the miss. Players in the pool
    that a source didn't rank are imputed at "last rank it published + 1"
    rather than scored as if predicted worst — they were unranked, not ranked
    last, and a source with a short list shouldn't be punished as though it
    actively ranked everyone it omitted.
    """
    # A player we could not resolve to an id cannot be scored — we don't know
    # what he did. Scoring him 0.0 instead silently inflates the result: those
    # rows sit deep in a source's list, so "ranked low, scored nothing" reads
    # as a correct call. ESPN's 2022 board matched only 128 of 484 rows and
    # posted a weekly RB Spearman of 0.81 on the strength of that alone, which
    # is not achievable by any real projection. Drop them and report the count.
    # Two kinds of row cannot be scored fairly and are excluded rather than
    # counted as zero:
    #
    #   no id        we don't know who it is, so we don't know what he did
    #   no stat line he never took the field that week
    #
    # The second matters more than it looks. Sources differ in whether they
    # list inactive players at all: FantasyPros drop them from the weekly
    # board, ESPN's projections include everyone. Zero-filling rewards ESPN for
    # "correctly" ranking a player who was never going to play, an advantage
    # FantasyPros structurally cannot earn. It is not a small effect — ESPN's
    # 2022 top-36 RB pool held 10 such rows and posted a weekly RB Spearman of
    # 0.81, against 0.01 for FantasyPros on the same week and the same actuals.
    scoreable = [p for p in players
                 if p.get("sleeper_id") and p["sleeper_id"] in points_by_pid]
    ranked = scoreable
    pool = list(scoreable[:top_n])
    in_pool = {p.get("sleeper_id") for p in pool}
    head = players[:top_n]
    dropped = sum(1 for p in head if not p.get("sleeper_id"))
    did_not_play = sum(1 for p in head
                       if p.get("sleeper_id") and p["sleeper_id"] not in points_by_pid)

    # top N by actual points AT THIS POSITION — filtering after the slice would
    # take the top N scorers overall (mostly QBs) and leave almost nothing
    at_pos = [(pid, v) for pid, v in points_by_pid.items()
              if not pos or POS_OF.get(pid) == pos]
    top_actual = sorted(at_pos, key=lambda kv: -kv[1])[:top_n]
    ranked_by_id = {p["sleeper_id"]: i + 1 for i, p in enumerate(ranked)}
    imputed_rank = len(ranked) + 1

    entries = [(i + 1, points_by_pid.get(p.get("sleeper_id"), 0.0),
                short_name(p.get("name") or NAME_OF.get(p.get("sleeper_id"))))
               for i, p in enumerate(pool)]
    added = 0
    for pid, pts in top_actual:
        if pid in in_pool:
            continue
        # in the pool on merit; use the source's own rank if it has one
        entries.append((ranked_by_id.get(pid, imputed_rank), pts,
                        short_name(NAME_OF.get(pid))))
        added += 1

    unmatched = dropped
    ranked_entries = entries[:len(pool)]
    if len(ranked_entries) < 3:
        return None

    def _stats(rows):
        pr = [r[0] for r in rows]
        pt = [r[1] for r in rows]
        ar = _avg_rank(pt)
        return {
            "spearman": spearman(pr, pt),
            "rank_mae": round(sum(abs(p - a) for p, a in zip(pr, ar)) / len(pr), 2),
            "hit_rate": round(sum(1 for p, a in zip(pr, ar)
                                  if p <= hit_n and a <= hit_n)
                              / min(hit_n, len(pr)), 3),
            "n": len(rows),
        }

    base = _stats(ranked_entries)

    # ---- points space: FantasyPros' "Accuracy Gap".
    # Each predicted rank implies the points that rank slot has historically
    # produced; the gap is how far that lands from what the player actually
    # scored. Weighting is automatic — missing at RB2 costs far more than at
    # RB45, which rank correlation cannot express.
    gap = None
    if kind and fmt and pos:
        gaps = []
        for pr, pts, _name in entries:
            proj = rankvalue.points_for_rank(CURVE, kind, fmt, pos, int(round(pr)))
            if proj is not None:
                gaps.append(abs(proj - pts))
        if gaps:
            gap = round(sum(gaps) / len(gaps), 2)

    # ---- calibration: predicted rank vs where the player actually finished,
    # for the scatter on the site. Capped so summary.json stays small.
    actual_rank_of = _avg_rank([e[1] for e in entries])
    # [predicted rank, actual finish, short name, actual fantasy points]
    calib = [[int(round(e[0])), round(actual_rank_of[i], 1), e[2] or "",
              round(e[1], 1)]
             for i, e in enumerate(entries)][:80]
    # Headline Spearman stays on the players the source actually ranked — that
    # is what rank correlation means, and it keeps the number comparable across
    # seasons. The union pool is reported alongside rather than folded in:
    # Spearman treats a breakout the source ranked 150th as an extreme outlier,
    # so mixing the pools would swing the headline wildly (0.32 -> 0.13 on 2025)
    # for a reason that is really about coverage, not ordering. FantasyPros pair
    # the union pool with points-space error, not rank correlation.
    union = _stats(entries) if added else dict(base)
    base.update({
        "ranked": len(pool),
        "unmatched": unmatched,
        "did_not_play": did_not_play,
        "missed_top": added,          # top-N scorers the source left out of its top-N
        "accuracy_gap": gap,          # mean |implied points - actual points|
        "calibration": calib,
        "union": {"spearman": union["spearman"], "rank_mae": union["rank_mae"],
                  "n": union["n"]},
    })
    return base


def attach_ids(players, matchers):
    for p in players:
        # some sources (Sleeper's own projections) already carry the id, so
        # there is nothing to guess
        if p.get("sleeper_id"):
            if not p.get("pos"):
                db = matchers["db"].get(p["sleeper_id"])
                if db:
                    p["pos"] = db["pos"]
            continue
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


def tags_of(payload):
    """Tags for a snapshot, defaulted for boards captured before tagging."""
    t = dict(DEFAULT_TAGS)
    t.update(payload.get("tags") or {})
    return t


def is_baseline(payload):
    """Can this board be compared directly against the default league?

    The default league is 1QB / half-PPR / K+DST / single flex redraft. A
    superflex board, an IDP board, or a best-ball ADP is measuring a different
    question, so none of them belong in the default consensus — but all stay
    captured, tagged, and available behind a toggle.
    """
    return matches_baseline(tags_of(payload))


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


def main(season=None, is_current=True):
    """Build site data for one season.

    Writes docs/data/{season}/*.json always, and mirrors the current season to
    docs/data/*.json so the site's default load path is unchanged.
    """
    if season is None:
        season = int(sleeper.get_state()["season"])
    players_db = sleeper.load_players()
    load_positions(players_db)
    load_curve()
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

    # which sources are directly comparable to the default league
    baseline_sources = {}
    for scope_name in ["predraft"] + [f"week{w:02d}" for w in weeks]:
        for (source, _f), payload in load_rankings(season, scope_name).items():
            baseline_sources.setdefault(source, is_baseline(payload))

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
                    m = evaluate(by_pos[pos], pts, TOP_N[pos], pos=pos, kind="weekly", fmt=fmt)
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
                wk_gaps = [wk["scopes"][scope].get("accuracy_gap")
                           for wk in entry["weeks"].values()
                           if wk["scopes"].get(scope)
                           and wk["scopes"][scope].get("accuracy_gap") is not None]
                row = {"source": source, "score": cum[scope]["avg_spearman"],
                       "weeks": len(scores),
                       "baseline": baseline_sources.get(source, True)}
                if wk_gaps:
                    row["accuracy_gap"] = round(sum(wk_gaps) / len(wk_gaps), 2)
                    cum[scope]["accuracy_gap"] = row["accuracy_gap"]
                board.append(row)
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
                        m = evaluate(by_pos[pos], cpts, TOP_N[pos], pos=pos, kind="season", fmt=fmt)
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
                    m = evaluate(by_pos[pos], cpts, TOP_N[pos], pos=pos, kind="season", fmt=fmt)
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
                            "baseline": is_baseline(payload),
                            "accuracy_gap": sc.get("accuracy_gap"),
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

    # Per-source tags so the site can badge instead of hardcoding. Kept
    # separately per scope: a source can be one thing pre-draft and another
    # weekly. ESPN is exactly that — a curated draft board, but weekly
    # projections — and one merged map would mislabel whichever came second.
    src_tags, weekly_tags = {}, {}
    for (source, _f), payload in load_rankings(season, "predraft").items():
        src_tags.setdefault(source, tags_of(payload))
    for w in weeks:
        for (source, _f), payload in load_rankings(season, f"week{w:02d}").items():
            weekly_tags.setdefault(source, tags_of(payload))
    for source, t in weekly_tags.items():
        src_tags.setdefault(source, t)
    summary["source_tags"] = src_tags
    summary["weekly_tags"] = weekly_tags
    summary["curve_window"] = (read_json(DATA / "rankvalue.json") or {}).get("default_window")
    summary["baseline"] = {"qb": "1qb", "format": "half_ppr",
                           "roster": "offense", "scope": "redraft"}

    write_json(DOCS / "data" / str(season) / "summary.json", summary)
    if is_current:
        write_json(DOCS / "data" / "summary.json", summary)
    log.info("%s/summary.json written (%d weeks evaluated)", season, len(weeks))

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
            if not is_baseline(payload):
                continue  # superflex / IDP / best-ball — different question
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
    write_json(DOCS / "data" / str(season) / "predraft.json", comparison)
    if is_current:
        write_json(DOCS / "data" / "predraft.json", comparison)
    log.info("%s/predraft.json written", season)

    if is_current:
        # cross-season player history for the site's drill-in panel; imported
        # lazily because player_history itself imports this module
        import player_history
        player_history.main()
        # expectation model (reads players.json written above). Needs nflverse
        # downloads on a cold cache; a network failure must not fail the run.
        try:
            import model
            model.main()
        except Exception as e:
            log.warning("expectation model failed: %s", e)
    return summary


def available_seasons():
    """Seasons with any captured rankings, newest first."""
    d = DATA / "rankings"
    if not d.exists():
        return []
    return sorted((int(p.name) for p in d.iterdir()
                   if p.is_dir() and p.name.isdigit()), reverse=True)


def write_index(current):
    seasons = available_seasons()
    # The current season has no completed weeks until it kicks off, so landing
    # on it shows empty leaderboards and reads as broken. Point the site at the
    # newest season that actually has scored weeks instead.
    scored = []
    for s in seasons:
        summary = read_json(DOCS / "data" / str(s) / "summary.json") or {}
        if summary.get("weeks_evaluated"):
            scored.append(s)
    write_json(DOCS / "data" / "seasons.json",
               {"current": current, "seasons": seasons,
                "scored": scored,
                "default": scored[0] if scored else current})
    log.info("seasons.json: %d seasons, %d scored, default %s",
             len(seasons), len(scored), scored[0] if scored else current)


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    current = int(sleeper.get_state()["season"])
    if args and args[0] == "all":
        targets = available_seasons()
    elif args:
        targets = [int(a) for a in args]
    else:
        targets = [current]
    for s in targets:
        main(season=s, is_current=(s == current))
    write_index(current)
    if current not in targets:
        # backfill-only run: main() skipped the player-history refresh
        import player_history
        player_history.main()
