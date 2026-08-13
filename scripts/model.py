"""Expectation models: value over draft slot, in points and in probability.

Unit of analysis: one player-season (QB/RB/WR/TE, PPR consensus boards —
the only format with a multi-source consensus in every captured season).

Two targets, same pre-season features:

  POE (headline)  points over expectation: season fantasy points minus the
                  points the player's pre-draft consensus slot has historically
                  produced (rank-value curve, kind="season"). Measured in
                  fantasy points, so a superstar season counts for far more
                  than narrowly clearing a rank — beating your slot by ten
                  ranks and 5 points is not the same as a 120-point blowout.
                  Fitted by ridge linear regression.
  P(beat)         probability the player finishes at or better than his slot
                  in positional-rank terms. Ridge logistic regression.

Features (all known before kickoff):
  pre, implied_pts       consensus positional rank and its historical value
  age, age_c2, age_rb    age, (age-26)^2 aging curve, RB-specific aging
  rookie, years_exp      experience
  draft_round, log_pick  NFL draft capital (undrafted = round 8 / pick 300)
  team_change, turnover  player moved; share of team skill roster that is new
  prior_poe              last season's points over expectation
  prior_board, prior_gp, prior_ppg
  prior2_gp              games played two seasons ago (durability trend)
  inj_listed, inj_out    injury-report weeks last season
  pos_RB/WR/TE           position indicators (QB reference)

Validation is strictly out-of-time: train 2014-2022, test 2023-2025.
Writes docs/data/model.json.
"""
from datetime import date, datetime, timezone

import numpy as np

from common import DOCS, get_logger, read_json, write_json
import compute
import nflverse
import rankvalue

log = get_logger("model")

FMT = "ppr"
POS = ["QB", "RB", "WR", "TE"]
TRAIN_MAX = 2022
UNDRAFTED_ROUND, UNDRAFTED_PICK = 8.0, 300.0

FEATURES = [
    ("pre", "Pre-draft consensus positional rank"),
    ("implied_pts", "Historical season points for that slot"),
    ("age", "Age at September 1"),
    ("age_c2", "(Age - 26) squared: aging curve"),
    ("age_rb", "(Age - 26) x RB: RB-specific aging"),
    ("rookie", "Rookie (no prior NFL season)"),
    ("years_exp", "Seasons of NFL experience"),
    ("draft_round", "NFL draft round (8 = undrafted)"),
    ("log_pick", "log(overall draft pick) (300 = undrafted)"),
    ("team_change", "Changed team since last season"),
    ("turnover", "Share of team's skill roster new to the team"),
    ("prior_poe", "Prior-season points over slot expectation"),
    ("prior_board", "Had a consensus rank last season"),
    ("prior_gp", "Games played last season"),
    ("prior_ppg", "Fantasy points per game last season"),
    ("prior2_gp", "Games played two seasons ago"),
    ("inj_listed", "Weeks on the injury report last season"),
    ("inj_out", "Weeks listed Out last season"),
    ("pos_RB", "Position: RB"),
    ("pos_WR", "Position: WR"),
    ("pos_TE", "Position: TE"),
]
NAMES = [f for f, _ in FEATURES]


def _age(birth_date, season):
    try:
        y, m, d = (int(x) for x in birth_date.split("-"))
        return (date(season, 9, 1) - date(y, m, d)).days / 365.25
    except (AttributeError, ValueError, TypeError):
        return None


def _implied(pos, rank):
    v = rankvalue.points_for_rank(compute.CURVE, "season", FMT, pos, int(rank))
    return float(v) if v is not None else None


def _poe(rec, pos):
    """Season points minus slot expectation; None without a consensus slot."""
    if rec.get("pre") is None:
        return None
    imp = _implied(pos, rec["pre"])
    if imp is None:
        return None
    return float(rec.get("pts") or 0.0) - imp


def build_rows(players, seasons):
    rosters, gsis_maps, injuries, turnovers = {}, {}, {}, {}
    for s in seasons:
        for yr in (s, s - 1):
            if yr not in rosters:
                rosters[yr], gsis_maps[yr] = nflverse.roster_index(yr)
        if s - 1 not in injuries:
            injuries[s - 1] = nflverse.injury_weeks(s - 1, gsis_maps[s - 1])
        if s not in turnovers:
            turnovers[s] = nflverse.team_turnover(s)
    merged_gsis = {}
    for m in gsis_maps.values():
        merged_gsis.update(m)
    draft = nflverse.draft_index(merged_gsis)

    rows = []
    for pid, p in players.items():
        if p.get("pos") not in POS:
            continue
        for s in seasons:
            rec = (p["seasons"].get(str(s)) or {}).get(FMT)
            if not rec or rec.get("pre") is None:
                continue
            cur = rosters[s].get(pid, {})
            prv = rosters[s - 1].get(pid, {})
            prior = (p["seasons"].get(str(s - 1)) or {}).get(FMT) or {}
            prior2 = (p["seasons"].get(str(s - 2)) or {}).get(FMT) or {}
            inj = injuries[s - 1].get(pid, {})
            dft = draft.get(pid, {})
            age = _age(cur.get("birth_date") or prv.get("birth_date"), s)
            try:
                yexp = float(cur.get("years_exp"))
            except (TypeError, ValueError):
                yexp = None
            rookie = 1.0 if (yexp == 0 or (yexp is None and not prv)) else 0.0
            gp = prior.get("gp") or 0
            prior_poe = _poe(prior, p["pos"])
            row = {
                "pid": pid, "name": p["name"], "pos": p["pos"], "season": s,
                "team": cur.get("team"),
                "pre": float(rec["pre"]),
                "implied_pts": _implied(p["pos"], rec["pre"]),
                "age": age,
                "age_c2": (age - 26.0) ** 2 if age is not None else None,
                "age_rb": ((age - 26.0) if age is not None else 0.0)
                          * (1.0 if p["pos"] == "RB" else 0.0),
                "rookie": rookie,
                "years_exp": yexp if yexp is not None else (0.0 if rookie else None),
                # a player in a roster but absent from the draft file is
                # genuinely undrafted; absent from both, draft capital is
                # unknown and left to mean imputation rather than punished
                "draft_round": (float(dft["round"]) if dft
                                else UNDRAFTED_ROUND if (cur or prv) else None),
                "log_pick": (float(np.log(dft["pick"])) if dft
                             else float(np.log(UNDRAFTED_PICK)) if (cur or prv)
                             else None),
                "team_change": (1.0 if (cur.get("team") and prv.get("team")
                                        and cur["team"] != prv["team"]) else 0.0),
                "turnover": turnovers[s].get(cur.get("team")),
                "prior_poe": prior_poe if prior_poe is not None else 0.0,
                "prior_board": 1.0 if prior.get("pre") is not None else 0.0,
                "prior_gp": float(gp),
                "prior_ppg": (prior.get("pts", 0.0) / gp) if gp else 0.0,
                "prior2_gp": float(prior2.get("gp") or 0),
                "inj_listed": float(inj.get("listed", 0)),
                "inj_out": float(inj.get("out", 0)),
                "pos_RB": 1.0 if p["pos"] == "RB" else 0.0,
                "pos_WR": 1.0 if p["pos"] == "WR" else 0.0,
                "pos_TE": 1.0 if p["pos"] == "TE" else 0.0,
            }
            row["beat"] = 1.0 if (rec.get("fin") is not None
                                  and rec["fin"] <= rec["pre"]) else 0.0
            row["poe"] = _poe(rec, p["pos"])
            if row["poe"] is None:
                continue
            rows.append(row)
    return rows


def to_matrix(rows, means=None, stds=None):
    X = np.array([[r[f] if r[f] is not None else np.nan for f in NAMES]
                  for r in rows], dtype=float)
    if means is None:
        means = np.nanmean(X, axis=0)
        stds = np.nanstd(X, axis=0)
        stds[stds == 0] = 1.0
    idx = np.where(np.isnan(X))
    X[idx] = np.take(means, idx[1])
    return (X - means) / stds, means, stds


def fit_logistic(X, y, lam=1.0, iters=50):
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = lam * np.eye(k + 1)
    pen[0, 0] = 0.0
    for _ in range(iters):
        eta = Xb @ beta
        p = 1 / (1 + np.exp(-eta))
        w = np.clip(p * (1 - p), 1e-6, None)
        z = eta + (y - p) / w
        WX = Xb * w[:, None]
        new = np.linalg.solve(Xb.T @ WX + pen, Xb.T @ (w * z))
        if np.max(np.abs(new - beta)) < 1e-8:
            beta = new
            break
        beta = new
    return beta[0], beta[1:]


def fit_ridge(X, y, lam=10.0):
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    pen = lam * np.eye(k + 1)
    pen[0, 0] = 0.0
    beta = np.linalg.solve(Xb.T @ Xb + pen, Xb.T @ y)
    return beta[0], beta[1:]


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    if not n1 or not n0:
        return None
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def spearman_np(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    ra -= ra.mean(); rb -= rb.mean()
    den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / den) if den else None


def reliability(y, p, bins=10):
    out = []
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    for i in range(bins):
        m = (p >= edges[i]) & (p <= edges[i + 1] if i == bins - 1 else p < edges[i + 1])
        if m.sum() < 5:
            continue
        out.append({"p_mean": round(float(p[m].mean()), 3),
                    "obs_rate": round(float(y[m].mean()), 3),
                    "n": int(m.sum())})
    return out


def quintiles(pred, actual, bins=5):
    """Mean actual POE by predicted-POE quintile — the regression's report card."""
    edges = np.quantile(pred, np.linspace(0, 1, bins + 1))
    out = []
    for i in range(bins):
        m = (pred >= edges[i]) & (pred <= edges[i + 1] if i == bins - 1 else pred < edges[i + 1])
        if not m.sum():
            continue
        out.append({"q": i + 1,
                    "pred_mean": round(float(pred[m].mean()), 1),
                    "obs_mean": round(float(actual[m].mean()), 1),
                    "n": int(m.sum())})
    return out


def main():
    compute.load_curve()
    payload = read_json(DOCS / "data" / "players.json")
    players = payload["players"]
    all_seasons = payload["seasons"]
    current = max(all_seasons)
    label_seasons = [s for s in all_seasons if s > min(all_seasons) and s < current]

    rows = build_rows(players, label_seasons)
    train = [r for r in rows if r["season"] <= TRAIN_MAX]
    test = [r for r in rows if r["season"] > TRAIN_MAX]
    Xtr, means, stds = to_matrix(train)
    Xte, _, _ = to_matrix(test, means, stds)
    ytr_c = np.array([r["beat"] for r in train])
    yte_c = np.array([r["beat"] for r in test])
    ytr_r = np.array([r["poe"] for r in train])
    yte_r = np.array([r["poe"] for r in test])

    b0c, bc = fit_logistic(Xtr, ytr_c)
    b0r, br = fit_ridge(Xtr, ytr_r)
    pte = sigmoid(b0c + Xte @ bc)
    poe_te = b0r + Xte @ br
    ss_res = float(((yte_r - poe_te) ** 2).sum())
    ss_tot = float(((yte_r - ytr_r.mean()) ** 2).sum())

    metrics = {
        "train_seasons": [min(r["season"] for r in train), TRAIN_MAX],
        "test_seasons": [TRAIN_MAX + 1, max(r["season"] for r in test)],
        "n_train": len(train), "n_test": len(test),
        "cls": {
            "base_rate": round(float(yte_c.mean()), 3),
            "auc": round(auc(yte_c, pte), 3),
            "brier": round(float(np.mean((pte - yte_c) ** 2)), 3),
        },
        "reg": {
            "r2": round(1 - ss_res / ss_tot, 3),
            "mae": round(float(np.abs(yte_r - poe_te).mean()), 1),
            "spearman": round(spearman_np(poe_te, yte_r), 3),
            "sd_actual": round(float(yte_r.std()), 1),
        },
    }
    log.info("model: %s", metrics)

    cur_rows = build_rows(players, [current])
    pred_out = []
    # Slot terms (rank, its historical value, position) carry the mean-reversion
    # baseline every player at that slot shares. The PLAYER-SPECIFIC edge is the
    # sum of the remaining contributions — age, durability, draft capital,
    # injuries, prior over/under-delivery — and is the number that separates two
    # players drafted next to each other.
    slot_idx = [NAMES.index(f) for f in
                ("pre", "implied_pts", "pos_RB", "pos_WR", "pos_TE")]
    player_idx = [j for j in range(len(NAMES)) if j not in slot_idx]
    if cur_rows:
        Xc, _, _ = to_matrix(cur_rows, means, stds)
        pc = sigmoid(b0c + Xc @ bc)
        poec = b0r + Xc @ br
        contrib = Xc * br               # regression contributions, in points
        for i, r in enumerate(cur_rows):
            pcontrib = [(j, contrib[i][j]) for j in player_idx]
            pcontrib.sort(key=lambda t: -abs(t[1]))
            drivers = [{"f": NAMES[j], "c": round(float(c), 1)}
                       for j, c in pcontrib[:3] if abs(c) > 2.0]
            pred_out.append({
                "id": r["pid"], "name": r["name"], "pos": r["pos"],
                "team": r["team"], "pre": int(r["pre"]),
                "implied": round(r["implied_pts"], 0) if r["implied_pts"] else None,
                "p": round(float(pc[i]), 3),
                "poe": round(float(poec[i]), 1),
                "edge": round(float(sum(c for _j, c in pcontrib)), 1),
                "drivers": drivers,
            })
        pred_out.sort(key=lambda x: -x["edge"])

    write_json(DOCS / "data" / "model.json", {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": FMT, "positions": POS, "season": current,
        "targets": {
            "poe": "season fantasy points minus the historical value of the pre-draft slot",
            "beat": "P(finish positional rank <= pre-draft consensus positional rank)",
        },
        "metrics": metrics,
        "coefficients": [
            {"f": f, "desc": d,
             "beta_reg": round(float(brv), 2), "beta_cls": round(float(bcv), 3)}
            for (f, d), brv, bcv in zip(FEATURES, br, bc)],
        "intercepts": {"reg": round(float(b0r), 2), "cls": round(float(b0c), 3)},
        "reliability_test": reliability(yte_c, pte),
        "quintiles_test": quintiles(poe_te, yte_r),
        "predictions": pred_out,
    })
    log.info("model.json written: %d predictions", len(pred_out))


if __name__ == "__main__":
    main()
