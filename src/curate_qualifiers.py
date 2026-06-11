#!/usr/bin/env python3
"""Flatten the six FIFA qualifier dumps into the common match schema.

Source files: data/raw/{conf}_qualifier_results.json (FIFA API `Results`
arrays). Keeps played matches only (MatchStatus == 0). ResultType 2 means the
tie was decided on penalties — flagged as extra_time + penalty_shootout; the
team scores FIFA reports for those matches are the post-extra-time scores.
The dumps contain no scorer information.
"""
from common import RAW, PROCESSED, MATCH_COLUMNS, load_json, write_csv

CONFEDERATIONS = ["uefa", "afc", "caf", "concacaf", "conmebol", "ofc"]


def first_desc(loc_list):
    return loc_list[0]["Description"] if loc_list else None


def curate():
    rows = []
    for conf in CONFEDERATIONS:
        results = load_json(RAW / f"{conf}_qualifier_results.json")["Results"]
        kept = skipped = 0
        for r in results:
            if r["MatchStatus"] != 0:
                skipped += 1
                continue
            shootout = r["ResultType"] == 2
            rows.append({
                "source": f"{conf}_qualifiers",
                "competition": "WC2026 Qualifiers",
                "confederation": conf.upper(),
                "season": first_desc(r["SeasonName"]),
                "match_id": f"Q26-{conf.upper()}-{r['IdMatch']}",
                "date": (r["Date"] or "")[:10],
                "stage": first_desc(r["StageName"]),
                "group": (first_desc(r["GroupName"]) or "").replace("Group ", "") or None,
                "matchday": r["MatchDay"],
                "home_team": first_desc(r["Home"]["TeamName"]),
                "away_team": first_desc(r["Away"]["TeamName"]),
                "home_code": r["Home"]["IdCountry"],
                "away_code": r["Away"]["IdCountry"],
                "home_score": r["HomeTeamScore"],
                "away_score": r["AwayTeamScore"],
                "ht_home_score": None,
                "ht_away_score": None,
                "extra_time": shootout,
                "penalty_shootout": shootout,
                "home_penalty_score": r["HomeTeamPenaltyScore"] if shootout else None,
                "away_penalty_score": r["AwayTeamPenaltyScore"] if shootout else None,
                "venue": first_desc(r["Stadium"]["Name"]) if r.get("Stadium") else None,
            })
            kept += 1
        print(f"  {conf.upper()}: {kept} matches kept, {skipped} skipped")

    bad = [r for r in rows if r["home_score"] is None or not r["date"]]
    if bad:
        raise SystemExit(f"qualifier curation: {len(bad)} rows missing score/date")
    rows.sort(key=lambda r: r["date"])
    write_csv(PROCESSED / "qualifiers_2026.csv", rows, MATCH_COLUMNS)
    print(f"  -> qualifiers_2026.csv ({len(rows)} rows)")
    return rows


if __name__ == "__main__":
    curate()
