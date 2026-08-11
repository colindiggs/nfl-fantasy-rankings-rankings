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
Per source, per format, per week, positions QB/RB/WR/TE/K/DST (top 24/36/48/24/24/24):

- **Spearman correlation** between predicted rank and actual points rank (headline metric)
- **Rank MAE** — average absolute positional-rank error
- **Top-12 hit rate** — how many predicted top-12 players finished top-12

Scores are reported under two **scopes**, both computed and stored:

| Scope | Positions | Why |
|---|---|---|
| `skill` | QB/RB/WR/TE | Every source publishes these, so it's comparable across the whole field and across seasons — the default view |
| `all` | + K and DST | The full redraft roster, for sources that rank kickers and defenses |

They're kept separate rather than blended because K/DST coverage is patchy and
both positions are far more luck-driven week to week. FantasyPros' own accuracy
competitions make the same call — they score K/DST and then leave them out of
"Overall." The site exposes the choice as a toggle.

The site also builds a **consensus draft board** (top 200 per format, with player
headshots): each source's board is re-numbered over matched skill players, and a
player's consensus rank is the mean of ranks from the sources that rank him.
Partial coverage is handled by transparency, not imputation — every row shows
"ranked by n of N sources" plus his best/worst rank spread, so a player ranked
5th by two sites isn't silently treated like one ranked 5th by ten. Rows need
at least two ranking sources to appear.

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
python compute.py [season|all]  # rebuild docs/data/{season}/*.json
python runner.py tuesday        # full scheduled run (capture + compute + push)
```

## What history actually exists

| Data | Seasons | Sources |
|---|---|---|
| Weekly rankings | 2013–2025 (13) | **FantasyPros only** |
| Pre-draft, PPR & Standard | 2023–2025 | FantasyPros, FF Calculator, MyFantasyLeague, ESPN |
| Pre-draft, PPR & Standard | 2013–2022 | FantasyPros, FF Calculator, MyFantasyLeague |
| Pre-draft, Half-PPR | 2013–2025 | FantasyPros, FF Calculator |
| Current season (2026) | — | 17 sources |

Half-PPR history is thinner than PPR/Standard because **ESPN and
MyFantasyLeague publish standard and PPR only** — neither offers a half-PPR
board. That's why a backfilled half-PPR season shows two sources while the same
season in PPR shows four. The site says so under the controls rather than
leaving it to be discovered.

Weekly rankings stay single-source for history because no other site archives
them; see the dead ends in `backfill.py`.

## Backfilling a past season

```
python backfill.py 2025          # actuals + weekly + pre-draft
python backfill.py 2025 --weeks 1-9
python compute.py 2025
```

Most ranking sites publish only the current week — once it passes, it's gone.
Three sources genuinely serve history, so a backfilled season is thinner than a
live-captured one:

| Source | What's archived | How |
|---|---|---|
| FantasyPros | weekly **and** pre-draft ECR, all positions, all formats | `?week=N&year=YYYY` on the ranking pages |
| FF Calculator | real mock-draft ADP for that season | `?year=YYYY` |
| MyFantasyLeague | ADP export | per-season path |

Everything captured is real published data — nothing is reconstructed. Verified
*not* backfillable: FFToday weekly (accepts a `Season` param but returns an empty
table for past seasons), CBS, NFL.com, ESPN, Yahoo, PFF, RotoBaller, The Ringer,
Underdog, Draft Sharks, FantasySharks, WalterFootball. For extra historical depth
the CSV inbox is the on-ramp.

## Adding a ranker (any ranker)

The benchmark is designed so nearly anyone who publishes fantasy rankings can be
added. Three on-ramps, cheapest first — all are scored identically:

**1. CSV inbox — no code, ~2 minutes.** Drop `{source}_{format}_{scope}.csv`
into `data/inbox/` with columns `rank,name,pos,team`. Works for podcasts,
Reddit/X posts, paywalled sites you transcribe, or your own rankings. See
[data/inbox/README.md](data/inbox/README.md).

**2. JSON spec — no code, ~10 minutes.** If the source has a JSON API, CSV
export, or regex-parseable HTML, describe it declaratively in
`scripts/sources/specs/{source}.json` (fetch URL per format, parse recipe,
field paths). The engine handles fetching, cleaning, position normalization,
de-duping, and validation. Four of the current sources (RotoBaller, FF
Calculator, The Ringer, Underdog) run this way — copy one as a template. Schema
documented in [scripts/spec_engine.py](scripts/spec_engine.py).

**3. Python adapter — for gnarly sites.** Anything needing multi-request joins,
custom headers, or odd markup gets a module in `scripts/sources/` returning
`{"players": [{"rank", "name", "team", "pos"}], "meta": {}}`, registered in
`capture.py`.

Player matching (normalized names + alias table + Sleeper ID database) and
display labels are automatic for all three paths; unknown positions are
backfilled from the player database. Sources may cover any subset of scoring
formats and be draft-only or weekly — the leaderboards only compare each source
where it competes.

## Notes / limitations

- Scrapers validate row counts and fail loudly per source/format; one source
  breaking never blocks the others. Check `logs/run.log` after schema changes.
- Player matching: ESPN by shared `espn_id` via Sleeper; FantasyPros/CBS by
  normalized name + position (aliases in `scripts/common.py`). Defenses resolve
  by team code instead — `scripts/teams.py` maps every published form
  ("Philadelphia Eagles", "Eagles D/ST", "Eagles", "PHI") onto the team code
  Sleeper keys defenses by. The **name** is authoritative for a defense, not the
  adjacent team column: The Ringer's sheet lists "Seattle Seahawks" against team
  "PIT", and trusting the column silently scored 12 defenses as the wrong team.

## Source tags

Every captured board is tagged at retrieval with what it actually is, so
downstream code filters on facts rather than inferring from a URL:

| Tag | Values | Meaning |
|---|---|---|
| `qb` | `1qb` / `superflex` | superflex boards never enter a 1QB consensus |
| `basis` | `expert` / `adp` / `projection` | opinion, market, or raw projections |
| `roster` | `offense` / `idp` | IDP boards rank LB/DL/DB alongside offense |
| `scope` | `redraft` / `bestball` | best ball has no waivers, streaming, or K/DST |
| `order` | `overall` / `positional` | positional boards restart ranks per position |

The **baseline** this benchmark answers for is 1QB, half-PPR, K+DST, single
RB/WR/TE flex redraft. Boards that don't match are still captured and scored —
they're just kept out of the default consensus and badged in the UI, which has
a header-level Team-DST/IDP toggle.

### Audit findings (Aug 2026)

Every source was re-inspected against its live site:

- **The Ringer** — the Google Sheet is their own publication, not a workaround
  (same title and update date as the web page). One CSV carries **four** boards:
  half-PPR, zero-PPR, PPR and superflex. We now capture all of them. The
  superflex board is the same analysts in the same week differing only in format,
  which makes it a labelled control: QB4 at rank 5 versus 33–43 on their 1QB
  boards.
- **FantasySharks** — was pulling `projections.php`, ordered by raw projected
  points pooled across positions, so ~25 QBs led the board. That's a projections
  table, not a draft board. Now uses `adp.php` (Gibbs #1, QB4 at 45).
- **Draft Sharks** — captured as an IDP board only. Their rankings interleave
  LB/DL/DB into a single value-based overall order (LB 10th, DL 13th, DB 18th).
  An offence-only view was tried and withdrawn: stripping IDP and renumbering
  still leaves Josh Allen 7th, Brock Bowers 8th, Trey McBride 9th and kicker
  Brandon Aubrey **12th overall**. Peers put QB4 between 36 and 67; this board
  had it at 28 with TE1 at 8. A kicker in the top 12 is the tell — it is a
  legitimate board for the league it targets and misleading in any other, so it
  is tagged `roster=idp` and kept out of the default consensus.
- **MyFantasyLeague** — QB-heavier than peers (QB4 at pick 23) but a genuine 1QB
  board, not superflex.
- **Underdog** — best-ball ADP: no K or DST at all, and QB4 goes at pick 67
  against 49 on the redraft consensus. Tagged `bestball` and kept out of the
  redraft leaderboard, since scoring it against redraft outcomes would penalise
  it for correctly doing its own job.
