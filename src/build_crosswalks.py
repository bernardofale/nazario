#!/usr/bin/env python3
"""Build the team and player ID crosswalks.

Canonical universe = the fantasy game files (data/raw/game/): 48 squads and
1,484 priced players. Each is linked to:
  teams:   FIFA country code (qualifier dumps), curated/ team_code, Euro 2024 name
  players: club_stats row (PL/Ligue 1), curated/ player_id (WC 2018/2022
           squads), Euro 2024 scorer goals

Matching is by normalized name (see common.norm_name) with explicit alias
tables for known naming differences. Anything ambiguous is left unmatched and
reported rather than guessed.
"""
from collections import defaultdict

from common import GAME, CURATED, PROCESSED, norm_name, load_json, read_csv, write_csv

# game squad name -> name used by other sources
TEAM_ALIASES = {
    "south korea": "korea republic",
    "iran": "ir iran",
    "usa": "usa",  # curated uses "United States"
    "united states": "usa",
    "ivory coast": "cote divoire",
    "cape verde": "cabo verde",
    "turkey": "turkiye",
}

TEAM_COLUMNS = ["squad_id", "name", "abbr", "group", "fifa_code",
                "curated_code", "euro2024_name"]
PLAYER_COLUMNS = ["wc_player_id", "full_name", "known_name", "country",
                  "position", "price", "club_league", "club_name",
                  "club_player_id", "club_match", "curated_player_id",
                  "curated_match", "euro2024_goals"]


def alias_norms(name):
    n = norm_name(name)
    out = [n]
    if n in TEAM_ALIASES:
        out.append(TEAM_ALIASES[n])
    out += [k for k, v in TEAM_ALIASES.items() if v == n]
    return out


def build_team_crosswalk():
    squads = load_json(GAME / "squads.json")
    quals = read_csv(PROCESSED / "qualifiers_2026.csv")
    qual_codes = {}  # norm name -> code
    for q in quals:
        qual_codes[norm_name(q["home_team"])] = q["home_code"]
        qual_codes[norm_name(q["away_team"])] = q["away_code"]
    curated_codes = {norm_name(t["team_name"]): t["team_code"]
                     for t in read_csv(CURATED / "teams_curated.csv")
                     if t["men"] == "TRUE"}
    euro = load_json(PROCESSED / "euro2024_results.json")["matches"]
    euro_names = {norm_name(m[k]): m[k] for m in euro
                  for k in ("home_team", "away_team")}

    rows, missing = [], []
    for s in squads:
        names = alias_norms(s["name"])
        fifa = next((qual_codes[n] for n in names if n in qual_codes), None)
        curated = next((curated_codes[n] for n in names if n in curated_codes), None)
        if fifa is None and s["abbr"] in set(qual_codes.values()) | set(curated_codes.values()):
            fifa = s["abbr"]  # hosts play no qualifiers but use standard codes
        rows.append({
            "squad_id": s["id"], "name": s["name"], "abbr": s["abbr"],
            "group": s["group"].upper(), "fifa_code": fifa or s["abbr"],
            "curated_code": curated,
            "euro2024_name": next((euro_names[n] for n in names if n in euro_names), None),
        })
        if fifa is None and curated is None:
            missing.append(s["name"])
    write_csv(PROCESSED / "team_crosswalk.csv", rows, TEAM_COLUMNS)
    n_euro = sum(1 for r in rows if r["euro2024_name"])
    print(f"  -> team_crosswalk.csv: {len(rows)} squads, "
          f"{sum(1 for r in rows if r['curated_code'])} with WC history, "
          f"{n_euro} at Euro 2024; unmatched anywhere: {missing or 'none'}")
    return rows


def build_player_crosswalk(team_rows):
    players = load_json(GAME / "players.json")
    abbr_by_squad = {t["squad_id"]: t for t in team_rows}

    # --- club stats lookups -------------------------------------------------
    club = read_csv(PROCESSED / "club_stats.csv")
    club_by_full = defaultdict(list)
    club_by_sorted = defaultdict(list)  # token-order-proof: "Lee Kang-In" vs "Kang-in Lee"
    club_by_last = defaultdict(list)
    for c in club:
        club_by_full[c["player_name_norm"]].append(c)
        club_by_sorted[" ".join(sorted(c["player_name_norm"].split()))].append(c)
        club_by_last[c["player_name_norm"].split()[-1]].append(c)

    # --- curated squads (recent men's WCs) ----------------------------------
    men_recent = {t["tournament_id"] for t in read_csv(CURATED / "tournaments_curated.csv")
                  if t["men"] == "TRUE" and int(t["year"]) >= 2018}
    cur_by_key = defaultdict(set)   # (norm full name, team_code) -> player_ids
    cur_by_name = defaultdict(set)  # norm full name -> player_ids
    for srow in read_csv(CURATED / "squads_curated.csv"):
        if srow["tournament_id"] not in men_recent:
            continue
        full = norm_name(f"{srow['given_name']} {srow['family_name']}".replace("not applicable", ""))
        cur_by_key[(full, srow["team_code"])].add(srow["player_id"])
        cur_by_name[full].add(srow["player_id"])

    # --- euro 2024 scorers ---------------------------------------------------
    euro_goals = defaultdict(int)  # (norm scorer, euro team name) -> goals
    for m in load_json(PROCESSED / "euro2024_results.json")["matches"]:
        for g in m["goals"]:
            if not g["own_goal"]:
                euro_goals[(norm_name(g["player"]), g["team"])] += 1

    rows = []
    n_club = n_cur = n_euro = 0
    for p in players:
        team = abbr_by_squad[p["squadId"]]
        full = norm_name(f"{p['firstName'] or ''} {p['lastName'] or ''}")
        known = norm_name(p["knownName"]) if p.get("knownName") else None
        last = full.split()[-1] if full else ""

        # club stats: full name, then known name, then unique-last-name.
        # Rows that carry a nation (La Liga/FBref) must agree with the
        # player's national team; nation-less rows (PL/L1) pass through.
        def nation_ok(c):
            return not c.get("nation") or c["nation"] == team["fifa_code"]

        cmatch, method = None, None
        for cand, mth in ((full, "full_name"), (known, "known_name")):
            hits = [c for c in club_by_full.get(cand, []) if nation_ok(c)]
            if cand and len(hits) == 1:
                cmatch, method = hits[0], mth
                break
        if cmatch is None:
            for cand in (full, known):
                if not cand:
                    continue
                skey = " ".join(sorted(cand.split()))
                hits = [c for c in club_by_sorted.get(skey, []) if nation_ok(c)]
                if len(hits) == 1:
                    cmatch, method = hits[0], "sorted_name"
                    break
        if cmatch is None and last:
            hits = [c for c in club_by_last.get(last, []) if nation_ok(c)]
            if len(hits) == 1:
                only = hits[0]
                # position guard where the source has positions; sources
                # without them (footymetrics) must pass the nation guard
                if only["position"]:
                    ok = only["position"][:1] == {"GK": "G", "DEF": "D",
                                                  "MID": "M", "FWD": "F"}[p["position"]]
                else:
                    ok = bool(only.get("nation"))
                if ok:
                    cmatch, method = only, "unique_last_name"

        # curated: name+country code, then unique name
        cur_id, cur_method = None, None
        code = team["curated_code"]
        for cand in (full, known):
            if not cand:
                continue
            if code and len(cur_by_key.get((cand, code), ())) == 1:
                cur_id, cur_method = next(iter(cur_by_key[(cand, code)])), "name+country"
                break
            if len(cur_by_name.get(cand, ())) == 1:
                cur_id, cur_method = next(iter(cur_by_name[cand])), "name_unique"
                break

        # euro scorers: surname (optionally with initial) within the squad's euro team
        egoals = 0
        if team["euro2024_name"]:
            for (scorer, eteam), n in euro_goals.items():
                if eteam != team["euro2024_name"]:
                    continue
                s = scorer.replace(".", "").strip()
                parts = s.split()
                surname = parts[-1]
                if surname == norm_name(p["lastName"] or "") or (known and surname == known.split()[-1]):
                    if len(parts) == 2 and len(parts[0]) == 1:  # "b varga" style initial
                        if not (p["firstName"] or "").lower().startswith(parts[0]):
                            continue
                    egoals += n

        n_club += cmatch is not None
        n_cur += cur_id is not None
        n_euro += egoals > 0
        rows.append({
            "wc_player_id": p["id"],
            "full_name": f"{p['firstName'] or ''} {p['lastName'] or ''}".strip(),
            "known_name": p.get("knownName"),
            "country": team["abbr"],
            "position": p["position"],
            "price": p["price"],
            "club_league": cmatch["league"] if cmatch else None,
            "club_name": cmatch["player_name"] if cmatch else None,
            "club_player_id": cmatch["player_id"] if cmatch else None,
            "club_match": method,
            "curated_player_id": cur_id,
            "curated_match": cur_method,
            "euro2024_goals": egoals or None,
        })

    write_csv(PROCESSED / "player_crosswalk.csv", rows, PLAYER_COLUMNS)
    print(f"  -> player_crosswalk.csv: {len(rows)} players | club stats: {n_club} "
          f"| WC-history id: {n_cur} | Euro 2024 scorer: {n_euro}")
    return rows


def build():
    teams = build_team_crosswalk()
    players = build_player_crosswalk(teams)
    return teams, players


if __name__ == "__main__":
    build()
