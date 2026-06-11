# Machine Learning Proposal: FIFA World Cup Fantasy 2026™ Squad Selection

**Goal:** Use the curated World Cup database plus recent international results to predict each player's expected fantasy points under the official game rules (`rules.md`), then solve for the optimal 15-player squad, starting XI, captaincy, transfer plan and booster timing.

**Short answer: yes, this is possible.** The historical database covers every men's World Cup from 1930–2022 (964 matches, ~20,600 player-match appearances, 2,720 goals) with match results, lineups, goals, cards, substitutions, penalties and squads. On top of that we now have **901 qualifier results (Sep 2023 – Mar 2026) across all six confederations**, the **full Euro 2024 with scorers**, and the **actual fantasy game files** (fixtures, player pool, prices, ownership). That supports modelling *current team strength*, *individual player output*, and the game's own economics, projected onto the 2026 fixtures.

---

## 1. Data inventory

| Source | File(s) | Contents | Role |
|---|---|---|---|
| WC history 1930–2022 | `data/curated/*.csv` | results, lineups, goals, cards, subs, penalties, squads | long-run player rates, backtesting, priors |
| 2026 qualifiers (all 6 confederations) | `data/raw/*_qualifier_results.json` | 901 matches, scorelines, possession — **no scorers** | recent team strength (the core of model A) |
| Euro 2024 | `data/processed/euro2024_results.json` (curated from the text dump) | 51 matches, 117 goals with scorer/minute/penalty/own-goal flags, 4 full lineups | recent team strength **and** recent player scoring form for UEFA players |
| Club season stats (11 leagues) | `data/raw/{premierleague,ligue1}_player_stats.json`, `data/raw/laliga_*_stats.txt`, `data/raw/footymetrics/*.json` (fetched by `src/fetch_footymetrics.py`) → `data/processed/club_stats.csv` | 5,520 player-seasons: minutes, goals, assists, shots on/off target, key passes, big chances created, tackles, interceptions, cards, ratings; xG/xA (PL/Ligue 1 JSONs); penalty detail + clean sheets (La Liga FBref); footymetrics adds **Bundesliga, Serie A, Liga Portugal, Saudi Pro League, Süper Lig, MLS, Championship, Eredivisie** with nationality flags | player-level estimates for the proxy components; cold-start signal for the **623** pool players matched |
| Game: fixtures | `data/raw/game/groupstage.json` | 72 group matches (Jun 11–28), venues, and `GoalScorersAssists` fields that populate live | simulator input now; **live results + assists feed in-tournament** |
| Game: player pool | `data/raw/game/players.json` | 1,484 players: price, position, status, **`percentSelected` (ownership) per round** | optimizer input; ownership makes the scouting bonus playable |
| Game: teams | `data/raw/game/squads.json` | 48 teams with group assignment | fixture/bracket mapping |
| Rules | `rules.md` | scoring matrix, budget, transfers, boosters | objective function and constraints |

Three notes on the new data:

- **The qualifiers fix the recency problem.** The original plan leaned on WC 2018/2022 with tournament-level time decay. With 901 matches from the last ~30 months, the team-strength model now estimates *current* attack/defence ratings. The catch: qualifiers are almost entirely within-confederation, so confederation scales can drift apart — they get anchored on inter-confederation results (World Cups 2014–2022) via a hierarchical confederation-strength term.
- **Euro 2024 is the only recent source with scorers**, so European players get a recent-form goal rate while others rely on WC history + priors. The model must treat this as a *feature with partial coverage* (a "has-recent-form" indicator), not silently advantage UEFA players. The same curation pattern (common schema, validated scorer counts) is ready to absorb Copa América 2024 / AFCON 2025 text dumps if provided — the single highest-value data addition now.
- **The club stats upgrade the proxy components to player-level — for 42% of the pool.** Eleven WC-feeder leagues are in: **623 of 1,484 pool players match** (conservative name matching with nationality guards where the source provides them), concentrated among premium-priced players where accuracy matters most. For them, tackles, chances created and shots on target come from real per-90 rates; xG/xA (PL/Ligue 1) are better goal/assist predictors than raw counts; the La Liga FBref dumps carry penalty goals/attempts, penalties won/conceded, penalty saves and clean sheets. The eight footymetrics leagues (fetched live from their paginated API, three stat tabs merged per player) brought the big previously-dark contingents into view: Bundesliga, Serie A, Liga Portugal, Saudi, Süper Lig and MLS — Kane, Ronaldo, Messi, Musiala and the entire Korean/Turkish/North-American home-league cohorts. Same partial-coverage discipline as Euro 2024: a "has-club-stats" indicator, with priors carrying everyone else.

**Common match schema:** every results source is normalized to one shape — `date, stage, group, home/away team, 90'/120' score, HT score, extra_time, penalty_shootout, shootout score, venue, goals[{team, player, minute, penalty, own_goal}]` — produced for Euro 2024 by `curate_euro2024.py` (validates every match's scorer count against its scoreline; 51/51 pass and the six 3-goal Golden Boot winners reproduce exactly). The qualifier FIFA dumps and `curated/` CSVs map into the same schema in Phase 0.

---

## 2. The scoring system drives the model design

The official scoring (`rules.md`) is position-specific. For each scoring action, here is where the model gets its signal:

| Scoring action | Points | Source | Coverage |
|---|---|---|---|
| Appearance / 60+ minutes | +1 / +1 | `player_appearances` (starter flag) + `substitutions` (minutes on/off) | ✅ direct |
| Goal scored (GK +9 / DF +7 / MF +6 / FW +5) | varies | `goals` + Euro 2024 scorers + position from `squads`/`players.json` | ✅ direct |
| Assist | +3 | not in history; **live from game feed (`GoalScorersAssists`) once tournament starts** | ⚠️ prior pre-MD1 → ✅ in-tournament |
| Clean sheet, 60+ min (GK/DF +5, MF +1) | +5 / +1 | team level from `matches` / qualifiers / Euro | ✅ direct |
| Goals conceded (–1 each after the first) | –1 | scorelines | ✅ direct |
| Yellow / Red card | –1 / –2 | `bookings` | ✅ direct |
| Own goal | –2 | `goals` (own-goal flag, also in Euro schema) | ✅ direct |
| Winning / conceding a penalty | +2 / –1 | penalty-goal flags give penalties scored; winner/conceder not identified | ⚠️ partial |
| GK: every 3 saves +1, penalty save +3 | +1 / +3 | club `saves` per-90 (PL/L1 players); opponent-strength proxy otherwise | ⚠️ partial |
| MF: every 3 tackles +1, every 2 chances created +1 | +1 / +1 | club `tackles`, `key_passes`, `big_chances_created` per-90 (PL/L1); position priors otherwise | ⚠️ partial |
| FW: every 2 shots on target +1 | +1 | club `shots_on_target` per-90 (PL/L1); goal-rate proxy otherwise | ⚠️ partial |
| Direct free-kick goal bonus | +1 | not flagged | ⚠️ proxy (set-piece taker list) |
| Scouting bonus (>4 pts and <5% ownership) | +2 | **`percentSelected` in `players.json`, per round** | ✅ observable |

**Three consequences:**

1. **The big point drivers are well covered.** Appearance, goals, clean sheets, conceded goals and cards — the bulk of any player's score — come straight from the data. Note the position-weighted goal values (a defender's goal is worth 7, a forward's 5): combined with the +5 clean sheet, attacking defenders on strong teams are the value sweet spot, and the model will find them.
2. **The secondary stats (saves, tackles, chances created, shots on target) are now player-level for PL/Ligue 1 players and proxied for the rest.** For unmatched players: saves scale with opponent attack strength (weak-team GKs earn save points — captured via the team-strength ratings); shots on target scale with a forward's goal rate; tackles and chances created get position×role priors, with the club-stats subsample used to *calibrate* those priors per position. Adding more league files tightens this further.
3. **The scouting bonus is now a real strategy, not a tiebreaker.** Ownership is visible per round, so the optimizer can compute E[bonus] = 2 × P(score >4) for any player under 5% owned and weigh genuinely cheap differentials properly.

*Assumption: appearance points are cumulative (+1 for playing, +1 more at 60+ minutes, FPL-style). Worth confirming in-game.*

---

## 3. Architecture: three models, one optimizer

```
 WC history +    ┌─────────────────────────┐
 901 qualifiers +│ A. Team-strength model  │──► attack/defence rating per country,
 Euro 2024 ─────►│ (Dixon-Coles Poisson,   │    anchored across confederations
                 │  time-decay, hierarchy) │
                 └───────────┬─────────────┘
                             ▼
 groupstage.json ┌─────────────────────────┐    per-team, per-round:
 + bracket map ─►│ B. Tournament simulator │──► expected goals for/against,
                 │   (Monte Carlo, 10k×)   │    clean-sheet prob., P(reach round R)
                 └───────────┬─────────────┘
                             ▼
 players.json    ┌─────────────────────────┐    per-player, per-round:
 + WC/Euro       │ C. Player points model  │──► E[fantasy points] under the
 player rates ──►│   (gradient boosting)   │    official scoring matrix
                 └───────────┬─────────────┘
                             ▼
 rules.md        ┌─────────────────────────┐    15-man squad, XI + bench order,
 constraints ───►│ D. Game-state optimizer │──► captain/VC, round-by-round
 + ownership ───►│   (integer programming) │    transfer plan, booster timing
                 └─────────────────────────┘
```

### A. Team-strength model — *past country games*

Dixon-Coles–style Poisson regression on historical scorelines:

- `goals(team i vs j) ~ Poisson(attack_i × defence_j × stage_factor)`
- **Training set:** WC 1930–2022 (down-weighted) + all 901 qualifiers + Euro 2024, with **time-decay weighting by match date** (half-life ≈ 18 months) so 2024–2026 form dominates.
- **Confederation anchoring:** qualifiers never cross confederations, so each confederation gets a strength offset identified from inter-confederation World Cup matches (2014–2022). Without this, e.g. OFC ratings would float freely against UEFA's.
- Extra features: host advantage (USA/Mexico/Canada — `host_countries` shows hosts systematically over-perform), knockout vs. group stage, match importance (qualifier dead rubbers down-weighted).
- First-time qualifiers: initialize from confederation average — but with ~20 qualifying matches each, every 2026 team now has real recent data; cold-start applies to players, not teams.

### B. Tournament simulator — *future fixtures*

Monte Carlo over the real 2026 structure: `groupstage.json` (72 matches, June 11–28) → official group-to-Round-of-32 bracket mapping → knockouts. 10,000 simulations give, per team and per round:

- P(team is still alive in round R) — directly prices the **rising country caps** (3 → 3 → 4 → 5 → 6 → 8) and tells the optimizer when loading up on a favourite becomes legal *and* likely to pay.
- Per-fixture expected goals for/against → clean-sheet and goals-conceded probabilities feeding GK/DF scoring.
- Expected matches remaining per team — the core of transfer planning.

### C. Player points model — *individual player stats*

For each player × potential fixture, predict each scoring component, then map through the official matrix:

| Component | Model | Key features |
|---|---|---|
| **E[minutes] / P(60+)** | Starter / sub / unused classifier | starts share at last WC and Euro 2024 (where lineups exist), age, position, manager continuity (`manager_appointments`); **updated with actual 2026 lineups after every matchday** |
| **E[goals]** (×9/7/6/5 by position) | Poisson GBM (LightGBM): per-90 rate × E[minutes] × team's expected-goals share | career WC goals per 90, **Euro 2024 goals (UEFA players)**, **club xG/npxG per-90 (PL/L1 players)**, position, penalty-taker flag, age curve — each partial-coverage source with its own indicator |
| **E[assists]** (×3) | Pre-MD1: club xA/assists per-90 where available, else position-based share of team's non-self goals; **from MD1 on: refit on live `GoalScorersAssists` feed** | position, attacking role, club xA |
| **E[clean sheet]** (+5 GK/DF, +1 MF) | From simulator B × P(plays 60+) | — |
| **E[conceded] penalty** | From simulator B goal distribution | — |
| **E[cards]** (–1/–2) | Poisson on `bookings` per-90 rate | position, historical rate |
| **E[saves]** (+1 per 3) | Club saves per-90 (PL/L1 GKs) scaled by opponent attack rating; save-rate prior otherwise | team defence rating (weak team ⇒ busy GK), club save volume |
| **E[shots on target]** (FW, +1 per 2) | Club shots-on-target per-90 where available; goal-rate / conversion prior otherwise | per-90 goal rate, club SoT |
| **E[tackles / chances created]** (MF) | Club tackles / key passes / big chances per-90 where available; position×role priors otherwise (calibrated on the club subsample) | defensive vs. attacking MF |

**Why gradient boosting:** ~20k player-match rows of tabular, mixed-type data with non-linear effects (age curves, position interactions). GBMs are the strongest maintainable choice; deep learning would overfit at this scale.

**Cold start (≈ a third of every squad are WC debutants):** hierarchical shrinkage — a debutant's rates start at the prior for his position/age/team-strength cell and update with any data that exists. Euro 2024 covers many UEFA debutants, club stats cover the PL/Ligue 1 contingent, and the game's own `price` is informative for everyone — it encodes the operator's expectation and serves as a strong prior feature.

**Name matching:** five player-name universes (curated CSVs, Euro text surnames, club stats, `players.json`, FIFA qualifier dumps) with diacritic inconsistencies (Gündogan/Gündoğan, Arnautovic/Arnautović). **Built in Phase 0** (`data/processed/player_crosswalk.csv`): normalized-name matching with country/position guards, conservative — ambiguous names stay unlinked rather than guessed. Current coverage: 269 club-stats links, 354 WC-history ids, 45 Euro 2024 scorers; 545 of 1,484 players have at least one external link.

### D. Game-state optimizer — *the rules engine*

This is where `rules.md` bites. Squad selection is an **integer linear program** (PuLP / OR-Tools, milliseconds to solve), but the game rules make it richer than a one-shot knapsack:

**Initial squad (lock: 11 June 2026, first match):**
- maximize E[points of starting XI] + λ·E[bench insurance value] + E[scouting bonuses]
- subject to: Σ price ≤ **$100m**; exactly **2 GK / 5 DF / 5 MF / 3 FW**; **≤ 3 per country**; XI must fit one of the 7 legal formations (4-4-2, 4-3-3, 4-5-1, 3-4-3, 3-5-2, 5-4-1, 5-3-2).
- **Bench players score nothing**, so the ILP concentrates budget in the XI — but auto-substitution (bench replaces a DNP starter, in priority order) means bench value = E[points] × P(a starter DNPs). The optimizer prices bench slots as *cheap, minutes-secure* players, and sets bench priority 1–3 accordingly.
- **Captain scores double**: the ILP includes a captain variable doubling one player's E[points]. Vice-captain = second choice; note the auto-assign-by-price on first save must be manually overridden if the model prefers a cheaper captain.

**Transfer plan (rolling-horizon re-optimization):** free transfers are scarce and stage-dependent — 2 before MD2, 2 before MD3 (1 may carry over), unlimited at R32, then 4 / 4 / 5 / 6. Extra transfers cost **–3 points each**. After every matchday: append actual results, re-fit ratings, re-simulate, then solve a transfer ILP where each change beyond the free allocation carries a –3 penalty and the country cap for the *current* stage applies. The unlimited-transfer window at the Round of 32 (plus the **+$5m budget bump** to $105m) is effectively a second wildcard — the plan treats the group stage and the knockout stage as two separately optimized squads.

**Booster timing (decision rules from simulation, not gut feel):**

| Booster | Model-driven usage |
|---|---|
| **Wildcard** | Banned for MD1 and R32. Best expected use: MD3, to pivot the squad toward teams the simulator now rates for deep runs — R32's unlimited transfers arrive one round later anyway, so wildcard value peaks just before the last group round if your squad has dead weight. |
| **Maximum Captain** | Doubles your XI's *best* scorer — its EV is always ≥ a named captain's. Save it for a round where captain choice is most uncertain (flat E[points] across candidates); burn a named captain when one player has a standout easy fixture. The simulator quantifies this gap per round. |
| **12th Man** | One extra scoring player, no budget/country limits. Optimal pick = highest E[points] player *not* in squad that round — typically a premium player from a country you're already capped on. |
| **Qualification Booster** | +2 per starting-XI player who advances (R32 onward). Value = 2 × Σ P(advance) over your XI — maximized in the round where the simulator says most of your players survive, usually R32 with an XI loaded from group winners. |
| **Mystery Booster** | Unknown until R32 — leave a slot in the plan, decide when revealed. |

**Scouting bonus** (+2 if a player scores >4 and is <5% owned): with `percentSelected` visible per round, the optimizer adds 2 × P(points > 4) to any candidate under the 5% threshold (with a safety margin, since ownership moves until lock). This systematically surfaces cheap differentials that pure E[points] ranking misses.

---

## 4. Validation: backtesting before trusting

Train on data up to 2014 → score the 2018 tournament with the *2026 scoring matrix* → measure. Repeat training up to 2018 → score 2022. Metrics:

- Spearman rank correlation between predicted and actual fantasy points per player.
- Points of the ILP squad picked *ex ante* (including simulated MD2/MD3 transfers under the –3 rule) vs. perfect-hindsight squad and naive baselines (most expensive squad; last WC's top scorers; highest-ownership squad).
- Simulator calibration: teams given 20% quarter-final probability should reach it ~20% of the time. Euro 2024 doubles as an out-of-sample calibration check for the team model: fit on data through May 2024, simulate the Euro, compare to what happened.

Caveat: saves/tackles components can't be backtested from this data alone — they're validated indirectly or via enrichment if added. Assists become measurable in-tournament from the live feed, so the assist proxy gets checked (and refit) from MD1 onwards.

---

## 5. Implementation plan & phasing

Stack: **Python + pandas + LightGBM + PuLP**, in this repo.

The phasing is driven by one hard fact: **the squad locks at the first match on 11 June 2026 — today.** Everything else is recoverable later (2 free transfers before MD2, 2 before MD3, unlimited at R32), but missing the lock is not. So the plan ships a defensible squad first and upgrades the machinery between matchdays, in time for each decision window.

| Phase | Deadline (game window) | Deliverable | Effort |
|---|---|---|---|
| 0. Data curation & common schema | today | all sources in one schema + ID crosswalk | ✅ **done** — `python3 src/build_phase0.py` |
| 1. Lock-day squad | **today, before first kickoff** | initial 15 + XI + captain + bench order | ✅ **done** — `.venv/bin/python src/phase1_squad.py` |
| 2. Team model + simulator | before MD2 (~Jun 18) | calibrated ratings + 10k-run simulator | ✅ **done** — `python3 src/phase2_simulate.py` |
| 3. Player component models | before MD3 (~Jun 24) | full E[points] per player per round + backtests | 2–3 days |
| 4. Transfer & booster optimizer | before R32 (~Jun 29) | rolling-horizon transfer ILP + booster advisor | 1–2 days |
| 5. In-tournament live loop | R32 → final, ongoing | results-in → recommendations-out, same day | minutes per round |

### Phase 0 — Data curation & common schema ✅ *(done)*
Everything rebuilds with `python3 src/build_phase0.py`; report in `data/processed/phase0_report.md`. The repo is reorganized as `data/raw` (originals) / `data/curated` (WC history) / `data/processed` (outputs) / `src` (pipeline) — see `README.md`.
- ✅ `euro2024_results.json` — 51 matches, 117 goals, every match validated scorers-vs-scoreline; the six 3-goal Golden Boot winners reproduce exactly.
- ✅ `qualifiers_2026.csv` — 892 played matches flattened from the six FIFA dumps (9 abandoned/awarded fixtures dropped via `MatchStatus`).
- ✅ `wc_history_matches.csv` / `wc_history_goals.csv` — 964 men's matches, 2,720 goals (women's editions filtered out).
- ✅ `matches_international.csv` — all 1,907 matches in one common-schema table; `goals_international.csv` — 2,837 attributed goals.
- ✅ `club_stats.csv` — 5,520 player-seasons across 11 leagues, tidy totals + per-90s (per-90s recomputed from minutes; the JSON sources' own P90 columns are inconsistent). The La Liga FBref copy-paste (4 txt tables) is parsed with repair logic for its one nameless and one truncated row; multi-club seasons are summed. The footymetrics leagues are fetched by `src/fetch_footymetrics.py` (paginated API, offensive/defensive/passing tabs merged on player slug; totals reconstructed from per-appearance averages; PL/Ligue 1/La Liga skipped there in favour of the richer sources).
- ✅ `team_crosswalk.csv` — 48/48 squads with FIFA codes (42 with WC history, 12 Euro 2024 participants); `player_crosswalk.csv` — spot-checked clean on hard cases (Saliba brothers, three Williamses, Mbappé/Kane Euro goal counts).
- ✅ `src/loaders.py` — single load API for all downstream phases, including `rules.md` constants for the optimizer.

### Phase 1 — Lock-day squad ✅ *(done — `src/phase1_squad.py`, PuLP in `.venv`)*
- Team strength: time-decayed (18-month half-life) Poisson attack/defence fit on all 1,907 matches. **Confederation anchoring got pulled forward from Phase 2** — without it the within-confederation qualifier scales made OFC/AFC sides look world-class (NZL attack 2.15) and the squad filled with their opponents' defenders. Anchors moment-matched on inter-confederation WC matches (8-year half-life): AFC 0.54, OFC 0.53, CAF 0.65, CONCACAF 0.79, CONMEBOL 1.08 vs UEFA 1.0 — in line with intuition.
- Per-fixture expected goals for MD1–MD3 (hosts get the home-advantage factor), → clean-sheet/conceded distributions.
- Player E[points]: depth-chart starter probabilities from price+ownership rank within (squad, position); attacking shares within squad scaled by club per-90s (goals/xG, assists/xA), Euro 2024 goals and penalty-taker flags; cards/saves/SoT/tackles components per the scoring matrix.
- Exact ILP (PuLP/CBC): budget, 2/5/5/3, ≤3 per country, legal-formation XI bounds, captain, bench weighting. Output: `data/processed/initial_squad.csv` (+ `player_projections.csv`, `team_ratings.csv`).
- Result (with all 9 club leagues feeding projections): 3-4-3, £99.9m, **Vargas (C) / Embolo (VC)** with a deliberate Switzerland triple-stack — their group (Qatar, Canada, Bosnia) is the softest draw by the anchored ratings — plus Haaland, Messi (MLS form now visible) and De Bruyne (Serie A). E[MD1–3 incl. captain] ≈ 177. Submit before lock; MD2 free transfers cover model upgrades.

### Phase 2 — Team model + simulator, production grade ✅ *(done — built Jun 11, ahead of the MD2 gate)*
- `src/team_model.py` — the rating fit refactored out of Phase 1 into a reusable module (confederation anchoring, host advantage, `asof` cutoffs for backtesting) plus a **tournament deflator**: the qualifier-heavy training data over-predicted tournament scoring by ~8–10% (blowouts vs minnows inflate the base); a factor fitted on historical WC/Euro matches fixes the goal means almost exactly (2018: predicted 2.54 vs actual 2.54).
- `src/ingest_results.py` — played 2026 fixtures from the refreshed `groupstage.json` flow into the common schema (and the fit, at full weight); goal/assist events captured raw for Phase 3.
- `src/simulator.py` + `data/bracket_2026.json` — full-tournament Monte Carlo over the 48-team format: group standings (points/GD/GF), 8 best thirds, knockout bracket from a data file (**approximate slots — replace with the official FIFA bracket mapping when transcribed**), extra time + shootouts. 10k runs in ~1 min, pure stdlib.
- `src/phase2_simulate.py` → `simulation_teams.csv`: per team P(reach each round), P(champion), expected matches remaining, and per-round expected goals against conditional on being alive. Headline: ESP 16.5% champion, NOR 15.8% (the model believes the qualifying campaign), SUI 98.9% R32.
- `src/backtest_team_model.py` → `backtest_team_model.md` — the acceptance gate, honestly reported: **Euro 2024 (the only test with production-like recent data) passes** — beats uniform and frequency baselines on log-loss and Brier; goal means and clean-sheet rates calibrate well everywhere. **WC 2018/2022 fail the outcome-probability test** — but diagnostically: those fits contain *no recent matches* (we hold only 2026-cycle qualifiers, so "as of 2018" the newest signal is WC 2014 at 16% weight), so they measure the model on starvation conditions production never faces. Higher shrinkage didn't help (failures are stale-signal, not overconfidence-given-data). The live check is the per-matchday scorecard (PLAYBOOK §1.4).

### Phase 3 — Player component models *(before MD3)*
- LightGBM components per the table in §3C; official scoring mapper; minutes model refit on actual 2026 MD1/MD2 lineups (the strongest minutes signal there is).
- Assist model refit on the live `GoalScorersAssists` feed.
- Backtests: Spearman per-player vs 2018/2022; ex-ante ILP squad vs baselines.
- **Acceptance:** beats the naive baselines on both backtest tournaments; MD3 transfers (and the wildcard decision — its value peaks at MD3, see §3D) made from model output.

### Phase 4 — Transfer & booster optimizer *(before R32)*
- Rolling-horizon transfer ILP: free-transfer allocation per stage, –3 penalty for extras, carryover, stage-dependent country caps, $105m knockout budget.
- Booster advisor quantifying each booster's EV each round (table in §3D).
- The R32 unlimited window is the single biggest decision of the game — the whole squad re-optimizes against knockout-only projections.
- **Acceptance:** R32 squad + booster schedule produced from one command.

### Phase 5 — In-tournament live loop *(R32 → final)*
- One command: ingest latest results (the `groupstage.json` feed format, including scorers/assists) → refit ratings → re-simulate → transfer ILP → booster check → human-readable recommendation.
- **Acceptance:** runs end-to-end in minutes, same evening as each matchday.

**Backlog / opportunistic:** Copa América 2024 & AFCON 2025 text dumps through the same curator (best bang-for-buck data addition); a Liga MX footymetrics season id would push club coverage past the current 623 players; penalty-taker list per squad (partially covered by La Liga `pk_attempts` already).

---

## 6. Honest expectations

Football is low-scoring and high-variance; no model predicts a single match reliably. The edge is systematic consistency across ~100 fixture-player decisions and 7 rounds of transfer/booster choices: correctly weighting fixture difficulty, tournament depth, minutes security, penalty duty, the –3 transfer economics and the country-cap schedule — exactly the things intuition misjudges. Expect a persistent top-tier league position, not a win every round.
