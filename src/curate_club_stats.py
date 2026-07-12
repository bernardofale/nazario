#!/usr/bin/env python3
"""Merge the club-stats provider dumps (data/raw/club_stats/{league}_{tab}.json)
into common club-stats rows.

Per league there are three tab files (offensive / defensive / passing), each
paginated and each covering a different subset of players — merged here on
the Player slug. Leagues already covered by richer sources (Premier League,
Ligue 1 JSONs with xG; La Liga tables with penalty detail) are skipped so the
crosswalk never sees duplicate candidate rows for one player.

Quirks: the API reports per-appearance averages, so totals are reconstructed
as avg x appearances; player full names come from the slug (shortName is
abbreviated); nationality comes from the flag URL filename and is mapped to
a FIFA code only for the 48 qualified squads (others stay blank = no guard).
"""
from collections import defaultdict

from common import RAW, GAME, norm_name, load_json

OUT_LEAGUE_NAMES = {
    "bundesliga": "Bundesliga", "serieA": "Serie A",
    "ligaportugal": "Liga Portugal", "saudi": "Saudi Pro League",
    "turkishleague": "Super Lig", "mls": "MLS",
    "championship": "Championship", "eredivise": "Eredivisie",
    # skipped (better sources exist): premierleague, ligue1, laliga
}
SKIP = {"premierleague", "ligue1", "laliga"}

# flag-name aliases where the filename differs from the squad name
FLAG_ALIASES = {
    "united states": "usa", "south korea": "south korea",
    "korea republic": "south korea", "turkiye": "turkey",
    "ir iran": "iran", "cote divoire": "ivory coast",
    "cabo verde": "cape verde",
}


def squad_code_by_flag():
    """norm flag-country-name -> FIFA code for the 48 qualified squads."""
    lookup = {}
    for s in load_json(GAME / "squads.json"):
        n = norm_name(s["name"])
        lookup[n] = s["abbr"]
        for alias, target in FLAG_ALIASES.items():
            if target == n:
                lookup[alias] = s["abbr"]
            if alias == n:
                lookup[target] = s["abbr"]
    return lookup


def flag_country(row):
    flag = row.get("flag") or ""
    name = flag.rsplit("/", 1)[-1].rsplit("_", 1)[0]
    return norm_name(name.replace("-", " "))


def merge_league(league):
    players = defaultdict(dict)
    for tab in ("offensive", "defensive", "passing"):
        path = RAW / "club_stats" / f"{league}_{tab}.json"
        if not path.exists():
            print(f"  ! missing {path.name}")
            continue
        for page in load_json(path)["pages"]:
            for row in page["data"]:
                slug = row["Player"]["slug"]
                players[slug].update(row)
    return players


def slug_to_name(slug):
    return " ".join(w.capitalize() for w in slug.split("/")[-1].split("-"))


def num(row, key):
    v = row.get(key)
    return float(v) if v not in (None, "") else 0.0


def curate():
    flag_codes = squad_code_by_flag()
    rows = []
    for league, pretty in OUT_LEAGUE_NAMES.items():
        merged = merge_league(league)
        for slug, r in merged.items():
            apps = num(r, "appearances")
            mins = num(r, "mins")
            if not apps:
                continue
            name = slug_to_name(slug)
            row = {
                "league": pretty,
                "player_id": "cs:" + slug.split("/")[0],
                "player_name": name,
                "player_name_norm": norm_name(name),
                "club": (r.get("team") or {}).get("name"),
                "position": "",  # tabs don't expose position
                "nation": flag_codes.get(flag_country(r), ""),
                "appearances": int(apps),
                "minutes": mins,
                "goals": num(r, "goals"),
                "assists": num(r, "assists"),
                "xg": None, "npxg": None, "xa": None,
                "shots_on_target": round(num(r, "sotAvg") * apps, 1),
                "shots_off_target": round(
                    max(num(r, "shAvg") - num(r, "sotAvg"), 0) * apps, 1),
                "key_passes": round(num(r, "keypAvg") * apps, 1),
                "big_chances_created": round(
                    num(r, "bigChancesCreatedAvg") * apps, 1),
                "tackles": round(num(r, "tacklesAvg") * apps, 1),
                "interceptions": round(num(r, "interceptionsAvg") * apps, 1),
                "clearances": round(num(r, "clearancesAvg") * apps, 1),
                "saves": None,  # no goalkeeping tab fetched
                "yellow_cards": round(num(r, "yellowCardsAvg") * apps, 1),
                "red_cards": num(r, "redCards"),
                "fouls": round(num(r, "foulsCAvg") * apps, 1),
                "fouled": round(num(r, "foulsDAvg") * apps, 1),
                "rating_sum": round(num(r, "ratingAvg") * apps, 1),
                "pk_goals": None, "pk_attempts": None, "pks_won": None,
                "pks_conceded": None, "own_goals": None,
                "penalty_saves": None, "clean_sheets": None,
                "avg_rating": num(r, "ratingAvg") or None,
            }
            for col in ("goals", "assists", "shots_on_target", "key_passes",
                        "big_chances_created", "tackles", "interceptions"):
                row[col + "_p90"] = (round(row[col] / mins * 90, 3)
                                     if mins else None)
            for col in ("xg", "npxg", "xa", "saves"):
                row[col + "_p90"] = None
            rows.append(row)
        print(f"  {pretty}: {len(merged)} players")
    return rows


if __name__ == "__main__":
    out = curate()
    print(len(out), "rows;",
          sum(1 for r in out if r["nation"]), "with a WC-squad nation")
