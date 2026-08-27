"""Colin's actual ESPN league — the lens every draft-day number is computed in.

Confirmed 2026-08-26 from the league's own settings page: 12 teams, 15 roster
spots, 9 starters, half-PPR. The bench is 6 plus 2 IR, not the 7 that ESPN's
generic default implies.

Kept here rather than inline in compute.py so there is exactly one place to
change when the league changes, and so `pick_label` and `TEAMS` cannot drift
apart.
"""

TEAMS = 12

# starters, in the order ESPN lists them
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1}
FLEX_POS = ("RB", "WR", "TE")
BENCH = 6
IR = 2
ROSTER_SIZE = 15

FORMAT = "half_ppr"

# Scoring that differs from nothing — ESPN standard defaults, recorded so a
# later change is visible as a diff rather than a memory.
SCORING = {"pass_yds_per_pt": 25, "pass_td": 4, "int": -2,
           "rush_yds_per_pt": 10, "rush_td": 6, "rec": 0.5, "rec_td": 6}

# How many of each position the league starts in aggregate — the replacement
# level a draft board should be judged against. FLEX is not attributed to a
# single position here; it is spread across RB/WR/TE by usage downstream.
def starters_league_wide():
    return {pos: n * TEAMS for pos, n in STARTERS.items() if pos != "FLEX"}


def pick_label(overall, teams=TEAMS):
    """26.4 -> '3.03' — the round and slot a pick number lands on.

    Snake order is irrelevant to the label: pick 26 is in round 3 slot 2
    whichever direction that round runs.
    """
    if overall is None:
        return None
    n = max(1, int(round(float(overall))))
    rnd = (n - 1) // teams + 1
    slot = (n - 1) % teams + 1
    return f"{rnd}.{slot:02d}"
