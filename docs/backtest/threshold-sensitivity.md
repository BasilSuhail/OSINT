# Lead-Time Gate — Threshold Sensitivity

The gate's spike thresholds are a pre-registered choice, not a discovered
one. A conclusion that holds only at the chosen value is a property of that
value, so the gate is re-run across a range to see whether it survives.

| tau | measured | observed median | null median | observed >=1d | null >=1d | p |
|---|---|---|---|---|---|---|
| 1.00 | 12 | -1.0 | -1.0 | 42% | 34% | 0.504 |
| 1.25 | 10 | -3.0 | -1.0 | 30% | 35% | 0.663 |
| 1.50 | 10 | -3.0 | -1.0 | 30% | 38% | 0.643 |
| 2.00 | 9 | -14.0 | -1.0 | 33% | 49% | 0.920 |
| 2.50 | 7 | -14.0 | +2.0 | 14% | 62% | 0.939 |
