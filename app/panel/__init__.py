"""Country-month panel export — the canonical thesis dataset artifact.

One row per (country, month) inside that country's ACLED coverage window,
carrying ground-truth labels and whatever signals the system has collected.
Pure functions per layer (spine, assemble, export), mirroring `app/labels/`.
"""
