# Data & attribution

Datasets under `data/` are third-party and keep their own terms. No license is
granted on this project's own code or analysis.

## Historical World Cup database (`data/curated/`)

The 27 `*_curated.csv` tables (tournaments, matches, goals, squads, bookings,
substitutions, penalty kicks, managers, referees, awards, …) are the
**Fjelstul World Cup Database**.

- Author: Joshua C. Fjelstul, Ph.D.
- Citation: Fjelstul, J. C. (2022). *The Fjelstul World Cup Database.*
- License: **CC-BY-4.0** — free to share and adapt **with attribution**.

This attribution is a condition of the license and is required.

## Other inputs (`data/raw/`)

Public football facts (match results, dates, scorers) and player statistics
compiled from public web sources and official game exports, retained so the
pipeline is reproducible. These are facts used for non-commercial analysis;
the fetch scripts under `src/` regenerate them from their origins.

## Disclaimer

Unofficial, personal analytics project. Not affiliated with, endorsed by, or
connected to FIFA, the FIFA World Cup Fantasy game, or any data provider.
"FIFA World Cup" is a trademark of FIFA. All data is used for non-commercial,
educational analysis.
