#!/usr/bin/env python3
"""Curate live World Cup 2026 player form from the club-stats provider's
'worldcup' dumps (offensive / defensive / passing) into a per-player table.

Output: data/processed/wc_player_form.csv keyed by (fifa_code, name_norm),
with per-90 goals/assists and tournament minutes/rating. Consumed by
squad_quality.py to blend actual tournament output into the attack index —
the strongest available signal for who is producing *now*.

The provider's 'team' field is the player's CLUB; nationality comes from the
flag filename (same scheme as curate_club_stats.py), mapped to a FIFA code
for the 48 qualified squads.
"""
from collections import defaultdict

from common import RAW, GAME, PROCESSED, norm_name, load_json, write_csv

LEAGUE = "worldcup"
TABS = ("offensive", "defensive", "passing")

FLAG_ALIASES = {
    "united states": "usa", "korea republic": "south korea",
    "turkiye": "turkey", "ir iran": "iran", "cote divoire": "ivory coast",
    "cabo verde": "cape verde", "congo dr": "democratic republic of the congo",
    "czechia": "czech republic",
}

COLUMNS = ["fifa_code", "name", "name_norm", "club", "mins", "appearances",
           "started", "goals", "assists", "rating", "goals_p90", "assists_p90",
           "sot_avg", "keyp_avg"]


def _squad_code_by_flag():
    lookup = {}
    for s in load_json(GAME / "squads.json"):
        n = norm_name(s["name"])
        lookup[n] = s["abbr"]
    for alias, target in FLAG_ALIASES.items():
        if norm_name(target) in lookup:
            lookup[norm_name(alias)] = lookup[norm_name(target)]
        if norm_name(alias) in lookup:
            lookup[norm_name(target)] = lookup[norm_name(alias)]
    return lookup


def _flag_country(row):
    flag = row.get("flag") or ""
    name = flag.rsplit("/", 1)[-1].rsplit("_", 1)[0]
    return norm_name(name.replace("-", " "))


def _num(row, key):
    v = row.get(key)
    try:
        return float(v) if v not in (None, "", "-") else 0.0
    except (ValueError, TypeError):
        return 0.0


def curate():
    flag_codes = _squad_code_by_flag()
    merged = defaultdict(dict)
    for tab in TABS:
        path = RAW / "club_stats" / f"{LEAGUE}_{tab}.json"
        if not path.exists():
            print(f"  ! missing {path.name}")
            continue
        for page in load_json(path)["pages"]:
            for row in page["data"]:
                merged[row["Player"]["slug"]].update(row)

    rows = []
    for slug, r in merged.items():
        # NB: the provider's 'flag' is the player's CLUB country and is often
        # wrong for nationality (e.g. Haaland tagged england_GB). It is kept as
        # a best-effort hint only — squad_quality joins on NAME and takes the
        # real nationality from players.json.
        code = flag_codes.get(_flag_country(r)) or ""
        mins = _num(r, "mins")
        if mins <= 0:
            continue
        name = r["Player"].get("shortName") or slug.split("/")[-1].replace("-", " ")
        goals, assists = _num(r, "goals"), _num(r, "assists")
        p90 = 90.0 / mins
        rows.append({
            "fifa_code": code, "name": name, "name_norm": norm_name(name),
            "club": (r.get("team") or {}).get("name", ""),
            "mins": int(mins), "appearances": int(_num(r, "appearances")),
            "started": int(_num(r, "started")),
            "goals": int(goals), "assists": int(assists),
            "rating": round(_num(r, "ratingAvg"), 2),
            "goals_p90": round(goals * p90, 3),
            "assists_p90": round(assists * p90, 3),
            "sot_avg": round(_num(r, "sotAvg"), 2),
            "keyp_avg": round(_num(r, "keypAvg"), 2),
        })
    write_csv(PROCESSED / "wc_player_form.csv", rows, COLUMNS)
    print(f"  -> wc_player_form.csv ({len(rows)} players with WC minutes)")
    return rows


if __name__ == "__main__":
    curate()
