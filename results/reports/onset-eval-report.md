# Onset evaluation — the composite's real exam (#380)

Protocol pre-registered in `docs/onset-eval.md` before the first run. Onset months only: country-months whose preceding calm window has no positive label and full coverage (month t itself is unconstrained — see amendment A1). Strict common support with the composite.

## Primary — 12-month calm window

| k | contender | n | pos rate | AUROC | AUPR |
|---|---|---|---|---|---|
| 1 | B0 random | 5764 | 0.017 | 0.467 | 0.015 |
| 1 | B1 persistence | 5764 | 0.017 | 0.544 | 0.032 |
| 1 | B2 base rate | 5764 | 0.017 | 0.744 | 0.059 |
| 1 | B6 composite | 5764 | 0.017 | 0.496 | 0.021 |
| 3 | B0 random | 5764 | 0.047 | 0.497 | 0.045 |
| 3 | B1 persistence | 5764 | 0.047 | 0.535 | 0.075 |
| 3 | B2 base rate | 5764 | 0.047 | 0.748 | 0.159 |
| 3 | B6 composite | 5764 | 0.047 | 0.520 | 0.058 |
| 6 | B0 random | 5761 | 0.086 | 0.488 | 0.081 |
| 6 | B1 persistence | 5761 | 0.086 | 0.533 | 0.126 |
| 6 | B2 base rate | 5761 | 0.086 | 0.749 | 0.282 |
| 6 | B6 composite | 5761 | 0.086 | 0.526 | 0.103 |

## Sensitivity — 6-month calm window (declared)

| k | contender | n | pos rate | AUROC | AUPR |
|---|---|---|---|---|---|
| 1 | B0 random | 7048 | 0.024 | 0.484 | 0.023 |
| 1 | B1 persistence | 7048 | 0.024 | 0.575 | 0.057 |
| 1 | B2 base rate | 7048 | 0.024 | 0.795 | 0.101 |
| 1 | B6 composite | 7048 | 0.024 | 0.521 | 0.030 |
| 3 | B0 random | 7048 | 0.065 | 0.492 | 0.062 |
| 3 | B1 persistence | 7048 | 0.065 | 0.559 | 0.126 |
| 3 | B2 base rate | 7048 | 0.065 | 0.790 | 0.231 |
| 3 | B6 composite | 7048 | 0.065 | 0.515 | 0.076 |
| 6 | B0 random | 7045 | 0.110 | 0.486 | 0.103 |
| 6 | B1 persistence | 7045 | 0.110 | 0.549 | 0.182 |
| 6 | B2 base rate | 7045 | 0.110 | 0.782 | 0.345 |
| 6 | B6 composite | 7045 | 0.110 | 0.517 | 0.125 |

## Secondary (exploratory, declared) — WS-F variants on the primary onset support

| k | rank | indicator | variant | n | AUROC | AUPR |
|---|---|---|---|---|---|---|
| 1 | 1 | signal_geopolitical | abs | 5674 | 0.558 | 0.020 |
| 1 | 2 | signal_hazard | abs | 5674 | 0.527 | 0.019 |
| 1 | 3 | signal_market | raw | 5674 | 0.506 | 0.020 |
| 1 | 4 | signal_market | abs | 5674 | 0.500 | 0.019 |
| 1 | 5 | composite_score | abs | 5674 | 0.491 | 0.018 |
| 1 | 6 | composite_score | raw | 5674 | 0.491 | 0.018 |
| 1 | 7 | signal_geopolitical | raw | 5674 | 0.490 | 0.019 |
| 1 | 8 | signal_hazard | raw | 5674 | 0.477 | 0.016 |
| 3 | 1 | signal_geopolitical | raw | 5505 | 0.539 | 0.032 |
| 3 | 2 | composite_score | abs | 5505 | 0.536 | 0.022 |
| 3 | 3 | composite_score | raw | 5505 | 0.536 | 0.022 |
| 3 | 4 | signal_hazard | abs | 5505 | 0.523 | 0.017 |
| 3 | 5 | signal_geopolitical | abs | 5505 | 0.510 | 0.029 |
| 3 | 6 | signal_market | raw | 5505 | 0.507 | 0.016 |
| 3 | 7 | signal_market | abs | 5505 | 0.501 | 0.015 |
| 3 | 8 | signal_hazard | raw | 5505 | 0.497 | 0.016 |
| 6 | 1 | signal_hazard | abs | 5278 | 0.537 | 0.016 |
| 6 | 2 | signal_geopolitical | abs | 5278 | 0.523 | 0.017 |
| 6 | 3 | signal_geopolitical | raw | 5278 | 0.519 | 0.018 |
| 6 | 4 | composite_score | abs | 5278 | 0.518 | 0.022 |
| 6 | 5 | composite_score | raw | 5278 | 0.518 | 0.022 |
| 6 | 6 | signal_market | raw | 5278 | 0.508 | 0.013 |
| 6 | 7 | signal_market | abs | 5278 | 0.502 | 0.013 |
| 6 | 8 | signal_hazard | raw | 5278 | 0.497 | 0.015 |

Read AUPR against the onset positive rate above, not the incidence exam's. The result stands as published whatever it says — see #282 for the trail.
