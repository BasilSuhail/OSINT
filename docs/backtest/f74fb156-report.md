# Divergence Lead-Time Gate — FAIL

- Method version: `div.v4`
- Registry hash: `f74fb156`
- Pass bar: median lead ≥ 1 day AND more than 50% of events leading

## Sample

- Registry events: 22
- Scored (narrative series available): 20
- Produced a lead measurement: 9
- Excluded as unscorable: 2

## Result

- Median physical lead: -1.0 days
- Events leading ≥ 1 day: 20%
- False-positive rate: 53%
- **Chance rate (narrative series rotated): 20%**
- Observed minus chance: +0%

- Null median lead: -1.0 days
- **Permutation p-value: 0.501** — share of chance runs producing a lead at least this long

The chance rate re-runs the same detector with each event's narrative series rotated, which breaks its timing against the physical side while preserving its values and autocorrelation. A pass rate only means something measured against it.

## Per-event lead

| event | lead (days) |
|---|---|
| mx-20260717-m6 | -2 |
| ph-20260714-m6.2 | 1 |
| jp-20260703-m6.1 | — |
| id-20260703-m6.2 | — |
| af-20260627-m6.1 | — |
| ve-20260624-m7.5 | — |
| ru-20260619-m6.6 | — |
| cn-20260616-m6.3 | — |
| cu-20260608-m6.1 | — |
| ph-20260608-m6.5 | — |
| it-20260601-m6.2 | — |
| cl-20260531-m6 | — |
| jp-20260515-m6.7 | 3 |
| id-20260514-m6.2 | — |
| ph-20260504-m6 | -2 |
| ph-20260404-m6 | -7 |
| id-20260402-m6.3 | 17 |
| pe-20260401-m6 | 1 |
| vu-20260330-m7.3 | -1 |
| jp-20260326-m6.5 | -17 |

## Excluded (no narrative series)

These events were not counted in either direction. A fetch failure is not evidence against the claim.

| event | reason |
|---|---|
| pg-20260713-m6.4 | PG 2026-05-01..2026-07-28: HTTP 429 |
| nz-20260610-m6 | NZ 2026-03-29..2026-06-25: no daily rows parsed — an empty window is not evidence of a quiet one |
