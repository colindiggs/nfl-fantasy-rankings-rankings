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
  sleeper      their own weekly projections, ordered into rankings, 2018+
  espn (wk)    weekly projections by scoringPeriodId, 2021+; half-PPR is
               exactly (standard + PPR) / 2, which is arithmetic on their
               own numbers rather than a third invented board
  espn         fantasy API keyed by season path — draft board, 2023+ only
               (2018-2022 respond but carry no draft ranks; 2017 and older 404)

Verified NOT backfillable (current-season only): FFToday weekly (serves an
empty table for past seasons), CBS, NFL.com, Yahoo, PFF, RotoBaller, The
Ringer, Underdog, Draft Sharks, FantasySharks, WalterFootball.

Two dead ends worth not re-testing:

  RotoBaller accepts a `season` param and ignores it — asking for 2025 returns
  the 2026 board (Gibbs first; 2025's was Chase). Silent, so it has to be
  checked against a known result rather than trusted.

  The Wayback Machine holds real captures but not enough of them. FFToday's
  archived weekly URLs DO carry GameWeek (an earlier probe used the wrong URL
  form and concluded otherwise), covering 18 weeks of 2025 — but only PosIDs
  10/30/50/80, so RB and TE are absent entirely. NFL.com has 2025 weeks 1, 4,
  5, 9, 15 and 18 with varying positions. Both are partial enough that they
  would skew per-position comparisons, and they are unnecessary now that
  Sleeper and ESPN supply complete weekly boards.

  FantasyPros individual experts (182 of them) are not publicly retrievable.
  The ecrData blob exposes an `experts_available` list and a `filters` param,
  but filtering is applied client-side: requesting ?filters=3900 returns the
  same 45-expert consensus, byte for byte, as the unfiltered page.
"""
import sys
import time

import capture
import sleeper
from common import get_logger
from sources import espn, fantasypros, sleeper_proj

log = get_logger("backfill")

WEEKLY_SOURCES = ["fantasypros", "sleeper", "espn"]
DRAFT_SOURCES = ["fantasypros", "ffcalc", "mfl", "espn"]

# Some historical sources only reach back so far; skip them rather than log a
# failure for every earlier season.
# A source can reach further back for one kind of data than another: ESPN's
# draft board starts in 2023 but their weekly projections go to 2021.
DRAFT_FIRST_SEASON = {"espn": 2023}
WEEKLY_FIRST_SEASON = {"sleeper": 2018, "espn": 2021}

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
        usable = {s for s in DRAFT_SOURCES
                  if season >= DRAFT_FIRST_SEASON.get(s, 0)}
        ok, failed = capture.capture_predraft(season, only=usable)
        results["draft"] = ok
        results["failed"] += [f"predraft {f}" for f in failed]

    if do_rankings:
        weekly = {s for s in WEEKLY_SOURCES
                  if season >= WEEKLY_FIRST_SEASON.get(s, 0)}
        for w in weeks:
            ok, failed = capture.capture_weekly(season, w, only=weekly)
            results["weekly"] += [f"wk{w} {o}" for o in ok]
            results["failed"] += [f"weekly wk{w} {f}" for f in failed]
            # the per-URL page cache saves refetching QB/K/DST across formats,
            # but each page is ~0.5MB — drop it between weeks or a long backfill
            # accumulates gigabytes of held HTML
            fantasypros.clear_cache()
            sleeper_proj.clear_cache()
            espn.clear_cache()
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
