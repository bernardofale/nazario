# World Cup Fantasy 2026 — ML pipeline

Predict expected fantasy points per player under the official game rules and
optimize squad, transfers and boosters. Full plan: `FANTASY_ML_PROPOSAL.md`;
scoring/rules reference: `rules.md`; in-tournament procedures (post-matchday
checklist, phase gates, booster rules, decision log): `PLAYBOOK.md`.

## Layout

```
data/
  raw/                       original inputs, never edited — LOCAL-ONLY (git-ignored);
                             regenerate via the fetch scripts (see data/raw/README.md)
    *_qualifier_results.json   FIFA dumps, 2026 qualifiers (6 confederations)
    euro_results_and_scorers.txt
    premierleague_player_stats.json, ligue1_player_stats.json  club season stats
    laliga_{standard,shooting,misc,goalkeeping}_stats.txt      public-stats copy-paste
    club_stats/{league}_{tab}.json   6 more leagues via src/ingest/fetch_club_stats.py
    game/                      fantasy game files: groupstage.json (fixtures),
                               players.json (pool + prices + ownership), squads.json
  curated/                   WC history 1930–2022 (CSV database)
  processed/                 pipeline outputs (rebuilt by src/ingest/build_phase0.py)
    matches_international.csv  all matches, common schema (WC + qualifiers + Euro)
    goals_international.csv    all attributed goals (WC history + Euro 2024)
    club_stats.csv             tidy PL/Ligue 1 player-season stats
    team_crosswalk.csv         48 squads <-> FIFA/curated codes <-> Euro names
    player_crosswalk.csv       fantasy pool <-> club stats / WC ids / Euro scorers
    phase0_report.md           coverage report
src/                         grouped by pipeline layer; modules import each
                             other by bare name (_bootstrap.py puts each
                             layer dir on sys.path for the entry scripts)
  _bootstrap.py              sys.path setup, imported by every runnable script
  core/                      shared foundation, imported everywhere
    common.py                paths, schema columns, name normalization
    loaders.py               read API for downstream phases + rules constants
    local_config.py          local-only source endpoints (git-ignored)
  ingest/                    Phase 0 — raw sources -> data/processed/ common schema
    build_phase0.py          entry point — runs everything below
    curate_qualifiers.py     FIFA dumps -> common schema
    curate_euro2024.py       Euro txt -> validated json
    curate_wc_history.py     curated csvs -> common schema (men's only)
    curate_league_stats.py   league jsons -> tidy csv (calls curate_laliga_stats)
    curate_laliga_stats.py   La Liga txt tables -> common club-stats rows
    curate_club_stats.py     merge provider's 3 tabs/league -> club-stats rows
    fetch_club_stats.py      pull league stats from the club-stats provider API
    ingest_results.py        played 2026 fixtures -> common schema (run per MD)
    build_crosswalks.py      team + player ID matching
  model/                     Phase 2 — team strength + tournament simulation
    team_model.py            rating fit (decay, anchoring, tournament factor)
    simulator.py             48-team Monte Carlo (bracket: data/bracket_2026.json)
    phase2_simulate.py       driver: fit + simulate -> simulation_teams.csv
    backtest_team_model.py   calibration backtests (2018/2022/Euro 2024)
  squad/                     Phases 1/3 — player projections + squad optimisation
    phase1_squad.py          Phase 1: projections + squad ILP
    squad_quality.py         per-player club stats -> team attack/defence indices
    predict_group_stage.py   group-stage match predictor (Poisson + Dixon-Coles)
    build_r32_squad.py       knockout squad ILP for R32 (unlimited-transfer window)
    build_sf_squad.py        knockout squad ILP for the semis
```

## Usage

```
python3 src/ingest/build_phase0.py           # rebuild data/processed/ from data/raw/
python3 src/core/loaders.py                  # smoke-test the load API
.venv/bin/python src/squad/phase1_squad.py   # Phase 1: ratings -> projections -> squad ILP
python3 src/model/phase2_simulate.py         # Phase 2: 10k-run tournament Monte Carlo
python3 src/model/backtest_team_model.py     # Phase 2 gate: calibration backtests
```

Phase 0 is stdlib-only. Phase 1 needs PuLP — one-time setup:
`python3 -m venv .venv && .venv/bin/pip install pulp`
(later phases add pandas + LightGBM).

Phase 1 outputs (in `data/processed/`): `team_ratings.csv` (confederation-
anchored attack/defence), `player_projections.csv` (E[points] per matchday),
`initial_squad.csv` (15 + XI + captain + bench order). Phases 2–5 (simulator,
player GBMs, transfer/booster optimizer, live loop): `FANTASY_ML_PROPOSAL.md` §5.

## Data & disclaimer

Third-party datasets under `data/` keep their own terms — see `DATA_SOURCES.md`
for attribution (incl. the CC-BY-4.0 Fjelstul World Cup Database). No license is
granted on the original code here; all rights reserved. Unofficial project, not
affiliated with or endorsed by FIFA or the FIFA World Cup Fantasy game; for
non-commercial, educational use only.
