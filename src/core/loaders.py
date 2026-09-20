#!/usr/bin/env python3
"""Loaders for everything downstream phases need (team model, simulator,
player model, optimizer). All read from data/processed/ + data/raw/game/.

    from loaders import load_matches, load_goals, load_club_stats, \\
        load_team_crosswalk, load_player_crosswalk, load_fixtures, \\
        load_players, load_rules_constants
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

from common import GAME, PROCESSED, load_json, read_csv


def load_matches():
    """All international matches in the common schema (WC history 1930–2022,
    2026 qualifiers, Euro 2024), sorted by date."""
    rows = read_csv(PROCESSED / "matches_international.csv")
    for r in rows:
        for k in ("home_score", "away_score"):
            r[k] = int(r[k])
        r["extra_time"] = r["extra_time"] == "True"
        r["penalty_shootout"] = r["penalty_shootout"] == "True"
    return rows


def load_goals():
    """All goals with scorer attribution (WC history + Euro 2024)."""
    rows = read_csv(PROCESSED / "goals_international.csv")
    for r in rows:
        r["penalty"] = r["penalty"] == "True"
        r["own_goal"] = r["own_goal"] == "True"
    return rows


def load_club_stats():
    """2025-26 PL + Ligue 1 player-season stats (totals and per-90)."""
    return read_csv(PROCESSED / "club_stats.csv")


def load_team_crosswalk():
    """48 squads: game id/abbr <-> FIFA code <-> curated code <-> Euro name."""
    return {int(r["squad_id"]): r for r in read_csv(PROCESSED / "team_crosswalk.csv")}


def load_player_crosswalk():
    """Fantasy pool linked to club stats / WC history / Euro 2024 scorers."""
    return {int(r["wc_player_id"]): r
            for r in read_csv(PROCESSED / "player_crosswalk.csv")}


def load_fixtures():
    """2026 group-stage fixtures: one row per match with matchday number."""
    fixtures = []
    for rnd in load_json(GAME / "groupstage.json"):
        for m in rnd["tournaments"]:
            fixtures.append({"matchday": rnd["id"], **m})
    return fixtures


def load_players():
    """Raw fantasy pool (price, position, status, ownership)."""
    return load_json(GAME / "players.json")


def load_squads():
    return load_json(GAME / "squads.json")


# rules.md constants the optimizer needs
RULES = {
    "budget": 100.0,
    "budget_r32": 105.0,
    "squad_size": 15,
    "positions": {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
    "country_cap_by_stage": {"group": 3, "r32": 4, "r16": 5,
                             "qf": 6, "sf": 8, "final": 8},
    "formations": [(4, 4, 2), (4, 3, 3), (4, 5, 1), (3, 4, 3),
                   (3, 5, 2), (5, 4, 1), (5, 3, 2)],
    "free_transfers": {"md2": 2, "md3": 2, "r32": None,  # None = unlimited
                       "r16": 4, "qf": 4, "sf": 5, "final": 6},
    "extra_transfer_cost": -3,
}


if __name__ == "__main__":
    print(f"matches: {len(load_matches())}")
    print(f"goals: {len(load_goals())}")
    print(f"club stats: {len(load_club_stats())}")
    print(f"fixtures: {len(load_fixtures())}")
    print(f"players: {len(load_players())}, teams: {len(load_team_crosswalk())}")
