# NFL Rankings of Rankings

Which site's fantasy football rankings actually predict performance? This project
snapshots expert rankings **before** games are played, scores them against actual
fantasy points every week, and publishes a running leaderboard for the season.

**Live site:** https://colindiggs.github.io/nfl-fantasy-rankings-rankings/

## How it works

| Piece | What it does |
|---|---|
| `scripts/sources/` | 15 source adapters — see coverage table below |
| `scripts/sleeper.py` | Sleeper API: player DB (cross-site ID matching) and actual weekly fantasy points in standard / half-PPR / PPR |
| `scripts/capture.py` | CLI: `predraft` / `weekly` / `actuals` snapshots → `data/` |
| `scripts/compute.py` | Scores every ranking vs. actual points; writes `docs/data/*.json` for the site |
| `scripts/runner.py` | Scheduled entry point: captures, computes, commits, pushes |
| `docs/` | Static GitHub Pages site (leaderboard, weekly trend, pre-draft comparison) |

### Sources & coverage

| Source | Std | Half | PPR | Weekly | How |
|---|---|---|---|---|---|
| FantasyPros | ✓ | ✓ | ✓ | ✓ | embedded ecrData JSON |
| ESPN | ✓ | | ✓ | | fantasy API (`kona_player_info`) |
| CBS Sports | ✓ | | ✓ | ✓ | HTML top-200 / positional pages |
| NFL.com | ✓ | | | ✓ | server-rendered research pages |
| Yahoo | | ✓ | | | public `pub-api-ro` JSON (default = half-PPR) |
| The Ringer | | ✓ | | | published Google Sheet CSV |
| PFF | | | ✓ | | consumer API (public client key — may rotate) |
| RotoBaller | ✓ | ✓ | ✓ | | WordPress JSON API |
| Draft Sharks | ✓ | ✓ | ✓ | | htmx table fragment |
| FantasySharks | ✓ | ✓ | ✓ | | HTML projections table |
| FFToday | ✓ | ✓ | ✓ | ✓ | HTML top-225 / weekly pages |
| WalterFootball | ✓ | | | | per-position HTML pages (positional-only) |
| FF Calculator (ADP) | ✓ | ✓ | ✓ | | free JSON API, real mock-draft ADP |
| MyFantasyLeague (ADP) | ✓* | | ✓ | | export API (*standard activates once enough non-PPR drafts exist) |
| Underdog (ADP) | | ✓ | | | BestBallTeamBuilder public feed |

Standard, half-PPR, and PPR are evaluated separately; each format's leaderboard
only includes sources that publish that format.

### Metrics
Per source, per format, per week, positions QB/RB/WR/TE (top 24/36/48/24):

- **Spearman correlation** between predicted rank and actual points rank (headline metric)
- **Rank MAE** — average absolute positional-rank error
- **Top-12 hit rate** — how many predicted top-12 players finished top-12

Weekly leaderboard = average Spearman across positions and weeks. Pre-draft boards
are frozen at kickoff and scored against cumulative season points: the headline
pre-draft score is average positional Spearman (comparable across all sources);
overall top-150 Spearman is also shown for sources with a true overall board.
ADP sources (FF Calculator, MFL, Underdog) measure "the market" against the experts.

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
