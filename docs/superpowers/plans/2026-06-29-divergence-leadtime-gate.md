# Divergence Lead-Time Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build (and run) the smallest system that proves or kills the claim that physical sensor activity leads the narrative — a divergence engine + a frozen-registry historical backtest that emits an explicit PASS/FAIL verdict.

**Architecture:** Layer on the existing pipeline (`fetchers → normalize → events table → API → frontend`). A new import-pure `app/divergence/` engine computes per-country×day physical-vs-narrative z-scores and lead time; a new `app/backtest/` harness backfills historical events for a frozen event registry, runs the engine, and reports lead-time + false-positive metrics. New sensors (VIIRS flaring fetcher, AIS WebSocket collector) and an extended source-health panel feed the live system but are *not* required for the gate verdict.

**Tech Stack:** Python 3.12, SQLAlchemy (SQLite in tests / Postgres in prod), Pydantic v2, pytest, httpx, Celery; Next.js 15 + TypeScript + SWR frontend.

## Global Constraints

- Divergence scoring code is **import-pure**: no DB, no network, no Celery — mirrors `app/cii/scoring.py`. I/O lives in task/aggregate modules.
- Every fetcher returns `list[Event]` (`app/models.py`) and never raises on malformed rows — match `app/sources/nasa_firms_fetcher.py`.
- Missing credentials → source is a no-op / `disabled`, never an error (match FIRMS `if not settings.firms_map_key: return []`).
- Canonical `Event` fields: `source, source_event_id, occurred_at, fetched_at, category, severity, confidence, keywords, country, lat, lon, payload`. `country` = ISO-3166-1 alpha-2 uppercase. `model_config = ConfigDict(extra="forbid")`.
- Tests run against in-memory SQLite via the `db_session` fixture in `tests/conftest.py`. No docker required for the unit suite.
- Method version strings are frozen constants, bumped never edited: `DIVERGENCE_METHOD_VERSION = "div.v1"`.
- The event registry, once committed and first run, is **never edited in place** — guarded by a content hash. New events → new registry version.
- Run tests with `pytest` from repo root (config in `pyproject.toml`). Lint: `ruff check`.
- Commit after every passing task. Branch: `spec/divergence-leadtime-gate` (already created). Issue: #250.

---

## Source partition (used everywhere)

Single source of truth for which side a source belongs to. Defined once in Task 1, imported by all later tasks.

- **Physical:** `nasa-firms`, `usgs-quake`, `gdacs`, `eonet`, `opensky-adsb`, `viirs-flaring`, `aisstream`
- **Narrative:** `gdelt`, and any source whose slug starts with `rss-`
- **Ignored** (not in divergence): market (`yfinance`, `fred`, `polymarket`), cyber (`abuse-ch-*`), `uk-police`, `acled`, `emdat`

---

## Task 1: Source-side classification + divergence config

**Files:**
- Create: `app/divergence/__init__.py` (empty)
- Create: `app/divergence/config.py`
- Test: `tests/test_divergence_config.py`

**Interfaces:**
- Produces: `classify_side(source: str) -> Literal["physical", "narrative"] | None`; constants `ROLLING_WINDOW_DAYS=28`, `TAU_P=1.5`, `TAU_N=1.5`, `LOG_CEILING_PHYSICAL`, `LOG_CEILING_NARRATIVE`, `MAX_LEAD_LOOKBACK_DAYS=21`, `DIVERGENCE_METHOD_VERSION="div.v1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_divergence_config.py
from app.divergence.config import classify_side


def test_physical_sources_classified():
    assert classify_side("usgs-quake") == "physical"
    assert classify_side("nasa-firms") == "physical"
    assert classify_side("viirs-flaring") == "physical"
    assert classify_side("aisstream") == "physical"


def test_narrative_sources_classified():
    assert classify_side("gdelt") == "narrative"
    assert classify_side("rss-bbc-world") == "narrative"


def test_ignored_sources_return_none():
    assert classify_side("yfinance") is None
    assert classify_side("abuse-ch-feodo") is None
    assert classify_side("uk-police") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_divergence_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.divergence'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/divergence/config.py
"""Frozen divergence parameters + source-side classification.

Import-pure. These constants define the gate; freezing them before any
backtest run is what keeps the proof honest (no post-hoc tuning).
"""

from __future__ import annotations

from typing import Final, Literal

#: Bumped together with any change to weights/thresholds. Never edited in place.
DIVERGENCE_METHOD_VERSION: Final[str] = "div.v1"

#: Trailing window for the rolling z-score baseline, in days.
ROLLING_WINDOW_DAYS: Final[int] = 28

#: z-score thresholds a side must cross to count as a "spike".
TAU_P: Final[float] = 1.5
TAU_N: Final[float] = 1.5

#: log1p ceilings (the count that reads as "fully saturated") per side.
LOG_CEILING_PHYSICAL: Final[float] = 200.0
LOG_CEILING_NARRATIVE: Final[float] = 300.0

#: How far before a narrative spike we look for a physical spike, in days.
MAX_LEAD_LOOKBACK_DAYS: Final[int] = 21

_PHYSICAL: Final[frozenset[str]] = frozenset(
    {"nasa-firms", "usgs-quake", "gdacs", "eonet", "opensky-adsb", "viirs-flaring", "aisstream"}
)


def classify_side(source: str) -> Literal["physical", "narrative"] | None:
    """Return which divergence side a source slug belongs to, or None to ignore."""
    slug = (source or "").lower()
    if slug in _PHYSICAL:
        return "physical"
    if slug == "gdelt" or slug.startswith("rss-"):
        return "narrative"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_divergence_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/divergence/__init__.py app/divergence/config.py tests/test_divergence_config.py
git commit -m "feat: #250 divergence source-side classification + frozen config"
```

---

## Task 2: Rolling z-score helper

**Files:**
- Create: `app/divergence/scoring.py`
- Test: `tests/test_divergence_scoring.py`

**Interfaces:**
- Consumes: `LOG_CEILING_*`, `ROLLING_WINDOW_DAYS` from `app.divergence.config`.
- Produces: `rolling_z(values: list[float], window: int) -> list[float]` — for index `i`, z = (values[i] − mean(prev `window`)) / std(prev `window`); 0.0 where < 2 prior points or zero variance.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_divergence_scoring.py
import math

from app.divergence.scoring import rolling_z


def test_rolling_z_flat_series_is_zero():
    assert rolling_z([5.0] * 10, window=5) == [0.0] * 10


def test_rolling_z_spike_is_positive():
    series = [1.0, 1.0, 1.0, 1.0, 1.0, 10.0]
    z = rolling_z(series, window=5)
    assert z[:5] == [0.0, 0.0, 0.0, 0.0, 0.0]  # warmup + zero-variance
    assert z[5] > 3.0  # 10 vs a flat 1.0 baseline is a big anomaly


def test_rolling_z_warmup_returns_zero_until_two_points():
    z = rolling_z([3.0, 7.0, 11.0], window=28)
    assert z[0] == 0.0  # no prior points
    assert z[1] == 0.0  # only one prior point


def test_rolling_z_no_nan():
    z = rolling_z([0.0, 0.0, 0.0, 4.0], window=3)
    assert all(not math.isnan(v) for v in z)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_divergence_scoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'rolling_z'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/divergence/scoring.py
"""Pure divergence scoring — no DB, no network.

Mirrors app/cii/scoring.py conventions: import-pure, log-dampened,
versioned. The orchestrators (backtest harness, future live task) handle
all I/O and call into here.
"""

from __future__ import annotations

import math
import statistics


def rolling_z(values: list[float], window: int) -> list[float]:
    """Standardized anomaly of each point vs the trailing `window` points.

    z[i] = (values[i] - mean(prev)) / std(prev), where `prev` is up to the
    last `window` values strictly before i. Returns 0.0 during warmup
    (< 2 prior points) or when the prior window has zero variance, so the
    output never contains NaN/inf.
    """
    out: list[float] = []
    for i, v in enumerate(values):
        prev = values[max(0, i - window):i]
        if len(prev) < 2:
            out.append(0.0)
            continue
        mean = statistics.fmean(prev)
        std = statistics.pstdev(prev)
        if std == 0.0:
            out.append(0.0)
            continue
        z = (v - mean) / std
        out.append(0.0 if math.isnan(z) else z)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_divergence_scoring.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/divergence/scoring.py tests/test_divergence_scoring.py
git commit -m "feat: #250 rolling z-score helper for divergence"
```

---

## Task 3: Divergence series + lead detection

**Files:**
- Modify: `app/divergence/scoring.py`
- Test: `tests/test_divergence_scoring.py`

**Interfaces:**
- Consumes: `rolling_z`, config constants.
- Produces:
  - `DivergenceSeries` dataclass: `days: list[date]`, `physical_z: list[float]`, `narrative_z: list[float]`, `divergence: list[float]`, `method_version: str`.
  - `compute_divergence_series(days, physical_raw, narrative_raw) -> DivergenceSeries` (log-scale → rolling_z → physical_z − narrative_z).
  - `LeadResult` dataclass: `physical_spike_day: date | None`, `narrative_spike_day: date | None`, `lead_days: int | None`.
  - `detect_lead(series) -> LeadResult` (first narrative spike `≥ TAU_N`; nearest physical spike `≥ TAU_P` within `MAX_LEAD_LOOKBACK_DAYS` before it; `lead_days = (D_n − D_p).days`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_divergence_scoring.py
from datetime import date, timedelta

from app.divergence.scoring import compute_divergence_series, detect_lead


def _days(n: int) -> list[date]:
    base = date(2025, 1, 1)
    return [base + timedelta(days=i) for i in range(n)]


def test_physical_leads_narrative_by_three_days():
    days = _days(40)
    physical = [1.0] * 40
    narrative = [1.0] * 40
    physical[30] = 80.0   # physical spike day 30
    narrative[33] = 200.0  # narrative spike day 33
    series = compute_divergence_series(days, physical, narrative)
    result = detect_lead(series)
    assert result.physical_spike_day == days[30]
    assert result.narrative_spike_day == days[33]
    assert result.lead_days == 3


def test_no_narrative_spike_returns_none_lead():
    days = _days(40)
    series = compute_divergence_series(days, [1.0] * 40, [1.0] * 40)
    result = detect_lead(series)
    assert result.narrative_spike_day is None
    assert result.lead_days is None


def test_divergence_positive_when_physical_moves_first():
    days = _days(40)
    physical = [1.0] * 40
    physical[30] = 80.0
    series = compute_divergence_series(days, physical, [1.0] * 40)
    assert series.divergence[30] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_divergence_scoring.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_divergence_series'`

- [ ] **Step 3: Write minimal implementation**

```python
# add to app/divergence/scoring.py
from dataclasses import dataclass
from datetime import date

from app.divergence.config import (
    DIVERGENCE_METHOD_VERSION,
    LOG_CEILING_NARRATIVE,
    LOG_CEILING_PHYSICAL,
    MAX_LEAD_LOOKBACK_DAYS,
    ROLLING_WINDOW_DAYS,
    TAU_N,
    TAU_P,
)


def _log_scale(raw: float, ceiling: float) -> float:
    """log1p(raw) / log1p(ceiling) — dampens volume bursts. Matches CII."""
    if raw <= 0 or ceiling <= 0:
        return 0.0
    return math.log1p(raw) / math.log1p(ceiling)


@dataclass(frozen=True)
class DivergenceSeries:
    days: list[date]
    physical_z: list[float]
    narrative_z: list[float]
    divergence: list[float]
    method_version: str = DIVERGENCE_METHOD_VERSION


@dataclass(frozen=True)
class LeadResult:
    physical_spike_day: date | None
    narrative_spike_day: date | None
    lead_days: int | None


def compute_divergence_series(
    days: list[date], physical_raw: list[float], narrative_raw: list[float]
) -> DivergenceSeries:
    """Build the divergence series for one country over a contiguous day range.

    `days`, `physical_raw`, `narrative_raw` must be equal-length and
    day-aligned (one entry per calendar day, gaps filled with 0).
    """
    if not (len(days) == len(physical_raw) == len(narrative_raw)):
        raise ValueError("days, physical_raw, narrative_raw must be equal length")
    phys_scaled = [_log_scale(v, LOG_CEILING_PHYSICAL) for v in physical_raw]
    narr_scaled = [_log_scale(v, LOG_CEILING_NARRATIVE) for v in narrative_raw]
    phys_z = rolling_z(phys_scaled, ROLLING_WINDOW_DAYS)
    narr_z = rolling_z(narr_scaled, ROLLING_WINDOW_DAYS)
    divergence = [p - n for p, n in zip(phys_z, narr_z, strict=True)]
    return DivergenceSeries(days=days, physical_z=phys_z, narrative_z=narr_z, divergence=divergence)


def detect_lead(series: DivergenceSeries) -> LeadResult:
    """First narrative spike, and the nearest physical spike preceding it."""
    n_idx = next((i for i, z in enumerate(series.narrative_z) if z >= TAU_N), None)
    if n_idx is None:
        return LeadResult(None, None, None)
    narrative_day = series.days[n_idx]
    lo = max(0, n_idx - MAX_LEAD_LOOKBACK_DAYS)
    # nearest physical spike in [lo, n_idx) — scan backward from the narrative day
    p_idx = next(
        (i for i in range(n_idx - 1, lo - 1, -1) if series.physical_z[i] >= TAU_P), None
    )
    if p_idx is None:
        return LeadResult(None, narrative_day, None)
    physical_day = series.days[p_idx]
    return LeadResult(physical_day, narrative_day, (narrative_day - physical_day).days)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_divergence_scoring.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add app/divergence/scoring.py tests/test_divergence_scoring.py
git commit -m "feat: #250 divergence series + lead-time detection"
```

---

## Task 4: Per-country×day aggregation from the event store

**Files:**
- Create: `app/divergence/aggregate.py`
- Test: `tests/test_divergence_aggregate.py`

**Interfaces:**
- Consumes: `classify_side`; `EventRow` from `app.db_models`.
- Produces: `daily_side_counts(session, country, start, end) -> tuple[list[date], list[float], list[float]]` — contiguous daily series (gaps filled with 0.0) for `[start, end]` inclusive, physical and narrative counts via `classify_side`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_divergence_aggregate.py
from datetime import UTC, date, datetime

from app.db_models import EventRow
from app.divergence.aggregate import daily_side_counts


def _ev(session, *, source, country, day, hour=12):
    session.add(
        EventRow(
            source=source,
            source_event_id=f"{source}-{day}-{hour}",
            occurred_at=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
            category="hazard",
            keywords=[],
            country=country,
            payload={},
        )
    )


def test_daily_counts_partition_and_fill(db_session):
    _ev(db_session, source="usgs-quake", country="JP", day=date(2025, 3, 1))
    _ev(db_session, source="usgs-quake", country="JP", day=date(2025, 3, 1), hour=14)
    _ev(db_session, source="gdelt", country="JP", day=date(2025, 3, 3))
    _ev(db_session, source="yfinance", country="JP", day=date(2025, 3, 1))  # ignored side
    db_session.commit()

    days, physical, narrative = daily_side_counts(
        db_session, "JP", date(2025, 3, 1), date(2025, 3, 3)
    )
    assert days == [date(2025, 3, 1), date(2025, 3, 2), date(2025, 3, 3)]
    assert physical == [2.0, 0.0, 0.0]   # two quakes day 1, yfinance ignored
    assert narrative == [0.0, 0.0, 1.0]  # one gdelt day 3


def test_other_country_excluded(db_session):
    _ev(db_session, source="usgs-quake", country="US", day=date(2025, 3, 1))
    db_session.commit()
    _, physical, _ = daily_side_counts(db_session, "JP", date(2025, 3, 1), date(2025, 3, 1))
    assert physical == [0.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_divergence_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.divergence.aggregate'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/divergence/aggregate.py
"""I/O layer: read events from the store into per-day side counts.

Kept separate from app/divergence/scoring.py so the scoring stays
import-pure (same split as app/cii/task.py vs app/cii/scoring.py).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.divergence.config import classify_side


def daily_side_counts(
    session: Session, country: str, start: date, end: date
) -> tuple[list[date], list[float], list[float]]:
    """Contiguous daily physical/narrative counts for one country in [start, end].

    Gaps are filled with 0.0 so the series is day-aligned for scoring.
    """
    iso = country.upper()
    window_start = datetime(start.year, start.month, start.day, tzinfo=UTC)
    window_end = datetime(end.year, end.month, end.day, tzinfo=UTC) + timedelta(days=1)
    stmt = (
        select(EventRow)
        .where(EventRow.country == iso)
        .where(EventRow.occurred_at >= window_start)
        .where(EventRow.occurred_at < window_end)
    )
    phys: dict[date, int] = {}
    narr: dict[date, int] = {}
    for ev in session.execute(stmt).scalars():
        side = classify_side(ev.source)
        if side is None:
            continue
        d = ev.occurred_at.astimezone(UTC).date()
        bucket = phys if side == "physical" else narr
        bucket[d] = bucket.get(d, 0) + 1

    days: list[date] = []
    physical: list[float] = []
    narrative: list[float] = []
    cur = start
    while cur <= end:
        days.append(cur)
        physical.append(float(phys.get(cur, 0)))
        narrative.append(float(narr.get(cur, 0)))
        cur += timedelta(days=1)
    return days, physical, narrative
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_divergence_aggregate.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/divergence/aggregate.py tests/test_divergence_aggregate.py
git commit -m "feat: #250 per-country daily side-count aggregation"
```

---

## Task 5: Frozen event registry + hash guard

**Files:**
- Create: `app/backtest/__init__.py` (empty)
- Create: `app/backtest/events.yaml`
- Create: `app/backtest/registry.py`
- Test: `tests/test_backtest_registry.py`

**Interfaces:**
- Produces:
  - `RegistryEvent` dataclass: `id: str`, `country: str`, `date: date`, `domain: str`, `source_url: str`, `notes: str`.
  - `load_registry(path) -> tuple[list[RegistryEvent], str]` returns events + content hash (sha256 of the canonical-serialized events).
  - `verify_frozen(path, expected_hash) -> None` raises `RegistryEditedError` if the current hash differs from `expected_hash`.

The YAML carries a top-level `frozen_hash` written after the first run; loader compares.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_registry.py
import textwrap

import pytest

from app.backtest.registry import RegistryEditedError, load_registry, verify_frozen


def _write(tmp_path, body, frozen_hash=None):
    p = tmp_path / "events.yaml"
    header = f"frozen_hash: {frozen_hash}\n" if frozen_hash else ""
    p.write_text(header + textwrap.dedent(body))
    return p


_BODY = """
    events:
      - id: jp-quake-2024
        country: JP
        date: 2024-01-01
        domain: hazard
        source_url: https://example.org/jp
        notes: test event
"""


def test_load_registry_parses_events(tmp_path):
    events, content_hash = load_registry(_write(tmp_path, _BODY))
    assert len(events) == 1
    assert events[0].country == "JP"
    assert len(content_hash) == 64  # sha256 hex


def test_verify_frozen_passes_when_hash_matches(tmp_path):
    p = _write(tmp_path, _BODY)
    _, content_hash = load_registry(p)
    verify_frozen(p, content_hash)  # no raise


def test_verify_frozen_raises_when_edited(tmp_path):
    p = _write(tmp_path, _BODY)
    _, original = load_registry(p)
    edited = _write(
        tmp_path,
        _BODY.replace("country: JP", "country: US"),
    )
    with pytest.raises(RegistryEditedError):
        verify_frozen(edited, original)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backtest'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/backtest/registry.py
"""Frozen event registry loader + edit guard.

The registry is the pre-registered list of events the backtest measures
against. Freezing it (hash guard) before looking at results is what stops
the proof from becoming post-hoc cherry-picking.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml


class RegistryEditedError(RuntimeError):
    """Raised when a frozen registry's content hash no longer matches."""


@dataclass(frozen=True)
class RegistryEvent:
    id: str
    country: str
    date: date
    domain: str
    source_url: str
    notes: str


def _canonical_hash(events: list[RegistryEvent]) -> str:
    payload = [
        {
            "id": e.id,
            "country": e.country,
            "date": e.date.isoformat(),
            "domain": e.domain,
            "source_url": e.source_url,
            "notes": e.notes,
        }
        for e in events
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_registry(path: str | Path) -> tuple[list[RegistryEvent], str]:
    """Parse the YAML registry → (events, content_hash)."""
    raw = yaml.safe_load(Path(path).read_text()) or {}
    events = [
        RegistryEvent(
            id=str(e["id"]),
            country=str(e["country"]).upper(),
            date=e["date"] if isinstance(e["date"], date) else date.fromisoformat(str(e["date"])),
            domain=str(e["domain"]),
            source_url=str(e["source_url"]),
            notes=str(e.get("notes", "")),
        )
        for e in (raw.get("events") or [])
    ]
    return events, _canonical_hash(events)


def verify_frozen(path: str | Path, expected_hash: str) -> None:
    """Raise RegistryEditedError if the registry content no longer hashes to expected."""
    _, current = load_registry(path)
    if current != expected_hash:
        raise RegistryEditedError(
            f"registry {path} was edited after freezing "
            f"(expected {expected_hash[:12]}…, got {current[:12]}…)"
        )
```

Also create a starter `app/backtest/events.yaml` with a single placeholder-free real example so the loader has something to read (the real ~15–20 events are curated in Task 11):

```yaml
# app/backtest/events.yaml
# Pre-registered events for the lead-time gate. FROZEN once `frozen_hash` is set.
# Each `date` is when the event PHYSICALLY began (best estimate), not when news broke.
events:
  - id: noto-quake-2024-01-01
    country: JP
    date: 2024-01-01
    domain: hazard
    source_url: https://earthquake.usgs.gov/earthquakes/eventpage/us6000m0xl
    notes: M7.5 Noto Peninsula earthquake.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backtest/__init__.py app/backtest/events.yaml app/backtest/registry.py tests/test_backtest_registry.py
git commit -m "feat: #250 frozen event registry + hash guard"
```

---

## Task 6: Backfill source adapters (GDELT narrative + USGS physical)

**Files:**
- Create: `app/backtest/backfill.py`
- Test: `tests/test_backtest_backfill.py`

**Interfaces:**
- Consumes: `Event`, `EventRow`, `upsert_events` from `app.persistence`.
- Produces:
  - `BackfillSource` protocol: `name: str`; `fetch_range(country: str, start: date, end: date) -> list[Event]`.
  - `UsgsBackfill` (physical) and `GdeltBackfill` (narrative) implementations, each injectable with an httpx client for testing.
  - `backfill_event(session, event, sources, *, lookback_days=45, lookahead_days=15) -> int` — fetch each source over `[date−lookback, date+lookahead]`, upsert, return inserted count. Idempotent via the existing `events_source_id_idx` unique constraint.

Why these two first: GDELT is the narrative backbone with deep date-ranged history; USGS exposes `starttime`/`endtime` query params for clean physical history. FIRMS/GDACS adapters are a fast-follow (Task 12).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_backfill.py
from datetime import date

from app.backtest.backfill import backfill_event
from app.backtest.registry import RegistryEvent
from app.db_models import EventRow
from app.models import Category, Event


class _StubSource:
    name = "stub"

    def __init__(self, events):
        self._events = events
        self.calls = []

    def fetch_range(self, country, start, end):
        self.calls.append((country, start, end))
        return self._events


def _event(i):
    return Event(
        source="stub",
        source_event_id=f"stub-{i}",
        occurred_at=date(2024, 1, 1).isoformat() + "T12:00:00+00:00",
        fetched_at=date(2024, 1, 2).isoformat() + "T00:00:00+00:00",
        category=Category.HAZARD,
        keywords=[],
        country="JP",
        payload={},
    )


def test_backfill_inserts_and_is_idempotent(db_session):
    ev = RegistryEvent("jp", "JP", date(2024, 1, 10), "hazard", "http://x", "")
    src = _StubSource([_event(1), _event(2)])

    first = backfill_event(db_session, ev, [src], lookback_days=45, lookahead_days=15)
    db_session.commit()
    assert first == 2
    assert db_session.query(EventRow).count() == 2

    second = backfill_event(db_session, ev, [src], lookback_days=45, lookahead_days=15)
    db_session.commit()
    assert second == 0  # same source_event_ids — no dupes
    assert db_session.query(EventRow).count() == 2


def test_backfill_uses_correct_window(db_session):
    ev = RegistryEvent("jp", "JP", date(2024, 1, 10), "hazard", "http://x", "")
    src = _StubSource([])
    backfill_event(db_session, ev, [src], lookback_days=45, lookahead_days=15)
    country, start, end = src.calls[0]
    assert country == "JP"
    assert start == date(2023, 11, 26)  # 2024-01-10 minus 45 days
    assert end == date(2024, 1, 25)     # plus 15 days
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backtest.backfill'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/backtest/backfill.py
"""Historical backfill for registry events.

For each pre-registered event we pull a window of historical events from
sources that support date-ranged queries, upsert them into the event
store, and let the divergence engine read them like any other rows.

Idempotent: upsert_events relies on the events_source_id_idx unique
constraint, so re-running never duplicates.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from app.backtest.registry import RegistryEvent
from app.models import Event
from app.persistence import upsert_events


class BackfillSource(Protocol):
    name: str

    def fetch_range(self, country: str, start: date, end: date) -> list[Event]: ...


def backfill_event(
    session: Session,
    event: RegistryEvent,
    sources: list[BackfillSource],
    *,
    lookback_days: int = 45,
    lookahead_days: int = 15,
) -> int:
    """Fetch + upsert the historical window for one registry event."""
    start = event.date - timedelta(days=lookback_days)
    end = event.date + timedelta(days=lookahead_days)
    inserted = 0
    for src in sources:
        events = src.fetch_range(event.country, start, end)
        inserted += upsert_events(events, session)
    return inserted
```

Then add the two real adapters in the same file (network code; unit-tested separately against recorded fixtures in Task 6b is overkill — verify by integration in Task 10). Implement `UsgsBackfill` using the USGS FDSN query API (`https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&starttime=…&endtime=…&minmagnitude=2.5`) reusing `app/enrichment/country.country_for` for country tagging, and `GdeltBackfill` using the GDELT 2.0 DOC API date range (`&startdatetime=YYYYMMDD000000&enddatetime=YYYYMMDD235959`). Both follow the `row_to_event` → `Event` pattern from `nasa_firms_fetcher.py`, set `source="usgs-quake"` / `source="gdelt"` so `classify_side` routes them, and return `[]` on any HTTP error (never raise).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_backfill.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backtest/backfill.py tests/test_backtest_backfill.py
git commit -m "feat: #250 historical backfill runner + USGS/GDELT adapters"
```

---

## Task 7: Backtest metrics (lead distribution + false-positive rate)

**Files:**
- Create: `app/backtest/metrics.py`
- Test: `tests/test_backtest_metrics.py`

**Interfaces:**
- Consumes: `DivergenceSeries`, `detect_lead`, `LeadResult`, config `TAU_P`.
- Produces:
  - `EventLead` dataclass: `event_id: str`, `lead_days: int | None`.
  - `GateMetrics` dataclass: `median_lead: float | None`, `pct_events_leading: float`, `n_events: int`, `false_positive_rate: float`, `verdict: str` (`"PASS"`/`"FAIL"`).
  - `lead_for_series(event_id, series) -> EventLead`.
  - `false_positive_rate(series_list, registry_spike_days) -> float` — fraction of physical-spike days (`physical_z ≥ TAU_P`) that are NOT within `MAX_LEAD_LOOKBACK_DAYS` before any registry narrative spike.
  - `summarize(leads, fp_rate) -> GateMetrics` — applies the frozen pass bar: median lead ≥ 1 day on a majority of events.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_metrics.py
from app.backtest.metrics import EventLead, summarize


def test_summarize_passes_when_majority_lead():
    leads = [EventLead("a", 3), EventLead("b", 2), EventLead("c", None)]
    m = summarize(leads, fp_rate=0.1)
    assert m.n_events == 3
    assert m.median_lead == 2.0          # median of [2, 3] (None dropped)
    assert m.pct_events_leading == 2 / 3  # 2 of 3 lead >= 1 day
    assert m.verdict == "PASS"


def test_summarize_fails_when_minority_lead():
    leads = [EventLead("a", 3), EventLead("b", None), EventLead("c", None)]
    m = summarize(leads, fp_rate=0.1)
    assert m.pct_events_leading == 1 / 3
    assert m.verdict == "FAIL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.backtest.metrics'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/backtest/metrics.py
"""Gate metrics: lead distribution + false-positive rate + PASS/FAIL.

The pass bar is frozen here (median lead >= 1 day on a MAJORITY of
registry events, plus a reported false-positive rate). Verdict is
derived, never hand-set.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from app.divergence.config import MAX_LEAD_LOOKBACK_DAYS, TAU_N, TAU_P
from app.divergence.scoring import DivergenceSeries, detect_lead

#: Frozen pass bar.
_MIN_LEAD_DAYS = 1
_MAJORITY = 0.5


@dataclass(frozen=True)
class EventLead:
    event_id: str
    lead_days: int | None


@dataclass(frozen=True)
class GateMetrics:
    median_lead: float | None
    pct_events_leading: float
    n_events: int
    false_positive_rate: float
    verdict: str


def lead_for_series(event_id: str, series: DivergenceSeries) -> EventLead:
    return EventLead(event_id, detect_lead(series).lead_days)


def false_positive_rate(
    series_list: list[DivergenceSeries], registry_narrative_days: set[date]
) -> float:
    """Fraction of physical-spike days not near any registry narrative spike."""
    total = 0
    false = 0
    for series in series_list:
        for i, z in enumerate(series.physical_z):
            if z < TAU_P:
                continue
            total += 1
            day = series.days[i]
            near = any(
                0 <= (n_day - day).days <= MAX_LEAD_LOOKBACK_DAYS
                for n_day in registry_narrative_days
            )
            if not near:
                false += 1
    return false / total if total else 0.0


def summarize(leads: list[EventLead], fp_rate: float) -> GateMetrics:
    valid = [lead.lead_days for lead in leads if lead.lead_days is not None]
    leading = [d for d in valid if d >= _MIN_LEAD_DAYS]
    n = len(leads)
    pct = len(leading) / n if n else 0.0
    median = statistics.median(valid) if valid else None
    passes = (
        median is not None
        and median >= _MIN_LEAD_DAYS
        and pct > _MAJORITY
    )
    return GateMetrics(
        median_lead=median,
        pct_events_leading=pct,
        n_events=n,
        false_positive_rate=fp_rate,
        verdict="PASS" if passes else "FAIL",
    )
```

(`TAU_N` import retained for the false-positive helper's narrative-day callers; if `ruff` flags it unused, drop it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_metrics.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/backtest/metrics.py tests/test_backtest_metrics.py
git commit -m "feat: #250 backtest gate metrics + frozen pass bar"
```

---

## Task 8: Backtest report generator

**Files:**
- Create: `app/backtest/report.py`
- Test: `tests/test_backtest_report.py`

**Interfaces:**
- Consumes: `GateMetrics`, `EventLead`.
- Produces: `render_report(metrics, leads, *, registry_hash, method_version) -> str` (markdown). States verdict in the title line.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_report.py
from app.backtest.metrics import EventLead, GateMetrics
from app.backtest.report import render_report


def test_report_states_verdict_and_events():
    metrics = GateMetrics(
        median_lead=2.0, pct_events_leading=0.66, n_events=3,
        false_positive_rate=0.1, verdict="PASS",
    )
    leads = [EventLead("noto-quake", 3), EventLead("x", None)]
    md = render_report(metrics, leads, registry_hash="abc123", method_version="div.v1")
    assert "PASS" in md
    assert "noto-quake" in md
    assert "div.v1" in md
    assert "abc123"[:8] in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# app/backtest/report.py
"""Render the gate backtest result as a markdown report.

This artifact is the deliverable: the thesis evidence and the sales proof.
It states an explicit PASS/FAIL up front.
"""

from __future__ import annotations

from app.backtest.metrics import EventLead, GateMetrics


def render_report(
    metrics: GateMetrics,
    leads: list[EventLead],
    *,
    registry_hash: str,
    method_version: str,
) -> str:
    median = "n/a" if metrics.median_lead is None else f"{metrics.median_lead:.1f} days"
    lines = [
        f"# Divergence Lead-Time Gate — {metrics.verdict}",
        "",
        f"- Method version: `{method_version}`",
        f"- Registry hash: `{registry_hash[:8]}`",
        f"- Events: {metrics.n_events}",
        f"- Median physical lead: {median}",
        f"- Events leading ≥ 1 day: {metrics.pct_events_leading:.0%}",
        f"- False-positive rate: {metrics.false_positive_rate:.0%}",
        "",
        "## Per-event lead",
        "",
        "| event | lead (days) |",
        "|---|---|",
    ]
    for lead in leads:
        lines.append(f"| {lead.event_id} | {'—' if lead.lead_days is None else lead.lead_days} |")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_report.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backtest/report.py tests/test_backtest_report.py
git commit -m "feat: #250 backtest report generator"
```

---

## Task 9: Backtest runner (CLI entry point)

**Files:**
- Create: `app/backtest/run.py`
- Test: `tests/test_backtest_run.py`

**Interfaces:**
- Consumes: everything above + `daily_side_counts`, `compute_divergence_series`, `session_scope` from `app.db`.
- Produces: `run_backtest(session, registry_path, *, backfill=True, sources=None) -> tuple[GateMetrics, list[EventLead], str]` (returns metrics, leads, rendered markdown). `python -m app.backtest.run` writes the report to `docs/backtest/<registry_hash>-report.md`.

- [ ] **Step 1: Write the failing test** (uses a stub source so no network)

```python
# tests/test_backtest_run.py
from datetime import UTC, datetime, timedelta

from app.backtest.run import run_backtest
from app.db_models import EventRow


def _seed_lead(session, country, narrative_day):
    # physical spike 3 days before a narrative spike, on a flat baseline
    base = narrative_day - timedelta(days=40)
    for i in range(45):
        day = base + timedelta(days=i)
        session.add(EventRow(
            source="usgs-quake", source_event_id=f"p-{country}-{i}",
            occurred_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC),
            category="hazard", keywords=[], country=country, payload={}))
    spike = narrative_day - timedelta(days=3)
    for k in range(60):
        session.add(EventRow(
            source="usgs-quake", source_event_id=f"ps-{country}-{k}",
            occurred_at=datetime(spike.year, spike.month, spike.day, 12, tzinfo=UTC),
            category="hazard", keywords=[], country=country, payload={}))
    for k in range(150):
        session.add(EventRow(
            source="gdelt", source_event_id=f"ns-{country}-{k}",
            occurred_at=datetime(narrative_day.year, narrative_day.month, narrative_day.day, 12, tzinfo=UTC),
            category="geopolitical", keywords=[], country=country, payload={}))


def test_run_backtest_detects_seeded_lead(db_session, tmp_path):
    from datetime import date
    narrative_day = date(2024, 2, 10)
    _seed_lead(db_session, "JP", narrative_day)
    db_session.commit()
    reg = tmp_path / "events.yaml"
    reg.write_text(
        "events:\n"
        "  - id: jp-test\n    country: JP\n    date: 2024-02-07\n"
        "    domain: hazard\n    source_url: http://x\n    notes: seeded\n"
    )
    metrics, leads, md = run_backtest(db_session, reg, backfill=False)
    assert leads[0].lead_days == 3
    assert "Lead-Time Gate" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtest_run.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# app/backtest/run.py
"""Backtest orchestrator: registry → (backfill) → divergence → metrics → report."""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.backtest.backfill import BackfillSource, GdeltBackfill, UsgsBackfill, backfill_event
from app.backtest.metrics import EventLead, GateMetrics, false_positive_rate, lead_for_series, summarize
from app.backtest.registry import load_registry
from app.backtest.report import render_report
from app.divergence.aggregate import daily_side_counts
from app.divergence.config import DIVERGENCE_METHOD_VERSION, MAX_LEAD_LOOKBACK_DAYS, TAU_N
from app.divergence.scoring import compute_divergence_series, detect_lead
from app.db import session_scope

_LOOKBACK = 45
_LOOKAHEAD = 15


def run_backtest(
    session: Session,
    registry_path: str | Path,
    *,
    backfill: bool = True,
    sources: list[BackfillSource] | None = None,
) -> tuple[GateMetrics, list[EventLead], str]:
    events, registry_hash = load_registry(registry_path)
    if sources is None:
        sources = [GdeltBackfill(), UsgsBackfill()]

    series_list = []
    leads: list[EventLead] = []
    narrative_days = set()
    for ev in events:
        if backfill:
            backfill_event(session, ev, sources, lookback_days=_LOOKBACK, lookahead_days=_LOOKAHEAD)
            session.commit()
        start = ev.date - timedelta(days=_LOOKBACK)
        end = ev.date + timedelta(days=_LOOKAHEAD)
        days, physical, narrative = daily_side_counts(session, ev.country, start, end)
        series = compute_divergence_series(days, physical, narrative)
        series_list.append(series)
        leads.append(lead_for_series(ev.id, series))
        nd = detect_lead(series).narrative_spike_day
        if nd is not None:
            narrative_days.add(nd)

    fp = false_positive_rate(series_list, narrative_days)
    metrics = summarize(leads, fp)
    md = render_report(metrics, leads, registry_hash=registry_hash, method_version=DIVERGENCE_METHOD_VERSION)
    return metrics, leads, md


def main() -> int:
    registry_path = Path("app/backtest/events.yaml")
    with session_scope() as session:
        metrics, _, md = run_backtest(session, registry_path, backfill=True)
    _, registry_hash = load_registry(registry_path)
    out = Path("docs/backtest") / f"{registry_hash[:8]}-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"verdict={metrics.verdict} report={out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_run.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/backtest/run.py tests/test_backtest_run.py
git commit -m "feat: #250 backtest runner + CLI entry point"
```

---

## Task 10: Integration smoke run against real history (manual gate dry-run)

**Files:**
- Create: `docs/backtest/.gitkeep`
- Modify: `docs/architecture/06-validation.md` (add a "Lead-time gate" subsection linking the spec + how to run)

**Interfaces:** none (operational task).

- [ ] **Step 1:** Bring up the dev stack (`docker compose up -d postgres redis`), run migrations (`alembic upgrade head`).
- [ ] **Step 2:** Run the backtest with backfill against the starter single-event registry to confirm the network adapters and end-to-end wiring work:

Run: `python -m app.backtest.run`
Expected: prints `verdict=… report=docs/backtest/<hash>-report.md`; a report file exists. (Verdict is not the real gate yet — registry has one event.)

- [ ] **Step 3:** Eyeball the report; confirm USGS + GDELT rows landed for the window (`/events/coverage` or a quick count query).
- [ ] **Step 4:** Document the run command in `docs/architecture/06-validation.md`.
- [ ] **Step 5: Commit**

```bash
git add docs/backtest/.gitkeep docs/architecture/06-validation.md
git commit -m "docs: #250 lead-time gate dry-run + validation notes"
```

---

## Task 11: Curate + freeze the real event registry

**Files:**
- Modify: `app/backtest/events.yaml`
- Test: `tests/test_backtest_registry_frozen.py`

**Interfaces:** none new.

- [ ] **Step 1:** Curate ~15–20 events across domains + regions + time (hazard, conflict, market-shock-with-physical-precursor). For each: `id`, `country` (alpha-2), `date` = physical onset, `source_url`, `notes`. Spread regions so no single country dominates.
- [ ] **Step 2: Write the freeze test** (records the frozen hash; fails if the file is later edited):

```python
# tests/test_backtest_registry_frozen.py
from app.backtest.registry import load_registry, verify_frozen

# Paste the hash printed by load_registry after curation (Step 3).
FROZEN_HASH = "REPLACE_WITH_REAL_HASH"


def test_registry_is_frozen():
    verify_frozen("app/backtest/events.yaml", FROZEN_HASH)
```

- [ ] **Step 3:** Compute the hash and paste it into the test:

Run: `python -c "from app.backtest.registry import load_registry; print(load_registry('app/backtest/events.yaml')[1])"`
Copy the 64-char hash into `FROZEN_HASH`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtest_registry_frozen.py -v`
Expected: PASS. (From now on, any edit to `events.yaml` breaks this test — intended.)

- [ ] **Step 5: Commit**

```bash
git add app/backtest/events.yaml tests/test_backtest_registry_frozen.py
git commit -m "feat: #250 curate + freeze lead-time event registry"
```

---

## Task 12: VIIRS flaring fetcher

**Files:**
- Create: `app/sources/viirs_flaring_fetcher.py`
- Modify: `app/fetcher_registry.py` (register `viirs-flaring`)
- Modify: `app/settings.py` (add `viirs_token` setting, mirroring `firms_map_key`)
- Modify: `env.example` (document the token var)
- Test: `tests/test_viirs_flaring_fetcher.py`

**Interfaces:**
- Produces: `ViirsFlaringFetcher(Fetcher)` with `name="viirs-flaring"`, `queue="slow"`; `parse_csv_body(body, *, fetched_at) -> list[Event]`; events with `source="viirs-flaring"`, `category=Category.HAZARD`, `keywords=["viirs","flaring"]`, country via `country_for(lat, lon)`.

Model the fetcher on `app/sources/nasa_firms_fetcher.py` (pull, CSV parse, `country_for`, no-op when token missing, never raise on bad rows). VIIRS Nightfire (VNF) source: NOAA/EOG VIIRS nightfire products; parse lat/lon/temperature columns. `severity` = normalized radiant heat (clamp to 0..1).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_viirs_flaring_fetcher.py
from datetime import UTC, datetime

from app.models import Category
from app.sources.viirs_flaring_fetcher import parse_csv_body

_SAMPLE = (
    "latitude,longitude,date,temp_bb,rh\n"
    "29.95,47.68,2024-03-01,1800,1.2\n"
    ",,2024-03-01,1800,1.2\n"  # malformed: no coords -> skipped
)


def test_parse_extracts_valid_rows_only():
    events = parse_csv_body(_SAMPLE, fetched_at=datetime(2024, 3, 2, tzinfo=UTC))
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "viirs-flaring"
    assert ev.category == Category.HAZARD
    assert ev.lat == 29.95
    assert "flaring" in ev.keywords


def test_parse_empty_body_returns_empty():
    assert parse_csv_body("", fetched_at=datetime(2024, 3, 2, tzinfo=UTC)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_viirs_flaring_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation** — mirror `nasa_firms_fetcher.py`: `_radiant_to_severity`, `hash_event_id`, `row_to_event`, `parse_csv_body`, `ViirsFlaringFetcher.fetch()` (no-op if `not settings.viirs_token`), `archive_path()`. Register in `fetcher_registry.py`:

```python
from app.sources.viirs_flaring_fetcher import ViirsFlaringFetcher
# ... in _REGISTRY:
    "viirs-flaring": ViirsFlaringFetcher(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_viirs_flaring_fetcher.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/sources/viirs_flaring_fetcher.py app/fetcher_registry.py app/settings.py env.example tests/test_viirs_flaring_fetcher.py
git commit -m "feat: #250 VIIRS flaring fetcher"
```

---

## Task 13: AIS stream collector (aggregation + failsafes)

**Files:**
- Create: `app/sources/aisstream_collector.py`
- Modify: `app/settings.py` (add `aisstream_api_key`)
- Modify: `env.example`
- Test: `tests/test_aisstream_collector.py`

**Interfaces:**
- Produces:
  - `aggregate_positions(messages, *, bucket) -> list[Event]` — pure: group AIS position messages by region bucket + time bucket → one summary `Event` per (region, bucket) with `source="aisstream"`, `category=Category.TRACKING`, vessel count in `payload`.
  - `AisStreamCollector` class: `run()` connects the WebSocket, buffers, flushes via `aggregate_positions`; `_handle_disconnect()` reconnect-with-backoff. Disabled (no-op) when `not settings.aisstream_api_key`.

Forward-live only — excluded from the historical backtest (`classify_side("aisstream") == "physical"` so the live signal still counts).

- [ ] **Step 1: Write the failing test** (pure aggregation only — no live socket)

```python
# tests/test_aisstream_collector.py
from datetime import UTC, datetime

from app.models import Category
from app.sources.aisstream_collector import aggregate_positions

_BUCKET = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def _msg(lat, lon, mmsi):
    return {"lat": lat, "lon": lon, "mmsi": mmsi}


def test_aggregate_counts_vessels_per_region():
    msgs = [_msg(26.5, 56.3, 1), _msg(26.6, 56.4, 2), _msg(1.3, 103.8, 3)]  # 2 Hormuz, 1 Malacca
    events = aggregate_positions(msgs, bucket=_BUCKET)
    counts = {e.payload["region"]: e.payload["vessel_count"] for e in events}
    assert counts["hormuz"] == 2
    assert counts["malacca"] == 1
    assert all(e.source == "aisstream" and e.category == Category.TRACKING for e in events)


def test_aggregate_ignores_positions_outside_watched_regions():
    events = aggregate_positions([_msg(0.0, 0.0, 9)], bucket=_BUCKET)
    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_aisstream_collector.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation** — define `_WATCHED_REGIONS` (name → bbox: hormuz, suez, malacca, bosphorus), `_region_for(lat, lon)`, pure `aggregate_positions`, and the `AisStreamCollector` with `websockets`-based `run()` + bounded `collections.deque(maxlen=…)` buffer + exponential backoff reconnect. The collector counts distinct MMSI per region per bucket. Run as a standalone worker (`python -m app.sources.aisstream_collector`), not a Celery pull task. No new dependency if `websockets` is already present; otherwise flag for approval before adding.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_aisstream_collector.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add app/sources/aisstream_collector.py app/settings.py env.example tests/test_aisstream_collector.py
git commit -m "feat: #250 AIS stream collector with region aggregation + failsafes"
```

---

## Task 14: Source-health status fields (backend)

**Files:**
- Modify: `app/db_models.py` (extend `IngestHealthRow`)
- Modify: `app/tasks.py` (`_record_success` / `_record_failure` write `status`, `last_error`; add `_record_rate_limited`)
- Modify: `app/api.py` (`_ingest_health_dict` surfaces new fields)
- Create: `migrations/versions/<rev>_ingest_health_status.py`
- Test: `tests/test_tasks.py` (extend), `tests/test_api.py` (extend)

**Interfaces:**
- Produces: `IngestHealthRow.status` (`str`, default `"online"`), `IngestHealthRow.last_error` (`str | None`), `IngestHealthRow.rate_limit_used` (`int | None`), `IngestHealthRow.rate_limit_max` (`int | None`). `/ingest-health` dict gains `status`, `last_error`, `rate_limit_used`, `rate_limit_max`.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_tasks.py
from datetime import date
from app.db_models import IngestHealthRow
from app.tasks import _record_failure, _record_success


def test_record_success_sets_status_online(db_session):
    _record_success(db_session, source="usgs-quake")
    db_session.commit()
    row = db_session.get(IngestHealthRow, ("usgs-quake", date.today()))
    assert row.status == "online"


def test_record_failure_sets_status_and_error(db_session):
    _record_failure(db_session, source="usgs-quake", exc=RuntimeError("boom"))
    db_session.commit()
    row = db_session.get(IngestHealthRow, ("usgs-quake", date.today()))
    assert row.status == "failing"
    assert "boom" in row.last_error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tasks.py -k status_or_error -v` (or run the two new test names)
Expected: FAIL — `IngestHealthRow` has no `status`.

- [ ] **Step 3: Write minimal implementation** — add the four columns to `IngestHealthRow` (nullable / defaulted so existing rows are valid); set `row.status = "online"` + clear `last_error` in `_record_success`; set `row.status = "failing"` + `row.last_error = str(exc)` in `_record_failure`. Generate the Alembic migration (`alembic revision --autogenerate -m "ingest_health status fields"`) and hand-verify it only adds columns. Extend `_ingest_health_dict` with the new keys.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tasks.py tests/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/db_models.py app/tasks.py app/api.py migrations/versions/ tests/test_tasks.py tests/test_api.py
git commit -m "feat: #250 source-health status + error fields"
```

---

## Task 15: Source-health panel (frontend)

**Files:**
- Create: `osint-frontend/components/SourceHealthPanel.tsx`
- Modify: `osint-frontend/lib/apiClient.ts` (add `fetchIngestHealth`)
- Modify: `osint-frontend/lib/types.ts` (add `IngestHealthRow` type)
- Modify: `osint-frontend/components/DashboardSection.tsx` (mount the panel)
- Test: `osint-frontend/__tests__/SourceHealthPanel.test.tsx`

**Interfaces:**
- Consumes: `/ingest-health` JSON (`source, day, status, last_success, last_error, rate_limit_used, rate_limit_max`).
- Produces: `SourceHealthPanel` rendering one row per source (status dot + relative last-pull + rate-limit bar + error tooltip), grouped physical / narrative / market.

- [ ] **Step 1: Write the failing test**

```tsx
// osint-frontend/__tests__/SourceHealthPanel.test.tsx
import { render, screen } from "@testing-library/react"
import { SourceHealthPanel } from "@/components/SourceHealthPanel"

const rows = [
  { source: "usgs-quake", day: "2026-06-29", status: "online", last_success: "2026-06-29T12:00:00Z", last_error: null, rate_limit_used: null, rate_limit_max: null },
  { source: "gdelt", day: "2026-06-29", status: "failing", last_success: null, last_error: "timeout", rate_limit_used: null, rate_limit_max: null },
]

test("renders a row per source with status", () => {
  render(<SourceHealthPanel rows={rows} />)
  expect(screen.getByText("usgs-quake")).toBeInTheDocument()
  expect(screen.getByText("gdelt")).toBeInTheDocument()
  expect(screen.getByTestId("status-gdelt")).toHaveAttribute("data-status", "failing")
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd osint-frontend && pnpm test SourceHealthPanel`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation** — `SourceHealthPanel({ rows })` presentational component: group rows by `classifySide(source)` (mirror the backend partition in a small TS helper in `lib/types.ts`), render name + a `data-status` dot + relative last-pull (reuse existing time-formatting util) + rate-limit bar when `rate_limit_max != null` + `title={last_error}` tooltip. Add `fetchIngestHealth()` to `apiClient.ts` following the `fetchScores` pattern, and a `useIngestHealth()` SWR hook (60s refresh) consumed where `DashboardSection` mounts the panel.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd osint-frontend && pnpm test SourceHealthPanel`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add osint-frontend/components/SourceHealthPanel.tsx osint-frontend/lib/apiClient.ts osint-frontend/lib/types.ts osint-frontend/components/DashboardSection.tsx osint-frontend/__tests__/SourceHealthPanel.test.tsx
git commit -m "feat: #250 source-health panel (frontend)"
```

---

## Task 16: Run the real gate + record the verdict

**Files:**
- Create: `docs/backtest/<hash>-report.md` (generated)
- Modify: `POSITIONING-SCRATCH.md` (record the verdict under the v2 pivot section) — note: this file is local/untracked; if it stays untracked, instead append the verdict to `docs/architecture/06-validation.md`.

**Interfaces:** none (operational).

- [ ] **Step 1:** Ensure the live pipeline (or backfill) has populated history for the frozen registry windows. Run with backfill: `python -m app.backtest.run`.
- [ ] **Step 2:** Read the generated `docs/backtest/<hash>-report.md`. Note `verdict`, `median_lead`, `pct_events_leading`, `false_positive_rate`.
- [ ] **Step 3:** Record the verdict + numbers in `docs/architecture/06-validation.md`. State plainly: PASS → proceed to Phase 2 (feed/alerting/overlay); FAIL → documented kill, treat as portfolio/thesis showcase.
- [ ] **Step 4: Commit**

```bash
git add docs/backtest/ docs/architecture/06-validation.md
git commit -m "docs: #250 lead-time gate verdict + numbers"
```

---

## Self-Review

**Spec coverage:**
- Divergence engine (spec §Component 1) → Tasks 1–4. ✓
- Backtest harness: registry + hash guard (§Component 2) → Task 5, 11; backfill → Task 6, 12-extension; metrics → Task 7; report → Task 8; runner → Task 9. ✓
- Hard constraint "AIS excluded from historical backtest" → backfill sources are USGS+GDELT (+FIRMS/GDACS follow-on); AIS only in live partition (Task 13). ✓
- VIIRS flaring sensor (§Component 3) → Task 12. ✓
- AIS collector + failsafes (§Component 3) → Task 13. ✓
- Source-health extend (§Component 4) → Task 14 (backend) + Task 15 (frontend). ✓
- Pass bar frozen + honest PASS/FAIL (§success criteria) → Task 7 (`summarize`), Task 16 (run + record). ✓
- Testing strategy (§Testing) → every task is TDD; integration smoke = Task 10, real gate = Task 16. ✓

**Known follow-on (not blocking the gate verdict):** FIRMS + GDACS backfill adapters broaden the physical side beyond USGS; add as a Task-6 sibling once the USGS+GDELT path is green. The gate is provable with one physical (USGS) + one narrative (GDELT) source; more sources strengthen but don't gate it.

**Placeholder scan:** registry `FROZEN_HASH` in Task 11 is intentionally filled during execution (computed from real curated data, not inventable ahead of time); all code steps contain real implementations.

**Type consistency:** `DivergenceSeries`, `LeadResult`, `RegistryEvent`, `EventLead`, `GateMetrics` names + fields are consistent across Tasks 3–9. `classify_side` signature stable across Tasks 1, 4, 15.
```
