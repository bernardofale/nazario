# data/raw/ — local-only inputs (git-ignored)

The raw source snapshots are **not tracked** in this repository. Only this
placeholder is committed; everything else under `data/raw/` is regenerated
locally from its origin and never redistributed here.

The analysis-ready outputs are already committed under `data/processed/`
(rebuilt by `src/build_phase0.py`), and the historical database under
`data/curated/` (the CC-BY Fjelstul World Cup Database — see `DATA_SOURCES.md`),
so the pipeline outputs are reproducible without shipping third-party raw data.

## Regenerating the raw inputs

1. Set your source endpoints in `src/local_config.py` (git-ignored) or the
   `CLUB_STATS_API_BASE`, `CLUB_STATS_REFERER`, `RESULTS_FEED_URL` env vars.
2. Club-league player stats: `python3 src/fetch_club_stats.py`
   → writes `data/raw/club_stats/{league}_{tab}.json`.
3. Live 2026 results: curl your results feed into
   `data/raw/game/wc_games_api.json`.
4. Other inputs (qualifier dumps, La Liga stat tables, Euro results, fantasy
   game exports) are provided to their curators under `data/raw/` in the
   shapes documented in `README.md`.
