"""Capture CLI.

Usage:
  python capture.py predraft          # snapshot pre-draft rankings from all sources
  python capture.py weekly            # snapshot weekly rankings for the upcoming week
  python capture.py actuals [week]    # fetch actual points for a completed week
  python capture.py players           # refresh Sleeper player cache
"""
import sys
from datetime import datetime, timezone

from common import DATA, FORMATS, get_logger, session, write_json
import sleeper
from sources import cbs, espn, fantasypros

log = get_logger("capture")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(season, scope, source, fmt, result):
    payload = {
        "source": source,
        "format": fmt,
        "scope": scope,
        "season": season,
        "captured_at": _now(),
        "meta": result.get("meta", {}),
        "players": result["players"],
    }
    path = DATA / "rankings" / str(season) / scope / f"{source}_{fmt}.json"
    write_json(path, payload)
    log.info("saved %s/%s %s: %d players", scope, source, fmt, len(result["players"]))


def capture_predraft(season):
    sess = session()
    ok, failed = [], []
    for fmt in FORMATS:
        for source, fn in [
            ("fantasypros", lambda f=fmt: fantasypros.fetch_draft(f, sess)),
            ("espn", lambda f=fmt: espn.fetch_draft(f, season, sess)),
            ("cbs", lambda f=fmt: cbs.fetch_draft(f, sess)),
        ]:
            try:
                _save(season, "predraft", source, fmt, fn())
                ok.append(f"{source}/{fmt}")
            except Exception as e:
                failed.append(f"{source}/{fmt}: {e}")
                log.warning("predraft %s %s failed: %s", source, fmt, e)
    return ok, failed


def capture_weekly(season, week):
    sess = session()
    scope = f"week{week:02d}"
    ok, failed = [], []
    for fmt in FORMATS:
        for source, fn in [
            ("fantasypros", lambda f=fmt: fantasypros.fetch_weekly(f, sess)),
            ("cbs", lambda f=fmt: cbs.fetch_weekly(f, sess)),
        ]:
            try:
                _save(season, scope, source, fmt, fn())
                ok.append(f"{source}/{fmt}")
            except Exception as e:
                failed.append(f"{source}/{fmt}: {e}")
                log.warning("weekly %s %s failed: %s", source, fmt, e)
    return ok, failed


def capture_actuals(season, week):
    stats = sleeper.get_week_stats(season, week)
    if len(stats) < 100:
        raise RuntimeError(f"only {len(stats)} stat lines for {season} week {week} — week not played yet?")
    path = DATA / "actuals" / str(season) / f"week{week:02d}.json"
    write_json(path, {"season": season, "week": week, "captured_at": _now(), "points": stats})
    log.info("saved actuals week %d: %d players", week, len(stats))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "predraft"
    state = sleeper.get_state()
    season = int(state["season"])
    if cmd == "players":
        sleeper.refresh_players()
    elif cmd == "predraft":
        sleeper.load_players()
        ok, failed = capture_predraft(season)
        print(f"predraft: {len(ok)} ok, {len(failed)} failed")
        for f in failed:
            print("  FAILED", f)
    elif cmd == "weekly":
        week = int(sys.argv[2]) if len(sys.argv) > 2 else int(state.get("display_week") or state["week"])
        ok, failed = capture_weekly(season, week)
        print(f"weekly {week}: {len(ok)} ok, {len(failed)} failed")
        for f in failed:
            print("  FAILED", f)
    elif cmd == "actuals":
        week = int(sys.argv[2]) if len(sys.argv) > 2 else int(state["week"]) - 1
        capture_actuals(season, week)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
