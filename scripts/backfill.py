"""Backfill a completed season: actual points plus whatever rankings are archived.

    python backfill.py 2025              # actuals + weekly + pre-draft
    python backfill.py 2025 --weeks 1-9  # a slice
    python backfill.py 2025 --skip-actuals

Most ranking sites publish only the current week — once it passes, it's gone.
The sources listed below are the ones that genuinely serve historical data, so
a backfilled season is thinner than a live-captured one. Everything captured
here is real published data, never reconstructed:

  fantasypros  weekly + pre-draft ECR, addressable by ?week=&year=
  ffcalc       real mock-draft ADP for a given season (?year=)
  mfl          MyFantasyLeague ADP export, per-season path

Verified NOT backfillable (current-season only): FFToday weekly (serves an
empty table for past seasons), CBS, NFL.com, ESPN, Yahoo, PFF, RotoBaller,
The Ringer, Underdog, Draft Sharks, FantasySharks, WalterFootball.
"""
import sys
import time

import capture
import sleeper
from common import get_logger
from sources import fantasypros

log = get_logger("backfill")

WEEKLY_SOURCES = ["fantasypros"]
DRAFT_SOURCES = ["fantasypros", "ffcalc", "mfl"]

# The NFL went from a 16-game/17-week season to 17 games/18 weeks in 2021.
# Asking for week 18 of 2019 just yields empty snapshots and wasted fetches.
FIRST_18_WEEK_SEASON = 2021


def weeks_in_season(season):
    return 18 if season >= FIRST_18_WEEK_SEASON else 17


def _weeks(arg, season):
    if not arg:
        return list(range(1, weeks_in_season(season) + 1))
    if "-" in arg:
        lo, hi = arg.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(w) for w in arg.split(",")]


def backfill(season, weeks, do_actuals=True, do_rankings=True, do_draft=True):
    results = {"actuals": [], "weekly": [], "draft": [], "failed": []}

    if do_actuals:
        for w in weeks:
            try:
                capture.capture_actuals(season, w)
                results["actuals"].append(w)
            except Exception as e:
                results["failed"].append(f"actuals wk{w}: {e}")
                log.warning("actuals %s wk%s failed: %s", season, w, e)

    if do_draft:
        ok, failed = capture.capture_predraft(season, only=set(DRAFT_SOURCES))
        results["draft"] = ok
        results["failed"] += [f"predraft {f}" for f in failed]

    if do_rankings:
        for w in weeks:
            ok, failed = capture.capture_weekly(season, w, only=set(WEEKLY_SOURCES))
            results["weekly"] += [f"wk{w} {o}" for o in ok]
            results["failed"] += [f"weekly wk{w} {f}" for f in failed]
            # the per-URL page cache saves refetching QB/K/DST across formats,
            # but each page is ~0.5MB — drop it between weeks or a long backfill
            # accumulates gigabytes of held HTML
            fantasypros.clear_cache()
            time.sleep(1)  # be a good citizen

    return results


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    season = int(args[0])
    weeks = _weeks(capture._flag("--weeks"), season)
    res = backfill(
        season, weeks,
        do_actuals="--skip-actuals" not in sys.argv,
        do_rankings="--skip-rankings" not in sys.argv,
        do_draft="--skip-draft" not in sys.argv,
    )
    print(f"\n{season} backfill:")
    print(f"  actuals : {len(res['actuals'])} weeks {res['actuals']}")
    print(f"  weekly  : {len(res['weekly'])} snapshots")
    print(f"  predraft: {len(res['draft'])} boards {res['draft']}")
    if res["failed"]:
        print(f"  FAILED  : {len(res['failed'])}")
        for f in res["failed"]:
            print("    ", f)


if __name__ == "__main__":
    sleeper.load_players()
    main()
