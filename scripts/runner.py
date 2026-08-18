"""Scheduled entry point. Works out what is missing, gets it, publishes.

  python runner.py            # sync: capture whatever is missing, compute, push
  python runner.py --dry-run  # decide and report, capture and push nothing
  python runner.py tuesday    # legacy aliases, both now run the same sync
  python runner.py thursday

The old design asked "what day is it": Thursday captured the current week's
rankings, Tuesday fetched actuals. That made a missed run into permanent data
loss, because it only ever tried the job for the day it woke up on. Weekly
rankings are perishable — CBS, NFL.com and FFToday publish the current week
and nothing else — so a Thursday the machine happened to be asleep took that
week off those sources for good.

This asks "what is missing" instead. Every run does the same thing, so it is
safe to run daily, twice, or after a three-day outage, and it repairs whatever
the previous runs did not get. The only judgement in here is about *when a
thing is still capturable*, which is a property of the data, not of the day:

  actual points     never perishable — Sleeper serves any past week
  pre-draft boards  refreshed all preseason, frozen once week 1 kicks off
  weekly rankings   perishable, and only from some sources:

      fantasypros / sleeper / espn   serve past weeks, so a gap can be repaired
      cbs / nfl / fftoday            current week only — miss it and it is gone

That split is why a missed run is worth repairing at all, and why the repair
can only ever be partial. The honest fix is to not miss runs: see
tasks/register_tasks.ps1, which now wakes the machine and catches up.
"""
import subprocess
import sys
from datetime import date, datetime, timezone
try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:      # pragma: no cover - zoneinfo missing
    EASTERN = timezone.utc

from common import DATA, ROOT, get_logger
import capture
import compute
import health
import sleeper

log = get_logger("runner")

# Weekly sources whose sites expose past weeks, so a missing week can still be
# repaired on a later run. Everything else is current-week-only.
ARCHIVE_WEEKLY = {"fantasypros", "sleeper", "espn"}


# A weekly board is only worth capturing while it is still a prediction. NFL
# weeks open with Thursday night football at about 20:15 ET, so the safe window
# to snapshot the upcoming week runs from the moment the previous week is done
# (Tuesday) until Thursday teatime. Outside it, a "catch-up" run would file a
# board that has already watched some of the games it is being scored on — the
# one way this pipeline could quietly produce numbers that flatter every source.
CAPTURE_OPENS = 1      # Tuesday (Monday=0)
CAPTURE_SHUTS = 3      # Thursday
CAPTURE_SHUTS_HOUR = 17


def within_capture_window(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(EASTERN)
    wd = now.weekday()
    if wd < CAPTURE_OPENS or wd > CAPTURE_SHUTS:
        return False
    if wd == CAPTURE_SHUTS and now.hour >= CAPTURE_SHUTS_HOUR:
        return False
    return True


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def commit_push(message):
    git("add", "-A")
    status = git("status", "--porcelain").stdout.strip()
    if not status:
        log.info("nothing to commit")
        return False
    git("commit", "-m", message)
    git("push", "origin", "main")
    log.info("pushed: %s", message)
    return True


def missing_actual_weeks(season, through_week):
    adir = DATA / "actuals" / str(season)
    return [w for w in range(1, through_week + 1)
            if not (adir / f"week{w:02d}.json").exists()]


def captured_weekly_sources(season, week):
    """Which sources already have a snapshot for this week."""
    d = DATA / "rankings" / str(season) / f"week{week:02d}"
    if not d.exists():
        return set()
    return {f.name.rsplit("_", 1)[0] for f in d.glob("*.json")}


def weekly_coverage(season):
    """source -> number of weeks captured this season, for the health page."""
    root = DATA / "rankings" / str(season)
    out = {}
    if not root.exists():
        return out
    for wk in sorted(root.glob("week*")):
        for f in wk.glob("*.json"):
            src = f.name.rsplit("_", 1)[0]
            out.setdefault(src, set()).add(wk.name)
    return {k: len(v) for k, v in out.items()}


def plan(state):
    """Decide what this run should do, from the calendar and what's on disk."""
    season = int(state["season"])
    stype = state.get("season_type")
    current = int(state.get("display_week") or state.get("week") or 1)
    jobs = {"season": season, "stype": stype, "week": current,
            "predraft": False, "weekly": [], "repair": [], "actuals": [],
            "skipped_weekly": [], "skip_reason": None}

    if stype == "pre":
        # boards move all preseason; the last snapshot before week 1 is the
        # one that gets frozen and scored
        jobs["predraft"] = True
        return jobs
    if stype not in ("regular", "post"):
        return jobs

    # this week's rankings, if we do not already have them. Only while the week
    # is current: capturing later would snapshot a board that has already seen
    # the games it is meant to predict.
    if stype == "regular":
        have = captured_weekly_sources(season, current)
        want = [s for s in capture.WEEKLY_SOURCES if s not in have]
        if want and within_capture_window():
            jobs["weekly"] = want
        elif want:
            jobs["skipped_weekly"] = want
            jobs["skip_reason"] = ("outside the Tue-Thu pre-kickoff window; "
                                   "capturing now would snapshot a board that "
                                   "has already seen this week's games")

    # earlier weeks we never got, from the sources that still serve them
    last_done = current - 1 if stype == "regular" else 18
    for w in range(1, min(last_done, 18) + 1):
        have = captured_weekly_sources(season, w)
        gaps = [s for s in ARCHIVE_WEEKLY if s in capture.WEEKLY_SOURCES and s not in have]
        if gaps:
            jobs["repair"].append((w, gaps))

    completed = current - 1 if stype == "regular" else 18
    jobs["actuals"] = missing_actual_weeks(season, min(completed, 18))
    return jobs


def sync(dry_run=False):
    state = sleeper.get_state()
    jobs = plan(state)
    season = jobs["season"]
    log.info("plan: season=%s type=%s week=%s | predraft=%s weekly=%s "
             "repair=%d weeks actuals=%s",
             season, jobs["stype"], jobs["week"], jobs["predraft"],
             jobs["weekly"] or "-", len(jobs["repair"]), jobs["actuals"] or "-")
    if jobs["skipped_weekly"]:
        log.warning("weekly capture held: %s (%s)",
                    ",".join(jobs["skipped_weekly"]), jobs["skip_reason"])
    if dry_run:
        for w, gaps in jobs["repair"]:
            log.info("  would repair week %02d from %s", w, ",".join(gaps))
        return jobs

    capture.import_inbox(season)

    if jobs["predraft"]:
        sleeper.refresh_players()
        ok, failed = capture.capture_predraft(season)
        health.record("predraft", ok, failed, season, "predraft")

    if jobs["weekly"]:
        ok, failed = capture.capture_weekly(season, jobs["week"], only=jobs["weekly"])
        health.record("weekly", ok, failed, season, f"week{jobs['week']:02d}")

    for w, gaps in jobs["repair"]:
        log.info("repairing week %02d from %s", w, ",".join(gaps))
        ok, failed = capture.capture_weekly(season, w, only=gaps)
        health.record("weekly-repair", ok, failed, season, f"week{w:02d}")

    for w in jobs["actuals"]:
        try:
            capture.capture_actuals(season, w)
            health.record("actuals", [f"sleeper/actuals"], [], season, f"week{w:02d}")
        except Exception as e:
            log.warning("actuals week %d failed: %s", w, e)
            health.record("actuals", [], [f"sleeper/actuals: {e}"], season, f"week{w:02d}")

    compute.main()
    compute.finalize(season)
    health.publish(season, weekly_coverage(season))
    commit_push(f"auto: sync {date.today().isoformat()}")
    return jobs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if args and args[0] not in ("sync", "tuesday", "thursday"):
        log.warning("unknown mode %r — running sync", args[0])
    try:
        sync(dry_run=dry)
    except Exception:
        log.exception("run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
