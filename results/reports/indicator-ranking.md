# Indicator value ranking — which number predicts best (WS-F)

Eval window 2015-01-01 → 2022-12-01, horizons (1, 3, 6), target = label_any in [t+1, t+k]. Every indicator takes the same exam the composite took; `abs` = magnitude variant (deviation signals are two-sided). No Brier — z-scores are not probabilities.

## Per-indicator support (each on every month it has a value)

| k | rank | indicator | variant | n | pos rate | AUROC | AUPR |
|---|---|---|---|---|---|---|---|
| 1 | 1 | signal_hazard | abs | 12618 | 0.260 | 0.593 | 0.348 |
| 1 | 2 | signal_market | abs | 12618 | 0.260 | 0.553 | 0.351 |
| 1 | 3 | signal_geopolitical | abs | 12618 | 0.260 | 0.507 | 0.264 |
| 1 | 4 | signal_geopolitical | raw | 12618 | 0.260 | 0.503 | 0.262 |
| 1 | 5 | composite_score | abs | 12618 | 0.260 | 0.502 | 0.274 |
| 1 | 6 | composite_score | raw | 12618 | 0.260 | 0.502 | 0.274 |
| 1 | 7 | signal_market | raw | 12618 | 0.260 | 0.493 | 0.293 |
| 1 | 8 | signal_hazard | raw | 12618 | 0.260 | 0.479 | 0.276 |
| 3 | 1 | signal_hazard | abs | 12618 | 0.341 | 0.596 | 0.449 |
| 3 | 2 | signal_market | abs | 12618 | 0.341 | 0.546 | 0.430 |
| 3 | 3 | signal_geopolitical | abs | 12618 | 0.341 | 0.514 | 0.351 |
| 3 | 4 | signal_geopolitical | raw | 12618 | 0.341 | 0.504 | 0.347 |
| 3 | 5 | composite_score | abs | 12618 | 0.341 | 0.502 | 0.361 |
| 3 | 6 | composite_score | raw | 12618 | 0.341 | 0.502 | 0.361 |
| 3 | 7 | signal_market | raw | 12618 | 0.341 | 0.494 | 0.374 |
| 3 | 8 | signal_hazard | raw | 12618 | 0.341 | 0.481 | 0.365 |
| 6 | 1 | signal_hazard | abs | 12615 | 0.395 | 0.593 | 0.506 |
| 6 | 2 | signal_market | abs | 12615 | 0.395 | 0.542 | 0.478 |
| 6 | 3 | signal_geopolitical | abs | 12615 | 0.395 | 0.515 | 0.406 |
| 6 | 4 | signal_geopolitical | raw | 12615 | 0.395 | 0.504 | 0.402 |
| 6 | 5 | composite_score | abs | 12615 | 0.395 | 0.502 | 0.415 |
| 6 | 6 | composite_score | raw | 12615 | 0.395 | 0.502 | 0.415 |
| 6 | 7 | signal_market | raw | 12615 | 0.395 | 0.493 | 0.423 |
| 6 | 8 | signal_hazard | raw | 12615 | 0.395 | 0.484 | 0.424 |

## Strict common support (only months where every indicator exists)

| k | rank | indicator | variant | n | pos rate | AUROC | AUPR |
|---|---|---|---|---|---|---|---|
| 1 | 1 | signal_hazard | abs | 12614 | 0.260 | 0.593 | 0.348 |
| 1 | 2 | signal_market | abs | 12614 | 0.260 | 0.553 | 0.351 |
| 1 | 3 | signal_geopolitical | abs | 12614 | 0.260 | 0.507 | 0.264 |
| 1 | 4 | signal_geopolitical | raw | 12614 | 0.260 | 0.503 | 0.262 |
| 1 | 5 | composite_score | abs | 12614 | 0.260 | 0.502 | 0.274 |
| 1 | 6 | composite_score | raw | 12614 | 0.260 | 0.502 | 0.274 |
| 1 | 7 | signal_market | raw | 12614 | 0.260 | 0.493 | 0.293 |
| 1 | 8 | signal_hazard | raw | 12614 | 0.260 | 0.479 | 0.276 |
| 3 | 1 | signal_hazard | abs | 12610 | 0.341 | 0.596 | 0.449 |
| 3 | 2 | signal_market | abs | 12610 | 0.341 | 0.546 | 0.430 |
| 3 | 3 | signal_geopolitical | abs | 12610 | 0.341 | 0.515 | 0.352 |
| 3 | 4 | signal_geopolitical | raw | 12610 | 0.341 | 0.504 | 0.347 |
| 3 | 5 | composite_score | abs | 12610 | 0.341 | 0.502 | 0.361 |
| 3 | 6 | composite_score | raw | 12610 | 0.341 | 0.502 | 0.361 |
| 3 | 7 | signal_market | raw | 12610 | 0.341 | 0.494 | 0.374 |
| 3 | 8 | signal_hazard | raw | 12610 | 0.341 | 0.481 | 0.366 |
| 6 | 1 | signal_hazard | abs | 12604 | 0.395 | 0.593 | 0.506 |
| 6 | 2 | signal_market | abs | 12604 | 0.395 | 0.542 | 0.478 |
| 6 | 3 | signal_geopolitical | abs | 12604 | 0.395 | 0.516 | 0.406 |
| 6 | 4 | signal_geopolitical | raw | 12604 | 0.395 | 0.504 | 0.402 |
| 6 | 5 | composite_score | abs | 12604 | 0.395 | 0.502 | 0.415 |
| 6 | 6 | composite_score | raw | 12604 | 0.395 | 0.502 | 0.415 |
| 6 | 7 | signal_market | raw | 12604 | 0.395 | 0.493 | 0.423 |
| 6 | 8 | signal_hazard | raw | 12604 | 0.395 | 0.484 | 0.424 |

Ranking, not aesthetics, decides dashboard prominence — reordering is a separate frontend task. Same incidence-exam caveat as the baselines report: per-country base rates ace this target; the deviation signals sit closer to an onset instrument (see the pinned #282 discussion).
