#!/usr/bin/env python3
"""Build an R32 fantasy squad (unlimited-transfer window).

Optimises the 15-man squad (2 GK / 5 DEF / 5 MID / 3 FWD, $105m, max 3 per
country) for Round-of-32 expected points, then picks the XI / captain via ILP.

R32 EP per player blends:
  • fixture: R32 lambdas from the current team ratings (xGF for attack,
    exp(-opp xG) for clean sheets)
  • form: live WC per-90 goals/assists (wc_player_form.csv) + season fantasy
  • minutes security: WC minutes played → P(start) and a 90-min flag. This
    is deliberately heavy after MD3 (Messi/Haaland/Gakpo cost points by only
    playing a half) — rotation-risk players are penalised.

Run:  .venv/bin/python src/build_r32_squad.py
"""
import csv
import json
import math
import sys
import unicodedata
from datetime import date

import pulp

import team_model
from common import ROOT, PROCESSED, GAME, norm_name, load_json
from loaders import load_team_crosswalk

ROUND = "r16"          # upcoming knockout round to optimise for (feed 'type')
BUDGET = 105.0
SQUAD = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
# country cap by round: group/R32 = 3, R16 = 4, QF = 5, SF = 6, Final = 8
MAX_PER_COUNTRY = {"r32": 3, "r16": 4, "qf": 5, "sf": 6, "final": 8}.get(ROUND, 3)
GOAL_PTS = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3
CS_PTS = {"GK": 5, "DEF": 5, "MID": 1, "FWD": 0}

# Mystery Booster: GK/DEF/MID keep their clean-sheet points until the team
# concedes a SECOND goal -> CS prob becomes P(concede <= 1) = e^-lam(1+lam).
# It was a one-time booster spent at R32, so OFF from R16 onward.
MYSTERY_BOOSTER = False


def cs_prob(opp_xg):
    if MYSTERY_BOOSTER:
        return math.exp(-opp_xg) * (1 + opp_xg)   # P(concede <= 1)
    return math.exp(-opp_xg)                        # P(concede 0)


def _nk(first, last):
    def n(s):
        return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().strip()
    return (n(first)[:1] or "?", n(last))


def main():
    ratings = team_model.fit(asof=date.today(), verbose=False)
    tw = load_team_crosswalk()
    code_of = {int(s): t["fifa_code"] for s, t in tw.items()}
    name_of = {t["fifa_code"]: t["name"] for t in tw.values()}

    # --- fixture metrics per team (upcoming ROUND, read from live feed) ----
    n2c = {norm_name(t["name"]): t["fifa_code"] for t in tw.values()}
    for disp, tgt in {"bosnia & herzegovina": "bosnia and herzegovina",
                      "ivory coast": "cote divoire", "d.r congo": "congo dr",
                      "cape verde": "cabo verde", "turkey": "turkiye",
                      "south korea": "korea republic", "iran": "ir iran",
                      "czech republic": "czechia", "united states": "usa"}.items():
        if norm_name(tgt) in n2c:
            n2c[disp] = n2c[norm_name(tgt)]
    games = load_json(GAME / "wc_games_api.json")["games"]
    team_fix = {}  # code -> (xgf, opp_xg, opp_name)
    for g in games:
        if g.get("type") != ROUND:
            continue
        hn, an = g.get("home_team_name_en"), g.get("away_team_name_en")
        if not hn or not an:
            continue
        h, a = n2c[norm_name(hn)], n2c[norm_name(an)]
        lh, la = ratings.lambdas(h, a, home_has_adv=h in team_model.HOSTS,
                                 away_has_adv=a in team_model.HOSTS)
        team_fix[h] = (lh, la, name_of[a])
        team_fix[a] = (la, lh, name_of[h])

    # --- WC form (per-90 + minutes) ---------------------------------------
    wc = {}
    for r in csv.DictReader(open(PROCESSED / "wc_player_form.csv")):
        nm = r["name"]
        if "." in nm:
            ini, sur = nm.split(".", 1)
            key = _nk(ini, sur)
        else:
            key = _nk("", nm)
        wc[key] = {"g90": float(r["goals_p90"]), "a90": float(r["assists_p90"]),
                   "mins": int(r["mins"]), "started": int(r["started"]),
                   "rating": float(r["rating"])}

    # --- candidate players (only teams still alive in R32) ----------------
    players = json.load(open(GAME / "players.json"))
    cands = []
    for p in players:
        if p["status"] != "playing":
            continue
        code = code_of.get(p["squadId"])
        if code not in team_fix:        # team eliminated in the group stage
            continue
        pos = p["position"]
        xgf, opp_xg, opp = team_fix[code]
        form = wc.get(_nk(p.get("firstName"), p.get("lastName")))
        # minutes security: fraction of a full 3-game group stage played.
        # GKs are absent from the outfield form tables, so fall back to the
        # number of fantasy rounds the player actually scored in (= played).
        rd = p["stats"].get("roundPoints")
        rounds_played = sum(1 for k in ("1", "2", "3")
                            if isinstance(rd, dict) and rd.get(k)) if isinstance(rd, dict) else 0
        mins = form["mins"] if form else 0
        if form:
            p_start = max(0.15, min(0.97, mins / 245.0))
        else:
            p_start = {0: 0.20, 1: 0.45, 2: 0.78, 3: 0.95}[rounds_played]
        g90 = form["g90"] if form else 0.0
        a90 = form["a90"] if form else 0.0
        if not form:  # no tournament minutes → fringe; floor the attack rate
            g90 = {"FWD": 0.15, "MID": 0.06, "DEF": 0.0, "GK": 0.0}[pos]

        e_min = p_start * 85
        mfrac = e_min / 90
        fixmult = xgf / 1.35                      # vs avg knockout attack
        e_goals = g90 * mfrac * fixmult
        e_assist = a90 * mfrac * fixmult
        p_cs = cs_prob(opp_xg)
        ep = 2 * p_start                          # appearance
        ep += GOAL_PTS[pos] * e_goals + ASSIST_PTS * e_assist
        ep += CS_PTS[pos] * p_cs * p_start
        if pos == "GK":
            # saves matter but a clean sheet on a favourite is worth far more;
            # keep the save term small so it can't rescue a losing-side keeper
            ep += min(opp_xg, 1.4) * 0.3 * p_start

        # Scouting bonus: +2 if the player scores >4 pts AND is <5% owned.
        # A (booster-protected) clean sheet alone clears 4 for GK/DEF, so cheap
        # low-owned defenders on favourites stack CS points + this bonus.
        own = p.get("percentSelected", 0) or 0
        if own < 5.0:
            if pos in ("GK", "DEF"):
                p_over4 = p_cs * p_start
            elif pos == "MID":
                p_over4 = min(0.9, 0.4 * p_cs * p_start + e_goals + e_assist)
            else:  # FWD
                p_over4 = min(0.9, 1.6 * e_goals + e_assist)
            ep += 2 * p_over4
            scout = round(2 * p_over4, 2)
        else:
            scout = 0.0
        cands.append({
            "id": p["id"], "name": p.get("knownName") or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
            "pos": pos, "country": name_of[code], "code": code,
            "price": float(p["price"]), "ep": round(ep, 2),
            "p_start": round(p_start, 2), "mins": mins, "opp": opp,
            "xgf": round(xgf, 2), "p_cs": round(p_cs, 2), "scout": scout,
            "own": own, "ft": p["stats"].get("totalPoints", 0),
        })

    # --- ILP: pick 15 maximising XI EP (bench weighted lightly) -----------
    prob = pulp.LpProblem("r32", pulp.LpMaximize)
    pick = {c["id"]: pulp.LpVariable(f"p{c['id']}", cat="Binary") for c in cands}
    start = {c["id"]: pulp.LpVariable(f"s{c['id']}", cat="Binary") for c in cands}
    by = {c["id"]: c for c in cands}
    BENCH_W = 0.10
    prob += pulp.lpSum(start[i] * by[i]["ep"] + BENCH_W * (pick[i] - start[i]) * by[i]["ep"]
                       for i in pick)
    for i in pick:
        prob += start[i] <= pick[i]
    prob += pulp.lpSum(pick[i] * by[i]["price"] for i in pick) <= BUDGET
    for pos, n in SQUAD.items():
        prob += pulp.lpSum(pick[i] for i in pick if by[i]["pos"] == pos) == n
    prob += pulp.lpSum(start[i] for i in pick) == 11
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "GK") == 1
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "DEF") >= 3
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "DEF") <= 5
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "MID") >= 2
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "FWD") >= 1
    prob += pulp.lpSum(start[i] for i in pick if by[i]["pos"] == "FWD") <= 3
    for cc in {c["code"] for c in cands}:
        prob += pulp.lpSum(pick[i] for i in pick if by[i]["code"] == cc) <= MAX_PER_COUNTRY
    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    chosen = [by[i] for i in pick if pick[i].value() == 1]
    xi = {i for i in start if start[i].value() == 1}
    chosen.sort(key=lambda c: (c["id"] not in xi,
                               {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}[c["pos"]],
                               -c["ep"]))
    cost = sum(c["price"] for c in chosen)
    cap = max((c for c in chosen if c["id"] in xi), key=lambda c: c["ep"])

    print(f"\nR32 SQUAD  (cost ${cost:.1f}m / ${BUDGET:.0f}m,  "
          f"XI EP {sum(by[i]['ep'] for i in xi):.1f})\n")
    print(f"{'':2}{'Pos':<4}{'Player':<19}{'Country':<13}{'R32 opp':<13}"
          f"{'$':>5}{'EP':>6}{'St%':>5}{'CS%':>5}{'Own%':>6}{'Scout':>6}")
    print("-" * 92)
    for c in chosen:
        tag = "C" if c["id"] == cap["id"] else (" " if c["id"] in xi else ".")
        print(f"{tag:2}{c['pos']:<4}{c['name'][:18]:<19}{c['country'][:12]:<13}"
              f"{c['opp'][:12]:<13}{c['price']:>5.1f}{c['ep']:>6.1f}"
              f"{c['p_start']*100:>5.0f}{c['p_cs']*100:>5.0f}{c['own']:>6}"
              f"{('+'+format(c['scout'],'.1f')) if c['scout'] else '':>6}")
    print("\n  C = captain   (blank) = starting XI   . = bench   "
          "Scout = expected scouting bonus (<5% owned)")


if __name__ == "__main__":
    main()
