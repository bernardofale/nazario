#!/usr/bin/env python3
"""Group-stage match result predictor — Poisson + Dixon-Coles.

For every group-stage fixture this script produces:
  • P(home win / draw / away win)
  • BTTS probability
  • Over-2.5 / over-1.5 goal probabilities
  • Top-8 most likely scorelines
  • A "confidence" score (max outcome probability)

Model: existing time-decayed Poisson ratings from team_model.py, refitted
with today's date so any live results already ingested by ingest_results.py
are included at full weight. Dixon-Coles correction (ρ = -0.10) adjusts the
joint probability of low-scoring results ({0-0, 1-0, 0-1, 1-1}) which plain
bivariate Poisson systematically mis-estimates.

Run:
    .venv/bin/python src/squad/predict_group_stage.py

Outputs:
    data/processed/group_stage_predictions.csv
    console table of unplayed fixtures ranked by matchday + confidence
"""
import csv
import json
import math
import sys
from datetime import date
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # src/squad/... -> repo root
sys.path.insert(0, str(ROOT / "src"))
import _bootstrap  # noqa: F401,E402  -- put src/<layer> dirs on sys.path

import team_model
from loaders import (load_fixtures, load_team_crosswalk,
                     load_players, load_player_crosswalk, load_club_stats)
from common import PROCESSED, write_csv
from squad_quality import compute_squad_indices, print_squad_rankings

# Blend weight: 0.0 = pure historical Poisson, 1.0 = pure squad quality
ALPHA = 0.35

# ------------------------------------------------------------------ constants
RHO = -0.10          # Dixon-Coles low-score correlation parameter
MAX_GOALS = 9        # grid ceiling per side (covers >99.9% of Poisson mass)
TOP_N_LINES = 8      # scorelines to keep in output


# --------------------------------------------------------- Dixon-Coles model

def _dc_tau(h, a, lam_h, lam_a, rho):
    """Multiplicative correction for the four low-scoring outcomes."""
    if   h == 0 and a == 0: return 1.0 - lam_h * lam_a * rho
    elif h == 0 and a == 1: return 1.0 + lam_h * rho
    elif h == 1 and a == 0: return 1.0 + lam_a * rho
    elif h == 1 and a == 1: return 1.0 - rho
    return 1.0

def _pmf(lam, k):
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def scoreline_grid(lam_h, lam_a, rho=RHO, cap=MAX_GOALS):
    """Return {(h, a): probability} over all (h, a) in [0, cap]^2, renormalised."""
    raw = {}
    for h, a in product(range(cap + 1), repeat=2):
        raw[(h, a)] = _pmf(lam_h, h) * _pmf(lam_a, a) * _dc_tau(h, a, lam_h, lam_a, rho)
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}

def outcome_probs(grid):
    """Return (p_home_win, p_draw, p_away_win)."""
    ph = sum(p for (h, a), p in grid.items() if h > a)
    pd = sum(p for (h, a), p in grid.items() if h == a)
    pa = sum(p for (h, a), p in grid.items() if h < a)
    return ph, pd, pa

def btts(grid):
    return sum(p for (h, a), p in grid.items() if h > 0 and a > 0)

def over_n5(grid, n):
    """P(total goals > n), e.g. n=2 → over-2.5."""
    return sum(p for (h, a), p in grid.items() if h + a > n)

def expected_goals(lam_h, lam_a):
    return round(lam_h, 2), round(lam_a, 2)

def top_lines(grid, n=TOP_N_LINES):
    return sorted(grid.items(), key=lambda x: -x[1])[:n]


# --------------------------------------------------------- played detection

def _load_played_ids():
    """
    Return a set of fixture IDs (as strings) for played matches.
    groupstage.json is a list of 3 matchday objects, each with a 'tournaments'
    list of 24 fixture dicts that carry homeScore / awayScore once played.
    Falls back to wc2026_results.csv if the JSON scores are all null (stale snapshot).
    """
    played = set()
    gs_path = ROOT / "data" / "raw" / "game" / "groupstage.json"
    if gs_path.exists():
        with open(gs_path) as f:
            gs = json.load(f)
        for md_obj in gs:
            for m in md_obj.get("tournaments", []):
                if m.get("homeScore") is not None:
                    played.add(str(m["id"]))

    # Also check wc2026_results.csv (written by ingest_results.py)
    results_path = ROOT / "data" / "processed" / "wc2026_results.csv"
    if results_path.exists():
        with open(results_path) as f:
            for row in csv.DictReader(f):
                fid = row.get("fixture_id") or row.get("id") or row.get("match_id")
                if fid:
                    played.add(str(fid))

    return played


def _fixture_score(f):
    """Return (home_goals, away_goals) if score is embedded in fixture dict, else None."""
    hv = f.get("homeScore")
    av = f.get("awayScore")
    if hv is not None:
        try:
            return int(hv), int(av)
        except (ValueError, TypeError):
            pass
    return None


# --------------------------------------------------------------- main logic

def _asof_after_last_result():
    """One day past the latest played WC2026 result (falls back to today)."""
    from datetime import timedelta
    path = PROCESSED / "wc2026_results.csv"
    last = None
    if path.exists():
        import csv
        with open(path) as fh:
            for row in csv.DictReader(fh):
                d = date.fromisoformat(row["date"])
                last = d if last is None or d > last else last
    return (last + timedelta(days=1)) if last else date.today()


def main():
    # Fit as-of the day AFTER the latest ingested result so every played
    # MD1/MD2 match enters the fit at full (zero-age) weight. Using
    # date.today() silently drops any result dated in the future relative
    # to the wall clock, which starves the model of its freshest evidence.
    asof = _asof_after_last_result()
    print(f"Fitting team model (asof {asof})…")
    ratings = team_model.fit(asof=asof)

    xwalk   = load_team_crosswalk()
    code_of  = {sid: t["fifa_code"] for sid, t in xwalk.items()}
    name_of  = {sid: t["name"]      for sid, t in xwalk.items()}
    group_of = {sid: t.get("group", "?") for sid, t in xwalk.items()}

    played_ids = _load_played_ids()
    print(f"  {len(played_ids)} fixtures detected as played in groupstage.json")

    # --- squad quality indices -----------------------------------------------
    print("computing squad quality indices…")
    sq_players = [p for p in load_players() if p["status"] == "playing"]
    sq_xwalk   = load_player_crosswalk()
    sq_club    = {c["player_id"]: c for c in load_club_stats()}
    sq_indices = compute_squad_indices(sq_players, sq_xwalk, sq_club)
    print_squad_rankings(sq_indices, xwalk)

    base_lam = ratings.base * ratings.tournament_factor

    rows = []
    for f in load_fixtures():
        h_sid = f["homeSquadId"]
        a_sid = f["awaySquadId"]
        md    = f["matchday"]

        hc = code_of.get(h_sid)
        ac = code_of.get(a_sid)
        if not hc or not ac:
            continue

        # Determine played status
        fid      = str(f.get("id", ""))
        score    = _fixture_score(f)
        is_played = bool(fid and fid in played_ids) or (score is not None)

        # Poisson lambdas (historical qualifier record)
        lam_h_poi, lam_a_poi = ratings.lambdas(
            hc, ac,
            home_has_adv=(hc in team_model.HOSTS),
            away_has_adv=(ac in team_model.HOSTS),
        )

        # Squad-quality lambdas (player stats from top-11 leagues)
        h_sq = sq_indices.get(h_sid, {"attack": 1.0, "defence": 1.0})
        a_sq = sq_indices.get(a_sid, {"attack": 1.0, "defence": 1.0})
        lam_h_sq = base_lam * h_sq["attack"] * a_sq["defence"]
        lam_a_sq = base_lam * a_sq["attack"] * h_sq["defence"]

        # Blend
        lam_h = (1 - ALPHA) * lam_h_poi + ALPHA * lam_h_sq
        lam_a = (1 - ALPHA) * lam_a_poi + ALPHA * lam_a_sq

        grid            = scoreline_grid(lam_h, lam_a)
        p_hw, p_d, p_aw = outcome_probs(grid)
        p_btts          = btts(grid)
        p_o25           = over_n5(grid, 2)
        p_o15           = over_n5(grid, 1)
        confidence      = max(p_hw, p_d, p_aw)
        favourite       = (
            "HOME" if p_hw == confidence else
            "DRAW" if p_d  == confidence else "AWAY"
        )
        top             = top_lines(grid, TOP_N_LINES)
        scorelines_str  = "  |  ".join(
            f"{h}-{a} ({p:.1%})" for (h, a), p in top
        )

        actual_score = ""
        if score:
            actual_score = f"{score[0]}-{score[1]}"

        rows.append({
            "md":           md,
            "group":        group_of.get(h_sid, "?"),
            "home":         name_of.get(h_sid, hc),
            "away":         name_of.get(a_sid, ac),
            "xg_home":      round(lam_h, 3),
            "xg_away":      round(lam_a, 3),
            "p_home_win":   round(p_hw, 4),
            "p_draw":       round(p_d,  4),
            "p_away_win":   round(p_aw, 4),
            "favourite":    favourite,
            "confidence":   round(confidence, 4),
            "btts":         round(p_btts, 4),
            "over_1_5":     round(p_o15, 4),
            "over_2_5":     round(p_o25, 4),
            "played":       is_played,
            "actual":       actual_score,
            "top_scorelines": scorelines_str,
        })

    rows.sort(key=lambda r: (r["md"], r["group"], r["home"]))

    # --- write CSV -----------------------------------------------------------
    fields = ["md", "group", "home", "away", "xg_home", "xg_away",
              "p_home_win", "p_draw", "p_away_win", "favourite", "confidence",
              "btts", "over_1_5", "over_2_5", "played", "actual", "top_scorelines"]
    out_path = PROCESSED / "group_stage_predictions.csv"
    write_csv(out_path, rows, fields)

    # --- console output ------------------------------------------------------
    unplayed = [r for r in rows if not r["played"]]
    played   = [r for r in rows if     r["played"]]

    _print_table("UNPLAYED FIXTURES — ranked by matchday",  unplayed, sort_by_conf=False)
    _print_table("MOST CONFIDENT REMAINING PREDICTIONS",
                 sorted(unplayed, key=lambda r: -r["confidence"])[:15],
                 sort_by_conf=True)

    if played:
        print(f"\n{'='*60}")
        print(f"PLAYED FIXTURES ({len(played)}) — model vs actual")
        print(f"{'='*60}")
        print(f"{'MD':>2}  {'Home':<22} {'Away':<22}  {'Model':^13}  {'Actual':>6}")
        print("-"*75)
        for r in played:
            model = f"H{r['p_home_win']:.0%}/D{r['p_draw']:.0%}/A{r['p_away_win']:.0%}"
            print(f"{r['md']:>2}  {r['home']:<22} {r['away']:<22}  {model:<13}  {r['actual']:>6}")

    print(f"\n-> {out_path}")


def _print_table(title, rows, sort_by_conf):
    print(f"\n{'='*110}")
    print(f"{title}  ({len(rows)} fixtures)")
    print(f"{'='*110}")
    hdr = (f"{'MD':>2}  {'Grp':>3}  {'Home':<22} {'Away':<22}  "
           f"{'xGH':>4} {'xGA':>4}  {'H%':>5} {'D%':>5} {'A%':>5}  "
           f"{'Fav':>4} {'Conf':>5}  {'BTTS':>5} {'O2.5':>5}")
    print(hdr)
    print("-"*110)
    for r in rows:
        print(
            f"{r['md']:>2}  {r['group']:>3}  {r['home']:<22} {r['away']:<22}  "
            f"{r['xg_home']:>4.2f} {r['xg_away']:>4.2f}  "
            f"{r['p_home_win']:>5.1%} {r['p_draw']:>5.1%} {r['p_away_win']:>5.1%}  "
            f"{r['favourite']:>4} {r['confidence']:>5.1%}  "
            f"{r['btts']:>5.1%} {r['over_2_5']:>5.1%}"
        )
    if rows:
        print(f"\nTop scorelines for first fixture: {rows[0]['top_scorelines']}")


if __name__ == "__main__":
    main()
