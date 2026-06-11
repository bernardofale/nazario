#!/usr/bin/env python3
"""Phase 1 — lock-day squad.

Deliberately simple but rules-complete (see FANTASY_ML_PROPOSAL.md §5):
  A. time-decayed Poisson attack/defence ratings on all 1,907 matches
  B. expected goals for/against per 2026 group fixture (MD1–MD3)
  C. heuristic per-player expected fantasy points per matchday
  D. exact ILP for the 15-man squad / XI / captain under all rules

Run:  .venv/bin/python src/phase1_squad.py
Outputs: data/processed/team_ratings.csv, player_projections.csv,
         initial_squad.csv + a console summary.
"""
import math
from collections import defaultdict
from datetime import date

import pulp

import team_model
from common import PROCESSED, write_csv
from loaders import (load_fixtures, load_players, load_team_crosswalk,
                     load_player_crosswalk, load_club_stats)

TODAY = date(2026, 6, 11)


# ----------------------------------------------------- B. fixture expectations

def fixture_expectations(ratings, team_xwalk):
    """Per squad_id, per matchday: (lambda_for, lambda_against)."""
    code_of = {sid: t["fifa_code"] for sid, t in team_xwalk.items()}
    exp = defaultdict(dict)
    for f in load_fixtures():
        hc, ac = code_of[f["homeSquadId"]], code_of[f["awaySquadId"]]
        lam_h, lam_a = ratings.lambdas(hc, ac,
                                       home_has_adv=hc in team_model.HOSTS,
                                       away_has_adv=ac in team_model.HOSTS)
        exp[f["homeSquadId"]][f["matchday"]] = (lam_h, lam_a)
        exp[f["awaySquadId"]][f["matchday"]] = (lam_a, lam_h)
    return exp


# ------------------------------------------------------- C. player projection

POS_GOAL_BASE = {"GK": 0.02, "DEF": 0.5, "MID": 1.0, "FWD": 2.2}
POS_GOAL_P90 = {"DEF": 0.05, "MID": 0.12, "FWD": 0.35}   # club-level averages
POS_ASSIST_BASE = {"GK": 0.05, "DEF": 0.6, "MID": 1.4, "FWD": 1.0}
GOAL_PTS = {"GK": 9, "DEF": 7, "MID": 6, "FWD": 5}
CS_PTS = {"GK": 5, "DEF": 5, "MID": 1, "FWD": 0}
YELLOW_BASE = {"GK": 0.06, "DEF": 0.22, "MID": 0.20, "FWD": 0.14}
SLOTS = {"GK": 1.0, "DEF": 4.5, "MID": 4.0, "FWD": 1.5}


def start_probability(rank_margin):
    """Soft starter probability from depth-chart margin (slots - rank + 1)."""
    return max(0.04, min(0.93, 1 / (1 + math.exp(-2.2 * rank_margin))))


def project_players(exp, team_xwalk):
    players = [p for p in load_players() if p["status"] == "playing"]
    xwalk = load_player_crosswalk()
    club = {c["player_id"]: c for c in load_club_stats()}

    # depth-chart rank within (squad, position) by price then ownership
    groups = defaultdict(list)
    for p in players:
        groups[(p["squadId"], p["position"])].append(p)
    rank = {}
    for (sid, pos), grp in groups.items():
        grp.sort(key=lambda q: (-q["price"], -(q["percentSelected"] or 0)))
        for i, q in enumerate(grp):
            rank[q["id"]] = SLOTS[pos] - i  # margin: + = inside the XI

    projections = []
    for p in players:
        pos, sid = p["position"], p["squadId"]
        xw = xwalk[p["id"]]
        cs_row = club.get(xw["club_player_id"]) if xw["club_player_id"] else None

        p_start = start_probability(rank[p["id"]])
        p_sub = 0.45 * (1 - p_start)
        e_min = p_start * 78 + p_sub * 18
        p60 = p_start * 0.78
        appearance_pts = p_start * (1 + 0.78) + p_sub * 1.0

        # attacking multipliers from club form / Euro 2024 goals / penalties
        g_mult = a_mult = 1.0
        if cs_row and float(cs_row["minutes"] or 0) >= 450:
            gp90 = float(cs_row["goals_p90"] or 0)
            xg90 = float(cs_row["xg_p90"] or 0) or gp90
            blend = (gp90 + xg90) / 2
            g_mult = max(0.4, min(3.0, 0.5 + blend / POS_GOAL_P90.get(pos, 0.12)))
            ap90 = float(cs_row["assists_p90"] or 0)
            xa90 = float(cs_row["xa_p90"] or 0) or ap90
            a_mult = max(0.4, min(3.0, 0.5 + (ap90 + xa90) / 2 / 0.12))
            if float(cs_row["pk_goals"] or 0) >= 2 or float(cs_row["xg"] or 0) - float(cs_row["npxg"] or 0) > 1.5:
                g_mult *= 1.25  # penalty taker
        if xw["euro2024_goals"]:
            g_mult *= 1 + 0.12 * int(xw["euro2024_goals"])
        raw_goal = POS_GOAL_BASE[pos] * g_mult
        raw_assist = POS_ASSIST_BASE[pos] * a_mult

        y_rate = YELLOW_BASE[pos]
        if cs_row and float(cs_row["minutes"] or 0) >= 450:
            club_y = float(cs_row["yellow_cards"] or 0) / max(float(cs_row["appearances"]), 1)
            y_rate = 0.5 * y_rate + 0.5 * club_y

        projections.append({
            "player": p, "pos": pos, "squad": sid, "p_start": p_start,
            "e_min": e_min, "p60": p60, "appearance_pts": appearance_pts,
            "raw_goal": raw_goal, "raw_assist": raw_assist, "y_rate": y_rate,
            "club_row": cs_row, "xw": xw,
        })

    # normalize attacking shares within squad (weighted by expected minutes)
    for sid in {pr["squad"] for pr in projections}:
        squad = [pr for pr in projections if pr["squad"] == sid]
        gtot = sum(pr["raw_goal"] * pr["e_min"] / 90 for pr in squad)
        atot = sum(pr["raw_assist"] * pr["e_min"] / 90 for pr in squad)
        for pr in squad:
            pr["goal_share"] = pr["raw_goal"] / gtot if gtot else 0
            pr["assist_share"] = 0.75 * pr["raw_assist"] / atot if atot else 0
            # ~75% of goals have an attributed assist

    # per-matchday expected points
    for pr in projections:
        pos, sid = pr["pos"], pr["squad"]
        md_pts, total = {}, 0.0
        for md in (1, 2, 3):
            lam_for, lam_against = exp[sid][md]
            mfrac = pr["e_min"] / 90
            e_goals = lam_for * pr["goal_share"] * mfrac
            e_assists = lam_for * pr["assist_share"] * mfrac
            p_cs = math.exp(-lam_against)
            e_conc_after1 = lam_against - 1 + math.exp(-lam_against)
            pts = pr["appearance_pts"]
            pts += GOAL_PTS[pos] * e_goals
            pts += 3 * e_assists
            pts += CS_PTS[pos] * p_cs * pr["p60"]
            if pos in ("GK", "DEF"):
                pts -= e_conc_after1 * pr["p_start"]
            pts -= pr["y_rate"] * mfrac - 0.0  # yellows
            pts -= 2 * 0.012 * mfrac          # reds, small prior
            if pos == "GK":
                e_saves = lam_against * 2.2 * pr["p_start"]
                pts += e_saves / 3
            if pos == "FWD":
                sot90 = None
                c = pr["club_row"]
                if c and float(c["minutes"] or 0) >= 450:
                    sot90 = float(c["shots_on_target_p90"] or 0)
                if not sot90:
                    sot90 = 3.2 * lam_for * pr["goal_share"]
                pts += (sot90 * mfrac) / 2 * 0.9
            if pos == "MID":
                t90, kp90 = 1.6, 0.9
                c = pr["club_row"]
                if c and float(c["minutes"] or 0) >= 450:
                    t90 = float(c["tackles_p90"] or 0) or t90
                    if c["key_passes_p90"]:
                        kp90 = float(c["key_passes_p90"])
                pts += (t90 * mfrac) / 3 + (kp90 * mfrac) / 2 * 0.5
            md_pts[md] = pts
            total += pts
        pr["md_pts"] = md_pts
        pr["total_pts"] = total
    return projections


# ------------------------------------------------------------- D. optimizer

def optimize(projections):
    POS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    XI_MIN = {"GK": 1, "DEF": 3, "MID": 3, "FWD": 1}
    XI_MAX = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
    BENCH_W = 0.12

    prob = pulp.LpProblem("squad", pulp.LpMaximize)
    x = {pr["player"]["id"]: pulp.LpVariable(f"x{pr['player']['id']}", cat="Binary")
         for pr in projections}
    y = {pid: pulp.LpVariable(f"y{pid}", cat="Binary") for pid in x}
    c = {pid: pulp.LpVariable(f"c{pid}", cat="Binary") for pid in x}
    pts = {pr["player"]["id"]: pr["total_pts"] for pr in projections}
    by_id = {pr["player"]["id"]: pr for pr in projections}

    prob += (pulp.lpSum(pts[i] * y[i] for i in x)
             + pulp.lpSum(pts[i] * c[i] for i in x)
             + BENCH_W * pulp.lpSum(pts[i] * (x[i] - y[i]) for i in x))
    prob += pulp.lpSum(x.values()) == 15
    prob += pulp.lpSum(y.values()) == 11
    prob += pulp.lpSum(c.values()) == 1
    prob += pulp.lpSum(by_id[i]["player"]["price"] * x[i] for i in x) <= 100.0
    for pos, n in POS.items():
        prob += pulp.lpSum(x[i] for i in x if by_id[i]["pos"] == pos) == n
        prob += pulp.lpSum(y[i] for i in x if by_id[i]["pos"] == pos) >= XI_MIN[pos]
        prob += pulp.lpSum(y[i] for i in x if by_id[i]["pos"] == pos) <= XI_MAX[pos]
    squads = {pr["squad"] for pr in projections}
    for s in squads:
        prob += pulp.lpSum(x[i] for i in x if by_id[i]["squad"] == s) <= 3
    for i in x:
        prob += y[i] <= x[i]
        prob += c[i] <= y[i]

    status = prob.solve(pulp.PULP_CBC_CMD(msg=False))
    assert pulp.LpStatus[status] == "Optimal", pulp.LpStatus[status]
    squad = [by_id[i] for i in x if x[i].value() > 0.5]
    xi = {i for i in x if y[i].value() > 0.5}
    captain = next(i for i in x if c[i].value() > 0.5)
    return squad, xi, captain


def main():
    print("fitting team ratings…")
    ratings = team_model.fit(asof=TODAY)
    att, dfc = ratings.att, ratings.dfc
    team_xwalk = load_team_crosswalk()
    write_csv(PROCESSED / "team_ratings.csv",
              sorted(({"team": t, "attack": round(att[t], 3),
                       "defence": round(dfc[t], 3)} for t in att),
                     key=lambda r: -r["attack"] / r["defence"]),
              ["team", "attack", "defence"])

    exp = fixture_expectations(ratings, team_xwalk)
    print("projecting players…")
    projections = project_players(exp, team_xwalk)
    write_csv(PROCESSED / "player_projections.csv",
              [{"player_id": pr["player"]["id"],
                "name": pr["xw"]["known_name"] or pr["xw"]["full_name"],
                "country": pr["xw"]["country"], "pos": pr["pos"],
                "price": pr["player"]["price"],
                "p_start": round(pr["p_start"], 2),
                "md1": round(pr["md_pts"][1], 2),
                "md2": round(pr["md_pts"][2], 2),
                "md3": round(pr["md_pts"][3], 2),
                "total": round(pr["total_pts"], 2),
                "pct_selected": pr["player"]["percentSelected"]}
               for pr in sorted(projections, key=lambda r: -r["total_pts"])],
              ["player_id", "name", "country", "pos", "price", "p_start",
               "md1", "md2", "md3", "total", "pct_selected"])

    print("solving squad ILP…")
    squad, xi, captain = optimize(projections)
    order = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    squad.sort(key=lambda pr: (pr["player"]["id"] not in xi, order[pr["pos"]],
                               -pr["total_pts"]))
    cost = sum(pr["player"]["price"] for pr in squad)
    xi_rows = [pr for pr in squad if pr["player"]["id"] in xi]
    bench = [pr for pr in squad if pr["player"]["id"] not in xi]
    bench.sort(key=lambda pr: (pr["pos"] == "GK", -pr["total_pts"]))
    vice = max((pr for pr in xi_rows if pr["player"]["id"] != captain),
               key=lambda pr: pr["total_pts"])

    rows = []
    print(f"\n=== INITIAL SQUAD  (cost {cost:.1f}/100.0, "
          f"E[pts MD1–3 incl. captain] "
          f"{sum(pr['total_pts'] for pr in xi_rows) + by(squad, captain)['total_pts']:.1f}) ===")
    for pr in squad:
        pid = pr["player"]["id"]
        role = ("CAPTAIN" if pid == captain else
                "vice" if pr is vice else
                "XI" if pid in xi else f"bench{bench.index(pr) + 1}")
        name = pr["xw"]["known_name"] or pr["xw"]["full_name"]
        print(f"  {pr['pos']:3} {name:28} {pr['xw']['country']}  "
              f"£{pr['player']['price']:>4}  E={pr['total_pts']:5.2f}  {role}")
        rows.append({"player_id": pid, "name": name,
                     "country": pr["xw"]["country"], "pos": pr["pos"],
                     "price": pr["player"]["price"],
                     "expected_points_md1_3": round(pr["total_pts"], 2),
                     "role": role})
    nd = sum(1 for pr in xi_rows if pr["pos"] == "DEF")
    nm = sum(1 for pr in xi_rows if pr["pos"] == "MID")
    nf = sum(1 for pr in xi_rows if pr["pos"] == "FWD")
    print(f"  formation: {nd}-{nm}-{nf}")
    write_csv(PROCESSED / "initial_squad.csv", rows,
              ["player_id", "name", "country", "pos", "price",
               "expected_points_md1_3", "role"])
    print("-> initial_squad.csv, player_projections.csv, team_ratings.csv")


def by(squad, pid):
    return next(pr for pr in squad if pr["player"]["id"] == pid)


if __name__ == "__main__":
    main()
