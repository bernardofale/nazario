#!/usr/bin/env python3
"""Curate euro_results_and_scorers.txt into euro2024_results.json.

Common match schema (shared by all curated result sources):
  competition, season, matches[]:
    match_id, date, kickoff_local, stage, group, matchday,
    home_team, away_team, home_score, away_score (after 90'/120'),
    ht_home_score, ht_away_score, extra_time, penalty_shootout,
    home_penalty_score, away_penalty_score, venue,
    goals[]: {team, player, minute, penalty, own_goal},
    lineups_raw: {team: text}  (only where the source lists lineups)

Validates that listed scorers match the scoreline for every match.
"""
import json
import re
import sys

from common import RAW, PROCESSED

SRC = RAW / "euro_results_and_scorers.txt"
OUT = PROCESSED / "euro2024_results.json"

MONTHS = {"Jun": 6, "Jul": 7}
DATE_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jun|Jul) (\d+)\s*$")
STAGE_RE = re.compile(r"^▪ (Round of 16|Quarter-finals|Semi-finals|Final)\s*$")
GROUP_RE = re.compile(r"^▪ Group ([A-F])\s*$")
MATCHDAY_RE = re.compile(r"^▪ Matchday (\d)")
# team score-score [pen. score-score a.e.t.] [(ht[, ...])] team @ venue
MATCH_RE = re.compile(
    r"^\s*(?:(\d{1,2}:\d{2})\s+)?"
    r"([A-Za-zÀ-ž][A-Za-zÀ-ž ]*?)\s+(\d+)-(\d+)\s*"
    r"(?:pen\.\s+(\d+)-(\d+)\s+a\.e\.t\.\s*)?"
    r"(?:\((\d+-\d+(?:,\s*\d+-\d+)?)\)\s*)?"
    r"([A-Za-zÀ-ž][A-Za-zÀ-ž ]*?)\s+@\s+(\S+)"
)
STAGE_NAMES = {
    "Round of 16": "round_of_16",
    "Quarter-finals": "quarter_final",
    "Semi-finals": "semi_final",
    "Final": "final",
}
# minute marker: 45+1' / 90+10' / 119', optionally followed by (pen.) / (o.g.)
GOAL_RE = re.compile(r"(\d+)(?:\+(\d+))?'(\s*\((pen|o\.g)\.\))?")


def parse_goal_side(text, team):
    """Parse one side's scorer list, e.g. "Demiral 1', 59'" or "Havertz 45+1' (pen.)"."""
    goals = []
    pos = 0
    last_name = None
    for m in GOAL_RE.finditer(text):
        name = text[pos:m.start()].strip(" ,;")
        if not name:
            name = last_name  # "Demiral 1', 59'" — second goal reuses the name
        last_name = name
        flag = m.group(4)
        base = int(m.group(1))
        minute = m.group(1) + ("+" + m.group(2) if m.group(2) else "")
        goals.append({
            "team": team,
            "player": name,
            "minute": minute,
            "minute_base": base,
            "stoppage": m.group(2) is not None,
            "penalty": flag == "pen",
            "own_goal": flag == "o.g",
        })
        pos = m.end()
    return goals


def main():
    lines = open(SRC, encoding="utf-8").read().splitlines()
    stage, group, matchday, date, last_time = None, None, None, None, None
    matches = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("="):
            i += 1
            continue
        m = STAGE_RE.match(stripped)
        if m:
            stage, group = STAGE_NAMES[m.group(1)], None
            i += 1
            continue
        m = GROUP_RE.match(stripped)
        if m:
            stage, group = "group", m.group(1)
            i += 1
            continue
        if MATCHDAY_RE.match(stripped) or stripped.startswith("Group "):
            i += 1
            continue
        m = DATE_RE.match(stripped)
        if m:
            date = f"2024-{MONTHS[m.group(2)]:02d}-{int(m.group(3)):02d}"
            last_time = None
            i += 1
            continue
        # strip trailing "# ..." comments before matching a result line
        code = line.split("#")[0].rstrip()
        m = MATCH_RE.match(code)
        if m and "@" in code:
            time, home, s1, s2, s3, s4, ht, away, venue = m.groups()
            if time:
                last_time = time
            shootout = s3 is not None
            if shootout:  # "3-0 pen. 0-0 a.e.t." → first pair is the shootout
                pen_h, pen_a = int(s1), int(s2)
                score_h, score_a = int(s3), int(s4)
            else:
                pen_h = pen_a = None
                score_h, score_a = int(s1), int(s2)
            ht_h = ht_a = None
            if ht:  # "(1-1, 0-0)" lists 90' then HT; plain "(3-0)" is HT
                first = ht.split(",")[-1].strip()
                ht_h, ht_a = (int(x) for x in first.split("-"))
            match = {
                "match_id": f"EURO2024-{len(matches) + 1:02d}",
                "date": date,
                "kickoff_local": last_time,
                "stage": stage,
                "group": group,
                "home_team": home.strip(),
                "away_team": away.strip(),
                "home_score": score_h,
                "away_score": score_a,
                "ht_home_score": ht_h,
                "ht_away_score": ht_a,
                "extra_time": shootout,
                "penalty_shootout": shootout,
                "home_penalty_score": pen_h,
                "away_penalty_score": pen_a,
                "venue": venue.strip(),
                "goals": [],
                "lineups_raw": {},
            }
            i += 1
            # scorer block: next non-empty line starting with "(" — runs to balanced ")"
            while i < len(lines) and lines[i].strip().startswith("("):
                block = ""
                depth = 0
                while i < len(lines):
                    block += " " + lines[i].strip()
                    depth += lines[i].count("(") - lines[i].count(")")
                    i += 1
                    if depth <= 0:
                        break
                block = block.strip()[1:-1]  # outer parens
                parts = block.split(";")
                if len(parts) == 1 and match["home_score"] == 0:
                    # no ";" separator when the home side didn't score
                    match["goals"] += parse_goal_side(parts[0], match["away_team"])
                else:
                    match["goals"] += parse_goal_side(parts[0], match["home_team"])
                    if len(parts) > 1:
                        match["goals"] += parse_goal_side(parts[1], match["away_team"])
            # lineup block: "TeamName: ..." lines plus indented continuations
            while i < len(lines) and lines[i].strip():
                lm = re.match(r"^\s*([A-Za-zÀ-ž ]+):\s+(.*)$", lines[i])
                if lm and lm.group(1).strip() in (match["home_team"], match["away_team"]):
                    team, text = lm.group(1).strip(), lm.group(2).strip()
                    i += 1
                    while i < len(lines) and lines[i].strip() and not re.match(
                        r"^\s*([A-Za-zÀ-ž ]+):\s", lines[i]
                    ) and "@" not in lines[i] and not DATE_RE.match(lines[i].strip()):
                        text += " " + lines[i].strip()
                        i += 1
                    match["lineups_raw"][team] = text
                else:
                    break
            # extra time without a shootout shows up as a goal minute past 90'
            if any(g["minute_base"] > 90 and not g["stoppage"] for g in match["goals"]):
                match["extra_time"] = True
            for g in match["goals"]:
                del g["minute_base"], g["stoppage"]
            matches.append(match)
            continue
        i += 1

    # validation: scorer counts must equal the scoreline wherever scorers are listed
    errors = []
    for mt in matches:
        if not mt["goals"]:
            if mt["home_score"] + mt["away_score"] > 0:
                errors.append(f"{mt['match_id']} {mt['home_team']}-{mt['away_team']}: "
                              f"{mt['home_score']}-{mt['away_score']} but no scorers listed")
            continue
        gh = sum(1 for g in mt["goals"] if g["team"] == mt["home_team"])
        ga = sum(1 for g in mt["goals"] if g["team"] == mt["away_team"])
        if (gh, ga) != (mt["home_score"], mt["away_score"]):
            errors.append(f"{mt['match_id']} {mt['home_team']}-{mt['away_team']}: "
                          f"score {mt['home_score']}-{mt['away_score']} vs scorers {gh}-{ga}")
        if any(g["player"] is None for g in mt["goals"]):
            errors.append(f"{mt['match_id']}: unnamed scorer")

    out = {
        "competition": "UEFA Euro 2024",
        "season": "2024",
        "source": SRC.name,
        "matches": matches,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    n_goals = sum(len(m["goals"]) for m in matches)
    by_stage = {}
    for mt in matches:
        by_stage[mt["stage"]] = by_stage.get(mt["stage"], 0) + 1
    print(f"matches: {len(matches)}  goals: {n_goals}  stages: {by_stage}")
    print(f"lineups captured: {sum(1 for m in matches if m['lineups_raw'])} matches")
    if errors:
        print("VALIDATION ERRORS:")
        print("\n".join(" - " + e for e in errors))
        sys.exit(1)
    print("validation: all scorer counts match scorelines ✓")


if __name__ == "__main__":
    main()
