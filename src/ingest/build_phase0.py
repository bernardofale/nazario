#!/usr/bin/env python3
"""Phase 0 entry point: curate every source into the common schemas, build
the crosswalks, and write data/processed/ plus a coverage report.

Run:  python3 src/build_phase0.py
"""
from collections import Counter

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

import build_crosswalks
import curate_euro2024
import curate_league_stats
import curate_qualifiers
import curate_wc_history
import ingest_results
from common import PROCESSED, MATCH_COLUMNS, GOAL_COLUMNS, load_json, read_csv, write_csv


def euro_to_common(teams):
    """euro2024_results.json -> common-schema match + goal rows."""
    code_by_euro_name = {t["euro2024_name"]: t["fifa_code"]
                         for t in teams if t["euro2024_name"]}
    matches, goals = [], []
    for m in load_json(PROCESSED / "euro2024_results.json")["matches"]:
        matches.append({
            **{k: m.get(k) for k in MATCH_COLUMNS},
            "source": "euro2024",
            "competition": "Euro 2024",
            "confederation": "UEFA",
            "season": 2024,
            "home_code": code_by_euro_name.get(m["home_team"]),
            "away_code": code_by_euro_name.get(m["away_team"]),
        })
        for g in m["goals"]:
            goals.append({
                "source": "euro2024",
                "match_id": m["match_id"],
                "date": m["date"],
                "team": g["team"],
                "team_code": code_by_euro_name.get(g["team"]),
                "player": g["player"],
                "player_id": None,
                "minute": g["minute"],
                "penalty": g["penalty"],
                "own_goal": g["own_goal"],
            })
    return matches, goals


def main():
    PROCESSED.mkdir(parents=True, exist_ok=True)
    print("[1/6] Euro 2024 text -> json")
    curate_euro2024.main()
    print("[2/6] FIFA qualifier dumps")
    qual_rows = curate_qualifiers.curate()
    print("[3/6] club league stats")
    club_rows = curate_league_stats.curate()
    print("[4/6] WC history")
    wc_matches, wc_goals = curate_wc_history.curate()
    print("[5/6] crosswalks")
    teams, players = build_crosswalks.build()
    print("[6/6] 2026 played matches (game-file refresh)")
    wc26_rows = ingest_results.curate()
    try:
        import curate_wc_form
        curate_wc_form.curate()
    except Exception as e:  # optional: only after the club-stats WC fetch
        print(f"  (skipped WC player form: {e})")

    euro_matches, euro_goals = euro_to_common(teams)
    all_matches = [dict(r, **{"extra_time": str(r["extra_time"]).upper() == "TRUE" or r["extra_time"] is True,
                              }) for r in (wc_matches + qual_rows + euro_matches + wc26_rows)]
    all_matches.sort(key=lambda r: str(r["date"]))
    write_csv(PROCESSED / "matches_international.csv", all_matches, MATCH_COLUMNS)
    all_goals = wc_goals + euro_goals
    write_csv(PROCESSED / "goals_international.csv", all_goals, GOAL_COLUMNS)

    # ---- report -------------------------------------------------------------
    src_counts = Counter(r["source"] for r in all_matches)
    n = len(players)
    n_club = sum(1 for p in players if p["club_player_id"])
    n_cur = sum(1 for p in players if p["curated_player_id"])
    n_euro = sum(1 for p in players if p["euro2024_goals"])
    n_any = sum(1 for p in players
                if p["club_player_id"] or p["curated_player_id"] or p["euro2024_goals"])
    teams_hist = sum(1 for t in teams if t["curated_code"])
    lines = [
        "# Phase 0 report — common schema & crosswalks",
        "",
        "## Match table (`matches_international.csv`)",
        "",
        "| source | matches |",
        "|---|---|",
        *[f"| {s} | {c} |" for s, c in sorted(src_counts.items())],
        f"| **total** | **{len(all_matches)}** |",
        "",
        f"Goals with scorer attribution (`goals_international.csv`): {len(all_goals)} "
        f"({sum(1 for g in all_goals if g['source'] == 'euro2024')} from Euro 2024).",
        "",
        "## Team crosswalk (48 squads)",
        "",
        f"- FIFA code resolved: 48/48",
        f"- WC history (curated/) link: {teams_hist}/48 "
        "(teams with no prior men's WC have none, by definition)",
        f"- Euro 2024 participants: {sum(1 for t in teams if t['euro2024_name'])}",
        "",
        "## Player crosswalk (fantasy pool)",
        "",
        f"- players in pool: {n}",
        f"- club stats (PL/Ligue 1): {n_club} ({n_club / n:.0%})",
        f"- WC-history player id (2018/2022 squads): {n_cur} ({n_cur / n:.0%})",
        f"- Euro 2024 goals attributed: {n_euro}",
        f"- at least one external link: {n_any} ({n_any / n:.0%})",
        "",
        "Matching is conservative: ambiguous names are left unlinked rather than guessed.",
    ]
    (PROCESSED / "phase0_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n-> matches_international.csv ({len(all_matches)}), "
          f"goals_international.csv ({len(all_goals)}), phase0_report.md")


if __name__ == "__main__":
    main()
