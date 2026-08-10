"""Sleeper API: NFL state, player database (for cross-site ID matching), weekly stats."""
from common import DATA, apply_alias, fetch, get_logger, norm_name, read_json, write_json

log = get_logger("sleeper")

BASE = "https://api.sleeper.app/v1"

PLAYERS_CACHE = DATA / "players" / "sleeper_players.json"

KEEP_POS = {"QB", "RB", "WR", "TE", "K"}


def get_state():
    return fetch(f"{BASE}/state/nfl").json()


def refresh_players():
    """Download and trim the Sleeper player DB (~5MB raw). Keeps skill positions."""
    raw = fetch(f"{BASE}/players/nfl", timeout=90).json()
    trimmed = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        pos = p.get("position")
        if pos not in KEEP_POS:
            continue
        trimmed[pid] = {
            "name": p.get("full_name") or f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "pos": pos,
            "team": p.get("team"),
            "espn_id": p.get("espn_id"),
            "active": p.get("active", False),
        }
    write_json(PLAYERS_CACHE, trimmed)
    log.info("players cache refreshed: %d players", len(trimmed))
    return trimmed


def load_players():
    players = read_json(PLAYERS_CACHE)
    if not players:
        players = refresh_players()
    return players


def build_matchers(players):
    """Return (by_espn, by_namepos) lookup dicts -> sleeper_id."""
    by_espn = {}
    by_namepos = {}
    for pid, p in players.items():
        if p.get("espn_id"):
            by_espn[str(p["espn_id"])] = pid
        key = (norm_name(p["name"]), p["pos"])
        # prefer active players on name collisions
        if key not in by_namepos or p.get("active"):
            by_namepos[key] = pid
    return by_espn, by_namepos


def match_player(by_espn, by_namepos, name=None, pos=None, espn_id=None):
    if espn_id and str(espn_id) in by_espn:
        return by_espn[str(espn_id)]
    if name and pos:
        n = apply_alias(norm_name(name))
        return by_namepos.get((n, pos))
    return None


def get_week_stats(season, week):
    """Actual fantasy points for a completed week, all three formats."""
    raw = fetch(f"{BASE}/stats/nfl/regular/{season}/{week}", timeout=60).json()
    out = {}
    for pid, st in raw.items():
        if not isinstance(st, dict):
            continue
        pts = {
            "standard": st.get("pts_std"),
            "half_ppr": st.get("pts_half_ppr"),
            "ppr": st.get("pts_ppr"),
        }
        if any(v is not None for v in pts.values()):
            out[pid] = {k: (v or 0.0) for k, v in pts.items()}
    return out
