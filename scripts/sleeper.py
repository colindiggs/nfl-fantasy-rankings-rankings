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
    """Return matcher dict: espn_id, (name,pos), and unambiguous name-only lookups."""
    by_espn = {}
    by_namepos = {}
    by_name = {}
    ambiguous = set()
    for pid, p in players.items():
        if p.get("espn_id"):
            by_espn[str(p["espn_id"])] = pid
        n = apply_alias(norm_name(p["name"]))
        key = (n, p["pos"])
        # prefer active players on name collisions
        if key not in by_namepos or p.get("active"):
            by_namepos[key] = pid
        if n in by_name and by_name[n] != pid:
            prev = players[by_name[n]]
            if p.get("active") and not prev.get("active"):
                by_name[n] = pid
            elif prev.get("active") and not p.get("active"):
                pass
            else:
                ambiguous.add(n)
        else:
            by_name[n] = pid
    for n in ambiguous:
        by_name.pop(n, None)
    return {"espn": by_espn, "namepos": by_namepos, "name": by_name, "db": players}


def match_player(matchers, name=None, pos=None, espn_id=None):
    if espn_id and str(espn_id) in matchers["espn"]:
        return matchers["espn"][str(espn_id)]
    if name:
        n = apply_alias(norm_name(name))
        if pos:
            pid = matchers["namepos"].get((n, pos))
            if pid:
                return pid
        return matchers["name"].get(n)
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
