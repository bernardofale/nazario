#!/usr/bin/env python3
"""Tidy the Premier League / Ligue 1 player-season stats into one CSV.

Source files: data/raw/{premierleague,ligue1}_player_stats.json — one row per
player-season with `players` (id, name, position), `teams` (club) and
`player_statistics` (string-typed totals plus PG/P90 variants).

We keep season totals for the stat families the fantasy scoring needs and
recompute per-90 rates from totals / minutes (the source P90 columns are
inconsistent — for some players they just repeat the per-game value).
"""
import curate_club_stats
import curate_laliga_stats
from common import RAW, PROCESSED, norm_name, load_json, write_csv

LEAGUES = {"premierleague": "Premier League", "ligue1": "Ligue 1"}

# stat family -> output column (season totals)
STATS = {
    "minutesPlayed": "minutes",
    "goals": "goals",
    "goalAssist": "assists",
    "expectedGoals": "xg",
    "npExpectedGoals": "npxg",
    "expectedAssists": "xa",
    "onTargetScoringAttempt": "shots_on_target",
    "shotOffTarget": "shots_off_target",
    "keyPass": "key_passes",
    "bigChanceCreated": "big_chances_created",
    "totalTackle": "tackles",
    "interceptionWon": "interceptions",
    "totalClearance": "clearances",
    "saves": "saves",
    "yellowCard": "yellow_cards",
    "redCard": "red_cards",
    "fouls": "fouls",
    "wasFouled": "fouled",
    "rating": "rating_sum",
}
PER90 = ["goals", "assists", "xg", "npxg", "xa", "shots_on_target",
         "key_passes", "big_chances_created", "tackles", "interceptions",
         "saves"]
# columns only the La Liga source provides — empty for PL/Ligue 1
EXTRA = ["nation", "pk_goals", "pk_attempts", "pks_won", "pks_conceded",
         "own_goals", "penalty_saves", "clean_sheets"]
COLUMNS = (["league", "player_id", "player_name", "player_name_norm",
            "club", "position", "appearances"]
           + list(STATS.values()) + EXTRA
           + [c + "_p90" for c in PER90] + ["avg_rating"])


def fnum(stats, key):
    v = stats.get(key + "Total")
    if v in (None, ""):
        return 0.0
    return float(v)


def curate():
    rows = []
    for key, league in LEAGUES.items():
        data = load_json(RAW / f"{key}_player_stats.json")["data"]
        for rec in data:
            p, stats = rec["players"], rec["player_statistics"]
            row = {
                "league": league,
                "player_id": p["id"],
                "player_name": p["name"],
                "player_name_norm": norm_name(p["name"]),
                "club": rec["teams"]["teamName"],
                "position": p["position"],
                "appearances": int(stats.get("appearances") or 0),
            }
            for fam, col in STATS.items():
                row[col] = fnum(stats, fam)
            mins = row["minutes"]
            for col in PER90:
                row[col + "_p90"] = round(row[col] / mins * 90, 3) if mins else None
            row["avg_rating"] = (round(row["rating_sum"] / row["appearances"], 2)
                                 if row["appearances"] else None)
            rows.append(row)
        print(f"  {league}: {len(data)} player-seasons")

    rows += curate_laliga_stats.curate()
    rows += curate_club_stats.curate()
    write_csv(PROCESSED / "club_stats.csv", rows, COLUMNS)
    print(f"  -> club_stats.csv ({len(rows)} rows)")
    return rows


if __name__ == "__main__":
    curate()
