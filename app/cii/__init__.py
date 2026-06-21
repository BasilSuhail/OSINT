"""CII (Country Instability Index) v1.

Per-country instability scoring inspired by koala73/worldmonitor's CII v8.
Pure functions in ``scoring`` + a Celery-callable orchestrator in ``task``.
See ``docs/architecture/CII-METHODOLOGY.md`` for the formula, weights, and
per-country baseline coefficients.
"""

from app.cii.config import CII_BASELINES, DEFAULT_CII_BASELINE, CiiBaseline
from app.cii.scoring import CII_METHOD_VERSION, CiiComponents, compute_cii

__all__ = [
    "CII_BASELINES",
    "CII_METHOD_VERSION",
    "DEFAULT_CII_BASELINE",
    "CiiBaseline",
    "CiiComponents",
    "compute_cii",
]
