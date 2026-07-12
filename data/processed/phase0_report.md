# Phase 0 report — common schema & crosswalks

## Match table (`matches_international.csv`)

| source | matches |
|---|---|
| afc_qualifiers | 225 |
| caf_qualifiers | 256 |
| concacaf_qualifiers | 99 |
| conmebol_qualifiers | 90 |
| euro2024 | 51 |
| ofc_qualifiers | 18 |
| uefa_qualifiers | 204 |
| wc2026 | 100 |
| wc_history | 964 |
| **total** | **2007** |

Goals with scorer attribution (`goals_international.csv`): 2837 (117 from Euro 2024).

## Team crosswalk (48 squads)

- FIFA code resolved: 48/48
- WC history (curated/) link: 42/48 (teams with no prior men's WC have none, by definition)
- Euro 2024 participants: 12

## Player crosswalk (fantasy pool)

- players in pool: 1489
- club stats (PL/Ligue 1): 625 (42%)
- WC-history player id (2018/2022 squads): 355 (24%)
- Euro 2024 goals attributed: 45
- at least one external link: 756 (51%)

Matching is conservative: ambiguous names are left unlinked rather than guessed.