#!/usr/bin/env python3
"""Calibration backtests for the team model (Phase 2 acceptance gate).

For each held-out tournament, the model is fitted strictly on matches
before its start date, then scored on that tournament's group-stage
matches (group games only — knockout 90' draws are recorded inconsistently
across sources):

  - log-loss & Brier of the win/draw/loss probabilities, vs two baselines
    (uniform 1/3 and the historical WDL frequency)
  - calibration table: predicted-probability buckets vs realized frequency
  - goal-mean check: average predicted lambda vs goals actually scored
  - clean-sheet check: predicted P(CS) vs realized CS rate

Run:  python3 src/model/backtest_team_model.py
Writes data/processed/backtest_team_model.md
"""
import math
from datetime import date

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

import team_model
from common import PROCESSED
from loaders import load_matches

TOURNAMENTS = [
    ("WC 2018", date(2018, 6, 14), "wc_history", "2018", "RUS"),
    ("WC 2022", date(2022, 11, 20), "wc_history", "2022", "QAT"),
    ("Euro 2024", date(2024, 6, 14), "euro2024", "2024", "GER"),
]


def evaluate(name, start, source, season, host):
    matches = load_matches()
    ratings = team_model.fit(asof=start, matches=matches, verbose=False)
    test = [m for m in matches
            if m["source"] == source and str(m["season"]) == season
            and m["stage"] == "group"]

    rows, lam_sum, goals_sum = [], 0.0, 0
    cs_pred, cs_real = 0.0, 0
    for m in test:
        h = ratings.key(m["home_team"], m["home_code"])
        a = ratings.key(m["away_team"], m["away_code"])
        lh, la = ratings.lambdas(h, a, home_has_adv=h == host,
                                 away_has_adv=a == host)
        pw, pd, pl = team_model.outcome_probs(lh, la)
        result = ("w" if m["home_score"] > m["away_score"]
                  else "d" if m["home_score"] == m["away_score"] else "l")
        rows.append((pw, pd, pl, result))
        lam_sum += lh + la
        goals_sum += m["home_score"] + m["away_score"]
        cs_pred += math.exp(-la) + math.exp(-lh)
        cs_real += (m["away_score"] == 0) + (m["home_score"] == 0)

    n = len(rows)
    freq = {"w": 0.0, "d": 0.0, "l": 0.0}
    for *_, r in rows:
        freq[r] += 1 / n

    def scores(prob_fn):
        ll = br = 0.0
        for pw, pd, pl, r in rows:
            p = dict(zip("wdl", prob_fn(pw, pd, pl)))
            ll -= math.log(max(p[r], 1e-9))
            br += sum((p[k] - (k == r)) ** 2 for k in "wdl")
        return ll / n, br / n

    model_ll, model_br = scores(lambda w, d, l: (w, d, l))
    uni_ll, uni_br = scores(lambda w, d, l: (1 / 3, 1 / 3, 1 / 3))
    frq_ll, frq_br = scores(lambda w, d, l: (freq["w"], freq["d"], freq["l"]))

    # calibration: bucket every (outcome, probability) pair
    buckets = {}
    for pw, pd, pl, r in rows:
        for k, p in zip("wdl", (pw, pd, pl)):
            b = min(int(p * 5), 4)  # 0-20-40-60-80-100%
            hit = (k == r)
            s = buckets.setdefault(b, [0, 0.0, 0])
            s[0] += 1
            s[1] += p
            s[2] += hit

    lines = [
        f"### {name} ({n} group matches, fit on data before {start})",
        "",
        f"| metric | model | uniform | frequency |",
        f"|---|---|---|---|",
        f"| log-loss | **{model_ll:.4f}** | {uni_ll:.4f} | {frq_ll:.4f} |",
        f"| Brier | **{model_br:.4f}** | {uni_br:.4f} | {frq_br:.4f} |",
        "",
        f"- goals/match: predicted {lam_sum / n:.2f}, actual {goals_sum / n:.2f}",
        f"- clean sheets: predicted {cs_pred / (2 * n):.1%}, actual {cs_real / (2 * n):.1%}",
        "",
        "| predicted prob | n | avg predicted | realized |",
        "|---|---|---|---|",
    ]
    for b in sorted(buckets):
        cnt, psum, hits = buckets[b]
        lines.append(f"| {b * 20}–{b * 20 + 20}% | {cnt} | "
                     f"{psum / cnt:.1%} | {hits / cnt:.1%} |")
    lines.append("")
    passed = model_ll < min(uni_ll, frq_ll)
    lines.append(f"**{'PASS' if passed else 'FAIL'}** — model "
                 f"{'beats' if passed else 'does not beat'} both baselines "
                 "on log-loss.")
    return lines, passed


def main():
    report = ["# Team-model calibration backtest (Phase 2 gate)", ""]
    all_pass = True
    for spec in TOURNAMENTS:
        print(f"backtesting {spec[0]}…")
        lines, ok = evaluate(*spec)
        report += lines + [""]
        all_pass &= ok
    out = PROCESSED / "backtest_team_model.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"-> {out.name}  ({'ALL PASS' if all_pass else 'FAILURES — see report'})")


if __name__ == "__main__":
    main()
