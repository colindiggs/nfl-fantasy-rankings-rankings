"""Shared utilities: HTTP session, paths, name normalization, JSON I/O."""
import json
import logging
import re
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
LOGS = ROOT / "logs"

SEASON = None  # resolved at runtime from Sleeper state

FORMATS = ["standard", "half_ppr", "ppr"]

# Positions scored by the benchmark. SKILL_POSITIONS drive the headline
# leaderboard (comparable across every source); K/DST are scored identically but
# reported separately — coverage is patchier and week-to-week results are far
# more luck-driven, which is why FantasyPros' own accuracy competitions compute
# them and then leave them out of "Overall".
SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]
EXTRA_POSITIONS = ["K", "DST"]
POSITIONS = SKILL_POSITIONS + EXTRA_POSITIONS

# Everything sites call these two positions, mapped to our canonical labels.
POS_FIX = {
    "DEF": "DST", "D": "DST", "D/ST": "DST", "DST": "DST", "D-ST": "DST",
    "TMDEF": "DST", "TEAM DEF": "DST", "DEFENSE": "DST",
    "PK": "K", "K": "K", "KICKER": "K",
}
VALID_POS = set(POSITIONS)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def get_logger(name):
    LOGS.mkdir(exist_ok=True)
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOGS / "run.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


log = get_logger("common")


def session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    return s


def fetch(url, sess=None, retries=3, timeout=30, **kwargs):
    sess = sess or session()
    last = None
    for attempt in range(retries):
        try:
            r = sess.get(url, timeout=timeout, **kwargs)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"fetch failed for {url}: {last}")


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name):
    """Normalize a player name for cross-site matching."""
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = name.replace("-", " ")
    name = re.sub(r"[.'’]", "", name)
    parts = [p for p in re.split(r"\s+", name.strip()) if p and p not in SUFFIXES]
    return " ".join(parts)


# Synonym groups for names sites disagree on. apply_alias canonicalizes to the
# first entry of each group and is applied to BOTH the scraped name and the
# Sleeper index, so direction never matters.
ALIAS_GROUPS = [
    ["gabe davis", "gabriel davis"],
    ["josh palmer", "joshua palmer"],
    ["jeff wilson", "jeffery wilson"],
    ["cam ward", "cameron ward"],
    ["hollywood brown", "marquise brown"],
    ["chig okonkwo", "chigoziem okonkwo"],
    ["kenny gainwell", "kenneth gainwell"],
    ["kyle monangai", "kyle monanagi"],
    ["jonathon brooks", "jonathan brooks"],
    ["andy borregales", "andres borregales"],  # brother Jose is also a K in the DB
]

ALIASES = {}
for group in ALIAS_GROUPS:
    for variant in group[1:]:
        ALIASES[variant] = group[0]


def apply_alias(n):
    return ALIASES.get(n, n)


def normalize_pos(pos):
    """Canonicalize a scraped position label, or None if it isn't one we score.

    Handles the DEF/D/D-ST and PK spellings, and strips positional-rank suffixes
    ("RB1" -> "RB", "DST3" -> "DST").
    """
    if not pos:
        return None
    p = str(pos).strip().upper().replace(".", "")
    p = POS_FIX.get(p, p)
    p = re.sub(r"\d+$", "", p).strip()
    p = POS_FIX.get(p, p)
    return p if p in VALID_POS else None
