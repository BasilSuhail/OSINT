# OSINT World Monitor — Positioning & Go-To-Market (scratch)

> Local, gitignored strategy memo. Date: 2026-06-28. Opinionated on purpose.
> Goal: decide WHO this is for, WHAT the real need is, and the ONE selling factor
> worth pivoting around — before writing any more features.

---

## 0. TL;DR (read this if nothing else)

- **What you actually built:** a self-hosted, zero-cost, multi-domain OSINT fusion
  engine + live world map. It ingests 16 free public feeds across 6 domains
  (hazards, geopolitics, news, cyber, markets, flight-tracking) and fuses them
  into a **per-country composite stress index** with convergence detection.
- **You are NOT Palantir.** Palantir sells integration of the *customer's own*
  classified/proprietary data + people. You have no customers' data, no services
  arm, no security clearance, no sales motion. Don't cosplay it.
- **The honest archetype you're closest to:** a **lightweight, self-hostable
  Dataminr/Factal/Samdesk** ("real-time event detection + situational awareness")
  — but your *wedge* is the opposite of theirs: **sovereign / on-prem / no-cloud /
  no-subscription-data**, plus **cross-domain fusion** (a composite index), which
  the incumbents mostly don't do or hide behind enterprise pricing.
- **Sharpest single selling factor (recommendation):**
  > **"Sovereign situational awareness you run yourself — every public early-warning
  > signal on one map, fused into a country risk score, no cloud and no per-seat
  > data subscription."**
  Wedge customer: **corporate/NGO security & duty-of-care teams** who need a
  common operating picture but can't or won't pay Dataminr's ~$100k+/yr or send
  their travelers'/sites' locations to a US SaaS.

---

## 1. What this *is* — honest capability inventory

Strip the thesis framing. As a product it does five things:

1. **Aggregates** 16 free public feeds with no API keys / no paid data:
   - **Hazards:** GDACS (multi-hazard, real footprints), USGS (quakes + ShakeMap),
     NASA FIRMS (active fire), EONET (storms/volcanoes w/ tracks).
   - **Geopolitical:** GDELT (CAMEO-coded global events).
   - **News:** 25 RSS wires (BBC/Reuters/AlJazeera/regional), de-duped into stories.
   - **Cyber:** abuse.ch (URLhaus, Feodo) threat feeds.
   - **Markets / macro:** yfinance drawdowns, FRED, Polymarket prediction odds.
   - **Tracking:** OpenSky ADS-B (live flights), UK Police crime.
2. **Normalises** everything to one event schema (lat/lon, severity, category,
   country, payload) — the genuinely hard, unsexy part.
3. **Fuses** into a **per-country composite stress / instability index (CII)** —
   the thesis claim: a composite of heterogeneous domains beats any single domain
   at flagging later instability. Plus **geographic convergence** (3+ categories
   co-occurring in a cell = alert).
4. **Visualises**: dark world map (real terrain, real disaster footprints + tracks,
   per-type icons, click-to-expand) + a 3D globe (satellites, day/night, NEOs) +
   a scroll-down analyst dashboard (news desk, severity histogram, CII trends).
5. **Runs anywhere, offline:** one folder of data, Postgres+Redis+Celery, designed
   to live for years on a Raspberry Pi. **No cloud, no vendor, no subscription.**

**The crown jewels (defensible work):** (a) the normalisation layer across messy
heterogeneous feeds, (b) the composite index methodology, (c) the local-first /
off-grid architecture, (d) the polished real-geometry hazard map.

---

## 2. The market & the incumbents (who already sells "situational awareness")

| Tier | Players | What they sell | Price | Weakness you exploit |
|---|---|---|---|---|
| Real-time event detection | **Dataminr, Factal, Samdesk, Liferaft, Signal AaaS** | "alert me seconds before the news" from social/sensors | $30k–$250k+/yr, per-seat | cloud-only, send-us-your-assets, opaque, $$$$ |
| Threat intel | **Recorded Future, Flashpoint, Silent Push** | curated threat/CTI feeds | $60k–$500k/yr | cyber-centric, not multi-hazard, enterprise-only |
| Geopolitical risk | **ACLED, Crisis24/GardaWorld, Sibylline, RANE** | analyst reports + data | data licences + retainers | human-analyst latency, not a live self-host tool |
| Big platforms | **Palantir Foundry/Gotham** | integrate *your* data + forward-deployed engineers | $1M+/yr + services | needs their people, their cloud, your data, huge |
| Open / free | **GDELT, ACLED, EpiWatch, Liveuamap, news maps** | raw data or a single-domain map | free | single-domain, no fusion, no self-host product |

**The gap on this table:** nobody sells a **self-hostable, multi-domain,
fused-index situational-awareness product built only on free public data.**
That whitespace is your wedge. Everyone is either (a) cloud SaaS you rent and feed
your assets to, or (b) raw single-domain data, or (c) a $1M platform + consultants.

---

## 3. Who could actually buy — candidate ICPs (ranked)

### A. Corporate & NGO security / duty-of-care (GSOC, travel risk) — **best wedge**
- **Who:** global security operations centres, travel-risk managers, NGO/UN field
  security, energy/mining/logistics with remote sites, universities with study-abroad.
- **Pain:** legally obligated to know where their people/sites are vs. unfolding
  hazards + unrest, but Dataminr/Crisis24 are expensive and cloud-only; many
  (defence-adjacent, EU-data-residency, NGOs in hostile states) **cannot** send
  traveler/site locations to a US cloud.
- **Why you:** drop your assets file in, get every public signal on one map + a
  country risk score, **on your own hardware, no data leaves the building.**
- **Willingness to pay:** high (it's a compliance/liability line item).

### B. Insurers / reinsurers / parametric & supply-chain risk
- **Who:** cat-risk teams, parametric insurers, supply-chain risk (ports, factories).
- **Pain:** need live hazard + disruption exposure against insured locations /
  supplier sites; want it in *their* environment, auditable.
- **Why you:** real disaster footprints + tracks + multi-hazard fusion mapped onto
  their portfolio; self-host = data governance happy.

### C. Newsrooms / investigative journalists / OSINT researchers
- **Who:** wire desks, Bellingcat-style shops, conflict reporters.
- **Pain:** want a fused live picture + free data; budgets tiny.
- **Why you:** open, self-host, free feeds, news-clustering already built.
- **Caveat:** low willingness to pay → community/credibility play, not revenue.

### D. Public sector / civil protection / humanitarian (lower-resource)
- **Who:** national disaster agencies in mid/low-income states, humanitarian ops.
- **Pain:** can't afford Palantir/Dataminr; need offline-capable (the Pi story!).
- **Why you:** **runs on a Raspberry Pi, off-grid, free data** — uniquely fits.

### E. Prosumer / analyst / "war room" hobbyist + small funds
- **Who:** macro/event-driven analysts, family offices, serious hobbyists.
- **Pain:** want one screen, own it, no $50k SaaS.
- **Why you:** self-host, markets + geopolitics + hazards in one view.

**Ranking for a wedge:** A (security/duty-of-care) > B (insurance/supply-chain) >
D (humanitarian, mission-fit but low $) > C/E (community/credibility, low $).

---

## 4. Positioning archetypes — which "who are we" to pick

1. **"Open-source sovereign Dataminr" (product company)** ← recommended spine.
   Self-hostable situational-awareness + country risk index. Open-core: free
   self-host community edition; paid = connectors (your assets/portfolio overlay),
   support, hardened deploy, premium feeds. Land with A/B above.
2. **"OSINT consultancy with a tool"** (services-led). You sell deployments +
   bespoke risk dashboards; the repo is your IP/accelerator. Lower scale, faster
   cash, you become the forward-deployed engineer. This is the *small Palantir*
   move — viable solo/small-team, but it's a job not a product.
3. **"Data/index provider"** — sell the **CII country-risk index** as an API/data
   product (à la ACLED/Recorded Future risk scores) rather than the UI. Narrow,
   defensible if the thesis validation is strong, but needs proven predictive lift.
4. **"Civic / humanitarian open infrastructure"** (grant/impact funded). Lean into
   the Pi/off-grid/free-data angle; fund via grants, not sales. Mission-rich,
   revenue-poor.

**Don't be:** Palantir (no clearance/services/data), or yet-another raw OSINT
aggregator (commoditised, GDELT is free).

---

## 5. The selling factor — 3 candidate wedges, pick one

Each = ICP + one-line pitch + why-now + moat + first money.

**Wedge 1 — Sovereign duty-of-care (RECOMMEND)**
- ICP: NGO/UN, defence-adjacent, EU-data-residency corporates' security teams.
- Pitch: *"Know where your people and sites are against every public hazard,
  unrest and disruption signal — fused into a country risk score, running on your
  own hardware. No cloud, no per-seat data bill."*
- Why now: data-sovereignty + cost pressure; Dataminr fatigue; everyone wants
  on-prem AI/situational tools post-2024.
- Moat: the normalisation + fusion + self-host packaging (hard to rebuild), data
  governance story, and the assets-overlay connector.
- First money: 2–3 design-partner deployments (paid pilots) at NGOs/universities.

**Wedge 2 — Insurance/supply-chain exposure monitor**
- ICP: parametric insurers + supply-chain risk teams.
- Pitch: *"Live multi-hazard exposure on your portfolio/suppliers, in your own
  environment, with real disaster footprints — not a circle on a map."*
- Why now: climate-driven cat losses + parametric growth + supplier-shock trauma.
- Moat: real-geometry footprints + portfolio overlay + auditable self-host.
- First money: one reinsurer/parametric design partner.

**Wedge 3 — The CII index as a product**
- ICP: funds, risk teams, researchers who want the *score*, not the UI.
- Pitch: *"A daily, methodologically-transparent country-instability index from
  fused open data — backtested to beat single-domain baselines."*
- Why now: demand for explainable, non-black-box risk signals.
- Moat: the validated methodology (IF the thesis backtest shows real lift).
- Risk: index value is unproven until the thesis numbers land. Highest-ceiling,
  highest-evidence-bar.

---

## 6. Honest gaps before any of this sells

- **No "your data" overlay yet** — every wedge needs an *assets/portfolio import*
  (CSV of sites/people/suppliers → overlay + per-asset alerting). This is the #1
  product gap and the thing that converts a pretty map into a bought tool.
- **Alerting/notifications** — situational-awareness tools are bought for the
  *alert*, not the map. Need rules → email/Slack/webhook/SMS.
- **Coverage credibility** — social/Telegram/local-language sources are where
  Dataminr/Factal win on speed; you're wire+sensor based (slower on breaking).
- **The thesis proof** — the CII's predictive lift is the difference between
  "nice dashboard" and "defensible index." Land the backtest.
- **Multi-tenant / auth / audit** — none yet; enterprises need it.
- **Trust/provenance** — every alert needs "why" + source link (partly there).

---

## 7. Recommendation (what I'd do)

1. **Identity:** "An open, **sovereign situational-awareness platform** — the
   self-hostable common operating picture for hazards, unrest and disruption,
   with a fused country-risk index." Open-core product company, NOT Palantir, NOT
   a raw aggregator.
2. **Wedge:** start with **Wedge 1 (sovereign duty-of-care)**; it has real pain,
   real budget, and your self-host/off-grid story is a *feature not a limitation*
   there. Insurance (Wedge 2) is the strong fast-follow.
3. **Next build (when we resume):** the **assets-overlay + alerting** loop —
   import locations → match against the live event/CII layer → notify. That single
   feature turns the demo into a product for A and B simultaneously.
4. **Keep the thesis alive in parallel** — a validated CII backtest is the
   credibility asset that makes Wedge 3 (and the pitch deck) real.
5. **Proof-of-pull before more features:** 5–10 discovery calls with NGO/UN
   security, a university travel-risk office, and one parametric insurer. If two
   say "I'd run a pilot," pivot the roadmap to them. If nobody bites, it's a
   portfolio/thesis showcase, not a company — which is also a fine outcome.

---

## 8. One-paragraph "who we are" (draft to react to)

> We build **sovereign situational awareness**. Every public early-warning signal
> — natural hazards, geopolitical events, unrest, cyber and market shocks — fused
> onto one live world map and distilled into a transparent country-risk index,
> running entirely on your own hardware. Not a cloud subscription that rents you
> alerts and hoards your data; an open platform you own, deploy, and trust —
> built so a humanitarian team on a Raspberry Pi and a corporate GSOC see the same
> truth. We're the common operating picture for everyone priced out of, or unable
> to trust, the incumbents.

---

### Appendix — quick gut-checks
- *Are we Palantir?* No. We have no customer data, no forward-deployed services,
  no clearance, no sales org. We're the **anti-Palantir**: own-it, open, cheap.
- *Are we consulting?* Only if you choose Archetype 2 (services-led). Faster cash,
  not a scalable product. Can bootstrap the product company though.
- *Is the tech the moat?* Partly — the normalisation + fusion + self-host packaging
  is genuinely hard. But the **moat is the wedge + the assets/alerting loop +
  (eventually) the validated index**, not the map.
- *Cheapest experiment to de-risk all this:* 10 discovery calls + a 1-page landing
  page for Wedge 1. No code. Do that before pivoting the build.

---

## v2 — THE PIVOT (2026-06-28): sensor-first, signal-before-narrative

**Trigger:** "I don't want to rely on news / what I'm being fed." + "I want my own
Palantir AND a customer base." Both resolve to ONE move.

### Who: alternative-data buyers (event-driven / macro / commodity funds + corp risk)
- Proven market: Geoquant (→Fitch), Predata (acq.), Kpler/Spire/Orbital ($100M+).
- They buy a **number that's early + verifiable**, not a map. Pay $100k–$1M+/yr.
- This reconciles everything: build the sovereign sensor-fusion engine FOR YOURSELF
  (own Palantir), sell ACCESS to the resulting signal (customers).

### What: physical-reality intelligence, not narrative
- Thesis (the REAL one, sharper than the academic one): **physical sensors move
  before the news.** Detect the **divergence between physical activity and the
  narrative** → that lead time is the product.
- Lean the weight from news/RSS → PRIMARY sensors. News becomes the *confirmation*
  layer (was the physical signal right?), not the input.

### Data to add (all free / cheap, sensor-first)
- **AIS ships** (aisstream.io free WS) — ports, chokepoints (Hormuz/Suez/Malacca),
  commodity flows, dark-vessel / sanctions-evasion (AIS gaps). Highest alt-data $.
- **VIIRS nightlights + gas flaring** (NASA, free) — economic pulse, blackouts,
  war damage, oil/gas output proxy.
- **ADS-B deepen** (have OpenSky) — VIP/gov/military jets, capital-flight pattern.
- **Have already:** FIRMS fires, USGS/GDACS hazards, Polymarket odds, yfinance/FRED.

### The signal product
- **Divergence engine:** per region/country/asset, score `physical_activity_delta`
  vs `narrative_volume`. Rank where reality moved but the story hasn't. That's the
  early-warning alpha.
- Sell as: (a) a **daily signal feed / API** (the number + the why), (b) the
  terminal for those who want to see it, (c) backtested lift vs market/event moves.

### Roadmap (phases)
1. **Prove lead time (no new UI):** wire AIS + flaring; pick 5–10 historical events
   (a coup, a port shock, a refinery hit); show the physical signal led the news by
   N days. THIS is the whole bet — if no lead, stop.
2. **Divergence score:** physical-vs-narrative index per country/asset, transparent.
3. **Backtest:** does the signal precede market moves / instability? (your thesis,
   repurposed for alpha). Quantify lift.
4. **Signal feed + alerting:** API + push when divergence spikes near a watchlist.
5. **Sell:** 3 funds / 1 commodity desk as design partners for the feed.

### Where it's going
From "pretty OSINT map" → **"the sovereign physical-intelligence terminal: see what's
happening on Earth from sensors, before the narrative, and own the machine."**
You = the independent ground-truth layer. Customers = people who trade or decide on
that lead time. The map is the demo; **the early, verifiable signal is the product.**

### The one honest gate (same as always)
The lead time must be REAL and measurable. Phase 1 proves or kills it. No proof →
it's a portfolio piece. Proof → it's a fundable alt-data company.

---

## Professor's challenge (the bar this project must clear)
Two questions from the supervisor — answer these in the thesis/defence:
1. **So what?**
2. **Why does this matter?**
3. **What is this solving?**

### The answers (post-pivot)
- **So what?** Physical sensors move before the narrative. We measure the lead time
  between *what is physically happening on Earth* (ships, flights, fires, flaring,
  market/odds) and *when the news reports it* — and show the sensors lead.
- **Why does it matter?** Whoever sees the lead time first decides/trades first.
  Today that edge is locked behind $1M Palantir / $100k Dataminr / proprietary
  alt-data. We build it from **free public sensors, self-hosted, narrative-
  independent** — ground truth you own, not a story you're fed.
- **What is it solving?** The dependence on narrative + the cost wall. It turns
  scattered free physical signals into one early, verifiable, quantified
  divergence score — the "something is happening here before the story breaks"
  signal — for people priced out of, or unwilling to trust, the incumbents.
- **The honest gate:** this only matters if the lead time is REAL and measurable.
  Phase 1 (AIS + flaring, 5–10 past events, show N-day lead) proves or kills it.
