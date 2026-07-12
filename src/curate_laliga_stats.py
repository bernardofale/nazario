#!/usr/bin/env python3
"""Parse the La Liga public-stats copy-paste dumps into common club-stats rows.

Four tab-separated files in data/raw/ (web copy-paste, so: repeated header
rows, thousands separators, one row missing its name, one truncated row):
  laliga_standard_stats.txt    minutes, goals, assists, PK/PKatt, cards
  laliga_shooting_stats.txt    shots, shots on target
  laliga_misc_stats.txt        fouls, interceptions, tackles won, PK won/
                               conceded, own goals
  laliga_goalkeeping_stats.txt saves, clean sheets, penalty saves

Differences vs the PL/Ligue 1 JSONs, handled here:
  - no xG/xA/key-pass/big-chance/rating columns -> left empty
  - `tackles` = tackles WON (tackles-won column), not attempted
  - shots_off_target = Sh - SoT (includes blocked)
  - has Nation -> kept, used as a matching guard downstream
  - players who switched clubs mid-season have one row per club -> summed
"""
import re
from collections import defaultdict

from common import RAW, norm_name

FILES = {
    "standard": ("laliga_standard_stats.txt",
                 ["rk", "player", "nation", "pos", "squad", "age", "born",
                  "mp", "starts", "min", "n90s", "gls", "ast", "ga", "gpk",
                  "pk", "pkatt", "crdy", "crdr"]),
    "shooting": ("laliga_shooting_stats.txt",
                 ["rk", "player", "nation", "pos", "squad", "age", "born",
                  "n90s", "gls", "sh", "sot"]),
    "misc": ("laliga_misc_stats.txt",
             ["rk", "player", "nation", "pos", "squad", "age", "born",
              "n90s", "crdy", "crdr", "crdy2", "fls", "fld", "off", "crs",
              "int", "tklw", "pkwon", "pkcon", "og"]),
    "goalkeeping": ("laliga_goalkeeping_stats.txt",
                    ["rk", "player", "nation", "pos", "squad", "age", "born",
                     "mp", "starts", "min", "n90s", "ga", "ga90", "sota",
                     "saves", "savepct", "w", "d", "l", "cs", "cspct",
                     "pkatt_faced", "pka", "pksv"]),
}
POS_MAP = {"GK": "G", "DF": "D", "MF": "M", "FW": "F"}
NATION_RE = re.compile(r"^[a-z]{2,3} [A-Z]{3}$")  # nation style: "es ESP"


def fnum(v):
    v = (v or "").strip().replace(",", "")
    return float(v) if v else 0.0


def parse_file(name, cols):
    """Return dict rows. Header rows are skipped; the copy-paste row that
    lost its rank+name is realigned; truncated rows keep what they have."""
    rows = []
    for ln in open(RAW / name, encoding="utf-8"):
        parts = [p.strip() for p in ln.rstrip("\n").split("\t")]
        if len(parts) < 8:
            continue
        if parts[0].isdigit():
            rec = parts
        elif parts[0] == "" and NATION_RE.match(parts[1] or ""):
            rec = ["", ""] + parts[1:]  # rank and name lost in copy-paste
        else:
            continue  # header / junk line
        rows.append({c: (rec[i] if i < len(rec) else "")
                     for i, c in enumerate(cols)})
    return rows


def attr_key(r):
    """Fallback identity for rows missing the player name."""
    return (r["nation"], r["pos"], r["squad"], r["born"])


def curate():
    tables = {k: parse_file(f, cols) for k, (f, cols) in FILES.items()}

    # repair nameless rows by unique (nation, pos, squad, born) match vs standard
    std_by_attr = defaultdict(list)
    for r in tables["standard"]:
        if r["player"]:
            std_by_attr[attr_key(r)].append(r["player"])
    repaired = dropped = 0
    for tname, rows in tables.items():
        for r in rows:
            if not r["player"]:
                cands = std_by_attr.get(attr_key(r), [])
                if len(set(cands)) == 1:
                    r["player"] = cands[0]
                    repaired += 1
                else:
                    r["player"] = None
                    dropped += 1
        tables[tname] = [r for r in rows if r["player"]]

    # merge the four tables on (player, squad)
    merged = {}
    for tname, rows in tables.items():
        for r in rows:
            key = (norm_name(r["player"]), r["squad"])
            m = merged.setdefault(key, {"player": r["player"],
                                        "nation": r["nation"].split()[-1] if r["nation"] else "",
                                        "pos": r["pos"], "born": r["born"],
                                        "squads": set()})
            m["squads"].add(r["squad"])
            for c, v in r.items():
                if c not in ("rk", "player", "nation", "pos", "squad", "age"):
                    m[c] = v

    # aggregate multi-club seasons on (name, nation, born)
    SUM = ["mp", "starts", "min", "gls", "ast", "pk", "pkatt", "crdy", "crdr",
           "sh", "sot", "fls", "fld", "int", "tklw", "pkwon", "pkcon", "og",
           "saves", "cs", "pksv"]
    agg = {}
    for m in merged.values():
        key = (norm_name(m["player"]), m["nation"], m["born"])
        if key not in agg:
            agg[key] = {**{c: 0.0 for c in SUM}, "player": m["player"],
                        "nation": m["nation"], "pos": m["pos"],
                        "clubs": set()}
        a = agg[key]
        a["clubs"] |= m["squads"]
        for c in SUM:
            a[c] += fnum(m.get(c))

    rows = []
    for a in agg.values():
        mins = a["min"]
        row = {
            "league": "La Liga",
            "player_id": "laliga:" + norm_name(a["player"]).replace(" ", "-"),
            "player_name": a["player"],
            "player_name_norm": norm_name(a["player"]),
            "club": " / ".join(sorted(a["clubs"])),
            "position": POS_MAP.get(a["pos"].split(",")[0], a["pos"][:1]),
            "nation": a["nation"],
            "appearances": int(a["mp"]),
            "minutes": mins,
            "goals": a["gls"], "assists": a["ast"],
            "xg": None, "npxg": None, "xa": None,
            "shots_on_target": a["sot"],
            "shots_off_target": max(a["sh"] - a["sot"], 0),
            "key_passes": None, "big_chances_created": None,
            "tackles": a["tklw"], "interceptions": a["int"],
            "clearances": None, "saves": a["saves"],
            "yellow_cards": a["crdy"], "red_cards": a["crdr"],
            "fouls": a["fls"], "fouled": a["fld"], "rating_sum": None,
            "pk_goals": a["pk"], "pk_attempts": a["pkatt"],
            "pks_won": a["pkwon"], "pks_conceded": a["pkcon"],
            "own_goals": a["og"], "penalty_saves": None, "clean_sheets": None,
            "avg_rating": None,
        }
        # goalkeeping extras only for keepers that appear in the GK file
        if a["saves"] or a["cs"]:
            row["penalty_saves"] = a["pksv"]
            row["clean_sheets"] = a["cs"]
        for col in ("goals", "assists", "shots_on_target", "tackles",
                    "interceptions", "saves"):
            row[col + "_p90"] = round(row[col] / mins * 90, 3) if mins else None
        for col in ("xg", "npxg", "xa", "key_passes", "big_chances_created"):
            row[col + "_p90"] = None
        rows.append(row)

    print(f"  La Liga: {len(rows)} players from {len(merged)} club-rows "
          f"({repaired} nameless repaired, {dropped} dropped)")
    return rows


if __name__ == "__main__":
    for r in curate()[:3]:
        print(r)
