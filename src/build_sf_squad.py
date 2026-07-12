#!/usr/bin/env python3
"""Build a Semi-final fantasy squad (SF: France-Spain, England-Argentina).

Same EP engine as build_r32_squad.py, adapted for the semis:
  • only the 4 alive teams are candidates
  • country cap = 6, budget $105m
  • Mystery Booster (revealed = Qualification booster): +2 to every starting-XI
    player whose team ADVANCES to the final and plays >=1 min. Modelled as an
    EV bonus of 2 * P(team reaches final) * p_start added to the XI term only,
    so the optimiser stacks the XI toward the likelier finalists. Two teams
    advance from the SF vs one champion from the final, so the booster is worth
    ~2x here — that's why we spend it now.

Run:  python3 src/build_sf_squad.py
"""
import csv
import json
import math
import unicodedata
from datetime import date

import pulp

import team_model
from common import PROCESSED, GAME, norm_name, load_json
from loaders import load_team_crosswalk

ROUND = "sf"
BUDGET = 105.0
SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
MAX_PER_COUNTRY = 6
FREE_TRANSFERS = 5           # SF allocation; each extra transfer costs -3 pts
# current squad after QF: 5 eliminated (auto-out) + 10 survivors we may keep free
CURRENT_SURVIVORS = {45, 1318, 498, 1088, 491, 517, 505, 500, 468, 38}
GOAL_PTS = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3
CS_PTS = {"GK": 5, "DEF": 5, "MID": 1, "FWD": 0}
USE_MYSTERY_BOOSTER = True   # +2 per advancing XI player, spent at the SF


def _nk(first, last):
    def n(s):
        return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()
    return (n(first)[:1] or "?", n(last))


def win_probs(ratings, n2c):
    """P(team reaches the final) for each of the 4 SF teams, from the feed."""
    def pois(k, l):
        return math.exp(-l) * l ** k / math.factorial(k)
    p_adv, xg = {}, {}
    for g in load_json(GAME / "wc_games_api.json")["games"]:
        if g.get("type") != "sf":
            continue
        hn, an = g["home_team_name_en"], g["away_team_name_en"]
        h, a = n2c[norm_name(hn)], n2c[norm_name(an)]
        lh, la = ratings.lambdas(h, a, home_has_adv=h in team_model.HOSTS,
                                 away_has_adv=a in team_model.HOSTS)
        ph = pa = pd = 0.0
        for i in range(11):
            for j in range(11):
                p = pois(i, lh) * pois(j, la)
                if i > j:
                    ph += p
                elif i < j:
                    pa += p
                else:
                    pd += p
        tilt = 0.5 + 0.08 * math.tanh(lh - la)
        wh, wa = ph + pd * tilt, pa + pd * (1 - tilt)
        p_adv[h], p_adv[a] = wh / (wh + wa), wa / (wh + wa)
        xg[h], xg[a] = (lh, la, an), (la, lh, hn)
    return p_adv, xg


def main():
    ratings = team_model.fit(asof=date.today(), verbose=False)
    tw = load_team_crosswalk()
    code_of = {int(s): t["fifa_code"] for s, t in tw.items()}
    name_of = {t["fifa_code"]: t["name"] for t in tw.values()}
    n2c = {norm_name(t["name"]): t["fifa_code"] for t in tw.values()}

    p_adv, team_fix = win_probs(ratings, n2c)   # only the 4 SF teams populate these

    wc = {}
    for r in csv.DictReader(open(PROCESSED / "wc_player_form.csv")):
        nm = r["name"]
        key = _nk(*nm.split(".", 1)) if "." in nm else _nk("", nm)
        wc[key] = {"g90": float(r["goals_p90"]), "a90": float(r["assists_p90"]),
                   "mins": int(r["mins"]), "started": int(r["started"])}

    players = json.load(open(GAME / "players.json"))
    cands = []
    for p in players:
        if p["status"] != "playing":
            continue
        code = code_of.get(p["squadId"])
        if code not in team_fix:
            continue
        pos = p["position"]
        xgf, opp_xg, opp = team_fix[code]
        form = wc.get(_nk(p.get("firstName"), p.get("lastName")))
        rd = p["stats"].get("roundPoints")
        rounds_played = sum(1 for k in ("1", "2", "3", "4", "5", "6")
                            if isinstance(rd, dict) and rd.get(k)) if isinstance(rd, dict) else 0
        mins = form["mins"] if form else 0
        if form:
            p_start = max(0.15, min(0.97, mins / 540.0))   # of a full 6-match run
        else:
            p_start = min(0.9, 0.12 + 0.13 * rounds_played)
        g90 = form["g90"] if form else 0.0
        a90 = form["a90"] if form else 0.0
        if not form:
            g90 = {"FWD": 0.15, "MID": 0.06, "DEF": 0.0, "GK": 0.0}[pos]

        e_min = p_start * 85
        mfrac = e_min / 90
        fixmult = xgf / 1.35
        e_goals = g90 * mfrac * fixmult
        e_assist = a90 * mfrac * fixmult
        p_cs = math.exp(-opp_xg)
        ep = 2 * p_start
        ep += GOAL_PTS[pos] * e_goals + ASSIST_PTS * e_assist
        ep += CS_PTS[pos] * p_cs * p_start
        if pos == "GK":
            ep += min(opp_xg, 1.4) * 0.3 * p_start

        own = p.get("percentSelected", 0) or 0
        scout = 0.0
        if own < 5.0:
            if pos in ("GK", "DEF"):
                p_over4 = p_cs * p_start
            elif pos == "MID":
                p_over4 = min(0.9, 0.4 * p_cs * p_start + e_goals + e_assist)
            else:
                p_over4 = min(0.9, 1.6 * e_goals + e_assist)
            ep += 2 * p_over4
            scout = round(2 * p_over4, 2)

        # Mystery booster EV — only realised if this player STARTS (XI term)
        boost = 2 * p_adv[code] * p_start if USE_MYSTERY_BOOSTER else 0.0
        cands.append({
            "id": p["id"], "name": p.get("knownName") or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
            "pos": pos, "country": name_of[code], "code": code,
            "price": float(p["price"]), "ep": round(ep, 2), "boost": round(boost, 2),
            "ep_xi": round(ep + boost, 2), "p_start": round(p_start, 2), "mins": mins,
            "opp": opp, "p_adv": round(p_adv[code], 2), "p_cs": round(p_cs, 2),
            "own": own, "scout": scout,
        })

    prob = pulp.LpProblem("sf", pulp.LpMaximize)
    pick = {c["id"]: pulp.LpVariable(f"p{c['id']}", cat="Binary") for c in cands}
    start = {c["id"]: pulp.LpVariable(f"s{c['id']}", cat="Binary") for c in cands}
    by = {c["id"]: c for c in cands}
    BENCH_W = 0.10
    # keeping a current survivor (even benched) avoids a -3 transfer hit; adding
    # a non-survivor beyond the 5 free replacements costs 3 pts. Model as +3 per
    # kept survivor (constant offset makes the -3 economics explicit).
    KEEP_BONUS = 3.0
    prob += pulp.lpSum(start[i] * by[i]["ep_xi"] + BENCH_W * (pick[i] - start[i]) * by[i]["ep"]
                       + (KEEP_BONUS * pick[i] if by[i]["id"] in CURRENT_SURVIVORS else 0)
                       for i in pick)
    for i in pick:
        prob += start[i] <= pick[i]
    prob += pulp.lpSum(pick[i] * by[i]["price"] for i in pick) <= BUDGET
    for pos, n in SQUAD.items():
        prob += pulp.lpSum(pick[i] for i in pick if by[i]["pos"] == pos) == n
    prob += pulp.lpSum(start[i] for i in pick) == 11
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "GK") == 1
    # legal formations only: DEF 3-5, MID 3-5, FWD 1-3 (sum=10 outfield)
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "DEF") >= 3
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "DEF") <= 5
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "MID") >= 3
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "MID") <= 5
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "FWD") >= 1
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "FWD") <= 3
    for cc in {c["code"] for c in cands}:
        prob += pulp.lpSum(pick[i] for i in pick if by[i]["code"] == cc) <= MAX_PER_COUNTRY
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    chosen = [by[i] for i in pick if pick[i].value() == 1]
    xi = {i for i in start if start[i].value() == 1}
    chosen.sort(key=lambda c: (c["id"] not in xi,
                               {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}[c["pos"]], -c["ep_xi"]))
    cost = sum(c["price"] for c in chosen)
    cap = max((c for c in chosen if c["id"] in xi), key=lambda c: c["ep_xi"])

    print(f"\nSF SQUAD  (cost ${cost:.1f}m / ${BUDGET:.0f}m,  "
          f"XI EP {sum(by[i]['ep_xi'] for i in xi):.1f} incl. booster)\n")
    print(f"{'':2}{'Pos':<4}{'Player':<20}{'Country':<11}{'SF opp':<11}"
          f"{'$':>5}{'EP':>6}{'+Bst':>5}{'St%':>5}{'Adv%':>5}{'CS%':>5}{'Own%':>6}")
    print("-" * 92)
    for c in chosen:
        tag = "C" if c["id"] == cap["id"] else (" " if c["id"] in xi else ".")
        print(f"{tag:2}{c['pos']:<4}{c['name'][:19]:<20}{c['country'][:10]:<11}"
              f"{c['opp'][:10]:<11}{c['price']:>5.1f}{c['ep']:>6.1f}{c['boost']:>5.1f}"
              f"{c['p_start']*100:>5.0f}{c['p_adv']*100:>5.0f}{c['p_cs']*100:>5.0f}{c['own']:>6}")
    print("\n  C = captain   (blank) = XI   . = bench   "
          "+Bst = Mystery-booster EV (only if starts & team advances)")

    kept = [c for c in chosen if c["id"] in CURRENT_SURVIVORS]
    new = [c for c in chosen if c["id"] not in CURRENT_SURVIVORS]
    n_transfers = len(new)
    paid = max(0, n_transfers - FREE_TRANSFERS)
    print(f"\nTRANSFERS: {n_transfers} ({FREE_TRANSFERS} free, {paid} paid = "
          f"{-3*paid} pts).  Kept {len(kept)}/10 survivors.")
    print("  IN :", ", ".join(f"{c['name']} ({c['country'][:3]},{c['pos']})" for c in new))
    print("  (drop the 5 eliminated: Courtois, Hakimi, Ryerson, Ounahi, Ødegaard)")
    # machine-readable for reconciliation
    json.dump({"xi": list(xi), "squad": [c["id"] for c in chosen],
               "cands": {c["id"]: c for c in chosen}},
              open(PROCESSED / "sf_squad.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
