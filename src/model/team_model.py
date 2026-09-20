#!/usr/bin/env python3
"""Team-strength model (Phase 2 production version, refactored out of
phase1_squad).

Time-decayed Poisson attack/defence ratings fitted on every match in
matches_international.csv (WC history, qualifiers, Euro 2024, and 2026
results as they are ingested — 2026 matches have ~zero age so they enter
at full weight). Confederation scales are anchored on inter-confederation
World Cup matches with a slow decay.

Public API:
    fit(asof=date)            -> Ratings (att, dfc, base, key fn)
    Ratings.lambdas(home_code, away_code, home_adv=False/True per side)
    outcome_probs(lh, la)     -> P(home win), P(draw), P(away win)
    poisson_pmf(lam, k)
"""
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from common import CURATED, PROCESSED, norm_name, read_csv
from loaders import load_matches

HALF_LIFE_DAYS = 18 * 30.4
ANCHOR_HALF_LIFE_DAYS = 8 * 365.25  # confederation gaps move slowly
HOSTS = {"MEX", "USA", "CAN"}
HOME_ADV = 1.25          # qualifier home advantage; hosts keep it in 2026
PRIOR_WEIGHT = 3.0       # pseudo-observations shrinking ratings to average
ANCHOR_PRIOR = 2.0
N_ITER = 60
LAMBDA_MIN, LAMBDA_MAX = 0.15, 4.5


def team_key_factory(matches):
    """Key teams by FIFA code; teams seen without a code (some Euro 2024
    sides) borrow the code attached to the same normalized name elsewhere."""
    name_to_code = {}
    for m in matches:
        for side in ("home", "away"):
            if m[f"{side}_code"]:
                name_to_code[norm_name(m[f"{side}_team"])] = m[f"{side}_code"]

    def key(team, code):
        return code or name_to_code.get(norm_name(team)) or norm_name(team)
    return key


def load_confederations():
    confs = {}
    for q in read_csv(PROCESSED / "qualifiers_2026.csv"):
        confs[q["home_code"]] = q["confederation"]
        confs[q["away_code"]] = q["confederation"]
    for t in read_csv(CURATED / "teams_curated.csv"):
        confs.setdefault(t["team_code"], t["confederation_code"])
    return confs


@dataclass
class Ratings:
    att: dict
    dfc: dict
    base: float
    key: object = field(repr=False)
    tournament_factor: float = 1.0  # tournament play scores below the
    # qualifier-heavy training average; fitted on WC/Euro matches

    def lambdas(self, home_code, away_code, home_has_adv=False,
                away_has_adv=False):
        lh = (self.att.get(home_code, 1.0) * self.dfc.get(away_code, 1.0)
              * self.base * self.tournament_factor
              * (HOME_ADV if home_has_adv else 1.0))
        la = (self.att.get(away_code, 1.0) * self.dfc.get(home_code, 1.0)
              * self.base * self.tournament_factor
              * (HOME_ADV if away_has_adv else 1.0))
        return (max(LAMBDA_MIN, min(LAMBDA_MAX, lh)),
                max(LAMBDA_MIN, min(LAMBDA_MAX, la)))


def fit(asof=None, matches=None, verbose=True):
    asof = asof or date.today()
    matches = matches if matches is not None else load_matches()
    matches = [m for m in matches if date.fromisoformat(m["date"]) < asof]
    key = team_key_factory(matches)

    obs = []  # (team, opponent, goals, weight, at_home_with_advantage)
    for m in matches:
        age = (asof - date.fromisoformat(m["date"])).days
        w = 0.5 ** (age / HALF_LIFE_DAYS)
        if w < 0.001:
            continue
        h = key(m["home_team"], m["home_code"])
        a = key(m["away_team"], m["away_code"])
        # home advantage is real in qualifiers; WC/Euro venues are neutral
        is_home = m["source"].endswith("_qualifiers")
        obs.append((h, a, int(m["home_score"]), w, is_home))
        obs.append((a, h, int(m["away_score"]), w, False))

    teams = {t for o in obs for t in (o[0], o[1])}
    total_w = sum(o[3] for o in obs)
    base = sum(o[2] * o[3] for o in obs) / total_w
    att = {t: 1.0 for t in teams}
    dfc = {t: 1.0 for t in teams}
    for _ in range(N_ITER):
        num, den = defaultdict(float), defaultdict(float)
        for t, opp, g, w, home in obs:
            lam = dfc[opp] * base * (HOME_ADV if home else 1.0)
            num[t] += w * g
            den[t] += w * lam
        att = {t: (num[t] + PRIOR_WEIGHT * base) / (den[t] + PRIOR_WEIGHT * base)
               for t in teams}
        num, den = defaultdict(float), defaultdict(float)
        for t, opp, g, w, home in obs:
            lam = att[t] * base * (HOME_ADV if home else 1.0)
            num[opp] += w * g
            den[opp] += w * lam
        dfc = {t: (num[t] + PRIOR_WEIGHT * base) / (den[t] + PRIOR_WEIGHT * base)
               for t in teams}

    att, dfc = _anchor(matches, key, att, dfc, base, asof, verbose)

    # tournament deflator: actual vs predicted goals on tournament matches
    # (slow decay — this is a property of tournament play, not of teams)
    num = den = 0.0
    for m in matches:
        if m["source"].endswith("_qualifiers"):
            continue
        w = 0.5 ** ((asof - date.fromisoformat(m["date"])).days
                    / ANCHOR_HALF_LIFE_DAYS)
        h = key(m["home_team"], m["home_code"])
        a = key(m["away_team"], m["away_code"])
        lh = att.get(h, 1) * dfc.get(a, 1) * base
        la = att.get(a, 1) * dfc.get(h, 1) * base
        num += w * (int(m["home_score"]) + int(m["away_score"]))
        den += w * (lh + la)
    factor = max(0.7, min(1.1, num / den)) if den else 1.0
    if verbose:
        print(f"  tournament factor: {factor:.3f}")
    return Ratings(att=att, dfc=dfc, base=base, key=key,
                   tournament_factor=factor)


def _anchor(matches, key, att, dfc, base, asof, verbose):
    """Per-confederation strength scalar moment-matched on
    inter-confederation matches (qualifiers never cross confederations)."""
    confs = load_confederations()
    inter = []
    for m in matches:
        h = key(m["home_team"], m["home_code"])
        a = key(m["away_team"], m["away_code"])
        ch, ca = confs.get(h), confs.get(a)
        if not ch or not ca or ch == ca:
            continue
        w = 0.5 ** ((asof - date.fromisoformat(m["date"])).days
                    / ANCHOR_HALF_LIFE_DAYS)
        inter.append((h, a, int(m["home_score"]), w))
        inter.append((a, h, int(m["away_score"]), w))

    s = {c: 1.0 for c in set(confs.values())}
    for _ in range(5):
        num_a, den_a = defaultdict(float), defaultdict(float)
        num_d, den_d = defaultdict(float), defaultdict(float)
        for t, opp, g, w in inter:
            ct, co = confs[t], confs[opp]
            mu = att.get(t, 1) * dfc.get(opp, 1) * base * s[ct] / s[co]
            num_a[ct] += w * g
            den_a[ct] += w * mu
            num_d[co] += w * g
            den_d[co] += w * mu
        for c in s:
            r_att = (num_a[c] + ANCHOR_PRIOR) / (den_a[c] + ANCHOR_PRIOR)
            r_def = (num_d[c] + ANCHOR_PRIOR) / (den_d[c] + ANCHOR_PRIOR)
            s[c] *= math.sqrt(r_att / r_def)
        ref = s.get("UEFA", 1.0)
        s = {c: v / ref for c, v in s.items()}
    if verbose:
        print("  confederation anchors:",
              {c: round(v, 3) for c, v in sorted(s.items())})
    confs_of = confs.get
    att = {t: v * s.get(confs_of(t, ""), 1.0) for t, v in att.items()}
    dfc = {t: v / s.get(confs_of(t, ""), 1.0) for t, v in dfc.items()}
    return att, dfc


def poisson_pmf(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def outcome_probs(lh, la, kmax=10):
    """(P(home win), P(draw), P(away win)) under independent Poisson."""
    ph = [poisson_pmf(lh, k) for k in range(kmax + 1)]
    pa = [poisson_pmf(la, k) for k in range(kmax + 1)]
    w = d = l = 0.0
    for i, pi in enumerate(ph):
        for j, pj in enumerate(pa):
            p = pi * pj
            if i > j:
                w += p
            elif i == j:
                d += p
            else:
                l += p
    z = w + d + l
    return w / z, d / z, l / z
