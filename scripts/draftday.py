"""Day-of refresh for an ESPN draft, plus the arbitrage report in the terminal.

    python draftday.py              # recapture, validate, rebuild, report
    python draftday.py --report     # report only, from what is already on disk
    python draftday.py --push       # also commit and push the refreshed site

ADP is the most perishable number in this project. A board captured a week ago
is not merely less accurate — it is actively misleading, because every edge it
shows has had a week for the room to price in. So this does the full capture
rather than filling gaps: `runner.py sync` asks what is *missing*, which in
preseason is nothing, and would happily leave last Tuesday's ADP in place.

The report is the fallback for drafting without the site up. It splits kickers
and defenses out of the headline lists on purpose: ESPN's rooms take them
several rounds early almost without exception, which is true, actionable once,
and would otherwise be the entire top of the table every single time.
"""
import sys

from common import get_logger, read_json, DOCS
import capture
import compute
import league
import sleeper
import validate

log = get_logger("draftday")

SKILL = ("QB", "RB", "WR", "TE")


def refresh(season):
    sleeper.refresh_players()
    ok, failed = capture.capture_predraft(season)
    log.info("captured %d boards, %d failed", len(ok), len(failed))
    for f in failed:
        log.warning("  FAILED %s", f)
    return ok, failed


def espn_wide(r):
    """Is the whole of ESPN on one side and the industry on the other?

    Compares the two detrended deviations, never the raw ones. ESPN's
    editorial board drifts far more with depth than its ADP does, and the two
    raw deviations are essentially uncorrelated (r = 0.05), so against raw
    numbers this fires on nearly every player at the top of the edge list.
    Detrended they correlate at 0.52, which is the real shared signal. See
    compute.annotate_espn.
    """
    a, e = r.get("arb_adj"), r.get("espn_dev_adj")
    if a is None or e is None or abs(r.get("arb") or 0) < 12:
        return False
    return (a > 0) == (e > 0) and abs(e) >= abs(a) / 2


def _fmt_row(r):
    e = r.get("espn") or {}
    adj = r.get("arb_adj")
    return (f"  {r['name'][:22]:22s} {r['pos']:3s} "
            f"cons {r['avg']:6.1f}  ESPN {e.get('adp', 0):6.1f} ({e.get('pick') or '--':>5s})  "
            f"raw {r['arb']:+6.1f}  edge {adj:+6.1f}" if adj is not None else
            f"  {r['name'][:22]:22s} {r['pos']:3s} "
            f"cons {r['avg']:6.1f}  ESPN {e.get('adp', 0):6.1f} ({e.get('pick') or '--':>5s})  "
            f"raw {r['arb']:+6.1f}")


def report(fmt=None, top=15):
    fmt = fmt or league.FORMAT
    data = read_json(DOCS / "data" / "predraft.json")
    if not data:
        log.error("no docs/data/predraft.json — run without --report first")
        return 1
    block = (data.get("formats") or {}).get(fmt)
    if not block:
        log.error("no %s board", fmt)
        return 1
    meta = (data.get("espn") or {}).get("sources", {}).get("espn-adp", {})
    rows = [r for r in block["players"] if r.get("arb") is not None]
    lg = data.get("league") or {}

    print(f"\n  ESPN ARBITRAGE - {data['season']} {fmt}, {lg.get('teams', league.TEAMS)}-team")
    print(f"  ESPN ADP captured {meta.get('captured_at', '?')} | "
          f"consensus from {len(block['sources'])} non-ESPN sources: "
          f"{', '.join(block['sources'])}")
    print("  raw  = ESPN ADP minus consensus rank. Positive = he falls to you.")
    print("  edge = the same gap net of the drift at that spot on the board.")
    print("         ESPN rooms run mid-round skill players about a round late,")
    print("         so edge is the part of the gap that is really a mispricing.")
    print("  Ordered by edge. The two headline lists exclude players where ESPN's")
    print("  own analysts back their drafters - those are listed separately, because")
    print("  a gap the whole of ESPN agrees on is news you are missing, not an edge.")
    print()

    skill = [r for r in rows if r["pos"] in SKILL]
    key = "arb_adj" if any(r.get("arb_adj") is not None for r in skill) else "arb"
    skill.sort(key=lambda r: -(r.get(key) if r.get(key) is not None else r["arb"]))
    clean = [r for r in skill if not espn_wide(r)]
    wide = [r for r in skill if espn_wide(r)]

    print(f"  WAIT ON HIM - ESPN's room is behind its own analysts (top {top})")
    for r in clean[:top]:
        print(_fmt_row(r))
    print()
    print(f"  DON'T CHASE - ESPN's room is ahead of its own analysts (top {top})")
    for r in clean[-top:][::-1]:
        print(_fmt_row(r))

    if wide:
        print()
        print(f"  CHECK THE NEWS FIRST - {len(wide)} players where ESPN's analysts back")
        print("  their drafters and the industry is the one disagreeing. The gap is")
        print("  real, but it is about the player, not about a slow room.")
        for r in wide[:8]:
            print(_fmt_row(r))

    kd = [r for r in rows if r["pos"] in ("K", "DST")]
    kd.sort(key=lambda r: -r["arb"])
    if kd:
        early = [r for r in kd if r["arb"] < -15]
        print(f"\n  K/DST - {len(early)} of {len(kd)} go more than 15 picks "
              f"ahead of consensus in ESPN rooms. Let them go; take yours last.")
    print()
    return 0


def main():
    season = int(sleeper.get_state()["season"])
    if "--report" not in sys.argv:
        refresh(season)
        # validate.main() reads sys.argv, which here belongs to draftday, so
        # go straight at the check and summarise it ourselves
        try:
            flagged = [f for f in validate.check(season, "predraft") if f["issues"]]
            for f in flagged:
                log.warning("board flagged: %s %s — %s",
                            f["source"], f["fmt"], "; ".join(f["issues"]))
            log.info("validation: %d board(s) flagged", len(flagged))
        except Exception as e:
            log.warning("validation could not run: %s", e)
        compute.main()
        compute.finalize(season)
        if "--push" in sys.argv:
            import runner
            runner.commit_push("draft-day refresh")
    return report()


if __name__ == "__main__":
    sys.exit(main())
