#!/usr/bin/env python3
"""Convert played 2026 fixtures from the refreshed game file
(data/raw/game/groupstage.json) into common-schema match rows.

Run after every matchday once the game files are re-exported (PLAYBOOK §1).
A fixture counts as played when both scores are non-null. Goal/assist
events (homeGoalScorersAssists / awayGoalScorersAssists) are saved raw to
wc2026_events_raw.json — their exact shape is unknown until the first
results land, so they are captured losslessly for inspection rather than
parsed on assumptions (the assist model needs them in Phase 3).
"""
import json

from common import GAME, PROCESSED, MATCH_COLUMNS, load_json, write_csv
from loaders import load_team_crosswalk


def curate():
    xwalk = load_team_crosswalk()
    code = {sid: t["fifa_code"] for sid, t in xwalk.items()}
    group = {sid: t["group"] for sid, t in xwalk.items()}
    rows, events = [], []
    for rnd in load_json(GAME / "groupstage.json"):
        for m in rnd["tournaments"]:
            if m["homeScore"] is None or m["awayScore"] is None:
                continue
            rows.append({
                "source": "wc2026",
                "competition": "World Cup 2026",
                "confederation": None,
                "season": 2026,
                "match_id": f"WC26-{m['id']}",
                "date": m["date"][:10],
                "stage": "group",
                "group": group[m["homeSquadId"]],
                "matchday": rnd["id"],
                "home_team": m["homeSquadName"],
                "away_team": m["awaySquadName"],
                "home_code": code[m["homeSquadId"]],
                "away_code": code[m["awaySquadId"]],
                "home_score": m["homeScore"],
                "away_score": m["awayScore"],
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
    write_csv(PROCESSED / "wc2026_results.csv", rows, MATCH_COLUMNS)
    if events:
        json.dump(events, open(PROCESSED / "wc2026_events_raw.json", "w",
                               encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  -> wc2026_results.csv ({len(rows)} played matches, "
          f"{len(events)} with goal events)")
    return rows


if __name__ == "__main__":
    curate()
