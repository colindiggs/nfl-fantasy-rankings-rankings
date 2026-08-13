"""Expectation model: P(player meets or beats his pre-draft consensus rank).

Unit of analysis: one player-season (QB/RB/WR/TE only, half-PPR baseline).
Target: 1 if the player's end-of-season positional finish was at least as good
as his pre-draft consensus positional rank (fin <= pre); a player who never
took the field scores 0.

Features (all measured BEFORE the season starts — no leakage):
  pre            pre-draft consensus positional rank
  age            at Sept 1, from nflverse rosters
  rookie         no prior NFL season
  years_exp      seasons of NFL experience
  team_change    on a different team than the season before
  turnover       share of his team's QB/RB/WR/TE roster new to the team
  prior_delta    last season's consensus miss (pre - fin; + = outperformed)
  prior_board    had a consensus rank last season
  prior_gp       games played last season
  prior_ppg      fantasy points per game last season
  inj_listed     weeks on an official injury report last season
  inj_out        weeks listed as Out last season
  pos_*          position indicators (QB reference)

Model: logistic regression, ridge penalty, fitted by IRLS on standardized
features. Validation is strictly out-of-time: train 2014-2022, test 2023-2025.
Writes docs/data/model.json: coefficients, test metrics, reliability table,
and predictions for the newest board.
"""
from datetime import date, datetime, timezone

import numpy as np

from common import DOCS, get_logger, read_json, write_json
import nflverse

log = get_logger("model")

# PPR is the modeling format: it is the only format with a multi-source
# consensus board in every captured season (2013+). Half-PPR consensus starts
# in 2018, which would halve the training data.
FMT = "ppr"
POS = ["QB", "RB", "WR", "TE"]
TRAIN_MAX = 2022

FEATURES = [
    ("pre", "Pre-draft consensus positional rank"),
    ("age", "Age at September 1"),
    ("rookie", "Rookie (no prior NFL season)"),
    ("years_exp", "Seasons of NFL experience"),
    ("team_change", "Changed team since last season"),
    ("turnover", "Share of team's skill roster new to the team"),
    ("prior_delta", "Prior-season consensus miss (+ = outperformed)"),
    ("prior_board", "Had a consensus rank last season"),
    ("prior_gp", "Games played last season"),
    ("prior_ppg", "Fantasy points per game last season"),
    ("inj_listed", "Weeks on the injury report last season"),
    ("inj_out", "Weeks listed Out last season"),
    ("pos_RB", "Position: RB"),
    ("pos_WR", "Position: WR"),
    ("pos_TE", "Position: TE"),
]


def _age(birth_date, season):
    try:
        y, m, d = (int(x) for x in birth_date.split("-"))
        return (date(season, 9, 1) - date(y, m, d)).days / 365.25
    except (AttributeError, ValueError, TypeError):
        return None


def build_rows(players, seasons):
    """One feature row per player-season with a consensus pre-draft rank."""
    rosters, gsis_maps, injuries, turnovers = {}, {}, {}, {}
    for s in seasons:
        for yr in (s, s - 1):
            if yr not in rosters:
                rosters[yr], gsis_maps[yr] = nflverse.roster_index(yr)
        if s - 1 not in injuries:
            injuries[s - 1] = nflverse.injury_weeks(s - 1, gsis_maps[s - 1])
        if s not in turnovers:
            turnovers[s] = nflverse.team_turnover(s)

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
            inj = injuries[s - 1].get(pid, {})
            age = _age(cur.get("birth_date") or prv.get("birth_date"), s)
            try:
                yexp = float(cur.get("years_exp"))
            except (TypeError, ValueError):
                yexp = None
            rookie = 1.0 if (yexp == 0 or (yexp is None and not prv)) else 0.0
            has_prior_board = 1.0 if prior.get("pre") is not None else 0.0
            prior_delta = ((prior["pre"] - prior["fin"])
                           if prior.get("pre") is not None and prior.get("fin") is not None
                           else 0.0)
            gp = prior.get("gp") or 0
            row = {
                "pid": pid, "name": p["name"], "pos": p["pos"], "season": s,
                "team": cur.get("team"),
                "pre": float(rec["pre"]),
                "age": age,
                "rookie": rookie,
                "years_exp": yexp if yexp is not None else (0.0 if rookie else None),
                "team_change": (1.0 if (cur.get("team") and prv.get("team")
                                        and cur["team"] != prv["team"]) else 0.0),
                "turnover": turnovers[s].get(cur.get("team")),
                "prior_delta": float(prior_delta),
                "prior_board": has_prior_board,
                "prior_gp": float(gp),
                "prior_ppg": (prior.get("pts", 0.0) / gp) if gp else 0.0,
                "inj_listed": float(inj.get("listed", 0)),
                "inj_out": float(inj.get("out", 0)),
                "pos_RB": 1.0 if p["pos"] == "RB" else 0.0,
                "pos_WR": 1.0 if p["pos"] == "WR" else 0.0,
                "pos_TE": 1.0 if p["pos"] == "TE" else 0.0,
                "fin": rec.get("fin"),
            }
            row["beat"] = 1.0 if (rec.get("fin") is not None
                                  and rec["fin"] <= rec["pre"]) else 0.0
            rows.append(row)
    return rows


def to_matrix(rows, means=None, stds=None):
    """Impute (column mean) and standardize; returns X, y, means, stds."""
    names = [f for f, _ in FEATURES]
    X = np.array([[r[f] if r[f] is not None else np.nan for f in names]
                  for r in rows], dtype=float)
    if means is None:
        means = np.nanmean(X, axis=0)
        stds = np.nanstd(X, axis=0)
        stds[stds == 0] = 1.0
    idx = np.where(np.isnan(X))
    X[idx] = np.take(means, idx[1])
    Xs = (X - means) / stds
    y = np.array([r["beat"] for r in rows], dtype=float)
    return Xs, y, means, stds


def fit_logistic(X, y, lam=1.0, iters=50):
    """Ridge logistic regression via IRLS. Returns (intercept, betas)."""
    n, k = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    beta = np.zeros(k + 1)
    pen = lam * np.eye(k + 1)
    pen[0, 0] = 0.0                      # don't shrink the intercept
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


def predict(X, b0, betas):
    return 1 / (1 + np.exp(-(b0 + X @ betas)))


def auc(y, p):
    order = np.argsort(p)
    ranks = np.empty(len(p))
    ranks[order] = np.arange(1, len(p) + 1)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    if not n1 or not n0:
        return None
    return float((ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


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


def main():
    payload = read_json(DOCS / "data" / "players.json")
    players = payload["players"]
    all_seasons = payload["seasons"]
    current = max(all_seasons)
    # label seasons: completed seasons with a prior season available for features
    label_seasons = [s for s in all_seasons if s > min(all_seasons) and s < current]

    rows = build_rows(players, label_seasons)
    train = [r for r in rows if r["season"] <= TRAIN_MAX]
    test = [r for r in rows if r["season"] > TRAIN_MAX]
    Xtr, ytr, means, stds = to_matrix(train)
    Xte, yte, _, _ = to_matrix(test, means, stds)
    b0, betas = fit_logistic(Xtr, ytr)
    pte = predict(Xte, b0, betas)
    ptr = predict(Xtr, b0, betas)

    metrics = {
        "train_seasons": [min(s["season"] for s in train), TRAIN_MAX],
        "test_seasons": [TRAIN_MAX + 1, max(s["season"] for s in test)],
        "n_train": len(train), "n_test": len(test),
        "base_rate_test": round(float(yte.mean()), 3),
        "auc_train": round(auc(ytr, ptr), 3),
        "auc_test": round(auc(yte, pte), 3),
        "brier_test": round(float(np.mean((pte - yte) ** 2)), 3),
    }
    log.info("model: %s", metrics)

    # predictions for the newest board
    cur_rows = build_rows(players, [current])
    pred_out = []
    if cur_rows:
        Xc, _, _, _ = to_matrix(cur_rows, means, stds)
        pc = predict(Xc, b0, betas)
        contrib = Xc * betas                     # signed contribution per feature
        names = [f for f, _ in FEATURES]
        for i, r in enumerate(cur_rows):
            top = np.argsort(-np.abs(contrib[i]))[:3]
            drivers = [{"f": names[j], "c": round(float(contrib[i][j]), 2)}
                       for j in top if abs(contrib[i][j]) > 0.05]
            pred_out.append({
                "id": r["pid"], "name": r["name"], "pos": r["pos"],
                "team": r["team"], "pre": int(r["pre"]),
                "p": round(float(pc[i]), 3), "drivers": drivers,
            })
        pred_out.sort(key=lambda x: -x["p"])

    write_json(DOCS / "data" / "model.json", {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "format": FMT, "positions": POS, "season": current,
        "target": "finish positional rank <= pre-draft consensus positional rank",
        "metrics": metrics,
        "coefficients": [
            {"f": f, "desc": d, "beta": round(float(b), 3)}
            for (f, d), b in zip(FEATURES, betas)],
        "intercept": round(float(b0), 3),
        "reliability_test": reliability(yte, pte),
        "predictions": pred_out,
    })
    log.info("model.json written: %d predictions", len(pred_out))


if __name__ == "__main__":
    main()
