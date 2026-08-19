# Baseline report — the composite against every rival it is defined against

The claim under test: a composite of market, geopolitical and hazard
signals discriminates later instability better than the best single
domain. It clears the bar only by beating **each** of B3/B4/B5 on
**both** AUROC and AUPR — beating the no-skill trio is a floor, not the
claim.

The held-out test window was first opened to scoring on **2026-08-10**,
before the methodology was locked: the Step 10 reporting checklist in
`docs/methodology.md` stood at 0 of 12. The test numbers below are
therefore not a clean pre-registered read, and no later write-up should
present them as one.

## train+validation 2015-01 → 2022-12

12785 country-months in the panel.

### Verdict

| k | n | verdict |
|---|---|---|
| 1 | 12618 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |
| 3 | 12618 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |
| 6 | 12615 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |

### Full panel — B0 / B1 / B2

| baseline | k | n | pos rate | AUROC | AUPR | Brier |
|---|---|---|---|---|---|---|
| B0 random | 1 | 12785 | 0.2661 | 0.504 | 0.269 | 0.330 |
| B1 persistence | 1 | 12785 | 0.2661 | 0.872 | 0.730 | 0.099 |
| B2 base rate | 1 | 12785 | 0.2661 | 0.931 | 0.843 | 0.096 |
| B0 random | 3 | 12785 | 0.3467 | 0.502 | 0.349 | 0.331 |
| B1 persistence | 3 | 12785 | 0.3467 | 0.835 | 0.796 | 0.125 |
| B2 base rate | 3 | 12785 | 0.3467 | 0.930 | 0.889 | 0.128 |
| B0 random | 6 | 12782 | 0.4004 | 0.497 | 0.398 | 0.334 |
| B1 persistence | 6 | 12782 | 0.4004 | 0.805 | 0.807 | 0.160 |
| B2 base rate | 6 | 12782 | 0.4004 | 0.926 | 0.908 | 0.160 |

Per-code positive rates: label_p1 = 0.1883, label_p2 = 0.1104, label_p3 = 0.0386, label_any = 0.2653

### Head-to-head on common support — B0-B2, B3-B5, B6

Restricted to rows every contender can score (12618 of 12785 at k=1, 99% coverage). The composite and each domain drop out on different months, so scoring them on their own rows would compare the difficulty of those rows rather than the quality of the forecasts.

| baseline | k | n | pos rate | AUROC | AUPR | Brier |
|---|---|---|---|---|---|---|
| B0 random | 1 | 12618 | 0.2599 | 0.504 | 0.262 | 0.330 |
| B1 persistence | 1 | 12618 | 0.2599 | 0.870 | 0.725 | 0.100 |
| B2 base rate | 1 | 12618 | 0.2599 | 0.929 | 0.835 | 0.096 |
| B3 geopolitical only | 1 | 12618 | 0.2599 | 0.503 | 0.262 | 2.089 |
| B4 market only | 1 | 12618 | 0.2599 | 0.493 | 0.293 | 0.398 |
| B5 hazard only | 1 | 12618 | 0.2599 | 0.479 | 0.276 | 0.628 |
| B6 composite | 1 | 12618 | 0.2599 | 0.502 | 0.274 | 0.261 |
| B0 random | 3 | 12618 | 0.3409 | 0.502 | 0.343 | 0.331 |
| B1 persistence | 3 | 12618 | 0.3409 | 0.831 | 0.791 | 0.126 |
| B2 base rate | 3 | 12618 | 0.3409 | 0.928 | 0.883 | 0.129 |
| B3 geopolitical only | 3 | 12618 | 0.3409 | 0.504 | 0.347 | 2.167 |
| B4 market only | 3 | 12618 | 0.3409 | 0.494 | 0.374 | 0.478 |
| B5 hazard only | 3 | 12618 | 0.3409 | 0.481 | 0.365 | 0.706 |
| B6 composite | 3 | 12618 | 0.3409 | 0.502 | 0.361 | 0.260 |
| B0 random | 6 | 12615 | 0.3953 | 0.496 | 0.392 | 0.335 |
| B1 persistence | 6 | 12615 | 0.3953 | 0.801 | 0.801 | 0.162 |
| B2 base rate | 6 | 12615 | 0.3953 | 0.924 | 0.903 | 0.162 |
| B3 geopolitical only | 6 | 12615 | 0.3953 | 0.504 | 0.402 | 2.223 |
| B4 market only | 6 | 12615 | 0.3953 | 0.493 | 0.423 | 0.535 |
| B5 hazard only | 6 | 12615 | 0.3953 | 0.484 | 0.424 | 0.755 |
| B6 composite | 6 | 12615 | 0.3953 | 0.502 | 0.415 | 0.260 |

## held-out test 2023-01 → 2024-12

4672 country-months in the panel.

### Verdict

| k | n | verdict |
|---|---|---|
| 1 | 4593 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |
| 3 | 4579 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |
| 6 | 4556 | FAIL — the composite does not beat B3 geopolitical only, B4 market only, B5 hazard only |

### Full panel — B0 / B1 / B2

| baseline | k | n | pos rate | AUROC | AUPR | Brier |
|---|---|---|---|---|---|---|
| B0 random | 1 | 4664 | 0.2193 | 0.502 | 0.224 | 0.330 |
| B1 persistence | 1 | 4664 | 0.2193 | 0.888 | 0.748 | 0.076 |
| B2 base rate | 1 | 4664 | 0.2193 | 0.950 | 0.844 | 0.073 |
| B0 random | 3 | 4650 | 0.2791 | 0.495 | 0.276 | 0.334 |
| B1 persistence | 3 | 4650 | 0.2791 | 0.852 | 0.800 | 0.092 |
| B2 base rate | 3 | 4650 | 0.2791 | 0.951 | 0.898 | 0.091 |
| B0 random | 6 | 4627 | 0.3205 | 0.494 | 0.316 | 0.335 |
| B1 persistence | 6 | 4627 | 0.3205 | 0.823 | 0.804 | 0.118 |
| B2 base rate | 6 | 4627 | 0.3205 | 0.949 | 0.914 | 0.111 |

Per-code positive rates: label_p1 = 0.1479, label_p2 = 0.1064, label_p3 = 0.0225, label_any = 0.2183

### Head-to-head on common support — B0-B2, B3-B5, B6

Restricted to rows every contender can score (4593 of 4664 at k=1, 98% coverage). The composite and each domain drop out on different months, so scoring them on their own rows would compare the difficulty of those rows rather than the quality of the forecasts.

| baseline | k | n | pos rate | AUROC | AUPR | Brier |
|---|---|---|---|---|---|---|
| B0 random | 1 | 4593 | 0.2151 | 0.503 | 0.221 | 0.329 |
| B1 persistence | 1 | 4593 | 0.2151 | 0.890 | 0.748 | 0.074 |
| B2 base rate | 1 | 4593 | 0.2151 | 0.949 | 0.841 | 0.073 |
| B3 geopolitical only | 1 | 4593 | 0.2151 | 0.506 | 0.225 | 1.827 |
| B4 market only | 1 | 4593 | 0.2151 | 0.495 | 0.253 | 0.282 |
| B5 hazard only | 1 | 4593 | 0.2151 | 0.478 | 0.241 | 0.707 |
| B6 composite | 1 | 4593 | 0.2151 | 0.498 | 0.235 | 0.262 |
| B0 random | 3 | 4579 | 0.2739 | 0.495 | 0.271 | 0.333 |
| B1 persistence | 3 | 4579 | 0.2739 | 0.852 | 0.798 | 0.092 |
| B2 base rate | 3 | 4579 | 0.2739 | 0.950 | 0.893 | 0.091 |
| B3 geopolitical only | 3 | 4579 | 0.2739 | 0.518 | 0.289 | 1.868 |
| B4 market only | 3 | 4579 | 0.2739 | 0.491 | 0.316 | 0.342 |
| B5 hazard only | 3 | 4579 | 0.2739 | 0.478 | 0.312 | 0.761 |
| B6 composite | 3 | 4579 | 0.2739 | 0.507 | 0.301 | 0.260 |
| B0 random | 6 | 4556 | 0.3154 | 0.495 | 0.312 | 0.334 |
| B1 persistence | 6 | 4556 | 0.3154 | 0.821 | 0.802 | 0.118 |
| B2 base rate | 6 | 4556 | 0.3154 | 0.947 | 0.908 | 0.112 |
| B3 geopolitical only | 6 | 4556 | 0.3154 | 0.512 | 0.326 | 1.919 |
| B4 market only | 6 | 4556 | 0.3154 | 0.491 | 0.358 | 0.386 |
| B5 hazard only | 6 | 4556 | 0.3154 | 0.484 | 0.361 | 0.801 |
| B6 composite | 6 | 4556 | 0.3154 | 0.504 | 0.337 | 0.261 |

## Reading the single-domain rivals

B3/B4/B5 are not separate models. The composite z-scores each domain
before combining them, and the panel stores those components, so each
rival is the composite deprived of its other inputs — the exact
counterfactual the claim needs. If a rival wins, the extra domains are
costing information rather than adding it.

Rolling within-country z-scores deliberately remove the cross-sectional
differences that dominate P1-P3 incidence, so all six contenders measure
deviation from a country's own baseline. That is an onset-shaped signal,
and against a ~0.93 per-country base rate a coin-flip AUROC is a
statement about construction rather than about signal absence. The
onset-restricted evaluation this points to must be pre-registered before
it is run.
