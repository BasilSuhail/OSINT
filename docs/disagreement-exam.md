# The Disagreement Exam — pre-registered (WS-B step 4, #374)

*Declared 2026-07-09, before the first disagreement prediction was issued.
Changes to anything below are versioned amendments, never edits.*

## The hypothesis

Cross-country narrative divergence on the same physical events rises **before**
confirmed instability. If contested tellings precede contested situations, a
country's divergence exposure should carry early-warning information about
next months' ground-truth labels.

## Why this is a forward exam, not a backtest

The divergence signal is built from RSS story clusters (WS-A) — data that
exists only from **July 2026** onward. There is no archive to backfill, so the
composite's 2015–2022 evaluation window cannot apply. Instead the exam uses
the WS-E forward-journal discipline: predictions are logged before outcomes
are knowable, graded when windows mature, and the track record accumulates in
public. This is slower but strictly more honest — nothing here can overfit a
past it has never seen.

## The signal (fixed)

For country *c* and issuance month *M*:

```
exposure(c, M) = Σ_p mean_divergence(p) · n_stories(p) / Σ_p n_stories(p)
```

over all country pairs *p* in `disagreement_pairs` for month *M* that contain
*c* (method `disagreement-v1.0`, #370/#372). The exposure is already in
[0, 1] and is used as the prediction score **directly** — no rescaling, no
calibration knobs, nothing to tune later.

## The protocol (fixed)

| element | value |
|---|---|
| journal source | `disagreement` |
| method version | `disagreement-v1.0` |
| horizons | 1, 3, 6 months (same as the composite journal) |
| ground truth | labels v1.1 (P1–P3 any-positive), same coverage windows as WS-E |
| hindcast guard | inherited — only current-month exposures are ever issued |
| immutability | inherited — a logged prediction is never rewritten |
| running metric | Brier score per horizon, on the /scoreboard automatically |
| headline metric | AUROC per horizon, computed **only after** ≥ 100 graded disagreement predictions spanning ≥ 3 distinct issuance months; published whatever it says |

## Known limitations, declared now

- **Coverage skew:** ~90 % of stories are single-country tellings and produce
  no divergence signal; exposure exists only for countries whose stories are
  co-told across origins. The exam therefore tests the signal *where it
  exists*, not for every country.
- **Wording, not stance:** `disagreement-v1.0` measures divergence of TF-IDF
  headline centroids — different *words*, which includes different angles and
  languages of emphasis but is not a tone/stance measure. A future
  sentiment-based `disagreement-v2` would be a new method version graded
  separately.
- **Origin granularity:** outlet origin is a single country per feed (#368);
  multi-national outlets carry their headquarters' flag.

## Amendment log

- *(none yet)*
