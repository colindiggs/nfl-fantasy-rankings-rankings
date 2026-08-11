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
| FantasyPros | ✓ | ✓ | ✓ | ✓ | embedded ecrData JSON, archive back to 2013 |
| Sleeper (projections) | ✓ | ✓ | ✓ | ✓ | `/projections/nfl/{season}/{week}`, 2018+ |
| ESPN | ✓ | ✓* | ✓ | ✓ | fantasy API; draft board 2023+, **weekly projections 2021+** (*half-PPR derived) |
| CBS Sports | ✓ | | ✓ | ✓ | HTML top-200 / positional pages |
| NFL.com | ✓ | | | ✓ | server-rendered research pages |
| Yahoo | | ✓ | | | public `pub-api-ro` JSON (default = half-PPR) |
| The Ringer | ✓ | ✓ | ✓ | | published Google Sheet CSV (4 boards incl. a labelled superflex control) |
| PFF | | | ✓ | | consumer API (public client key — may rotate) |
| RotoBaller | ✓ | ✓ | ✓ | | WordPress JSON API |
| Draft Sharks (IDP) | ✓ | ✓ | ✓ | | htmx table fragment — **IDP board, excluded from the 1QB consensus** |
| FantasySharks (ADP) | ✓ | ✓ | ✓ | | `adp.php` draft order (scoring param is ignored) |
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

Both are computed and stored. The site scores the full roster the league starts
(`all`); the per-position detail lives in the "Average error by position" chart,
where the K/DST effect is legible instead of averaged away.

Alongside Spearman, every board is scored in **points space** using the
FantasyPros "Accuracy Gap": each predicted rank implies the points that rank slot
has historically produced (from 13 seasons of our own actuals, see
`scripts/rankvalue.py`), and the gap is the distance from what the player really
scored. It weights automatically — a miss at RB2 costs far more than one at RB45.
The two metrics can disagree, which is usually the interesting case: kickers have
the *lowest* points-space error of any position despite near-random rank
correlation, because they all score within a narrow band.

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
| Weekly rankings | 2023–2025 | **FantasyPros, Sleeper, ESPN** |
| Weekly rankings | 2018–2022 | FantasyPros, Sleeper |
| Weekly rankings | 2013–2017 | FantasyPros only |
| Pre-draft, PPR & Standard | 2023–2025 | FantasyPros, FF Calculator, MyFantasyLeague, ESPN |
| Pre-draft, PPR & Standard | 2013–2022 | FantasyPros, FF Calculator, MyFantasyLeague |
| Pre-draft, Half-PPR | 2013–2025 | FantasyPros, FF Calculator |
| Current season (2026) | — | 17 sources |

Half-PPR history is thinner than PPR/Standard because **ESPN and
MyFantasyLeague publish standard and PPR only** — neither offers a half-PPR
board. That's why a backfilled half-PPR season shows two sources while the same
season in PPR shows four. The site says so under the controls rather than
leaving it to be discovered.

Weekly history is multi-source from 2018 because two sites expose past weeks
through their own APIs rather than an archive:

- **Sleeper** publishes a projection for every player every week at
  `/projections/nfl/{season}/{week}`, back to 2018. It is keyed by Sleeper
  player_id — the same id space as our actuals — so matching is exact rather
  than name-based.
- **ESPN** exposes weekly projections by `scoringPeriodId` with the season in
  the URL path, used from 2023 (2021–22 respond but are survivorship-biased —
  see below). `leaguedefaults/1` scores standard and `/3`
  scores PPR; half-PPR is exactly `(standard + PPR) / 2`, since half-PPR is
  standard plus 0.5/reception and PPR is standard plus 1.0. That's arithmetic
  on ESPN's own projection, not a third invented board.

Both are tagged `basis="projection"` and badged in the UI. A projection ordered
by points is a real ranking, but it answers "who scores most" rather than "who
should you start", and the two come apart where usage is volatile.

### Rows that can't be scored fairly

Two kinds of row are excluded from scoring rather than counted as zero, and
both are reported per position (`unmatched`, `did_not_play`):

- **No id** — we don't know who it is, so we don't know what he did.
- **No stat line** — he never took the field. This one matters more than it
  looks: sources differ in whether they list inactive players at all.
  FantasyPros drop them from the weekly board; ESPN's projections include
  everyone. Zero-filling rewards ESPN for "correctly" ranking a player who was
  never going to play, an advantage FantasyPros structurally cannot earn. It's
  not subtle — ESPN's 2022 top-36 RB pool held 10 such rows and posted a weekly
  RB Spearman of 0.81 against FantasyPros' 0.01 on the same week and the same
  actuals.

A position whose scoreable pool falls below 8 players is still reported but
left out of the leaderboard average, since a rho over five players swings
wildly enough to dominate a six-position mean.

**ESPN weekly is used from 2023 only.** 2021 and 2022 respond, but the player
set returned for those seasons skews toward players prominent today — 12 of the
top-24 projected QBs in 2022 week 3 never played that week. The survivors are a
biased sample of players who were good in that era, which inflated weekly
Spearman to ~0.43 against ~0.26 for every other source. From 2023 the
did-not-play counts are ~0 and it tracks the field normally.

Dead ends are recorded in `backfill.py` so they aren't re-tested: the Wayback
Machine (real captures, but FFToday's archive is missing RB and TE entirely and
NFL.com covers 6 weeks of 2025), RotoBaller's ignored `season` param, and
FantasyPros' 182 individual experts (the `filters` param is applied
client-side, so every request returns the same 45-expert consensus).

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
| ESPN | that season's draft board | season in the API path, **2023+ only** |

Everything captured is real published data — nothing is reconstructed. Verified
*not* backfillable: FFToday weekly (accepts a `Season` param but returns an empty
table for past seasons), CBS, NFL.com, Yahoo, PFF, RotoBaller, The Ringer,
Underdog, Draft Sharks, FantasySharks, WalterFootball. RotoBaller accepts a
`season` param and silently ignores it. The Wayback Machine holds only one
capture of FFToday's weekly page for all of 2025, with the week params stripped. For extra historical depth
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
