"""Ground-truth labels — country-month positive labels for composite evaluation.

Reads ACLED aggregate exports and writes P1-P3 geopolitical labels into the
`labels` table (methodology.md Step 2, aggregate-adapted as labels-v1.0).
Pure functions per layer (loader, rules, persistence) so each step is
independently testable, mirroring `app/composite/`.
"""
