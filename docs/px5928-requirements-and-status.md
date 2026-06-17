# PX5928 — Requirements, Scope & Where You Stand

*Companion to `master-plan.md`. That document is the "how to build it". This one is the "what's actually required, by whom, and where do things currently stand". Read this when you need to check whether something is mandatory, optional, or purely your own ambition.*

---

## 1. Where you are right now

- Allocated to "Open-Source Intelligence and Early-Warning Dashboard", supervised by Marco Thiel
- Group of 3 for the **oral presentation only**. Per PX5901/02 guidelines (slides 5-6): "Thesis: individual work. Each student needs to work individually on their own thesis"; "Oral presentation: teamwork." Group-presentation lane assignments do **not** constrain individual thesis scope.
- Group presentation structure agreed: shared intro/outro, ~2-2.5 min individual sections each, total 15 min + 10 min Q&A
- Your individual focus (re-anchored): **multi-modal OSINT composite stress index** across three input domains — geopolitical events (GDELT), market signals (yfinance + FRED + optional FinBERT), hazards (USGS + GDACS + NASA FIRMS). Evaluated against hybrid ground truth (ACLED + market-crisis dates + EM-DAT disruption labels). An earlier draft anchored the thesis on finance alone; finance is now one of three composite inputs, not the headline.
- Technical master plan written (`master-plan.md`): Pi setup, four-module architecture (A market + B geo + C hazard + D composite + E eval), ten-week timeline
- Architecture spec started under `docs/architecture/` (sections 01-03 merged to main; sections 04-07 pending)
- **Not yet started**: Pi setup itself, any code, GDELT ingestion, anything in the master plan's Section 3 onward
- **Upcoming**: presentation slides due 22 June 5pm, group presentation 23-26 June, thesis due 28 August, viva 7-11 September

---

## 2. What the project wants from you, by source

### 2.1 Marco's brief (the actual project proposal)

This is what he wrote when proposing the project, paraphrased close to his original wording:

You're designing and building a small-scale open-source intelligence and early-warning dashboard. It collects public data streams, extracts relevant signals, visualises them, and generates warnings when predefined patterns or thresholds are detected. **It must not depend on a single data source.**

His suggested starting points, named explicitly: GDELT (Event Database and Global Knowledge Graph), ShadowBroker, World Monitor, and Pushover for phone notifications. Suggested indicator domains: geopolitical instability, environmental hazards, infrastructure disruption, **supply-chain disruption, market stress**, "or other publicly observable developments."

**His six core tasks**:

1. **Data ingestion** — timestamped records from one or more public sources (GDELT, RSS, hazard feeds, market feeds, transport feeds, etc.)
2. **Data processing** — clean, deduplicate, geocode where needed, transform into a common event table with fields: **time, location, source, category, severity, keywords, confidence**
3. **Signal detection** — warning indicators via event-count spikes, abnormal sentiment/tone changes, regional clustering, theme-frequency changes, or **co-occurrence of multiple risk signals**
4. **Dashboard** — maps, time series, event tables, filters, warning scores
5. **Notification extension** (optional) — Pushover or similar, for high-priority warnings to a phone
6. **Evaluation** — test retrospectively on selected historical events or known time periods; discuss **detection delay, false positives, missed events, and data limitations**

**His expected deliverables**:

- A working data-ingestion pipeline
- A structured event database or stored event files
- A dashboard with maps, time series, filters, and warning indicators
- Optionally, a phone-notification module
- A documented GitHub repository
- A final report covering data sources, methods, warning logic, evaluation, limitations, and **possible industrial applications**

**His framing of value** (worth quoting because it sets expectations and is a great line for your Introduction/Conclusion): the point isn't perfect prediction, it's building a transparent system that detects early signals, reduces manual monitoring effort, and supports human decision-making under uncertainty.

**His stated industrial relevance**: logistics companies, energy companies, insurers, public-sector bodies, NGOs, journalists, supply-chain managers, strategic-risk teams. (Note how directly this maps onto your own freelance target list.)

### 2.2 The University (PX5901/02/PX5928 course-wide requirements)

These apply to every Data Science project regardless of topic:

- **Assessment split**: oral presentation (mandatory, 0% of grade) / thesis (65%) / viva (35%)
- **Thesis structure**, 4,000-word main report (excluding abstract, references, figures/tables and captions, appendix): Title → Abstract (~300 words) → Introduction → Data → Methods → Results → Conclusion & Discussion → References → Appendix
- **Supplementary material**: no length limit, must include well-commented, runnable code, referenced from the main report
- **Key dates**: presentation slides 22 June 5pm, presentations 23-26 June, thesis 28 August, viva 7-11 September
- **Plagiarism**: standard university policy, cite everything, including data sources and code you build on
- **First draft to supervisor**: send well before the deadline for feedback, this is on you to schedule with Marco

### 2.3 Your group (negotiated among the three of you)

- Shared intro covering: what "OSINT/early-warning dashboard" means, why it matters, common data sources (GDELT mentioned)
- Each person presents their individual angle for ~2-2.5 minutes
- Shared close: how the individual approaches connect, next steps
- Your slot (re-anchored): **multi-modal OSINT composite** with three input domains and hybrid ground truth. Presented as the methodology contribution within the shared umbrella. Mirrors the thesis frame, so there is no scope-expansion between June presentation and August thesis.
- Group-presentation lane is independent of the thesis (per university guidelines). Even if the group conversation continues to treat your slot as "finance lens," the thesis is yours alone to scope and write.

### 2.4 You (the personal layer)

Everything in `master-plan.md` beyond the four core modules, the Pi infrastructure choices, the HomeForge integration question, the decade roadmap, is **your own addition**, made because it serves your career goals, not because anyone requires it. The good news, established above, is that this layer sits *on top of* Marco's brief rather than alongside it. Building it properly doesn't distract from the academic requirement, it largely *is* the academic requirement, just built with more care and a longer horizon than a typical student project.

The one place to stay disciplined: don't let the personal ambition (HomeForge integration, additional modules beyond A-D, polish on the public-facing dashboard) consume time that should go toward the 4,000-word report, the evaluation methodology, and the literature comparison. Those are 65% + 35% of your grade and have a hard deadline. The extra modules don't.

---

## 3. The actual scope, three layers

**Layer 1, the floor (Marco's minimum for "this is a valid project")**: ingestion from at least two independent public sources, a common event table, at least one signal-detection method, a dashboard with maps/time-series/filters, a written evaluation against historical events, a documented repo. No Pi required, no Pushover required (it's explicitly optional), this could technically be done on a laptop with a SQLite file.

**Layer 2, your thesis build (Modules A-E from the master plan)**: market signals (yfinance + FRED + optional FinBERT) + GDELT (deduplicated, CAMEO-filtered, Goldstein-weighted) + hazards (USGS + GDACS + NASA FIRMS), a multi-modal composite stress index per JRC handbook methodology, Pushover alerting, pre-registered evaluation against hybrid ground truth (ACLED + NBER + IMF currency-crisis + EM-DAT). This is comfortably "strong project" territory per Marco's own description: three independent input domains (exceeds "not only one"), a principled composite (directly answers "signal detection" with multi-modal fusion), and a real retrospective evaluation against documented event labels.

**Layer 3, the decade roadmap**: everything in Section 9 of the master plan, plus HomeForge integration, plus any public-facing/monetisation work. Doesn't affect the grade. Doesn't have a deadline. Genuinely valuable, but Layer 1 and 2 come first, always.

---

## 4. The literal checklist

| Deliverable | Required by | Status |
|---|---|---|
| Project allocation | University | Done |
| Group presentation structure | Group | Agreed |
| Architecture spec sections 01-03 | You | Merged to main |
| Architecture spec sections 04-07 | You | Pending |
| Presentation slides | University (22 Jun 5pm) | Not started |
| Pi 5 + 2x4TB btrfs RAID1 hardware | You (Layer 2 infrastructure) | Not started |
| Module A (market signals) | You | Not started |
| Module B (GDELT) | Marco's brief, Layer 1 minimum | Not started |
| Module C (hazards, promoted to composite) | You | Not started |
| Module D (multi-modal composite, JRC) | Thesis core | Not started |
| Module E (evaluation harness) | Thesis core | Not started |
| Common event table schema | Marco's brief, explicit | Spec'd in `architecture/04-schema.md` (pending) |
| Signal detection method | Marco's brief, Layer 1 minimum | Spec'd (Module D + composite) |
| Dashboard with maps/time series/filters | Marco's brief, Layer 1 minimum | Not started |
| Pushover notification | Marco's brief, optional | Not started |
| Retrospective evaluation (pre-registered) | Marco's brief, explicit | Protocol in `evaluation-protocol.md` v1.0 (locks with Marco before Week 4) |
| Documented GitHub repo | Marco's brief + University | In progress (this repo) |
| 4,000-word report | University | Not started |
| First draft to Marco | University (schedule with him) | Not yet scheduled |

---

## 5. Open questions for Marco

Worth raising at a supervisory meeting, ideally the first one:

- Does he have specific historical events or time periods in mind for the retrospective evaluation, or is that entirely your choice? (He proposed the evaluation method, he may have examples in mind, e.g. a known conflict escalation, a market shock, a major earthquake, that would make a clean case study.)
- For the group: does he expect three genuinely separate systems that happen to share a presentation, or is there value in designing the common event table schema *once*, collaboratively, so all three modules are interoperable from day one? (This could be raised lightly, doesn't need to become a coordination burden on you.)
- Given the four-module scope (A-D), is there a risk of the 4,000-word limit being too tight to cover all of it properly, or is the expectation that breadth goes in the appendix/supplementary material and the main report focuses on the methodology and evaluation in depth?
- Is Pushover a hard suggestion or just an example, any notification mechanism acceptable as long as it demonstrates the "notification extension" task?

---

## 6. One-line summary

Marco asked for roughly what you already wanted to build, at a slightly smaller scale, with a specific evaluation methodology (retrospective testing against real events) that rewards exactly the thing your Pi-based, always-on architecture is best at: accumulating real data over time. The master plan's Modules A-D are your Layer 2. Everything else is yours, on your own timeline.
