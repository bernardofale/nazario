#!/usr/bin/env python3
"""Phase 2 driver: fit the team model on everything ingested so far
(including any played 2026 matches), run the Monte Carlo, and write the
simulator outputs that MD2+ transfer decisions consume.

Run:  python3 src/phase2_simulate.py [n_sims]
Outputs (data/processed/):
  simulation_teams.csv    per team: P(reach round), P(champion),
                          expected matches remaining, conditional
                          knockout lambdas-against, group CS rate
  team_ratings.csv        refreshed confederation-anchored ratings
"""
import sys
from datetime import date

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

import team_model
from common import PROCESSED, write_csv
from simulator import Simulator, ROUNDS


def main(n=10000):
    print("fitting team model…")
    ratings = team_model.fit(asof=date.today())
    write_csv(PROCESSED / "team_ratings.csv",
              sorted(({"team": t, "attack": round(ratings.att[t], 3),
                       "defence": round(ratings.dfc[t], 3)}
                      for t in ratings.att),
                     key=lambda r: -r["attack"] / r["defence"]),
              ["team", "attack", "defence"])

    print(f"simulating tournament ({n:,} runs)…")
    sim = Simulator(ratings)
    res = sim.run(n)

    cols = (["team"] + ["p_" + r for r in ROUNDS]
            + ["exp_matches_remaining", "group_cs_rate"]
            + [f"lambda_against_{r}" for r in ("r32", "r16", "qf", "sf")])
    rows = sorted(res.values(), key=lambda r: -r["p_champion"])
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float):
                r[k] = round(v, 4)
    write_csv(PROCESSED / "simulation_teams.csv", rows, cols)

    print(f"\n{'team':5} {'R32':>6} {'R16':>6} {'QF':>6} {'SF':>6} "
          f"{'final':>6} {'champ':>6}  E[matches]")
    for r in rows[:12]:
        print(f"{r['team']:5} {r['p_r32']:6.1%} {r['p_r16']:6.1%} "
              f"{r['p_qf']:6.1%} {r['p_sf']:6.1%} {r['p_final']:6.1%} "
              f"{r['p_champion']:6.1%}  {r['exp_matches_remaining']:.2f}")
    print("-> simulation_teams.csv, team_ratings.csv")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 10000)
