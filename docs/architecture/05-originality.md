# 05 — Originality Defense

The system takes inspiration from [Shadowbroker](https://github.com/BigBodyCobain/Shadowbroker). This file documents how it is **independent work**, defendable against the three flavours of "you just copied that" charge an examiner can level.

- [The three charges](#the-three-charges)
- [Defense 1 — Literal code copy](#defense-1--literal-code-copy)
- [Defense 2 — Concept / architecture copy](#defense-2--concept--architecture-copy)
- [Defense 3 — Shallow wrapper accusation](#defense-3--shallow-wrapper-accusation)
- [What the thesis claims, precisely](#what-the-thesis-claims-precisely)
- [Provenance trail](#provenance-trail)

---

## The three charges

| # | Charge | Risk |
|---|---|---|
| 1 | **Literal code copy** — "you cloned Shadowbroker and renamed it" | Low if discipline holds, catastrophic if it slips |
| 2 | **Concept / architecture copy** — "this is Shadowbroker with the serial numbers filed off" | Medium — the architecture overlap is real, must be honestly framed |
| 3 | **Shallow wrapper accusation** — "you just glue together a few APIs, no research contribution" | Highest — this is what kills weak final-year projects |

All three are addressed below.

---

## Defense 1 — Literal code copy

**Rule**: zero source files from Shadowbroker. No reference to its code while writing the system. The repository's `git log` is the proof.

Operational discipline:

- Repo is initialised by Basil, MIT-licensed, public.
- Shadowbroker is referenced in two places only: this file and [`01-overview.md`](01-overview.md) under "What this system is NOT".
- Citation in the thesis: "Architectural inspiration was drawn from publicly visible OSINT systems including Shadowbroker (BigBodyCobain, 2025). No source code was used."
- Pre-emptive provenance: every PR's commit history is public. An examiner who runs MOSS or `git log --follow` will see the system grew from scratch, not from a clone.

This is the easiest charge to defeat. The cost of defeating it is just discipline.

---

## Defense 2 — Concept / architecture copy

The honest answer: yes, some architectural ideas are shared with Shadowbroker. Tiered polling cadences, per-source workers, a map-based dashboard — none of these are novel, and Shadowbroker is one of several systems that demonstrates them. The defense is **what the system does with the architecture**, which is different in ways that matter to an examiner:

| Dimension | Shadowbroker | This system |
|---|---|---|
| **Primary output** | A live geospatial dashboard for an operator/analyst | A multi-modal composite stress index per country, with the dashboard as the secondary surface |
| **Consumer** | Real-time situational awareness ("what is happening right now") | Research artefact ("does the multi-modal composite discriminate later instability events better than the best single-domain baseline") |
| **Methodology spine** | Engineering-first; no published evaluation methodology | OECD/JRC 10-step composite indicator handbook, pre-registered evaluation against a hybrid ACLED + market-crisis + EM-DAT ground truth |
| **Evaluation** | None published | AUROC / AUPR / Brier / lead-time vs nine baselines (random, persistence, base-rate, three single-domain, three composite variants) — see [`../methodology.md`](../methodology.md) |
| **Scope of feeds in core claim** | 60+ feeds, all surfaced | Three input domains in the composite (market, geopolitical, hazard). Other feeds are explicitly Layer 3 dashboard, not claimed as contribution |
| **Mesh / decentralised layer** | InfoNet mesh, agent channel, Sovereign Shell governance | None. Out of scope. |
| **Implementation choices** | FastAPI + APScheduler in-process, SQLite + in-memory layers | FastAPI + Celery + Redis + Postgres + Parquet (worker isolation, queue durability, replayable cold archive). Schema in [`04-schema.md`](04-schema.md). |

The architecture overlap (FastAPI, MapLibre, Pi-deployable) is consistent with these being **standard, sensible OSINT system choices**, not Shadowbroker-specific inventions. The thesis cites the OECD/JRC handbook, the ViEWS conflict-forecasting paper (Hegre et al. 2019), and the CEWS field review (Davies et al. 2023) as its actual lineage.

**One-line defense**: "Shadowbroker was a visible example of a working OSINT stack on commodity hardware. The architecture of this system was chosen for thesis reproducibility, Pi resource constraints, and the multi-modal composite's specific data-flow needs, not by reference to Shadowbroker's source."

---

## Defense 3 — Shallow wrapper accusation

This is the dangerous one. "You wired together a few free APIs into a dashboard, the work is the libraries, where is your contribution?" The defense rests entirely on the thesis methodology, not on the engineering. The engineering is the substrate; the contribution is what is built on top.

The five claims the thesis makes and defends:

1. **A multi-modal composite stress index defined via the OECD/JRC 10-step methodology over three heterogeneous input domains** (market, geopolitical, hazard). Each JRC step is documented: theoretical framework → indicator selection → imputation policy → multivariate analysis → normalisation choice → weighting scheme → aggregation rule → uncertainty analysis → sensitivity analysis → results interpretation. The composite is not "average of three scores" — it is a derived, justified, evaluated construct.
2. **A pre-registered evaluation protocol against a hybrid ground truth** (ACLED conflict events + NBER / IMF / FRED market-crisis dates + EM-DAT / GDACS hazard-induced disruption). [`../methodology.md`](../methodology.md) is locked with Marco at the first supervisory meeting, before any composite output is examined. AUROC, AUPR, Brier score, lead-time distribution, all reported with documented baselines (B0 random, B1 persistence, B2 base rate, B3 geo-only, B4 market-only, B5 hazard-only, B6 composite equal weights, B7 composite PCA weights, B8 composite geometric mean). Negative findings count: if the composite does not beat **each** single-domain baseline on the primary any-positive target, the thesis says so.
3. **Honest treatment of literature critiques.** GDELT tone validity (Wang 2025, Wallace 2014), FinBERT predictive R² ≈ 0.01 for downstream price prediction (Yang 2024), hazard-as-exogenous-shock interaction risk — these are documented in [`../methodology.md`](../methodology.md) Part B and the thesis explicitly does not claim the system overcomes them. The contribution is the multi-modal composite + evaluation, not a defense of any single feed.
4. **A replayable, time-honest evaluation harness.** The cold Parquet archive ([`02-storage.md`](02-storage.md#hot--cold-split)) means evaluation can be re-run on the locked feature set without re-fetching. The split is Train 2015-2021 / Val 2022 / Test 2023-2024 with the Pi-collected 2025-26 data used as a demonstration of the live system, **not** as part of the formal evaluation. This decouples thesis quality from Pi uptime.
5. **Industrial-application analysis.** Marco's brief asks for "possible industrial applications" in the final report. The thesis identifies five (logistics, insurance, energy, NGO/journalist, strategic-risk teams) and maps each to which Tier-1 / Tier-2 feeds matter to them. This is independent analysis, not generic boilerplate.

The shallow-wrapper charge is defeated by being able to point at any of these five and say "this is the research contribution; the engineering exists to support it." If an examiner is still unconvinced after Claim 2, the project genuinely has a problem — but the project has not been designed to fail Claim 2.

---

## What the thesis claims, precisely

To avoid overclaim:

- **Claims**: that a multi-modal composite of market, geopolitical, and hazard signals, weighted via JRC handbook procedure, achieves AUROC and AUPR on country-month any-positive instability prediction that improves on the best single-domain baseline by a margin reported with confidence intervals. Per-domain subtasks are reported as secondary.
- **Does not claim**: to predict specific events; to outperform ViEWS or other established forecasting systems; that the system would generalise to feeds it was not evaluated on; that the Pi-collected live data is part of the formal evaluation; that the auxiliary FinBERT signal is a market predictor.

This is the bar the thesis is written to. It is achievable, it is defensible, and it is original to this project.

---

## Provenance trail

For an examiner who wants to verify:

- **Code**: `git log --all --pretty=fuller` on the OSINT repo shows every commit, every author, every date.
- **Design**: this `docs/architecture/` directory is committed before any application code is written. The spec precedes the implementation in the git history.
- **Methodology**: [`../methodology.md`](../methodology.md) Part A is locked (v1.0) before evaluation harness coding begins. Subsequent changes are versioned, not silently overwritten.
- **Literature**: [`../methodology.md`](../methodology.md) Part B lists the sources actually read, with citation snippets. These are the lineage, not Shadowbroker.
- **Decisions**: every scope shift (e.g. the re-anchor from finance-led to multi-modal) is captured as its own PR with a written rationale referencing the PX5901/02 guidelines, the JRC handbook, or the relevant literature — not invented at write-up time.

The provenance trail is the thesis's defense against every flavour of the copy charge. It is also the reason every section of this spec lives on a branch with a PR, not as a local draft.
