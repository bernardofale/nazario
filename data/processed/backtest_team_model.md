# Team-model calibration backtest (Phase 2 gate)

### WC 2018 (48 group matches, fit on data before 2018-06-14)

| metric | model | uniform | frequency |
|---|---|---|---|
| log-loss | **1.0605** | 1.0986 | 1.0391 |
| Brier | **0.6277** | 0.6667 | 0.6293 |

- goals/match: predicted 2.54, actual 2.54
- clean sheets: predicted 30.6%, actual 28.1%

| predicted prob | n | avg predicted | realized |
|---|---|---|---|
| 0–20% | 23 | 13.8% | 26.1% |
| 20–40% | 85 | 28.8% | 24.7% |
| 40–60% | 20 | 47.6% | 65.0% |
| 60–80% | 16 | 67.9% | 50.0% |

**FAIL** — model does not beat both baselines on log-loss.

### WC 2022 (48 group matches, fit on data before 2022-11-20)

| metric | model | uniform | frequency |
|---|---|---|---|
| log-loss | **1.1862** | 1.0986 | 1.0605 |
| Brier | **0.7199** | 0.6667 | 0.6432 |

- goals/match: predicted 2.58, actual 2.50
- clean sheets: predicted 29.8%, actual 35.4%

| predicted prob | n | avg predicted | realized |
|---|---|---|---|
| 0–20% | 29 | 16.3% | 41.4% |
| 20–40% | 72 | 27.3% | 23.6% |
| 40–60% | 27 | 49.4% | 55.6% |
| 60–80% | 16 | 64.4% | 25.0% |

**FAIL** — model does not beat both baselines on log-loss.

### Euro 2024 (36 group matches, fit on data before 2024-06-14)

| metric | model | uniform | frequency |
|---|---|---|---|
| log-loss | **1.0730** | 1.0986 | 1.0893 |
| Brier | **0.6495** | 0.6667 | 0.6605 |

- goals/match: predicted 2.66, actual 2.25
- clean sheets: predicted 27.5%, actual 27.8%

| predicted prob | n | avg predicted | realized |
|---|---|---|---|
| 0–20% | 8 | 17.8% | 12.5% |
| 20–40% | 83 | 31.1% | 32.5% |
| 40–60% | 13 | 47.8% | 46.2% |
| 60–80% | 4 | 63.8% | 50.0% |

**PASS** — model beats both baselines on log-loss.
