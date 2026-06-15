# PX5928 — Requirements, Scope & Where You Stand

*Companion to `master-plan.md`. That document is the "how to build it". This one is the "what's actually required, by whom, and where do things currently stand". Read this when you need to check whether something is mandatory, optional, or purely your own ambition.*

---

## 1. Where you are right now

- Allocated to "Open-Source Intelligence and Early-Warning Dashboard", supervised by Marco Thiel
- Group of 3 (Data Science / Business Management students), each taking an individual focus within the shared project umbrella
- Group presentation structure agreed: shared intro/outro, ~2-2.5 min individual sections each, total 15 min + 10 min Q&A
- Your individual focus: financial/market risk module, building on your existing Market Terminal pipeline
- Technical master plan written (`master-plan.md`): Pi setup, four-module architecture, ten-week timeline
- **Not yet started**: Pi setup itself, porting any code, GDELT ingestion, anything in the master plan's Section 3 onward
- **Upcoming**: presentation slides due 22 June, group presentation 23-26 June, thesis due 28 August, viva 7-11 September

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
- Your slot: financial/market risk, framed as one of the indicator domains under the shared umbrella

### 2.4 You (the personal layer)

Everything in `master-plan.md` beyond the four core modules, the Pi infrastructure choices, the HomeForge integration question, the decade roadmap, is **your own addition**, made because it serves your career goals, not because anyone requires it. The good news, established above, is that this layer sits *on top of* Marco's brief rather than alongside it. Building it properly doesn't distract from the academic requirement, it largely *is* the academic requirement, just built with more care and a longer horizon than a typical student project.

The one place to stay disciplined: don't let the personal ambition (HomeForge integration, additional modules beyond A-D, polish on the public-facing dashboard) consume time that should go toward the 4,000-word report, the evaluation methodology, and the literature comparison. Those are 65% + 35% of your grade and have a hard deadline. The extra modules don't.

---

## 3. The actual scope, three layers

**Layer 1, the floor (Marco's minimum for "this is a valid project")**: ingestion from at least two independent public sources, a common event table, at least one signal-detection method, a dashboard with maps/time-series/filters, a written evaluation against historical events, a documented repo. No Pi required, no Pushover required (it's explicitly optional), this could technically be done on a laptop with a SQLite file.

**Layer 2, your thesis build (Modules A-D from the master plan)**: financial sentiment + GDELT + disaster/climate feeds, a composite index using co-occurrence of multiple risk signals (his words, almost exactly what Module D does), Pushover alerting, evaluation against real historical events using your accumulated data. This is comfortably "strong project" territory per his own description, three independent sources (exceeds "not only one"), a principled composite score (directly answers "signal detection"), and a real evaluation with real data because the Pi has been running for weeks.

**Layer 3, the decade roadmap**: everything in Section 9 of the master plan, plus HomeForge integration, plus any public-facing/monetisation work. Doesn't affect the grade. Doesn't have a deadline. Genuinely valuable, but Layer 1 and 2 come first, always.

---

## 4. The literal checklist

| Deliverable | Required by | Status |
|---|---|---|
| Project allocation | University | Done |
| Group presentation structure | Group | Agreed |
| Presentation slides | University (22 Jun) | Not started |
| Pi setup | You (infrastructure for Layer 2) | Not started |
| Module A (financial) ported | You | Not started |
| Module B (GDELT) | Marco's brief, Layer 1 minimum | Not started |
| Module C (disaster/climate) | You, exceeds Layer 1 | Not started |
| Common event table schema | Marco's brief, explicit | Not started |
| Signal detection method | Marco's brief, Layer 1 minimum | Not started (Module D covers this) |
| Dashboard with maps/time series/filters | Marco's brief, Layer 1 minimum | Not started |
| Pushover notification | Marco's brief, optional | Not started |
| Retrospective evaluation | Marco's brief, explicit | Depends on accumulated data, start ingestion ASAP |
| Documented GitHub repo | Marco's brief + University | Not started |
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
