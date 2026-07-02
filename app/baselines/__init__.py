"""No-skill baselines over the country-month panel.

Scores methodology.md Step 5's B0 (random), B1 (persistence) and B2 (base
rate) against horizon targets built from the panel export, reporting AUROC /
AUPR / Brier. These are the bar the composite must clear. Pure functions per
layer (targets, predictors, metrics), mirroring `app/panel/`.
"""
