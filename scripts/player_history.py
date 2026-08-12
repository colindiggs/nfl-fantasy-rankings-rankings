"""Cross-season player history for the site's drill-in panel.

For every player who has appeared on any season's consensus pre-draft board,
writes per-season, per-format aggregates to docs/data/players.json:

  pre   consensus pre-draft positional rank (order of consensus averages
        within the position, from that season's board)
  fin   actual end-of-season positional rank by total fantasy points
  pts   season total fantasy points
  gp    games with a recorded stat line
  wk    weekly aggregates over weeks where a baseline consensus ranked the
        player AND he played:
          n         qualifying weeks
          proj      mean consensus positional rank
          act       mean actual positional finish that week
          over      weeks finishing strictly better than the consensus rank
          under     weeks finishing strictly worse
          ppg_proj  mean points implied by the consensus rank (rank-value curve)
          ppg_act   mean points actually scored in those weeks

All ranks are positional (RB12 = 12), not overall. Weekly consensus uses
baseline boards only (1QB / offense / redraft), the same filter as the site's
default view.
"""
from datetime import datetime, timezone

from common import DATA, DOCS, FORMATS, POSITIONS, get_logger, read_json, write_json
import compute
import rankvalue
import sleeper

log = get_logger("player_history")


def _positional_rank(totals, pos_of, pos):
    """pid -> 1-based rank among players of `pos`, by descending points."""
    rows = sorted(((pid, v) for pid, v in totals.items() if pos_of.get(pid) == pos),
                  key=lambda kv: -kv[1])
    return {pid: i + 1 for i, (pid, _v) in enumerate(rows)}


def _board_positional_ranks(board_rows):
    """Consensus board rows (already sorted by avg) -> pid -> positional rank."""
    seen = {}
    out = {}
    for rec in board_rows:
        pos = rec.get("pos")
        if pos not in POSITIONS:
            continue
        seen[pos] = seen.get(pos, 0) + 1
        out[rec["id"]] = seen[pos]
    return out


def season_history(season, matchers, pos_of):
    """-> {fmt: {pid: {pre, fin, pts, gp, wk}}} for one season."""
    out = {fmt: {} for fmt in FORMATS}

    # consensus pre-draft positional ranks from the published board
    board = read_json(DOCS / "data" / str(season) / "predraft.json") or {}
    for fmt in FORMATS:
        rows = ((board.get("formats") or {}).get(fmt) or {}).get("players") or []
        for pid, pre in _board_positional_ranks(rows).items():
            out[fmt][pid] = {"pre": pre}

    # actual points per completed week
    actual_weeks = {}
    adir = DATA / "actuals" / str(season)
    if adir.exists():
        for f in sorted(adir.glob("week*.json")):
            payload = read_json(f)
            actual_weeks[int(payload["week"])] = payload["points"]
    weeks = sorted(actual_weeks)

    # weekly consensus positional rank per player: mean of positional ranks
    # across baseline sources that ranked him that week
    wk_consensus = {fmt: {} for fmt in FORMATS}   # fmt -> wk -> pid -> mean rank
    for w in weeks:
        rankings = compute.load_rankings(season, f"week{w:02d}")
        per_fmt = {fmt: {} for fmt in FORMATS}    # pid -> [ranks]
        for (source, fmt), payload in rankings.items():
            if fmt not in per_fmt or not compute.is_baseline(payload):
                continue
            plist = compute.attach_ids(payload["players"], matchers)
            for pos, ordered in compute.pos_lists(plist).items():
                for i, p in enumerate(ordered):
                    pid = p.get("sleeper_id")
                    if pid:
                        per_fmt[fmt].setdefault(pid, []).append(i + 1)
        for fmt in FORMATS:
            wk_consensus[fmt][w] = {pid: sum(rs) / len(rs)
                                    for pid, rs in per_fmt[fmt].items()}

    for fmt in FORMATS:
        totals, gp = {}, {}
        wk_act_rank = {}                          # wk -> pid -> positional rank
        for w in weeks:
            pts = {pid: v.get(fmt, 0.0) for pid, v in actual_weeks[w].items()}
            for pid, v in pts.items():
                totals[pid] = totals.get(pid, 0.0) + v
                gp[pid] = gp.get(pid, 0) + 1
            wk_act_rank[w] = {}
            for pos in POSITIONS:
                wk_act_rank[w].update(_positional_rank(pts, pos_of, pos))

        fin_rank = {}
        for pos in POSITIONS:
            fin_rank.update(_positional_rank(totals, pos_of, pos))

        # players of interest: on the board OR ranked by a weekly consensus
        pids = set(out[fmt])
        for w in weeks:
            pids.update(wk_consensus[fmt][w])

        for pid in pids:
            rec = out[fmt].setdefault(pid, {})
            if pid in totals:
                rec["fin"] = fin_rank.get(pid)
                rec["pts"] = round(totals[pid], 1)
                rec["gp"] = gp.get(pid, 0)
            projs, acts, pp, pa = [], [], [], []
            over = under = 0
            pos = pos_of.get(pid)
            for w in weeks:
                proj = wk_consensus[fmt][w].get(pid)
                act = wk_act_rank[w].get(pid)
                if proj is None or act is None:
                    continue   # not ranked that week, or did not play
                projs.append(proj)
                acts.append(act)
                if act < proj:
                    over += 1
                elif act > proj:
                    under += 1
                implied = rankvalue.points_for_rank(
                    compute.CURVE, "weekly", fmt, pos, int(round(proj)))
                actual_pts = actual_weeks[w][pid].get(fmt, 0.0)
                if implied is not None:
                    pp.append(implied)
                    pa.append(actual_pts)
            if projs:
                rec["wk"] = {
                    "n": len(projs),
                    "proj": round(sum(projs) / len(projs), 1),
                    "act": round(sum(acts) / len(acts), 1),
                    "over": over, "under": under,
                }
                if pp:
                    rec["wk"]["ppg_proj"] = round(sum(pp) / len(pp), 1)
                    rec["wk"]["ppg_act"] = round(sum(pa) / len(pa), 1)
        # drop empty records (no board slot, no season data)
        out[fmt] = {pid: rec for pid, rec in out[fmt].items() if rec}
    return out


def main():
    players_db = sleeper.load_players()
    compute.load_positions(players_db)
    compute.load_curve()
    matchers = sleeper.build_matchers(players_db)
    pos_of = compute.POS_OF

    seasons = compute.available_seasons()   # newest first
    players = {}
    for season in sorted(seasons):
        hist = season_history(season, matchers, pos_of)
        for fmt in FORMATS:
            for pid, rec in hist[fmt].items():
                p = players.setdefault(pid, {"seasons": {}})
                p["seasons"].setdefault(str(season), {})[fmt] = rec
        log.info("player history %s: %d players (half_ppr)",
                 season, len(hist["half_ppr"]))

    # keep only players who made at least one season's consensus board — they
    # are the only rows the site can drill into, and the cut halves the payload
    def on_any_board(p):
        return any("pre" in rec for fmts in p["seasons"].values()
                   for rec in fmts.values())

    players = {pid: p for pid, p in players.items() if on_any_board(p)}

    # names/positions from the player DB; drop anything we can't label
    for pid in list(players):
        db = players_db.get(pid)
        if not db:
            del players[pid]
            continue
        players[pid]["name"] = db.get("name") or pid
        players[pid]["pos"] = db.get("pos")

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seasons": sorted(int(s) for s in seasons),
        "players": players,
    }
    write_json(DOCS / "data" / "players.json", payload)
    log.info("players.json written: %d players", len(players))


if __name__ == "__main__":
    main()
