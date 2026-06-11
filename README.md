# World Cup Fantasy 2026 — ML pipeline

Predict expected fantasy points per player under the official game rules and
optimize squad, transfers and boosters. Full plan: `FANTASY_ML_PROPOSAL.md`;
scoring/rules reference: `rules.md`; in-tournament procedures (post-matchday
checklist, phase gates, booster rules, decision log): `PLAYBOOK.md`.

## Layout

```
data/
  raw/                       original inputs, never edited
    *_qualifier_results.json   FIFA dumps, 2026 qualifiers (6 confederations)
    euro_results_and_scorers.txt
    premierleague_player_stats.json, ligue1_player_stats.json  club season stats
    laliga_{standard,shooting,misc,goalkeeping}_stats.txt      FBref copy-paste
    footymetrics/{league}_{tab}.json   6 more leagues via src/fetch_footymetrics.py
    game/                      fantasy game files: groupstage.json (fixtures),
                               players.json (pool + prices + ownership), squads.json
  curated/                   WC history 1930–2022 (CSV database)
  processed/                 pipeline outputs (rebuilt by src/build_phase0.py)
    matches_international.csv  all matches, common schema (WC + qualifiers + Euro)
    goals_international.csv    all attributed goals (WC history + Euro 2024)
    club_stats.csv             tidy PL/Ligue 1 player-season stats
    team_crosswalk.csv         48 squads <-> FIFA/curated codes <-> Euro names
    player_crosswalk.csv       fantasy pool <-> club stats / WC ids / Euro scorers
    phase0_report.md           coverage report
src/
  build_phase0.py            Phase 0 entry point — runs everything below
  curate_euro2024.py         Euro txt -> validated json
  curate_qualifiers.py       FIFA dumps -> common schema
  curate_league_stats.py     league jsons -> tidy csv (calls curate_laliga_stats)
  curate_laliga_stats.py     FBref txt tables -> common club-stats rows
  fetch_footymetrics.py      pull league stats from the footymetrics API
  curate_footymetrics.py     merge its 3 tabs/league -> common club-stats rows
  phase1_squad.py            Phase 1: projections + squad ILP
  team_model.py              rating fit (decay, anchoring, tournament factor)
  ingest_results.py          played 2026 fixtures -> common schema (run per MD)
  simulator.py               48-team Monte Carlo (bracket: data/bracket_2026.json)
  phase2_simulate.py         Phase 2 driver: fit + simulate -> simulation_teams.csv
  backtest_team_model.py     calibration backtests (2018/2022/Euro 2024)
  curate_wc_history.py       curated csvs -> common schema (men's only)
  build_crosswalks.py        team + player ID matching
  loaders.py                 read API for downstream phases + rules constants
  common.py                  paths, schema columns, name normalization
```

## Usage

```
python3 src/build_phase0.py            # rebuild data/processed/ from data/raw/
python3 src/loaders.py                 # smoke-test the load API
.venv/bin/python src/phase1_squad.py   # Phase 1: ratings -> projections -> squad ILP
python3 src/phase2_simulate.py         # Phase 2: 10k-run tournament Monte Carlo
python3 src/backtest_team_model.py     # Phase 2 gate: calibration backtests
```

Phase 0 is stdlib-only. Phase 1 needs PuLP — one-time setup:
`python3 -m venv .venv && .venv/bin/pip install pulp`
(later phases add pandas + LightGBM).

Phase 1 outputs (in `data/processed/`): `team_ratings.csv` (confederation-
anchored attack/defence), `player_projections.csv` (E[points] per matchday),
`initial_squad.csv` (15 + XI + captain + bench order). Phases 2–5 (simulator,
player GBMs, transfer/booster optimizer, live loop): `FANTASY_ML_PROPOSAL.md` §5.
