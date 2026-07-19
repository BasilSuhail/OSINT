# Divergence Lead-Time Gate — PASS

- Method version: `div.v3`
- Registry hash: `f74fb156`
- Pass bar: median lead ≥ 1 day AND more than 50% of events leading

## Sample

- Registry events: 22
- Scored (narrative series available): 11
- Produced a lead measurement: 7
- Excluded as unscorable: 11

## Result

- Median physical lead: 4.0 days
- Events leading ≥ 1 day: 64%
- False-positive rate: 31%

> **Caution — the measured sample is too small to interpret.** The median above is computed over 7 lead measurement(s), not over 22 registry events. A median of two numbers is not a distribution, and a lead landing at the edge of the 60-day window is more likely detector boundary behaviour than signal. Treat this run as a pipeline check, not as evidence for or against the claim.

## Per-event lead

| event | lead (days) |
|---|---|
| ph-20260714-m6.2 | 1 |
| af-20260627-m6.1 | 4 |
| ru-20260619-m6.6 | 1 |
| cu-20260608-m6.1 | — |
| ph-20260608-m6.5 | — |
| cl-20260531-m6 | 4 |
| jp-20260515-m6.7 | 3 |
| ph-20260504-m6 | 8 |
| id-20260402-m6.3 | — |
| vu-20260330-m7.3 | — |
| jp-20260326-m6.5 | 5 |

## Excluded (no narrative series)

These events were not counted in either direction. A fetch failure is not evidence against the claim.

| event | reason |
|---|---|
| mx-20260717-m6 | MX 2026-05-05..2026-08-01: HTTP 429 |
| pg-20260713-m6.4 | PG 2026-05-01..2026-07-28: HTTP 429 |
| jp-20260703-m6.1 | JP 2026-04-21..2026-07-18: HTTP 429 |
| id-20260703-m6.2 | ID 2026-04-21..2026-07-18: HTTP 429 |
| ve-20260624-m7.5 | VE 2026-04-12..2026-07-09: HTTP 429 |
| cn-20260616-m6.3 | CN 2026-04-04..2026-07-01: HTTP 429 |
| nz-20260610-m6 | NZ 2026-03-29..2026-06-25: HTTP 429 |
| it-20260601-m6.2 | IT 2026-03-20..2026-06-16: HTTP 429 |
| id-20260514-m6.2 | ID 2026-03-02..2026-05-29: HTTP 429 |
| ph-20260404-m6 | PH 2026-01-21..2026-04-19: HTTP 429 |
| pe-20260401-m6 | PE 2026-01-18..2026-04-16: HTTP 429 |
