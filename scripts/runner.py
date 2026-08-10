"""Scheduled entry point. Decides what to capture based on the NFL calendar, then
recomputes site data and pushes to GitHub.

  python runner.py tuesday    # after the week completes: actuals + evaluation
  python runner.py thursday   # before games: snapshot weekly rankings
"""
import subprocess
import sys
from datetime import date

from common import DATA, ROOT, get_logger
import capture
import compute
import sleeper

log = get_logger("runner")


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


def run_tuesday():
    state = sleeper.get_state()
    season = int(state["season"])
    stype = state.get("season_type")
    capture.import_inbox(season)
    if stype == "pre":
        log.info("preseason: refreshing pre-draft rankings")
        sleeper.refresh_players()
        capture.capture_predraft(season)
    else:
        # every completed regular-season week we don't have yet
        current_week = int(state.get("week") or 1)
        completed = current_week - 1 if stype == "regular" else 18
        for w in missing_actual_weeks(season, min(completed, 18)):
            try:
                capture.capture_actuals(season, w)
            except Exception as e:
                log.warning("actuals week %d failed: %s", w, e)
    compute.main()
    commit_push(f"auto: tuesday update {date.today().isoformat()}")


def run_thursday():
    state = sleeper.get_state()
    season = int(state["season"])
    stype = state.get("season_type")
    capture.import_inbox(season)
    if stype == "pre":
        log.info("preseason: refreshing pre-draft rankings")
        capture.capture_predraft(season)
    elif stype == "regular":
        week = int(state.get("display_week") or state["week"])
        capture.capture_weekly(season, week)
    else:
        log.info("season over: nothing to capture")
        return
    compute.main()
    commit_push(f"auto: thursday rankings {date.today().isoformat()}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "tuesday"
    try:
        if mode == "thursday":
            run_thursday()
        else:
            run_tuesday()
    except Exception:
        log.exception("run failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
