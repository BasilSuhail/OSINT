# Within-country evaluation — result

Generated 2026-07-22T11:30:08.519691+00:00. Protocol: `docs/within-country-eval.md`, fixed before this ran.

## Primary — calm window 12 months

| contender | k | n | countries | concordance | 95% CI | mean country AUROC | qualifying |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 random | 1 | 5764 | 56 | 0.449 | [0.332, 0.562] | 0.593 | 7 |
| B1 persistence | 1 | 5764 | 56 | 0.502 | [0.477, 0.535] | 0.563 | 7 |
| B2 base rate | 1 | 5764 | 56 | 0.304 | [0.181, 0.437] | 0.402 | 7 |
| B6 composite | 1 | 5764 | 56 | 0.489 | [0.374, 0.622] | 0.505 | 7 |
| B0 random | 3 | 5764 | 54 | 0.470 | [0.395, 0.537] | 0.484 | 50 |
| B1 persistence | 3 | 5764 | 54 | 0.501 | [0.480, 0.530] | 0.492 | 50 |
| B2 base rate | 3 | 5764 | 54 | 0.302 | [0.170, 0.441] | 0.305 | 50 |
| B6 composite | 3 | 5764 | 54 | 0.516 | [0.429, 0.589] | 0.504 | 50 |
| B0 random | 6 | 5761 | 52 | 0.460 | [0.401, 0.520] | 0.469 | 46 |
| B1 persistence | 6 | 5761 | 52 | 0.506 | [0.485, 0.525] | 0.498 | 46 |
| B2 base rate | 6 | 5761 | 52 | 0.286 | [0.153, 0.437] | 0.314 | 46 |
| B6 composite | 6 | 5761 | 52 | 0.531 | [0.474, 0.582] | 0.498 | 46 |

## Sensitivity — calm window 6 months

| contender | k | n | countries | concordance | 95% CI | mean country AUROC | qualifying |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 random | 1 | 7048 | 71 | 0.472 | [0.382, 0.556] | 0.495 | 27 |
| B1 persistence | 1 | 7048 | 71 | 0.514 | [0.484, 0.551] | 0.535 | 27 |
| B2 base rate | 1 | 7048 | 71 | 0.324 | [0.237, 0.412] | 0.386 | 27 |
| B6 composite | 1 | 7048 | 71 | 0.498 | [0.413, 0.600] | 0.524 | 27 |
| B0 random | 3 | 7048 | 67 | 0.479 | [0.424, 0.535] | 0.478 | 58 |
| B1 persistence | 3 | 7048 | 67 | 0.513 | [0.491, 0.541] | 0.517 | 58 |
| B2 base rate | 3 | 7048 | 67 | 0.321 | [0.230, 0.420] | 0.322 | 58 |
| B6 composite | 3 | 7048 | 67 | 0.520 | [0.439, 0.596] | 0.507 | 58 |
| B0 random | 6 | 7045 | 64 | 0.466 | [0.421, 0.511] | 0.472 | 56 |
| B1 persistence | 6 | 7045 | 64 | 0.511 | [0.493, 0.529] | 0.507 | 56 |
| B2 base rate | 6 | 7045 | 64 | 0.306 | [0.211, 0.417] | 0.317 | 56 |
| B6 composite | 6 | 7045 | 64 | 0.527 | [0.470, 0.581] | 0.512 | 56 |

## Verdict (pre-registered rule, applied mechanically)

**NEGATIVE** — no horizon met the pre-registered rule (concordance > 0.55, CI excluding 0.5, above B2).

A null here does not separate 'the composite's construction carries no signal' from 'the inputs carry no signal'. #580 found severity near-degenerate across nearly every source and #579 that the FIRMS value is the wrong quantity — see the protocol's interpretation limits.
