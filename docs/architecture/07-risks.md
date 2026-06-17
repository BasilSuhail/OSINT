# 07 — Risks and Mitigations

Honest risk register. Each entry: what could go wrong, how likely, how bad, what mitigates it. Sorted by combined likelihood × impact within each section.

- [Hardware risks](#hardware-risks)
- [Data risks](#data-risks)
- [Methodology risks](#methodology-risks)
- [Schedule risks](#schedule-risks)
- [Operational risks](#operational-risks)
- [Legal and policy risks](#legal-and-policy-risks)
- [Using this register](#using-this-register)

---

## Hardware risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **USB-SATA bridge corrupts data under load** | Medium | Catastrophic (silent bitrot) | btrfs RAID1 with checksums detects it; only buy JMS583 / ASM2362 enclosures; monthly `btrfs scrub` cron |
| **Both HDDs fail simultaneously** | Low | Catastrophic | Nightly `restic` to B2 / R2 off-site; monthly restore-smoke-test verifies the backup is real |
| **Pi 5 thermal throttle stops ingestion mid-backfill** | Medium | Moderate (just slower) | Active cooler mandatory; backfill runs scheduled overnight; throttle alerts via `/admin/health` |
| **Power outage during write** | Medium | Low (Postgres WAL recovers, btrfs CoW survives) | UPS optional but recommended; document recovery procedure in `docs/operations/` once written |
| **Pi 5 SD card wears out** | Low (over 10-week thesis window) | Moderate (boot lost; data safe on HDDs) | Boot from SSD if available; otherwise A2-rated SD; nightly `dd` of root partition to HDD |

---

## Data risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Upstream API schema change breaks fetcher** | High (over months) | Moderate (gap in series) | Raw archive lets re-parse; plausibility checks catch silently; CI runs fetchers against recorded fixtures weekly to catch field drift |
| **GDELT zip publishes late or partial** | High | Low (next batch backfills) | Idempotent dedup means re-fetching is safe; missing windows logged in `ingest_health` |
| **ACLED rate-limits academic accounts mid-backfill** | Medium | High (eval blocked) | Backfill in early Week 5, well before evaluation Week 9; spread fetches over days, not minutes; cache aggressively |
| **FinBERT model card disappears from HuggingFace** | Low | Low (auxiliary signal only) | Pin model checkpoint into `/mnt/data/models/finbert/`; document checkpoint hash. If lost, drop FinBERT entirely — it is auxiliary per the multi-modal frame, not anchor. |
| **Ingestion bug pollutes hot store with bad rows** | Medium | Moderate | Replay path documented; deletes are batched and auditable; pg snapshot before housekeeping runs |
| **Country panel selection biases evaluation results** | Medium | High (thesis credibility) | Country panel is fixed before any composite output is examined and committed to `config/country_panel.yaml`; LOOCV sensitivity test catches single-country dominance; panel stratified across geo / market / hazard event density |
| **Hazard label leakage** — a P5 label correlates with the hazard input it was derived from | Medium | High (P5 score artificially inflated) | P5 requires "sustained composite stress in following 30 days" filter (not raw hazard occurrence) — see `methodology.md` Step 2; per-domain ablation in Step 9 tests whether the hazard-only baseline already saturates P5 |
| **Market data coverage gaps for emerging markets** | High | Moderate (P4 weak for EM countries) | Country panel stratified to include EM countries with adequate market-data coverage; document EM-coverage limitation explicitly in thesis Discussion |

---

## Methodology risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Composite underperforms single-domain baselines** | Medium | Survivable (negative result is honest, defendable, and explicit in protocol) | Pre-registered protocol means this counts as a legitimate finding; thesis Discussion frames it constructively (what would multi-modal composites need to do differently). Per `05-originality.md` Claim 2 already commits to reporting this honestly. |
| **Examiner challenges JRC handbook fidelity** | Low | Moderate | Every JRC step is referenced in the Methods chapter; choices are justified by literature, not by what made the numbers look better |
| **Multiple-testing across 9 baselines × 3 horizons × 4 targets** | High | Moderate | Holm-Bonferroni correction reported alongside raw p-values; primary claim is on the any-positive target only, per-domain subtasks reported as secondary; ablations as exploratory, not confirmatory |
| **Look-ahead bias via Pi-collected data leaking into eval** | Low (architecturally prevented) | Catastrophic | Test window (2023-2024) lives only in Parquet; Pi-collected 2025-26 data is explicitly outside the formal evaluation per `methodology.md` Step 3; section 06 pre-eval checklist includes a label-leakage CI grep |
| **Reviewer says "your composite is just GDELT in a hat"** | Medium | Moderate | Sensitivity Step 9.5 (source ablation, B3 / B4 / B5) directly answers this; geo-only, market-only, hazard-only baselines are mandatory in the results table |
| **Hazard-as-exogenous-shock interpretation challenge** | Medium | Moderate | The methodology explicitly accepts that hazards are exogenous and tests whether the JRC normalisation filters out isolated hazard events — this is the rationale for the `P5` "sustained composite stress" filter, not raw hazard occurrence |
| **Label-source bias toward US / developed markets** | High | Moderate | NBER recessions are US-only; IMF currency-crisis dataset and equity drawdowns cover EM but with different conventions; explicitly document the asymmetric label-coverage in Discussion |

---

## Schedule risks

10-week thesis window starting Week 2 of the term, hard deadline 28 August.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Pi setup / RAID tuning eats 2+ weeks** | Medium | High (everything else compresses) | Time-box hardware to one weekend; if blocked by Week 3, fall back to single 4TB drive + restic-only redundancy and revisit RAID post-thesis |
| **Layer 3 ambitions consume thesis-core time** | High (personal preference) | Catastrophic to thesis grade | **Hard rule: no Layer 3 worker is committed after end of Week 7.** Strict scope guard, documented here as the load-bearing rule of the project. Layer 3 PRs after Week 7 are politely closed without merge. |
| **Thesis report scope creep — Tier 2 ends up in main body instead of appendix** | High | Moderate-to-High (word-budget burn) | Thesis Methods + Results chapters cover **Tier 1 only** (three composite domains + ground truth). Tier 2 (Layer 3) gets a single Discussion paragraph + appendix table. README documents this; supervisor draft review (Week 8) explicitly checks this. |
| **Marco unavailable for protocol lock-in meeting** | Low | High (evaluation cannot start) | Email Marco at end of Week 1 with the locked protocol draft and three meeting slots in Weeks 2-3; flag the dependency in the `methodology.md` open questions |
| **Group presentation prep collides with build phase** | Certain | Moderate | Presentation slides 22 June fall in the build window; build pace dropped by ~3 days, plan around it |
| **Viva prep collides with thesis writing tail** | High | High | First thesis draft to Marco by Week 8 (mid-August), leaving Weeks 9-10 for viva rehearsal and report polish |

---

## Operational risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Pi loses Tailscale connectivity from outside** | Low | Low | Watchdog systemd service restarts `tailscaled`; manual SSH over local LAN as fallback |
| **Pushover spam from a stuck composite** | Medium | Low (annoying) | `notifications` table dedup-key, rate-limit at 1 per country per 6 h, hard kill switch in `/admin/notifications/disable` |
| **Disk fills due to raw archive growth** | Medium (over months) | Moderate | Retention policy: raw archive 90 d hot, then off-site only; `/admin/health` warns at 80% disk; monthly `du` audit |
| **Frontend build on dev mac drifts from Pi runtime** | Medium | Low | Same Node major version pinned; dev-mac build runs in CI to catch divergence |

---

## Legal and policy risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **ACLED ToS breach via inappropriate redistribution** | Low (with discipline) | High | ACLED data stored only in Parquet, never exposed on public dashboard endpoints, never committed to git; thesis appendix cites ACLED per their citation policy |
| **GDELT redistribution interpreted as derivative work** | Low | Low | Only aggregate scores are shown publicly; raw GDELT rows never exposed; standard CC-BY attribution in thesis |
| **EM-DAT redistribution** | Low | Low | EM-DAT is freely available for academic use with citation; stored as Parquet, cited in thesis, not redistributed in raw form on the public dashboard |
| **University plagiarism check flags borrowed code blocks** | Low (with discipline) | Catastrophic | Every external code snippet (e.g. SGP4 propagator) is cited inline and referenced in `references.bib`; nothing copy-pasted without attribution |
| **Telegram OSINT scraping (Layer 3 idea) violates ToS** | High if attempted | Moderate | Telegram scraping is **not in scope** for the thesis; if added post-thesis, run with explicit consent / public channels only |
| **Personal data (faces, plate numbers) ingested accidentally** | Low | Catastrophic (GDPR) | None of the Tier-1 sources contain personal data; Layer-3 CCTV ideas are deferred and would require their own DPIA before implementation |

---

## Using this register

This file is not a prediction. It is a checklist for the regular project-management self-review (every two weeks, written into the supervisor meeting notes). For each entry, the question is: is the mitigation still in place, and is the likelihood / impact still accurate? Update this file when answers change.

Two entries are **load-bearing for the thesis grade**:

1. **Layer 3 ambitions consume thesis-core time** — Week-7 hard-stop, documented here, no Layer 3 commits after that point.
2. **Thesis report scope creep** — Methods + Results chapters cover Tier 1 only; Tier 2 lives in the appendix.

If either of those slips, the grade does. Everything else is recoverable.
