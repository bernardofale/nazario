#!/usr/bin/env python3
"""Fetch player stats from footymetrics for all major WC-feeder leagues.

For every league and every (tab, stat, sort) view, walks the paginated
endpoint until `pagination.pages` is exhausted and saves the combined
records to data/raw/footymetrics/{league}_{tab}.json (skipped if the file
already exists — delete a file to refetch it).

Run:  python3 src/fetch_footymetrics.py            # fetch everything
      python3 src/fetch_footymetrics.py laliga     # one league only
"""
import json
import sys
import time
import urllib.error
import urllib.request

from common import RAW

OUT_DIR = RAW / "footymetrics"
BASE = ("https://www.footymetrics.com/api/front/leagues/stats/players"
        "?lg={lg}&sid={sid}&tab={tab}&stat={stat}&loc=overall&sort={sort}&page={page}")

LEAGUES = {  # league -> (lg, sid)
    "bundesliga":     (82, 1109),
    "laliga":         (564, 1151),
    "ligaportugal":   (462, 1166),
    "serieA":         (384, 977),
    "saudi":          (944, 13511),
    "ligue1":         (301, 1104),
    "premierleague":  (8, 987),
    "turkishleague":  (600, 1154),
    "mls":            (779, 90992),
    "championship":   (9, 1066),
    "eredivise":      (72, 995),
}
VIEWS = [  # (tab, stat, sort) — stat must match the sort key's base,
    # e.g. defensive 400s with stat=tackles but works with stat=tacklesAvg
    ("offensive", "goals", "goals-d"),
    ("defensive", "tacklesAvg", "tacklesAvg-d"),
    ("passing", "passesAvg", "passesAvg-d"),
]
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.footymetrics.com/",
    "X-Requested-With": "XMLHttpRequest",
}
DELAY_S = 0.6
RETRIES = 3


def get_json(url):
    last_err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            wait = 2 ** attempt
            print(f"    retry {attempt + 1}/{RETRIES} in {wait}s — {e}")
            time.sleep(wait)
    raise RuntimeError(f"giving up on {url}: {last_err}")


def find_pagination(payload):
    """Locate the pagination object wherever the API nests it."""
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "pagination" in node and isinstance(node["pagination"], dict):
                return node["pagination"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return {}


def fetch_view(league, lg, sid, tab, stat, sort):
    pages_payloads = []
    page, total_pages = 1, None
    while total_pages is None or page <= total_pages:
        url = BASE.format(lg=lg, sid=sid, tab=tab, stat=stat, sort=sort, page=page)
        payload = get_json(url)
        pages_payloads.append(payload)
        if total_pages is None:
            pg = find_pagination(payload)
            total_pages = int(pg.get("pages") or 1)
            print(f"    {tab}: {total_pages} pages "
                  f"(pagination: { {k: pg[k] for k in list(pg)[:4]} })")
        page += 1
        time.sleep(DELAY_S)
    return pages_payloads


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for league, (lg, sid) in LEAGUES.items():
        if only and league != only:
            continue
        for tab, stat, sort in VIEWS:
            out = OUT_DIR / f"{league}_{tab}.json"
            if out.exists():
                print(f"  {league}/{tab}: exists, skipping")
                continue
            print(f"  {league}/{tab}: fetching…")
            payloads = fetch_view(league, lg, sid, tab, stat, sort)
            json.dump({"league": league, "lg": lg, "sid": sid, "tab": tab,
                       "stat": stat, "sort": sort, "pages": payloads},
                      open(out, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"    -> {out.name} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
