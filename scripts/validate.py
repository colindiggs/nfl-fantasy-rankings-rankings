"""Quality gate for captured ranking boards.

A scraper rarely fails loudly. It returns nine rows instead of two hundred, or
it keeps returning last week's page, or the site renames a column and every
name stops matching — and the board still lands in the leaderboard looking
like an opinion. This checks each captured board against the things that are
true of every real board, and reports the ones that aren't.

    python validate.py                 # current season, pre-draft
    python validate.py 2025            # a past season
    python validate.py 2026 week03     # a weekly snapshot
    python validate.py --strict        # exit 1 if anything is flagged

Checks per board:
  rows          a board far shorter than its peers is usually a broken parse
  match rate    share of rows resolving to a Sleeper id; unmatched rows are
                dropped at scoring time, so a low rate silently shrinks a
                source's sample rather than showing up as an error
  duplicates    the same player twice means the parse is picking up a repeated
                layout, or two different players share one name
  positions     a board missing a whole position it used to carry
  qb4 slot      where the 4th quarterback goes: the cheapest single tell that a
                board is superflex, IDP, or scored differently than assumed
  agreement     Spearman against the consensus of the other boards in the same
                format; a board that agrees with nobody is either wrong or is
                answering a different question, and both need a look
"""
import sys
from collections import Counter
from datetime import datetime, timezone

from common import DATA, FORMATS, get_logger, read_json
import compute
import sleeper

log = get_logger("validate")

# a board with fewer than this many rows can't be a top-200 style board
MIN_ROWS = 40
# below this share of rows matching a player id, something is wrong with names
MIN_MATCH = 0.85
# a board correlating below this with its peers is not ranking the same thing
MIN_AGREEMENT = 0.5
# a pre-draft board that has not been refreshed in a fortnight is stale
MAX_AGE_DAYS = 14


def payload_tags(boards, source, fmt):
    return (boards.get((source, fmt), {}) or {}).get("tags") or {}


def staleness(boards, source, fmt):
    """Age in days of this snapshot, or None if it carries no capture time."""
    stamp = (boards.get((source, fmt), {}) or {}).get("captured_at")
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).days


def spearman(pairs):
    """Rank correlation over (rank_a, rank_b) pairs."""
    n = len(pairs)
    if n < 5:
        return None
    a = compute._avg_rank([-p[0] for p in pairs])
    b = compute._avg_rank([-p[1] for p in pairs])
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return round(num / (da * db), 3) if da and db else None


def board_rows(payload, matchers):
    plist = compute.attach_ids(list(payload["players"]), matchers)
    return plist


def check(season, scope):
    players_db = sleeper.load_players()
    compute.load_positions(players_db)
    matchers = sleeper.build_matchers(players_db)
    boards = compute.load_rankings(season, scope)
    if not boards:
        log.warning("no boards captured for %s/%s", season, scope)
        return []

    # rank by id, per format, so boards can be compared with each other
    by_fmt = {}
    parsed = {}
    for (source, fmt), payload in boards.items():
        rows = board_rows(payload, matchers)
        parsed[(source, fmt)] = rows
        ranks = {}
        for p in sorted(rows, key=lambda x: x["rank"]):
            if p.get("sleeper_id") and p["sleeper_id"] not in ranks:
                ranks[p["sleeper_id"]] = len(ranks) + 1
        by_fmt.setdefault(fmt, {})[source] = ranks

    findings = []
    for (source, fmt), rows in sorted(parsed.items()):
        issues = []
        n = len(rows)
        matched = sum(1 for p in rows if p.get("sleeper_id"))
        rate = matched / n if n else 0.0
        names = Counter(p.get("name") for p in rows)
        dupes = [x for x, c in names.items() if c > 1]
        pos = Counter(p.get("pos") for p in rows if p.get("pos"))

        if n < MIN_ROWS:
            issues.append(f"only {n} rows")
        # An IDP board ranks linebackers and safeties the offence-only player
        # database does not contain, so a low match rate there is the board
        # being itself rather than a broken parse.
        if rate < MIN_MATCH and (payload_tags(boards, source, fmt).get("roster") != "idp"):
            issues.append(f"match rate {rate:.0%} ({n - matched} unmatched)")
        if dupes:
            issues.append(f"{len(dupes)} duplicate names e.g. {dupes[:2]}")
        # A scraper that starts failing leaves the last good snapshot in place,
        # so the board keeps scoring on stale data and nothing looks wrong.
        stale = staleness(boards, source, fmt)
        if stale is not None and stale > MAX_AGE_DAYS:
            issues.append(f"snapshot {stale} days old")

        # where the 4th QB goes, over the matched board
        order = [p for p in sorted(rows, key=lambda x: x["rank"]) if p.get("sleeper_id")]
        qbs = [i for i, p in enumerate(order, 1) if p.get("pos") == "QB"]
        qb4 = qbs[3] if len(qbs) >= 4 else None

        # agreement with the consensus of the other boards in this format
        mine = by_fmt[fmt][source]
        others = [r for s, r in by_fmt[fmt].items() if s != source]
        agree = None
        if others and mine:
            pool = {}
            for r in others:
                for pid, rk in r.items():
                    pool.setdefault(pid, []).append(rk)
            cons = {pid: sum(v) / len(v) for pid, v in pool.items() if len(v) >= 2}
            pairs = [(rk, cons[pid]) for pid, rk in mine.items() if pid in cons]
            agree = spearman(pairs)
            if agree is not None and agree < MIN_AGREEMENT:
                issues.append(f"agreement with peers {agree}")

        findings.append({
            "source": source, "fmt": fmt, "rows": n, "match": rate,
            "dupes": len(dupes), "positions": "".join(
                k[0] if k != "DST" else "D" for k in
                sorted(pos, key=lambda x: ["QB", "RB", "WR", "TE", "K", "DST"].index(x)
                       if x in ("QB", "RB", "WR", "TE", "K", "DST") else 9)),
            "qb4": qb4, "agree": agree, "issues": issues,
        })
    return findings


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    season = int(args[0]) if args else int(sleeper.get_state()["season"])
    scope = args[1] if len(args) > 1 else "predraft"

    findings = check(season, scope)
    if not findings:
        return 0
    print(f"\n{season} {scope} — {len(findings)} boards\n")
    print(f"{'source':<20}{'fmt':<10}{'rows':>6}{'match':>7}{'dup':>5}"
          f"{'pos':>8}{'QB4':>6}{'agree':>7}  notes")
    flagged = 0
    for f in sorted(findings, key=lambda x: (bool(x["issues"]), x["source"]), reverse=True):
        mark = "!!" if f["issues"] else "  "
        print(f"{mark}{f['source']:<18}{f['fmt']:<10}{f['rows']:>6}"
              f"{f['match']:>6.0%}{f['dupes']:>5}{f['positions']:>8}"
              f"{(f['qb4'] if f['qb4'] is not None else '-'):>6}"
              f"{(f['agree'] if f['agree'] is not None else '-'):>7}  "
              f"{'; '.join(f['issues'])}")
        if f["issues"]:
            flagged += 1
    print(f"\n{flagged} of {len(findings)} boards flagged")
    return 1 if (strict and flagged) else 0


if __name__ == "__main__":
    sys.exit(main())
