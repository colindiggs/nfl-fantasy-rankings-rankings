"""Capture CLI.

Usage:
  python capture.py predraft          # snapshot pre-draft rankings from all sources
  python capture.py weekly            # snapshot weekly rankings for the upcoming week
  python capture.py actuals [week]    # fetch actual points for a completed week
  python capture.py players           # refresh Sleeper player cache
  python capture.py inbox             # import manual CSV boards from data/inbox/

Flags:
  --season YYYY     target a season other than the current one (historical backfill)
  --only a,b        restrict to named sources (most sources are current-season only)

Sources come from three places, all equal citizens downstream:
  1. JSON specs in scripts/sources/specs/ (no code — see spec_engine.py)
  2. Python adapters in scripts/sources/ (for sites needing custom logic)
  3. Manual CSVs dropped in data/inbox/ named {source}_{format}_{scope}.csv
"""
import csv
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import DATA, FORMATS, get_logger, session, write_json
import sleeper
import spec_engine
from sources import (cbs, draftsharks, espn, fantasypros, fftoday, mfl,
                     nfl_com, pff, sharks, walter, yahoo)

log = get_logger("capture")

INBOX = DATA / "inbox"

# Python adapters: source -> (formats, fetch(fmt, season, sess))
DRAFT_SOURCES = {
    "fantasypros": (FORMATS, lambda f, y, s: fantasypros.fetch_draft(f, s, season=y)),
    "espn": (["standard", "ppr"], lambda f, y, s: espn.fetch_draft(f, y, s)),
    "cbs": (["standard", "ppr"], lambda f, y, s: cbs.fetch_draft(f, s)),
    "nfl": (["standard"], lambda f, y, s: nfl_com.fetch_draft(f, s)),
    "yahoo": (["half_ppr"], lambda f, y, s: yahoo.fetch_draft(f, s)),
    "pff": (["ppr"], lambda f, y, s: pff.fetch_draft(f, s)),
    "mfl": (["standard", "ppr"], lambda f, y, s: mfl.fetch_draft(f, y, s)),
    "sharks": (FORMATS, lambda f, y, s: sharks.fetch_draft(f, s)),
    "fftoday": (FORMATS, lambda f, y, s: fftoday.fetch_draft(f, s)),
    "walter": (["standard"], lambda f, y, s: walter.fetch_draft(f, y, s)),
    "draftsharks": (FORMATS, lambda f, y, s: draftsharks.fetch_draft(f, s)),
}

# source -> (formats, fetch(fmt, season, week, sess))
WEEKLY_SOURCES = {
    "fantasypros": (FORMATS, lambda f, y, w, s: fantasypros.fetch_weekly(f, s, season=y, week=w)),
    "cbs": (["standard", "ppr"], lambda f, y, w, s: cbs.fetch_weekly(f, s)),
    "nfl": (["standard"], lambda f, y, w, s: nfl_com.fetch_weekly(f, w, s)),
    "fftoday": (FORMATS, lambda f, y, w, s: fftoday.fetch_weekly(f, y, w, s)),
}


def _merge_specs():
    """Fold spec-driven sources into the registries (specs win on name clashes)."""
    for name, spec in spec_engine.load_specs().items():
        for kind, registry in (("draft", DRAFT_SOURCES), ("weekly", WEEKLY_SOURCES)):
            fmts = spec_engine.formats_for(spec, kind)
            if fmts:
                if kind == "draft":
                    fn = (lambda sp: lambda f, y, s: spec_engine.run(sp, "draft", f, season=y, sess=s))(spec)
                else:
                    fn = (lambda sp: lambda f, y, w, s: spec_engine.run(sp, "weekly", f, season=y, week=w, sess=s))(spec)
                registry[name] = (fmts, fn)


_merge_specs()


def import_inbox(season):
    """Import manual CSV boards: data/inbox/{source}_{format}_{scope}.csv.

    scope = 'predraft' or 'weekNN'. Columns (header optional): rank,name,pos,team.
    Processed files move to data/inbox/processed/.
    """
    if not INBOX.exists():
        return []
    done = []
    for f in sorted(INBOX.glob("*.csv")):
        m = re.match(r"([a-z0-9\-]+)_(standard|half_ppr|ppr)_(predraft|week\d{2})\.csv$", f.name)
        if not m:
            log.warning("inbox: skipping %s (name must be source_format_scope.csv)", f.name)
            continue
        source, fmt, scope = m.group(1), m.group(2), m.group(3)
        players = []
        with open(f, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        header = [c.strip().lower() for c in rows[0]] if rows else []
        idx = {"rank": 0, "name": 1, "pos": 2, "team": 3}
        start = 0
        if "name" in header:
            idx = {k: (header.index(k) if k in header else -1) for k in idx}
            start = 1
        for row in rows[start:]:
            def col(key):
                i = idx.get(key, -1)
                return row[i].strip() if 0 <= i < len(row) else None
            try:
                rank = int(col("rank"))
            except (TypeError, ValueError):
                continue
            c = spec_engine._clean({"rank": rank, "name": col("name"),
                                    "pos": col("pos"), "team": col("team")})
            if c:
                players.append(c)
        if len(players) < 10:
            log.warning("inbox: %s parsed only %d rows — skipped", f.name, len(players))
            continue
        _save(season, scope, source, fmt, {"players": players, "meta": {"manual": True}})
        processed = INBOX / "processed"
        processed.mkdir(exist_ok=True)
        shutil.move(str(f), str(processed / f.name))
        done.append(f"{source}/{fmt}/{scope}")
    return done


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


def capture_predraft(season, only=None):
    sess = session()
    ok, failed = [], []
    for source, (formats, fn) in DRAFT_SOURCES.items():
        if only and source not in only:
            continue
        for fmt in formats:
            try:
                _save(season, "predraft", source, fmt, fn(fmt, season, sess))
                ok.append(f"{source}/{fmt}")
            except Exception as e:
                failed.append(f"{source}/{fmt}: {e}")
                log.warning("predraft %s %s failed: %s", source, fmt, e)
    return ok, failed


def capture_weekly(season, week, only=None):
    sess = session()
    scope = f"week{week:02d}"
    ok, failed = [], []
    for source, (formats, fn) in WEEKLY_SOURCES.items():
        if only and source not in only:
            continue
        for fmt in formats:
            try:
                _save(season, scope, source, fmt, fn(fmt, season, week, sess))
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


def _flag(name):
    """Pull '--name value' out of argv, or None."""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    cmd = args[0] if args else "predraft"
    state = sleeper.get_state()
    season = int(_flag("--season") or state["season"])
    only = set((_flag("--only") or "").split(",")) - {""} or None
    if cmd == "players":
        sleeper.refresh_players()
    elif cmd == "predraft":
        sleeper.load_players()
        ok, failed = capture_predraft(season, only=only)
        print(f"predraft {season}: {len(ok)} ok, {len(failed)} failed")
        for f in failed:
            print("  FAILED", f)
    elif cmd == "weekly":
        week = int(args[1]) if len(args) > 1 else int(state.get("display_week") or state["week"])
        ok, failed = capture_weekly(season, week, only=only)
        print(f"weekly {season} wk{week}: {len(ok)} ok, {len(failed)} failed")
        for f in failed:
            print("  FAILED", f)
    elif cmd == "actuals":
        week = int(args[1]) if len(args) > 1 else int(state["week"]) - 1
        capture_actuals(season, week)
    elif cmd == "inbox":
        done = import_inbox(season)
        print(f"inbox: imported {len(done)}: {done}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
