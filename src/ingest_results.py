#!/usr/bin/env python3
"""Convert played 2026 World Cup fixtures into common-schema match rows.

Two sources, in priority order:
  1. data/raw/game/wc_games_api.json — a live results feed. Carries real
     scores + scorer strings for every finished match, keyed by English team
     name. (Set RESULTS_FEED_URL in local_config.py / the environment and
     curl it into this file; the URL is not committed to the repo.)
  2. data/raw/game/groupstage.json — the fantasy game export (fallback;
     scores are null until the operator re-exports it).

Output (unchanged contract so build_phase0.py keeps working):
  data/processed/wc2026_results.csv  — common-schema rows fed to the team fit
  data/processed/wc2026_events_raw.json — raw scorer strings for the Phase 3
                                          assist/goal-scorer model.

Run after each matchday:  curl the feed into wc_games_api.json, then
`python3 src/build_phase0.py` (which calls curate() here).
"""
import json

from common import GAME, PROCESSED, MATCH_COLUMNS, norm_name, load_json, write_csv
from loaders import load_team_crosswalk

API_FILE = GAME / "wc_games_api.json"

# feed English names that differ from our squad crosswalk names
NAME_ALIASES = {
    "turkey": "türkiye",
    "united states": "usa",
    "ivory coast": "côte d'ivoire",
    "south korea": "korea republic",
    "democratic republic of the congo": "congo dr",
    "iran": "ir iran",
    "cape verde": "cabo verde",
    "czech republic": "czechia",
}


def _name_to_code(xwalk):
    """norm(team name) -> FIFA code, including the API aliases."""
    by_norm = {norm_name(t["name"]): t["fifa_code"] for t in xwalk.values()}
    for alias, target in NAME_ALIASES.items():
        code = by_norm.get(norm_name(target))
        if code:
            by_norm[norm_name(alias)] = code
    return by_norm


def _group_by_code(xwalk):
    return {t["fifa_code"]: t["group"] for t in xwalk.values()}


def curate_from_api(xwalk):
    """Parse the results feed. Returns (match_rows, event_rows)."""
    code_of = _name_to_code(xwalk)
    group_of = _group_by_code(xwalk)
    rows, events = [], []
    # matchday offset so knockout rounds keep sorting after the 3 group rounds
    ko_md = {"r32": 4, "r16": 5, "qf": 6, "sf": 7, "third": 8, "final": 8}
    for g in load_json(API_FILE)["games"]:
        gtype = g.get("type")
        if str(g.get("finished")).upper() != "TRUE":
            continue
        if gtype not in ("group",) and gtype not in ko_md:
            continue
        hn, an = g.get("home_team_name_en"), g.get("away_team_name_en")
        if not hn or not an:
            continue
        hc = code_of.get(norm_name(hn))
        ac = code_of.get(norm_name(an))
        if not hc or not ac:
            print(f"  ! unmapped team: {hn} vs {an}")
            continue
        # local_date like "06/13/2026 21:00" -> ISO 2026-06-13
        mm, dd, yy = g["local_date"].split()[0].split("/")
        iso_date = f"{yy}-{mm}-{dd}"
        is_ko = gtype in ko_md
        pen = g.get("home_penalty_score") not in (None, "null", "")
        rows.append({
            "source": "wc2026",
            "competition": "World Cup 2026",
            "confederation": None,
            "season": 2026,
            "match_id": f"WC26-{g['id']}",
            "date": iso_date,
            "stage": gtype if is_ko else "group",
            "group": None if is_ko else group_of.get(hc, g.get("group")),
            "matchday": ko_md[gtype] if is_ko else int(g["matchday"]),
            "home_team": hn,
            "away_team": an,
            "home_code": hc,
            "away_code": ac,
            "home_score": int(g["home_score"]),
            "away_score": int(g["away_score"]),
            "ht_home_score": None, "ht_away_score": None,
            "extra_time": False, "penalty_shootout": bool(pen),
            "home_penalty_score": g.get("home_penalty_score") if pen else None,
            "away_penalty_score": g.get("away_penalty_score") if pen else None,
            "venue": g.get("stadium_id"),
        })
        if g.get("home_scorers") not in (None, "null") or \
           g.get("away_scorers") not in (None, "null"):
            events.append({"match_id": f"WC26-{g['id']}",
                           "home_code": hc, "away_code": ac,
                           "home": g.get("home_scorers"),
                           "away": g.get("away_scorers")})
    return rows, events


def curate_from_groupstage(xwalk):
    """Fallback: parse the fantasy groupstage.json export."""
    code = {sid: t["fifa_code"] for sid, t in xwalk.items()}
    group = {sid: t["group"] for sid, t in xwalk.items()}
    rows, events = [], []
    for rnd in load_json(GAME / "groupstage.json"):
        for m in rnd["tournaments"]:
            if m["homeScore"] is None or m["awayScore"] is None:
                continue
            rows.append({
                "source": "wc2026", "competition": "World Cup 2026",
                "confederation": None, "season": 2026,
                "match_id": f"WC26-{m['id']}", "date": m["date"][:10],
                "stage": "group", "group": group[m["homeSquadId"]],
                "matchday": rnd["id"],
                "home_team": m["homeSquadName"], "away_team": m["awaySquadName"],
                "home_code": code[m["homeSquadId"]],
                "away_code": code[m["awaySquadId"]],
                "home_score": m["homeScore"], "away_score": m["awayScore"],
                "ht_home_score": None, "ht_away_score": None,
                "extra_time": False, "penalty_shootout": False,
                "home_penalty_score": m["homePenaltyScore"],
                "away_penalty_score": m["awayPenaltyScore"],
                "venue": m["venueName"],
            })
            if m.get("homeGoalScorersAssists") or m.get("awayGoalScorersAssists"):
                events.append({"match_id": f"WC26-{m['id']}",
                               "home": m["homeGoalScorersAssists"],
                               "away": m["awayGoalScorersAssists"]})
    return rows, events


def curate():
    xwalk = load_team_crosswalk()
    if API_FILE.exists():
        rows, events = curate_from_api(xwalk)
        src = "results feed"
    else:
        rows, events = curate_from_groupstage(xwalk)
        src = "groupstage.json"
    write_csv(PROCESSED / "wc2026_results.csv", rows, MATCH_COLUMNS)
    if events:
        json.dump(events, open(PROCESSED / "wc2026_events_raw.json", "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  -> wc2026_results.csv ({len(rows)} played matches from {src}, "
          f"{len(events)} with scorer events)")
    return rows


if __name__ == "__main__":
    curate()
