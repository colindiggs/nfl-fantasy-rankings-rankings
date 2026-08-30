# NFL Rankings of Rankings

Which site's fantasy football rankings actually predict performance? This project
snapshots expert rankings **before** games are played, scores them against actual
fantasy points every week, and publishes a running leaderboard for the season.

**Live site:** https://colindiggs.github.io/nfl-fantasy-rankings-rankings/

## How it works

| Piece | What it does |
|---|---|
| `scripts/sources/` | 20 source adapters — see coverage table below |
| `scripts/sleeper.py` | Sleeper API: player DB (cross-site ID matching) and actual weekly fantasy points in standard / half-PPR / PPR |
| `scripts/capture.py` | CLI: `predraft` / `weekly` / `actuals` snapshots → `data/` |
| `scripts/compute.py` | Scores every ranking vs. actual points; writes `docs/data/*.json` for the site |
| `scripts/player_history.py` | Cross-season per-player record (`docs/data/players.json`): pre-draft consensus rank vs. season finish, weekly consensus rank vs. weekly finish, over/under rates, rank-implied vs. actual points. Feeds the board's click-to-drill panel; refreshed by `compute.py` on current-season runs |
| `scripts/nflverse.py` | Free historical context from [nflverse-data](https://github.com/nflverse/nflverse-data) releases, cached in `data/nflverse/`: per-season rosters (ages, experience, teams, `sleeper_id` for exact joins), weekly injury reports (2013+), and NFL draft picks |
| `scripts/model.py` | Expectation models (`docs/data/model.json`), fitted on PPR boards 2014+ and validated out-of-time (train ≤2022, test 2023–25). **Value model** (headline): ridge regression on points over expectation — season points minus the historical value of the pre-draft slot — so magnitude matters, not just rank order. **Rank model**: ridge logistic P(finish ≥ slot). Features: slot value, age + aging curve (incl. RB-specific), experience, NFL draft capital, team change, team skill-roster turnover, prior-season games/scoring/injury-report weeks/POE, two-season durability. The site shows predicted POE, a slot-free player-specific **Edge**, P(beat), and per-player signed drivers |
| `scripts/validate.py` | Quality gate over captured boards: row counts, id match rate, duplicate names, position coverage, snapshot age, the QB4 slot, and each board's agreement with its peers. `python validate.py [season] [scope] [--strict]` |
| `scripts/history.py` | Cross-season record (`docs/data/history.json`): every source's score in every scored season, plus a **paired** comparison against a reference source computed only on the weeks/seasons the two actually share, with 95% confidence intervals. See "Which differences are real" below |
| `scripts/runner.py` | Scheduled entry point. `sync` works out what is missing, captures it, computes, publishes health, commits, pushes. Idempotent, so a missed run repairs itself — see "How it runs unattended" |
| `scripts/health.py` | Operational record: which sources the unattended run actually got data from. Publishes `docs/data/health.json`, rendered as the site's Pipeline health panel |
| `docs/` | Static GitHub Pages site (leaderboard, weekly trend, pre-draft comparison) |

### Sources & coverage

| Source | Std | Half | PPR | Weekly | How |
|---|---|---|---|---|---|
| FantasyPros | ✓ | ✓ | ✓ | ✓ | embedded ecrData JSON, archive back to 2013 |
| Footballguys | | | ✓ | | staff consensus, ~530 players; only their default (PPR) board is reachable — the scoring presets are session-based, not URL-based |
| NFFC (ADP) | | | ✓ | | high-stakes money-league ADP via `adp.data.php`; the sharpest market board captured |
| Yahoo (ADP) | | ✓ | | | `draft_analysis.average_pick` — what Yahoo's drafters did, not what Yahoo's analysts said |
| ESPN (ADP) | | | ✓ | | `ownership.averageDraftPosition` |
| CBS (ADP) | | | ✓ | | the draft-averages table |
| Sleeper (projections) | ✓ | ✓ | ✓ | ✓ | `/projections/nfl/{season}/{week}`, 2018+ |
| ESPN | ✓ | ✓* | ✓ | ✓ | fantasy API; draft board 2023+, **weekly projections 2021+** (*half-PPR derived) |
| CBS Sports | ✓ | | ✓ | ✓ | HTML top-200 / positional pages |
| ~~NFL.com~~ | ✓ | | | ✓ | **retired Aug 2026** — research pages now 301 to a news feed and the research APIs 404; snapshots through 2025 are kept and still scored |
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

The three platform ADPs (Yahoo, ESPN, CBS) are each published as a **single
pooled figure**, not one per scoring format — ESPN returns byte-identical
numbers through its standard and PPR endpoints — so each is captured once
rather than relabelled three times to look like three sources.

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

### Which differences are real

A single season orders the sources, but it does not separate them: in 2025
half-PPR the top three weekly boards finished 0.263 / 0.263 / 0.251 Spearman
and 6.0 / 6.1 / 6.1 points of accuracy gap. Reporting that as a ranking would
be reporting noise.

So the durable comparison is made across all scored seasons, and it is
**paired**. Sources publish different seasons — FantasyPros covers 2013–25,
Sleeper 2018–25, ESPN 2023–25 — so their career averages are not taken over
the same games and cannot be ranked against each other directly. Instead each
source is compared with a reference source using only the weeks (or, for
pre-draft, the seasons) both actually covered, giving a mean difference and a
95% confidence interval. An interval containing zero is a difference the data
cannot establish.

The reference is chosen by a paired round robin: a source is eligible if no
other source beats it head-to-head, and among those the one with the most
observations is used, so the intervals are as tight as the evidence allows.
Picking the highest average instead would hand the yardstick to whichever
source had the shortest, luckiest record.

Two consequences are visible on the site and worth stating plainly:

- **Weekly, nothing separates.** Over 13 seasons FantasyPros, ESPN and Sleeper
  are all statistically tied. The one exception is ESPN over Sleeper on the 54
  weeks they share (+0.022, CI +0.004 to +0.040) — a pair that a
  compare-everyone-to-the-leader table would have hidden, since both are tied
  with the reference.
- **Pre-draft in standard, the experts do separate from the market.**
  FantasyPros beats MyFantasyLeague (−0.036, CI −0.063 to −0.008) and FF
  Calculator (−0.071, CI −0.106 to −0.035) across all 13 seasons.

Career averages are still shown, marked with an asterisk, because they
describe a source — they just cannot rank the field.

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

## How it runs unattended

The pipeline exists to need nothing weekly. That requires being explicit about
who does what, because the three parties involved fail in different ways.

| | Responsible for | Fails by |
|---|---|---|
| **Windows Task Scheduler** | making sure Python runs at all | not running (asleep, on battery, missed window) |
| **Python in this repo** | working out what is missing and getting it | a source changing shape |
| **Colin** | nothing weekly | — |
| **Claude** | fixing broken adapters, adding sources, retiring dead ones | not being there (summoned, not scheduled) |

### The runner asks "what is missing", not "what day is it"

`runner.py sync` is idempotent: every run works out what it does not have and
gets it. That is what makes a missed run survivable, and it is why the task
runs **daily** rather than on the two days the jobs used to be pinned to.

The old design pinned the weekly capture to Thursday. Weekly rankings are
perishable — CBS and FFToday publish the current week and nothing else — so a
Thursday the machine happened to be asleep took that week off those sources
permanently. It also had `StartWhenAvailable` off, meaning a missed run was
never retried, and `DisallowStartIfOnBatteries` on.

What can and cannot be repaired later is a property of the source:

| Data | Perishable? | Repairable |
|---|---|---|
| Actual points | no | any past week, from Sleeper |
| Pre-draft boards | frozen at week 1 | FantasyPros, FF Calculator, ESPN |
| Weekly rankings | **yes** | only FantasyPros, Sleeper, ESPN — they serve past weeks |
| Weekly rankings | **yes** | CBS, FFToday: current week only, gone if missed |

### Rankings are only captured before kickoff

A catch-up run must not quietly snapshot a board that has already watched the
games it is about to be scored on — that is the one way this project could
produce numbers that flatter every source. Weekly capture is therefore allowed
only between Tuesday and Thursday 17:00 ET, comfortably before Thursday night
kickoff. Outside that window the run holds off and logs why, and the week is
repaired later only from the sources that genuinely serve past weeks.

### Breakage is published, not logged

Sources break regularly and quietly: FantasyPros has changed its weekly schema,
ESPN its API shape, and NFL.com withdrew its rankings product entirely. A
broken scraper does not announce itself — it stops contributing while the rest
of the page carries on looking normal.

`scripts/health.py` records every capture outcome and publishes
`docs/data/health.json`, which the site renders as a **Pipeline health** panel.
A source that fails twice in a row is marked broken and raises a banner at the
top of the page. That record is the handover to Claude: dated, machine-written,
and specific enough to fix from without anyone having to diagnose it first.

Retiring a source is deliberately *not* automated — a 404 for a week is a site
having a bad day. `capture.RETIRED` records the decision with a date and a
reason, keeps the source's history, and stops attempting it.

### Register the schedule

```
powershell -ExecutionPolicy Bypass -File tasks
egister_tasks.ps1
```

Registers `NFL-Rankings-Sync` daily at 07:00 and 12:00 with the settings that
actually matter for unattended running: `StartWhenAvailable` (run a missed task
as soon as the machine is back), `WakeToRun`, retries on transient failure, and
no battery restriction.

## Manual runs

```
pip install -r requirements.txt
cd scripts
python capture.py predraft      # snapshot pre-draft boards
python capture.py weekly [wk]   # snapshot weekly rankings
python capture.py actuals [wk]  # pull actual points for a completed week
python compute.py [season|all]  # rebuild docs/data/{season}/*.json (+ seasons.json, history.json)
python history.py               # rebuild only the cross-season record
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

### The ESPN lane

ESPN publishes two different things and the app foregrounds the first:

- **ESPN RANK** — the editorial list you scroll on draft day. It comes from
  `draftRanksByRankType` on the `kona_player_info` endpoint, rank type `PPR`.
  Verified against a screenshot of the app's "2026 Fantasy Football Rankings"
  screen: the top ten match exactly, including the inversions that prove it is
  not a points sort (McCaffrey has the second-highest projection but ranks 7th,
  Taylor ranks 5th on a lower projection than Nacua at 4th).
- **ESPN ADP** — where the room actually takes him, from the ADP feed.

The board leads with the rank and keeps ADP alongside, and the red caret on the
range bar marks the **rank**, because that is the list in front of him when the
pick is on the clock.

### Draft day: picks, roster, needs

The board is two things at once, and the second one grew out of the first. It
started as an accuracy benchmark — thirteen seasons of rankings scored against
what actually happened — and the draft-day view is that benchmark pointed at
Sunday: the same consensus, plus where ESPN's room takes each player. The site
now commits to that, so a draft can be run off it rather than read off it.

Each row carries two pill buttons: **+ ROSTER** when you take a player, which
turns into **✓ ROSTER**, and **DRAFTED** when anyone else does. They are
exclusive — a player leaves the board once — and pressing the lit one is the
undo for a misclick on the clock. Yours tint green, everyone else's grey out and
strike through, and **Hide drafted** drops the gone so the list is only players
you can still have.

These were checkbox squares labelled ME and OUT first, and both halves of that
were wrong. No draft tool does it that way: FantasyPros' simulator puts a single
labelled `Draft` button on each row and its cheat sheets just strike drafted
players through, with a `Hide Drafted` checkbox over the list. On the clock you
read a word, not a tick state, and the word has to name what happens —
`+ ROSTER` is the panel he lands in, `DRAFTED` is what everyone else calls a
player who is off the board. Stacking the two pills rather than setting them
side by side also cut the column from 104px to 57px, which on a phone is the
difference between seeing the board and not.

A roster panel tracks the consequences. It fills your starting lineup from
`scripts/league.py` (nothing here hardcodes twelve teams or a lineup — the
league travels with the board in `predraft.json`), walking your picks in
consensus order and giving each his own position's slot, then FLEX, then the
bench. Below it: the starting spots still open, and the best players available
at one of those positions. On a phone it collapses to a bar carrying the count.

The phone landing was rebuilt around this. The board used to start 830px down a
812px screen — every pixel above it explanation you have already read by the
time you are drafting. The intro now clamps to two lines behind a `more`, the
legend folds into `How to read the board`, and the controls tighten, which puts
the board at 423px and six players on screen before any scrolling.

Picks live in `localStorage`, keyed by season. A draft is a two-hour event on
one device, there is no account here to sync to, and last year's roster turning
up on this year's board would be worse than no memory at all. Nothing about
pick state reaches the pipeline or the repo.

One wrinkle worth knowing: ESPN only publishes `STANDARD` and `PPR` rank types
— there is no half-PPR list, and the app's default rankings screen shows the
PPR order even for a half-PPR league. The projection *values* the app displays
are half-PPR: every one of the ten checked lands within ~1.4 points of
`(standard + PPR) / 2`, which is exactly half-PPR since half is standard plus
0.5/reception and PPR is standard plus 1.0. So the order is PPR and the points
are half-PPR, which is ESPN's behaviour, not ours.

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
- **MyFantasyLeague** — *reclassified Aug 2026.* Previously vouched for here as
  "QB-heavier than peers but a genuine 1QB board". It isn't a redraft board at
  all. MFL pools every league type its hosts run into one ADP export, and the
  `IS_KEEPER` and `FRANCHISES` filters are accepted and silently ignored (the
  same trap as RotoBaller's `season`). Measured against the consensus of the
  other 2026 PPR boards:

  | | |
  |---|---|
  | rookies | drafted **192 ranks earlier** on average (n=49) |
  | 5+ year veterans | drafted 41 ranks later (n=88) |
  | agreement with peers | **0.50**, against 0.87–0.95 for every other board |

  The disagreement is not a quarterback effect — excluding QBs it is 0.50,
  and QBs alone are 0.70. The biggest reaches are obscure rookie tight ends
  going 300+ picks early. That is dynasty and devy drafts in the pool. It is
  still captured and scored, but tagged `scope=dynasty-mixed` and kept out of
  the redraft consensus, the cross-season card and the leaderboards — the same
  reasoning that keeps Underdog's best ball out. The tag is applied by source
  rather than by snapshot, so all 13 seasons are reclassified, not just new
  captures.
- **Underdog** — best-ball ADP: no K or DST at all, and QB4 goes at pick 67
  against 49 on the redraft consensus. Tagged `bestball` and kept out of the
  redraft leaderboard, since scoring it against redraft outcomes would penalise
  it for correctly doing its own job.
