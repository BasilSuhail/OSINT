# Source data audit — design

**Issue:** #580
**Date:** 2026-07-22

## Problem

#576 §5 named one failure shape behind five separate defects shipped in a day:
the system confidently producing numbers from data it never read. #577 and #579
added two more within the same domain. Every one was found because a person
happened to ask what a column was actually made of. Nothing asks automatically.

The specific defects, for calibration:

- **#574** — VIIRS confidence `l`/`n`/`h` did not parse; 536,097 rows stored
  `severity = NULL`; the composite skips null severity.
- **#577** — the #574 fix was forward-only, so 462,643 stored rows kept their
  NULLs and the composite still read 13.7% of its hazard input.
- **#579** — the value #574 wired in is detection confidence, not intensity, and
  runs non-monotonic to fire radiative power.
- **FRED** — `severity = None` on every row behind a docstring asserting the
  composite normalises it. The composite contains no such code.
- **Polymarket** — `country = None`, and `composite/task.py` filters
  `country IS NOT NULL`, so all 109 rows drop silently.

None of these crashed. Each produced a confident number.

## Why a variance threshold does not work

Measured across the live database, severity is near-degenerate almost everywhere:

| source | rows | distinct severity | top value % | std |
|---|---:|---:|---:|---:|
| opensky-adsb | 58,793 | 1 | 100.0 | 0.0000 |
| gdacs | 616 | 3 | 98.4 | 0.0577 |
| abuse-ch-urlhaus | 20,664 | 2 | 93.9 | 0.0478 |
| nasa-firms | 73,454 | 3 | 83.6 | 0.1424 |

Every RSS row in the system carries 0.35 or 0.65 — 13,431 and 6,291 — a
two-level flag rather than the sentiment score the column implies. OpenSky is
58,793 rows of exactly 0.0.

`severity` is declared as a float in `[0,1]` and is, nearly everywhere, a two or
three level categorical. A rule that flags low variance therefore fires on
almost every source and carries no information.

## Approach

Check measured shape against a **declared expectation** per source. The
declaration is the deliverable: it forces intent to be written down, and makes
the absence of an answer a visible failure rather than silence.

```python
@dataclass(frozen=True)
class Expectation:
    severity: Literal["continuous", "graded", "none"]
    country:  Literal["required", "optional", "none"]
    feeds_composite: bool
```

`graded` is a legitimate answer. GDACS having three alert levels is plausibly
correct. The audit does not object to a coarse scale — it objects to a coarse
scale nobody declared, and to a source declaring `continuous` while emitting two
values.

## Components

Follows the existing package shape (`app/coverage`, `app/divergence`).

- **`app/audit/expectations.py`** — the declared table. `rss-*` resolves as a
  family with explicit per-source overrides. Pure data plus a lookup function.
- **`app/audit/checks.py`** — pure functions over a stats record. No DB access,
  so the whole rule set is testable against literals.
- **`app/audit/stats.py`** — `SourceStats`, the measured shape. Data only.
- **`app/audit/run.py`** — two grouped queries over the whole table, assembles
  stats, applies checks, returns findings. Severity spread is computed in Python
  from grouped value counts rather than in SQL, so the arithmetic is identical on
  SQLite and Postgres.
- **`scripts/data_audit.py`** — prints findings grouped by source.

## Data flow

```
events table
  -> run.gather_stats(session)     two grouped queries -> SourceStats per source
  -> expectations.for_source(name) declared Expectation
  -> checks.run_all(stats, exp)    -> list[Finding]
  -> scripts/data_audit.py         prints
```

`SourceStats` carries: rows, severity non-null count, distinct severity count,
top-value share, severity std, min/max severity, country non-null count,
earliest and latest `occurred_at`, and rows passing the composite's real filter.

## Checks

| check | fires when | catches today |
|---|---|---|
| `severity_coverage` | declared `continuous`/`graded`, non-null share below 99% | FRED (0%), FIRMS pre-#577 (13.7%) |
| `severity_shape` | declared `continuous`, distinct <= 3 or top value > 90% | RSS, urlhaus, GDACS |
| `severity_constant` | std == 0 with more than one row, any declaration | OpenSky |
| `severity_absent_but_present` | declared `none`, yet severity is set | drift |
| `country_coverage` | declared `required`, non-null share below 99% | — |
| `composite_reachability` | `feeds_composite` true, zero rows pass the real filters | Polymarket |
| `occurred_at_plausible` | any row dated in the future, or all rows older than retention | the #571 evergreen class |

Thresholds are module constants, not literals, so tuning does not mean editing
rules.

`composite_reachability` re-expresses the composite's own filter
(`category IN (...) AND severity IS NOT NULL AND country IS NOT NULL`) rather
than importing it. That is deliberate duplication: the check must fail when the
composite's filter and a source's data drift apart, which it cannot do if it
derives both sides from the same expression.

## Error handling

A source present in `events` with no declared expectation is itself a finding
(`undeclared_source`) rather than an exception — a new fetcher must not be able
to enter the system unnoticed. A declared source with zero rows is reported as
`no_data`, not an error, since paused sources (#160, #155) legitimately have none.

## Testing

Hermetic SQLite via the existing `db_session` fixture. `checks.py` is pure, so
each rule is tested against a constructed `SourceStats` with no database at all.
`run.py` gets a small seeded integration test confirming stats assembly and that
an undeclared source is reported.

The audit is report-only and always exits 0. It is a tool, not a gate.

## Scope

**In:** the module, the checks, the declared table, the script, tests.

**Out:** fixing anything the audit finds. Every finding is an existing defect
with its own issue or in need of one. A scheduled job persisting verdicts, and
a CI structural test asserting every registered fetcher is declared, are natural
follow-ups deliberately excluded — CI runs hermetic SQLite with no live data
(`tests/conftest.py`), so a CI gate could only check the table is self-consistent,
never that FRED's severity is 0%.

## Expected first run

A long finding list, including sources nobody has questioned. That is the
intended outcome, not a regression.
