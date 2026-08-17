"""Aggregate every scored season into one cross-season record.

Reads the per-season docs/data/{year}/summary.json files that compute.py
already writes and emits docs/data/history.json: for each kind (weekly /
pre-draft), format and scope, a source x season matrix plus career means and
a paired significance test against the field leader.

The point of the paired test is that a single season's leaderboard routinely
separates sources by less than the noise in the measurement. Sources are
scored on the *same* weeks against the *same* actuals, so the honest
comparison is a paired one on the observations they share, not a contest
between two independent means.
"""
from datetime import datetime, timezone
from math import sqrt

from common import (DEFAULT_TAGS, DOCS, FORMATS, get_logger, matches_baseline,
                    read_json, write_json)

log = get_logger("history")

SCOPES = ("skill", "all")

# A career mean over two weeks is not a career. Sources below these thresholds
# are still listed — hiding them would misrepresent the field — but they are
# marked thin and are never eligible to be the leader everyone is tested
# against, since a leader set by a three-week sample makes every real source
# look worse than it is.
# Weekly gets one observation per scored week, so a single season already
# carries real sample size. Pre-draft gets one per season — a source with three
# is not a record, it is an anecdote, and the interval around it is wide enough
# to swallow the whole field.
MIN_OBS = {"weekly": 17, "predraft": 5}

# Two-sided 95% critical values. The weekly pool runs to hundreds of paired
# observations, but pre-draft has one observation per season — 13 at most —
# where the normal approximation is meaningfully too narrow.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
        14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
        20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
        26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042, 40: 2.021,
        60: 2.000, 120: 1.980}


def tcrit(df):
    if df < 1:
        return None
    if df in _T95:
        return _T95[df]
    for cut in (30, 40, 60, 120):
        if df <= cut:
            return _T95[cut]
    return 1.960


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def ci_of_mean(xs):
    """95% CI for the mean of xs. None when a spread can't be estimated."""
    n = len(xs)
    if n < 2:
        return None, None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    t = tcrit(n - 1)
    if t is None or var < 0:
        return None, None
    half = t * sqrt(var / n)
    return m - half, m + half


def paired_delta(a_obs, b_obs):
    """Paired mean difference a - b over the observations they share.

    Returns None when fewer than two shared observations exist, since a
    difference with no estimable spread cannot support a claim either way.
    """
    keys = sorted(set(a_obs) & set(b_obs))
    diffs = [a_obs[k] - b_obs[k] for k in keys
             if a_obs[k] is not None and b_obs[k] is not None]
    if len(diffs) < 2:
        return None
    m = sum(diffs) / len(diffs)
    lo, hi = ci_of_mean(diffs)
    if lo is None:
        return None
    return {"delta": round(m, 4), "lo": round(lo, 4), "hi": round(hi, 4),
            "n": len(diffs), "tied": lo <= 0 <= hi}


def collect(kind, fmt, scope, summaries):
    """source -> {"score": {obskey: v}, "gap": {obskey: v}, "seasons": {...}}"""
    out = {}

    def slot(src):
        return out.setdefault(src, {"score": {}, "gap": {}, "seasons": {}})

    for season, summary in summaries.items():
        if kind == "weekly":
            # per-week observations, so the paired test has real sample size
            for src, entry in (summary.get("weekly", {}).get(fmt) or {}).items():
                s = slot(src)
                per_season_scores, per_season_gaps = [], []
                for wk, data in (entry.get("weeks") or {}).items():
                    sc = (data.get("scopes") or {}).get(scope)
                    if not sc or sc.get("avg_spearman") is None:
                        continue
                    key = f"{season}-{int(wk):02d}"
                    s["score"][key] = sc["avg_spearman"]
                    per_season_scores.append(sc["avg_spearman"])
                    if sc.get("accuracy_gap") is not None:
                        s["gap"][key] = sc["accuracy_gap"]
                        per_season_gaps.append(sc["accuracy_gap"])
                if per_season_scores:
                    s["seasons"][str(season)] = {
                        "score": round(mean(per_season_scores), 4),
                        "gap": round(mean(per_season_gaps), 2) if per_season_gaps else None,
                        "n": len(per_season_scores),
                    }
        else:
            # pre-draft is scored once per season, against full-season totals
            rows = ((summary.get("leaderboard", {}).get("predraft", {}) or {})
                    .get(fmt) or {})
            rows = rows.get(scope) if isinstance(rows, dict) else rows
            for r in rows or []:
                if r.get("score") is None:
                    continue
                src = r["source"]
                s = slot(src)
                key = str(season)
                s["score"][key] = r["score"]
                if r.get("accuracy_gap") is not None:
                    s["gap"][key] = r["accuracy_gap"]
                s["seasons"][key] = {
                    "score": round(r["score"], 4),
                    "gap": round(r["accuracy_gap"], 2) if r.get("accuracy_gap") is not None else None,
                    "overall": round(r["overall"], 4) if r.get("overall") is not None else None,
                    "n": 1,
                }
    return out


def build_block(kind, fmt, scope, summaries, src_tags=None):
    raw = collect(kind, fmt, scope, summaries)
    # The card answers the benchmark's default question — 1QB redraft offence —
    # so a superflex, IDP, best-ball or dynasty-mixed board does not belong in
    # it. Leaving them in also breaks the comparison mechanically: the site
    # hides them, and a reference source the reader cannot see makes every
    # interval in the table meaningless.
    if src_tags:
        raw = {s: v for s, v in raw.items()
               if matches_baseline({**DEFAULT_TAGS, **(src_tags.get(s) or {})})}
    if not raw:
        return None

    rows = []
    for src, s in raw.items():
        scores = list(s["score"].values())
        gaps = list(s["gap"].values())
        if not scores:
            continue
        lo, hi = ci_of_mean(scores)
        by_season = s["seasons"]
        ranked = sorted(by_season.items(), key=lambda kv: -kv[1]["score"])
        rows.append({
            "source": src,
            "score": round(mean(scores), 4),
            "score_lo": round(lo, 4) if lo is not None else None,
            "score_hi": round(hi, 4) if hi is not None else None,
            "gap": round(mean(gaps), 2) if gaps else None,
            "n_obs": len(scores),
            "n_seasons": len(by_season),
            "seasons": sorted(int(y) for y in by_season),
            "by_season": by_season,
            "best": {"season": int(ranked[0][0]), "score": ranked[0][1]["score"]} if ranked else None,
            "worst": {"season": int(ranked[-1][0]), "score": ranked[-1][1]["score"]} if ranked else None,
            "thin": len(scores) < MIN_OBS[kind],
        })
    if not rows:
        return None
    rows.sort(key=lambda r: -r["score"])

    # Career means are NOT measured on the same weeks: a source that only
    # covers 2023-25 is averaging different, possibly harder, weeks than one
    # going back to 2013. Ordering by pooled mean therefore cannot settle who
    # is better, and in this data it actively misleads — ESPN's pooled mean
    # trails Sleeper's while ESPN wins the weeks they both cover.
    #
    # So the leader is decided by a paired round robin: a source leads if no
    # other source beats it head-to-head on shared observations. Only sources
    # clearing the sample-size floor can lead, or one lucky week sets the bar.
    eligible = [r for r in rows if not r["thin"]] or rows
    beaten_by = {r["source"]: [] for r in rows}
    separations = 0
    for a in eligible:
        for b in eligible:
            if a["source"] == b["source"]:
                continue
            d = paired_delta(raw[a["source"]]["score"], raw[b["source"]]["score"])
            if d and not d["tied"] and d["delta"] > 0:
                beaten_by[b["source"]].append(a["source"])
                separations += 1

    # Among sources nobody beats, the reference is the one with the most
    # observations rather than the highest average. Everyone else's interval
    # is measured against it, so the best-evidenced source makes those
    # intervals as tight as the data allows; picking on average instead would
    # hand the yardstick to whichever source has the shortest, luckiest record.
    undefeated = [r for r in eligible if not beaten_by[r["source"]]]
    leader = max(undefeated or eligible,
                 key=lambda r: (r["n_obs"], r["score"]))["source"]
    lead_obs_score = raw[leader]["score"]
    lead_obs_gap = raw[leader]["gap"]

    for r in rows:
        r["beaten_by"] = beaten_by.get(r["source"], [])
        if r["source"] == leader:
            r["vs_leader"] = {"delta": 0.0, "lo": 0.0, "hi": 0.0,
                              "n": r["n_obs"], "tied": True, "is_leader": True}
            r["vs_leader_gap"] = None
            continue
        r["vs_leader"] = paired_delta(raw[r["source"]]["score"], lead_obs_score)
        r["vs_leader_gap"] = paired_delta(raw[r["source"]]["gap"], lead_obs_gap)

    # Flag the case above explicitly so the site can say it out loud rather
    # than quietly presenting a pooled order the paired test contradicts.
    paired_order = [r["source"] for r in sorted(
        rows, key=lambda r: -((r.get("vs_leader") or {}).get("delta") or -9))]
    pooled_order = [r["source"] for r in rows]

    tied = [r["source"] for r in rows
            if r.get("vs_leader") and r["vs_leader"].get("tied")]
    behind = [r["source"] for r in rows if r.get("vs_leader")
              and not r["vs_leader"]["tied"] and r["vs_leader"]["delta"] < 0]
    ahead = [r["source"] for r in rows if r.get("vs_leader")
             and not r["vs_leader"]["tied"] and r["vs_leader"]["delta"] > 0]
    return {
        "sources": rows,
        "leader": leader,
        "tied_with_leader": tied,
        "behind_leader": behind,
        "ahead_on_shared": ahead,
        "untested": [r["source"] for r in rows if not r.get("vs_leader")],
        "pooled_disagrees": paired_order != pooled_order,
        # no separable pair anywhere = the field is one undifferentiated blob,
        # which is a finding, not a failure to produce a ranking
        "separable": separations > 0,
    }


def main():
    seasons = sorted((int(p.name) for p in (DOCS / "data").iterdir()
                      if p.is_dir() and p.name.isdigit()), reverse=True)
    summaries = {}
    for s in seasons:
        summary = read_json(DOCS / "data" / str(s) / "summary.json")
        if summary and summary.get("weeks_evaluated"):
            summaries[s] = summary
    if not summaries:
        log.warning("no scored seasons; history.json not written")
        return None

    labels, src_tags, weekly_tags = {}, {}, {}
    for s in sorted(summaries):        # newest season wins on conflicts
        labels.update(summaries[s].get("labels") or {})
        src_tags.update(summaries[s].get("source_tags") or {})
        weekly_tags.update(summaries[s].get("weekly_tags") or {})

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seasons": sorted(summaries, reverse=True),
        "labels": labels,
        "source_tags": src_tags,
        "weekly_tags": weekly_tags,
        "min_obs": MIN_OBS,
        "kinds": {},
    }
    for kind in ("weekly", "predraft"):
        out["kinds"][kind] = {}
        for fmt in FORMATS:
            out["kinds"][kind][fmt] = {}
            for scope in SCOPES:
                block = build_block(kind, fmt, scope, summaries, src_tags)
                if block:
                    out["kinds"][kind][fmt][scope] = block

    write_json(DOCS / "data" / "history.json", out)
    log.info("history.json written (%d seasons: %s-%s)", len(summaries),
             min(summaries), max(summaries))
    return out


if __name__ == "__main__":
    main()
