"""WalterFootball fantasy rankings — per-position paginated HTML pages, draft only.

One list per position (his own projections, standard-ish scoring) -> standard.
"""
import html as htmllib
import re

from common import fetch, get_logger

log = get_logger("walter")

PAGES = {
    "QB": ["fantasy{y}quarterbacks.php", "fantasy{y}quarterbacks_2.php", "fantasy{y}quarterbacks_3.php"],
    "RB": ["fantasy{y}runningbacks.php", "fantasy{y}runningbacks_2.php",
           "fantasy{y}runningbacks_3.php", "fantasy{y}runningbacks_4.php"],
    "WR": ["fantasy{y}widereceivers.php", "fantasy{y}widereceivers_2.php", "fantasy{y}widereceivers_3.php",
           "fantasy{y}widereceivers_4.php", "fantasy{y}widereceivers_5.php"],
    "TE": ["fantasy{y}tightends.php", "fantasy{y}tightends_2.php", "fantasy{y}tightends_3.php"],
}

BASE = "https://walterfootball.com/"

ENTRY_RE = re.compile(
    r"(\d+)\.\s*<b>(?:<img[^>]*>)?\s*([^,<]+?),\s*(QB|RB|WR|TE),\s*([A-Za-z0-9 .]+?)\.",
)


def fetch_draft(fmt, season, sess=None):
    if fmt != "standard":
        raise RuntimeError("WalterFootball publishes one list per position — standard only")
    out = []
    for pos, pages in PAGES.items():
        rows = {}
        for page in pages:
            url = BASE + page.format(y=season)
            try:
                html = fetch(url, sess=sess).text
            except RuntimeError:
                break  # later pages may not exist yet
            for m in ENTRY_RE.finditer(html):
                rank, name, p = int(m.group(1)), htmllib.unescape(m.group(2)).strip(), m.group(3)
                if p == pos and rank not in rows:
                    rows[rank] = {"rank": rank, "name": name, "team": None, "pos": pos}
        out.extend(rows[r] for r in sorted(rows))
    if len(out) < 40:
        raise RuntimeError(f"Walter parse yielded only {len(out)} players")
    return {"players": out, "meta": {"count": len(out)}}
