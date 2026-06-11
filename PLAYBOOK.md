# In-Tournament Playbook — procedures from MD1 onwards

Companion to `FANTASY_ML_PROPOSAL.md` (§5 phasing) and `rules.md`. The
proposal says *what* gets built; this document says *what to do, when,
with which command* once the tournament is running — and the criteria for
moving to each next phase.

**Game calendar (decision deadlines are the first kickoff of each round):**

| Round | Dates | Free transfers | Country cap | Budget | Boosters available |
|---|---|---|---|---|---|
| MD1 | Jun 11–18 | squad locked | 3 | $100m | no wildcard |
| MD2 | Jun 18–24 | 2 | 3 | $100m | wildcard, Max Captain, 12th Man |
| MD3 | Jun 24–28 | 2 (1 may carry from MD2) | 3 | $100m | wildcard (best EV window) |
| R32 | ~Jun 29+ (official schedule TBC) | **unlimited** | 4 | **$105m** | no wildcard; Qualification + Mystery Booster appear |
| R16 | TBC | 4 | 5 | $105m | all remaining |
| QF | TBC | 4 | 6 | $105m | all remaining |
| SF | TBC | 5 | 8 | $105m | all remaining |
| Final | TBC | 6 | 8 | $105m | all remaining |

Extra transfers beyond the free allocation cost **–3 points each**, every
round. The knockout dates aren't in `groupstage.json` — confirm them from
the official schedule when the bracket fixes and note them here.

---

## 1. The standing post-matchday procedure

Run after **every** matchday/round, in this order. Steps marked 🔜 use
machinery from a phase that isn't built yet — until it lands, apply the
listed fallback.

1. **Refresh the game files** (same export route as the originals):
   - `data/raw/game/groupstage.json` — now carries results and the
     `homeGoalScorersAssists` / `awayGoalScorersAssists` fields for played
     matches. This is our only source of **assists**.
   - `data/raw/game/players.json` — updated `status` (injuries/suspensions
     show up here), `percentSelected` per round, and any price moves.
2. **Append results to the model data.** ✅ built (`src/ingest_results.py`,
   runs inside `build_phase0.py`): played fixtures become common-schema
   match rows at full fit weight; goal/assist events are saved raw to
   `wc2026_events_raw.json` — **inspect their shape after MD1** and write
   the proper parser for the Phase 3 assist model.
3. **Rebuild + refit:** `python3 src/build_phase0.py` then
   `.venv/bin/python src/phase1_squad.py` (or the Phase 2/3 successors once
   they exist). WC-2026 matches must enter the team-strength fit with full
   weight (zero age) — they are the freshest evidence there is.
4. **Score the model** (5 minutes, keeps us honest — log it in this file):
   - Spearman rank correlation: predicted `player_projections.csv` round
     points vs actual round points for players who played.
   - Team level: goals predicted vs scored per fixture; clean sheets called
     correctly.
   - Note the 3 worst misses and *why* (wrong lineup? wrong team strength?
     missing penalty taker?). These feed the next phase's priorities.
5. **Update minutes evidence.** Actual lineups are the strongest starter
   signal available — far better than the price/ownership depth chart.
   🔜 *Phase 3 ingests them properly; fallback: manually override
   `p_start` for players whose MD1 role contradicted the depth chart
   (injured starters, surprise benchings) before re-running.*
6. **Transfer decision.** 🔜 *Phase 4 solves this as an ILP with the –3
   economics. Fallback rule until then:* rank current squad by updated
   E[remaining group points]; only transfer when the incoming player's
   edge over the outgoing one exceeds **2.5 points per remaining match**
   for a free transfer, or **(edge × matches) > 3 + 2.5** for a paid one;
   never breach the country cap of the *current* stage.
7. **Captain, vice, bench order, formation** for the next round: highest
   E[points] in the XI, second-highest as vice; bench ordered by
   E[points] × P(plays); check the XI still fits a legal formation after
   transfers.
8. **Booster check** (see §4 — default is *hold*).
9. **Record everything:** commit the refreshed data + decisions
   (`git commit`), and append a dated entry to the decision log (§5).

---

## 2. After MD1 specifically (run by Jun 17, decide before first MD2 kickoff Jun 18)

MD1 is the single biggest information release of the group stage: 48 real
lineups, real minutes, real set-piece takers, and the first hard evidence
on every team the ratings only knew from qualifiers.

- [ ] Steps 1–5 of the standing procedure.
- [ ] **Lineup audit of our 15:** flag anyone who didn't start MD1 or was
      subbed off early without explanation — they are transfer candidates
      regardless of E[points].
- [ ] **Switzerland-stack check:** the squad deliberately triple-stacks
      SUI on the strength of the ratings (soft group: QAT/CAN/BIH). If
      Switzerland's MD1 performance contradicts the rating (lost/failed to
      create vs Bosnia-level opposition), unwind one slot with a free
      transfer rather than doubling down.
- [ ] **Penalty-taker harvest:** record every penalty taker observed at
      MD1 into the projections (the La Liga `pk_attempts` column covers
      only part of the pool; observed WC penalties override everything).
- [ ] **Captain sanity:** Vargas (C) vs Haaland was a 16.10-vs-15.90
      coin-flip. Re-run after MD1 results; switch freely — captaincy costs
      nothing to change before the deadline.
- [ ] **Spend at most the 2 free transfers.** Paid transfers this early
      are almost never right: the R32 unlimited window resets the squad in
      ~10 days, so a –3 hit must pay back within the group stage alone.
- [ ] **No wildcard at MD2** unless ≥4 of our 15 became dead weight
      (injuries/red cards/benchings) — its EV peaks at MD3 (§4).

---

## 3. Phase gates — when to move to the next phase, and what "ready" means

Build order is dictated by which decision each phase serves. **The phase
must be ready before its decision window opens; if it isn't, fall back
(§1 fallbacks) rather than rush an unvalidated model into a live decision.**

| Phase | Build window | Must be live before | Serves which decision | Go-live criteria |
|---|---|---|---|---|
| 2. Full simulator | ✅ live (built Jun 11) | **MD2 deadline (Jun 18)** | MD2 transfers need P(advance) and knockout-depth value, not just MD-by-MD points | Euro 2024 out-of-sample: PASS (beats both baselines); goal means + CS rates calibrated on 2018/2022/2024; WC 2018/2022 outcome tests fail on data starvation (no qualifier archives for those cycles — see `backtest_team_model.md`), so the live scorecard (§1.4) is the operative check. Rerun `python3 src/phase2_simulate.py` after every matchday once results are ingested. **Bracket is approximate** — transcribe the official R32 slot mapping into `data/bracket_2026.json` before R32. |
| 3. Player GBMs + minutes model | Jun 17–23 | **MD3 deadline (Jun 24)** | MD3 transfers + the wildcard call; first round where per-player accuracy dominates | beats Phase-1 heuristic on 2018/2022 backtest (Spearman) *and* on the observed MD1–MD2 scorecards (§1.4); minutes model trained on actual 2026 lineups |
| 4. Transfer/booster ILP | Jun 23–28 | **R32 window opens (~Jun 29)** | the biggest decision of the game: full-squad re-optimization with $105m, unlimited transfers, 4-per-country, knockout-only horizon | reproduces sensible plans on 2022 backtest; handles carryover/–3/country-cap schedule; booster EV table produced |
| 5. Live loop | during Phase 4 | R32 onwards | same-evening turnaround every knockout round | one command: results → refit → re-simulate → transfer ILP → recommendation, end-to-end in minutes |

Phase-advance procedure, each time: run the new phase's backtest, compare
against the incumbent on the §1.4 scorecards, switch only on a win, commit
with the comparison in the message, and update `FANTASY_ML_PROPOSAL.md` §5
status + this playbook.

**If a phase misses its window:** keep deciding with the previous phase's
machinery + §1 fallback rules. A validated simple model beats an
unvalidated sophisticated one — the –3s and dead boosters from a bad
decision are real; the regret from a slightly coarser model is small.

---

## 4. Booster guardrails (default: hold)

One booster per round max; all single-use. Decision rule per round: burn a
booster only when its quantified EV gain exceeds what the *best remaining
round* for it would likely offer.

| Booster | Earliest sensible | Target window | Trigger |
|---|---|---|---|
| Wildcard | MD2 (allowed) | **MD3** | ≥3–4 dead squad slots, or simulator says our squad's teams are collapsing pre-R32. Using it at MD2 needs a disaster; holding it past MD3 wastes it (R32 transfers are free anyway) |
| Maximum Captain | MD2 | round with the flattest captain distribution | top-3 captain E[points] within ~0.5 of each other → auto-captain insurance is worth most |
| 12th Man | MD2 | a round where a non-squad player has standout E | best non-squad E[points] exceeds our worst XI starter by ≥3 |
| Qualification Booster | R32 | **R32**, XI full of group winners | 2 × Σ P(advance) over the XI — simulator (Phase 2) computes it; typically peaks at R32 |
| Mystery Booster | revealed at R32 | — | leave a slot in the plan; decide when revealed |

---

## 5. Decision log

Append one entry per round. Keep it short: what changed, why, what the
model said, what we overrode and the reason. This is the raw material for
the post-tournament review (and for catching systematic model misses).

```
## MD1 → MD2 (decided 2026-06-__)
Scorecard: Spearman __, clean sheets _/24 called, worst misses: …
Transfers: OUT … IN … (free/–3), rationale: …
Captain: …  Vice: …  Formation: …
Boosters: held / used … because …
Overrides vs model: …
```

---

*Created 2026-06-11, between squad lock and the end of MD1. Maintain this
file as rounds complete; it is the operational source of truth — the
proposal stays the architectural one.*
