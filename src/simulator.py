#!/usr/bin/env python3
"""Monte Carlo tournament simulator for the 2026 World Cup (Phase 2).

Simulates the remaining tournament from the current state: played group
matches (wc2026_results.csv) enter as facts, everything else is sampled
from the team-strength ratings. Group standings use points / GD / GF /
random (head-to-head omitted — it changes outcomes only in rare multi-way
ties); the 8 best thirds advance; the knockout bracket comes from
data/bracket_2026.json (approximate until the official mapping is
transcribed).

Outputs per team: P(reach each round), P(champion), expected matches
remaining, and per-knockout-round expected goals against conditional on
being alive (feeds clean-sheet projections for knockout horizons).
"""
import math
import random
from collections import defaultdict

from common import ROOT, PROCESSED, load_json, read_csv
import team_model
from loaders import load_fixtures, load_team_crosswalk

ET_FACTOR = 1 / 3  # extra time is 30' of regulation-rate scoring
ROUNDS = ["r32", "r16", "qf", "sf", "final", "champion"]


def poisson_sample(lam, rng):
    l, k, p = math.exp(-lam), 0, rng.random()
    cum = l
    while p > cum and k < 12:
        k += 1
        l *= lam / k
        cum += l
    return k


class Simulator:
    def __init__(self, ratings, rng_seed=2026):
        self.ratings = ratings
        self.rng = random.Random(rng_seed)
        xwalk = load_team_crosswalk()
        self.code = {sid: t["fifa_code"] for sid, t in xwalk.items()}
        self.group_of = {t["fifa_code"]: t["group"] for t in xwalk.values()}
        self.teams = sorted(self.group_of)
        self.groups = defaultdict(list)
        for c, g in self.group_of.items():
            self.groups[g].append(c)

        played = {}
        try:
            for r in read_csv(PROCESSED / "wc2026_results.csv"):
                played[(r["home_code"], r["away_code"])] = (
                    int(r["home_score"]), int(r["away_score"]))
        except FileNotFoundError:
            pass
        self.fixtures = []  # (home_code, away_code, result_or_None)
        for f in load_fixtures():
            h, a = self.code[f["homeSquadId"]], self.code[f["awaySquadId"]]
            self.fixtures.append((h, a, played.get((h, a))))
        self.bracket = load_json(ROOT / "data" / "bracket_2026.json")

    # ---------------------------------------------------------- one sim run

    def _match(self, h, a, knockout):
        lh, la = self.ratings.lambdas(h, a,
                                      home_has_adv=h in team_model.HOSTS,
                                      away_has_adv=a in team_model.HOSTS)
        gh = poisson_sample(lh, self.rng)
        ga = poisson_sample(la, self.rng)
        if not knockout or gh != ga:
            return gh, ga, lh, la
        gh += poisson_sample(lh * ET_FACTOR, self.rng)
        ga += poisson_sample(la * ET_FACTOR, self.rng)
        if gh == ga:  # shootout: slight tilt toward the stronger side
            p_home = 0.5 + 0.08 * math.tanh((lh - la))
            gh += 1 if self.rng.random() < p_home else 0
            ga += 1 if gh == ga else 0
        return gh, ga, lh, la

    def _group_stage(self, stats):
        table = {t: [0, 0, 0] for t in self.teams}  # pts, gd, gf
        for h, a, res in self.fixtures:
            if res is not None:
                gh, ga = res
            else:
                gh, ga, lh, la = self._match(h, a, knockout=False)
            for t, gf, gc in ((h, gh, ga), (a, ga, gh)):
                table[t][1] += gf - gc
                table[t][2] += gf
                stats[t]["group_cs"] += (gc == 0)
            table[h][0] += 3 if gh > ga else 1 if gh == ga else 0
            table[a][0] += 3 if ga > gh else 1 if gh == ga else 0
        firsts, seconds, thirds = {}, {}, []
        for g, members in self.groups.items():
            order = sorted(members,
                           key=lambda t: (table[t][0], table[t][1],
                                          table[t][2], self.rng.random()),
                           reverse=True)
            firsts[g], seconds[g] = order[0], order[1]
            thirds.append((table[order[2]][0], table[order[2]][1],
                           table[order[2]][2], self.rng.random(), order[2]))
        thirds.sort(reverse=True)
        best_thirds = [t[-1] for t in thirds[:8]]
        return firsts, seconds, best_thirds

    def _knockouts(self, firsts, seconds, best_thirds, stats):
        # fill R32 slots; thirds assigned to T? slots avoiding group rematches
        slots = []
        t_pool = best_thirds[:]
        self.rng.shuffle(t_pool)
        for m in self.bracket["r32"]:
            pair = []
            for side in (m["home"], m["away"]):
                if side == "T?":
                    pair.append(None)
                else:
                    kind, g = side.split("_")
                    pair.append(firsts[g.upper()] if kind == "W"
                                else seconds[g.upper()])
            slots.append(pair)
        for pair in slots:
            if pair[0] is None or pair[1] is None:
                fixed = pair[0] or pair[1]
                idx = next((i for i, t in enumerate(t_pool)
                            if self.group_of[t] != self.group_of[fixed]),
                           0)
                third = t_pool.pop(idx)
                pair[pair.index(None)] = third

        alive = [tuple(p) for p in slots]
        for rnd, nxt in (("r32", "r16"), ("r16", "qf"), ("qf", "sf"),
                         ("sf", "final")):
            winners = []
            for h, a in alive:
                for t, opp in ((h, a), (a, h)):
                    stats[t][rnd] += 1
                    lo, _ = self.ratings.lambdas(
                        opp, t, home_has_adv=opp in team_model.HOSTS,
                        away_has_adv=t in team_model.HOSTS)
                    stats[t][rnd + "_la"] += lo  # expected conceded if alive
                gh, ga, lh, la = self._match(h, a, knockout=True)
                winners.append(h if gh > ga else a)
            alive = [(winners[i], winners[j]) for i, j in self.bracket[nxt]]
        h, a = alive[0]
        stats[h]["final"] += 1
        stats[a]["final"] += 1
        gh, ga, _, _ = self._match(h, a, knockout=True)
        stats[h if gh > ga else a]["champion"] += 1

    def run(self, n=10000):
        stats = {t: defaultdict(float) for t in self.teams}
        for _ in range(n):
            firsts, seconds, thirds = self._group_stage(stats)
            self._knockouts(firsts, seconds, thirds, stats)
        out = {}
        for t in self.teams:
            s = stats[t]
            row = {"team": t}
            for r in ROUNDS:
                row["p_" + r] = s[r] / n
            row["exp_matches_remaining"] = (
                sum(1 for h, a, res in self.fixtures
                    if res is None and t in (h, a))
                + sum(s[r] / n for r in ("r32", "r16", "qf", "sf", "final")))
            row["group_cs_rate"] = s["group_cs"] / (3 * n)
            for r in ("r32", "r16", "qf", "sf"):
                row[f"lambda_against_{r}"] = (s[r + "_la"] / s[r]
                                              if s[r] else None)
            out[t] = row
        return out
