#!/usr/bin/env python3
"""Map the men's World Cup history (data/curated/*.csv) into the common
match + goal schemas: wc_history_matches.csv and wc_history_goals.csv."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

from common import CURATED, PROCESSED, MATCH_COLUMNS, GOAL_COLUMNS, read_csv, write_csv

STAGE_MAP = {
    "group stage": "group", "first group stage": "group",
    "second group stage": "second_group", "first round": "group",
    "round of 16": "round_of_16", "quarter-finals": "quarter_final",
    "semi-finals": "semi_final", "third place match": "third_place",
    "final round": "final_round", "final": "final",
}


def men_tournament_ids():
    return {t["tournament_id"]: int(t["year"])
            for t in read_csv(CURATED / "tournaments_curated.csv")
            if t["men"] == "TRUE"}


def curate():
    men = men_tournament_ids()
    rows = []
    for m in read_csv(CURATED / "matches_curated.csv"):
        if m["tournament_id"] not in men:
            continue
        shootout = m["penalty_shootout"] == "TRUE"
        rows.append({
            "source": "wc_history",
            "competition": "World Cup",
            "confederation": None,
            "season": men[m["tournament_id"]],
            "match_id": f"WC-{m['match_id']}",
            "date": m["match_date"],
            "stage": STAGE_MAP.get(m["stage_name"], m["stage_name"]),
            "group": m["group_name"].replace("Group ", "") or None,
            "matchday": None,
            "home_team": m["home_team_name"],
            "away_team": m["away_team_name"],
            "home_code": m["home_team_code"],
            "away_code": m["away_team_code"],
            "home_score": m["home_team_score"],
            "away_score": m["away_team_score"],
            "ht_home_score": None,
            "ht_away_score": None,
            "extra_time": m["extra_time"] == "TRUE",
            "penalty_shootout": shootout,
            "home_penalty_score": m["home_team_score_penalties"] if shootout else None,
            "away_penalty_score": m["away_team_score_penalties"] if shootout else None,
            "venue": m["stadium_name"],
        })
    rows.sort(key=lambda r: r["date"])
    write_csv(PROCESSED / "wc_history_matches.csv", rows, MATCH_COLUMNS)
    print(f"  -> wc_history_matches.csv ({len(rows)} men's matches)")

    goals = []
    for g in read_csv(CURATED / "goals_curated.csv"):
        if g["tournament_id"] not in men:
            continue
        goals.append({
            "source": "wc_history",
            "match_id": f"WC-{g['match_id']}",
            "date": g["match_date"],
            "team": g["team_name"],
            "team_code": g["team_code"],
            "player": f"{g['given_name']} {g['family_name']}".replace("not applicable ", "").strip(),
            "player_id": g["player_id"],
            "minute": g["minute_label"].rstrip("'"),
            "penalty": g["penalty"] == "TRUE",
            "own_goal": g["own_goal"] == "TRUE",
        })
    write_csv(PROCESSED / "wc_history_goals.csv", goals, GOAL_COLUMNS)
    print(f"  -> wc_history_goals.csv ({len(goals)} goals)")
    return rows, goals


if __name__ == "__main__":
    curate()
