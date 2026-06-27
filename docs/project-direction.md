# Project Direction — What This Is, Who It Is For, and Where It Can Go

This document exists because the project had drifted toward a vague "Palantir for me"
description. That framing is not useful. It is too broad, too loaded, and too easy to defend badly.

The right framing is narrower and stronger:

**This project is a self-hosted OSINT analyst workbench for lawful public data.**
It ingests, deduplicates, enriches, scores, and visualises public signals so one operator can
understand emerging risk faster.

This is the product answer to the professor's three questions:

- **So what?** It turns fragmented public data into usable situational awareness.
- **Why does it matter?** Important signals are spread across feeds, formats, and time scales.
  Humans miss them when they have to scan everything manually.
- **What is it solving?** It solves the problem of signal overload, duplication, and weak
  cross-source fusion.

If you want the short version for conversations:

> An off-grid OSINT intelligence workspace that turns public data into ranked, explainable early warning.

---

## 1. The honest answer: what you are building

You are not building Palantir.

You are building a smaller, sharper system that borrows one useful idea from Palantir's public
image: a single analyst-facing layer that connects disparate data into a decision workflow.
The difference is that your system is:

- self-hosted
- public-source only
- explainable
- auditable
- thesis-driven
- usable by one operator without a large organisation behind it

That makes it a research product, a personal operations tool, and an open-source platform candidate.
It is not a generic surveillance platform.

The current repo already points to that shape:

- `README.md` frames the system as a multi-modal early-warning dashboard.
- `docs/methodology.md` defines the evaluation loop and ground truth.
- `docs/architecture-spec.md` locks the pipeline and storage plan.
- The frontend shows the actual operator experience: map, globe, filters, alerts, source views.

So the project is already more concrete than the fear suggests.

---

## 2. The actual problem it solves

The problem is not "lack of data".
The problem is "too much low-quality, disconnected data".

A real analyst workflow has these constraints:

- news is duplicated across outlets
- hazard feeds use different geometry and severity conventions
- market, weather, cyber, and geopolitical signals do not line up cleanly
- timestamps are messy
- the same event appears in multiple feeds under different names
- a human cannot keep all of that in working memory

This project is solving that by giving the operator:

1. a canonical event model
2. source-specific enrichment
3. deduplication and ranking
4. country-level scoring
5. a map / globe / dashboard for triage

That is not "surveillance" in the broad, loaded sense.
It is operational sense-making over lawful public data.

---

## 3. Who the customer is

You need a real customer profile, even if the first customer is you.

### Primary customer

The primary customer is a **single operator** who needs a private, always-on public-intelligence console.

That operator could be:

- you
- a researcher
- a journalist
- a crisis analyst
- a resilience or NGO analyst
- a small risk team

### Secondary customers

Secondary customers are small teams that need:

- private deployment
- no cloud dependence
- explainable outputs
- full data control
- lower cost than enterprise platforms

### Not the customer

This is not trying to serve:

- casual consumers
- mass-market news readers
- enterprise procurement by default
- agencies that want hidden black-box scoring with no audit trail

That last point matters. If the customer is "everyone", the product gets blurry and undeliverable.
If the customer is "one operator who needs lawful public risk monitoring", the product becomes buildable.

---

## 4. The most defensible product thesis

The strongest product thesis is:

**Public signals can be fused into a practical early-warning layer that is more useful than any single feed alone.**

That is a research claim and a product claim at the same time.

It is defensible because the literature and the repo already point in the same direction:

- situational awareness systems work when they help humans make sense of fast-moving events
- social and open data are useful precisely because they are high-volume and near real-time
- analyst tools need interactive geovisualisation and user control, not just raw model output
- OSINT communities already use public data to detect and discuss real-world events

Relevant research:

- [Snyder et al. 2019](https://arxiv.org/abs/1909.07316) on situational awareness and social media analytics for first responders
- [Karimzadeh et al. 2019](https://arxiv.org/abs/1910.05441) on geovisual analytics and interactive machine learning for situational awareness
- [Niu et al. 2024](https://arxiv.org/abs/2409.01052) on OSINT Tweets about the Russo-Ukrainian war
- [Niu et al. 2025](https://arxiv.org/abs/2508.03599) on OSINT versus misinformation in that same space
- [CERES 2026](https://arxiv.org/abs/2603.09425) as a recent example of a multi-stream early-warning system

My inference from this literature is simple:

**The winning product is not a huge model. It is a workflow that compresses attention and preserves evidence.**

That is the right target for your project.

---

## 5. What the project is not

This project should not try to become:

- a blanket surveillance product
- a dark intelligence platform
- a consumer social feed
- a generic AI chatbot
- a fake "Palantir clone"
- a featureless data lake

If you keep the product too broad, you lose three things:

- the thesis becomes fuzzy
- the software becomes hard to finish
- the open-source story becomes impossible to explain

The repo already has enough breadth. The job now is to keep that breadth legible.

---

## 6. Why this can become something people care about

To be worth the effort, the project needs more than functionality.
It needs a reason to exist after the thesis ends.

The durable value is:

- local-first control
- lawful public data only
- explainable scoring
- operational UX instead of model hype
- reproducible evaluation
- a clear split between thesis core and dashboard breadth

That combination is rare.

Most tools do one of these well:

- ingest a lot of data
- score risk
- show a map
- run locally
- provide thesis-grade evaluation

Very few do all of them together in a single, comprehensible system.

That is where the project can become hard to replace.

---

## 7. How this becomes a sustainable app

The sustainable version is not "more features".
It is a tighter product boundary.

### Core product

The core product should stay:

- public-source only
- self-hosted
- evidence-linked
- alertable
- country and event aware
- easy to audit

### Sustainable extensions

Extensions that make sense later:

- better deduplication across news sources
- source reliability weighting
- stronger event clustering
- analyst annotations
- saved investigations
- alert rules
- exportable reports
- shareable case packets

### Extensions that are risky

These are tempting but should stay controlled:

- broad identity tracing
- hidden private datasets
- opaque model output with no evidence trail
- "surveillance AI" positioning

The sustainable product is the one that can be trusted, inspected, and maintained.

---

## 8. How this can help with jobs or a PhD

This project can support both, if it is framed correctly.

### For jobs

It demonstrates:

- full-stack engineering
- data engineering
- streaming and queue systems
- geospatial UI work
- evaluation discipline
- product judgement

That is a credible portfolio for:

- software engineering
- data engineering
- applied ML engineering
- risk / intelligence tooling
- geoanalytics products

### For a PhD

It becomes research-grade if you keep:

- a pre-registered methodology
- a clear evaluation target
- an ablation story
- a reproducible data pipeline
- a negative-result path

In other words, the PhD value is not "I built a dashboard".
It is:

**I tested whether fused public signals improve early warning over single-source baselines, with a reproducible system and explicit failure modes.**

That is a legitimate research contribution.

---

## 9. What the project should optimize for next

If the goal is long-term value, the next priorities should be:

1. **Pick one primary wedge**
   - Recommended wedge: country instability / public risk early warning
   - Keep hazards, markets, and news as evidence streams feeding that wedge

2. **Make the thesis core obvious**
   - one composite score
   - one evaluation protocol
   - one set of baselines
   - one answer to "did it help?"

3. **Keep Layer 3 as product breadth**
   - use it to make the app worth opening every day
   - do not let it dilute the thesis

4. **Make the system inspectable**
   - show why a score moved
   - show which sources contributed
   - show what got filtered and why

5. **Make it runnable offline**
   - that is a major differentiator
   - it matters for trust, reproducibility, and autonomy

---

## 10. The one-sentence customer and product statement

If you need to answer quickly, use this:

**This is a self-hosted OSINT early-warning workbench for a single operator or small team that needs lawful public-data situational awareness, explainable scoring, and a clear audit trail.**

If you need the thesis version:

**This project tests whether combining heterogeneous public signals into one explainable risk score improves early warning over single-source monitoring.**

If you need the founder version:

**I am building a private analyst console that turns public noise into actionable risk awareness.**

---

## 11. References

- [Snyder et al. 2019](https://arxiv.org/abs/1909.07316) - situational awareness from social media analytics
- [Karimzadeh et al. 2019](https://arxiv.org/abs/1910.05441) - geovisual analytics for situational awareness
- [Niu et al. 2024](https://arxiv.org/abs/2409.01052) - OSINT dataset on the Russo-Ukrainian war
- [Niu et al. 2025](https://arxiv.org/abs/2508.03599) - OSINT vs misinformation on the same topic
- [CERES 2026](https://arxiv.org/abs/2603.09425) - modern multi-stream early-warning system
- [Palantir Gotham](https://www.palantir.com/platforms/gotham/)
- [Palantir Foundry](https://www.palantir.com/platforms/foundry/)
- [Palantir AIP](https://www.palantir.com/platforms/aip/)
- [Wired overview of Palantir](https://www.wired.com/story/palantir-what-the-company-does)

These references are not a claim that your project should copy Palantir.
They are evidence that the market already values data integration, analyst workflows, and operational decision support.

