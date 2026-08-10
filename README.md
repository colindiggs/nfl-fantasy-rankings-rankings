# NFL Rankings of Rankings

Which site's fantasy football rankings actually predict performance? This project
snapshots expert rankings **before** games are played, scores them against actual
fantasy points every week, and publishes a running leaderboard for the season.

**Live site:** https://colindiggs.github.io/nfl-fantasy-rankings-rankings/

## How it works

| Piece | What it does |
|---|---|
| `scripts/sources/` | Scrapers: FantasyPros (expert consensus, all formats), ESPN (draft ranks, std+PPR), CBS Sports (std+PPR) |
| `scripts/sleeper.py` | Sleeper API: player DB (cross-site ID matching) and actual weekly fantasy points in standard / half-PPR / PPR |
| `scripts/capture.py` | CLI: `predraft` / `weekly` / `actuals` snapshots → `data/` |
| `scripts/compute.py` | Scores every ranking vs. actual points; writes `docs/data/*.json` for the site |
| `scripts/runner.py` | Scheduled entry point: captures, computes, commits, pushes |
| `docs/` | Static GitHub Pages site (leaderboard, weekly trend, pre-draft comparison) |

### Scoring formats
Standard, half-PPR, and PPR are evaluated separately. Coverage varies by source:
FantasyPros publishes all three; ESPN and CBS publish standard + PPR only.

### Metrics
Per source, per format, per week, positions QB/RB/WR/TE (top 24/36/48/24):

- **Spearman correlation** between predicted rank and actual points rank (headline metric)
- **Rank MAE** — average absolute positional-rank error
- **Top-12 hit rate** — how many predicted top-12 players finished top-12

Weekly leaderboard = average Spearman across positions and weeks. Pre-draft boards
are frozen at kickoff and scored against cumulative season points (top 150 overall).

## Schedule (Windows Task Scheduler)

- **Thursday 12:00** — snapshot the week's rankings before any games kick off
- **Tuesday 07:00** — fetch completed-week actual points, re-score everything, push

Register both: `powershell -ExecutionPolicy Bypass -File tasks\register_tasks.ps1`

During the preseason both runs refresh the pre-draft snapshots instead; the last
snapshot before Week 1 becomes the frozen pre-draft board.

## Manual runs

```
pip install -r requirements.txt
cd scripts
python capture.py predraft      # snapshot pre-draft boards
python capture.py weekly [wk]   # snapshot weekly rankings
python capture.py actuals [wk]  # pull actual points for a completed week
python compute.py               # rebuild docs/data/*.json
python runner.py tuesday        # full scheduled run (capture + compute + push)
```

## Notes / limitations

- Scrapers validate row counts and fail loudly per source/format; one source
  breaking never blocks the others. Check `logs/run.log` after schema changes.
- Player matching: ESPN by shared `espn_id` via Sleeper; FantasyPros/CBS by
  normalized name + position (aliases in `scripts/common.py`).
- K/DST are excluded from scoring in v1.
