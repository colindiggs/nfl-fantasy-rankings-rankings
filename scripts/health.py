"""Operational health record for the capture pipeline.

The pipeline is meant to run unattended. That only works if a failure is
*visible* without anyone reading a log: sources break regularly (FantasyPros
has changed its weekly schema, ESPN its API shape, NFL.com currently returns
nothing at all), and a broken source does not announce itself — it just stops
contributing while everything around it keeps working.

This keeps a running record in data/health.json and publishes it to
docs/data/health.json so the site can show it. It is the handover point
between the three parties:

  Windows Task Scheduler  makes sure Python runs at all
  Python (this repo)      captures what is missing, and records what failed
  Colin                   reads one line: is anything broken
  Claude                  gets a dated, machine-written fault record to fix

Nothing here makes a judgement call. It records outcomes and counts
consecutive failures, so "NFL.com has produced nothing for 5 runs" is a fact
on the page rather than something someone has to notice.
"""
from datetime import datetime, timezone

from common import DATA, DOCS, get_logger, read_json, write_json

log = get_logger("health")

STATE = DATA / "health.json"
PUBLISHED = DOCS / "data" / "health.json"

# How many consecutive failed runs before a source is called broken rather
# than merely flaky. Two is enough to clear a transient network blip without
# waiting a week to notice a real breakage.
BROKEN_AFTER = 2


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load():
    return read_json(STATE) or {"sources": {}, "runs": []}


def record(kind, ok, failed, season=None, scope=None):
    """Fold one capture round into the record.

    `ok` and `failed` are capture.py's return shape: "source/format" strings,
    with failures carrying ": reason".
    """
    rec = load()
    srcs = rec.setdefault("sources", {})
    seen = set()

    for item in ok:
        source = item.split("/")[0]
        seen.add(source)
        s = srcs.setdefault(source, {})
        s["last_ok"] = _now()
        s["last_ok_scope"] = f"{season}/{scope}" if scope else str(season)
        s["fails"] = 0
        s.pop("last_error", None)

    for item in failed:
        source = item.split("/")[0]
        reason = item.split(": ", 1)[1] if ": " in item else "unknown"
        seen.add(source)
        s = srcs.setdefault(source, {})
        s["last_fail"] = _now()
        s["last_error"] = reason[:300]
        s["fails"] = int(s.get("fails", 0)) + 1

    rec["runs"] = ([{"at": _now(), "kind": kind, "season": season,
                     "scope": scope, "ok": len(ok), "failed": len(failed)}]
                   + rec.get("runs", []))[:60]
    write_json(STATE, rec)
    return rec


def publish(season=None, weekly_expected=None):
    """Write the public health file the site reads.

    weekly_expected: {source: weeks_captured} for the current season, so the
    page can show coverage rather than only pass/fail — a source that quietly
    stopped halfway through a season is the failure this is built to catch.
    """
    rec = load()
    sources = []
    for name, s in sorted(rec.get("sources", {}).items()):
        fails = int(s.get("fails", 0))
        sources.append({
            "source": name,
            "state": "broken" if fails >= BROKEN_AFTER else ("flaky" if fails else "ok"),
            "fails": fails,
            "last_ok": s.get("last_ok"),
            "last_fail": s.get("last_fail"),
            "last_error": s.get("last_error"),
            "weeks": (weekly_expected or {}).get(name),
        })
    out = {
        "generated_at": _now(),
        "season": season,
        "broken_after": BROKEN_AFTER,
        "sources": sources,
        "runs": rec.get("runs", [])[:12],
        "n_broken": sum(1 for s in sources if s["state"] == "broken"),
        "n_flaky": sum(1 for s in sources if s["state"] == "flaky"),
    }
    write_json(PUBLISHED, out)
    log.info("health: %d sources, %d broken, %d flaky",
             len(sources), out["n_broken"], out["n_flaky"])
    return out
