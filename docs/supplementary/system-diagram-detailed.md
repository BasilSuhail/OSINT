# The system in detail

The long-form version of the diagram in [`SUPPLEMENTARY.md`](../../SUPPLEMENTARY.md).
Same thirty stages, but each box carries the reasoning, the thresholds and the
measured counts rather than a one-line summary.

Kept as a reference. The short diagram is the one a reader meets first.

---

<pre>
════════════════════════════════ PART I — INGEST ════════════════════════════════

                     ╔═══════════════════════════════════════╗
                     ║ <a id="map-1" href="#ch-1">§1  THE CLOCK</a>                         ║
                     ║ app/tasks.py :: beat_schedule         ║
                     ║ 84 entries, cron-style, all UTC       ║
                     ║ */5min ─ 15min ─ hourly ─ nightly ─ wk ║
                     ╚════════════════════╦══════════════════╝
                                          │ publishes {task name, args}
                                          ▼
                     ╔═══════════════════════════════════════╗
                     ║ §2  THE BROKER — Redis                ║
                     ╠══════════════════╤════════════════════╣
                     ║ queue "celery"   │ queue "analytics"  ║
                     ║ concurrency 4    │ concurrency 1      ║
                     ║ 67 fetchers      │ 15 heavy jobs      ║
                     ║ I/O-bound, small │ one at a time, so  ║
                     ║                  │ peak RAM = max(1)  ║
                     ╚═════════╤════════╧═══════════╤════════╝
                               │                    │
                               │                    └──────────────┐
                               ▼                                   │
   ┌───────────────────────────────────────────────────────┐       │
   │ §3  THE SOURCES — app/fetcher_registry.py             │       │
   ├───────────────────────────────────────────────────────┤       │
   │ 14 core fetchers                                      │       │
   │   market      yfinance · fred                         │       │
   │   geopolitical gdelt · acled                          │       │
   │   hazard      usgs-quake · gdacs · eonet · emdat      │       │
   │   wildfire    nasa-firms                              │       │
   │   presence    opensky-adsb                            │       │
   │   other       uk-police · polymarket ·                │       │
   │               abuse-ch-urlhaus · abuse-ch-feodo       │       │
   │                                                       │       │
   │ 55 RSS feeds declared in app/sources/rss_feeds.json   │       │
   │   53 enabled and scheduled · 2 parked (enabled=false) │       │
   │   classes: 24 regional · 16 mainstream ·              │       │
   │            8 state · 7 independent                    │       │
   │   each becomes a named RssNewsFetcher subclass,       │       │
   │   staggered by index so they never all hit at once    │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §4  THE REST GATE — app/ingest/quarantine.py          │       │
   │ a source that failed repeatedly is resting            │       │
   │  ├─ resting  → return {"skipped", reason}  ── 1 query │       │
   │  └─ awake    → continue                               │       │
   │ a 404 from a time-addressed URL is not death: GDELT   │       │
   │ names its window in the filename (stable_urls=False)  │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §5  fetch() — app/sources/base.py                     │       │
   │ pure HTTP. no database, no Redis, no Celery.          │       │
   │ returns list[Event] | FetchBatch(events, unchanged)   │       │
   │        ┌──────────────┬──────────────┬─────────────┐  │       │
   │  raises│Misconfigured │ Exception    │ returns ok  │  │       │
   │        ▼              ▼              ▼             │  │       │
   │  state=misconfig  record_failure   carry on        │  │       │
   │  (local config)   → quarantine     to §6           │  │       │
   │                   NOT re-raised: 5 retries on a       │       │
   │                   403 cost 420 requests in a week     │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼   (RSS rows only)                    │
   ┌───────────────────────────────────────────────────────┐       │
   │ §6  INLINE ENRICHMENT — app/sources/rss_news_fetcher  │       │
   │ order is load-bearing, one arrow at a time:           │       │
   │                                                       │       │
   │  title ─▶ translation.apply()   non-English → English │       │
   │            original kept verbatim in payload          │       │
   │        ─▶ resolve_geo()         country + lat/lon +   │       │
   │            GEO_METHOD_VERSION   provenance of guess   │       │
   │        ─▶ ner extract           named places/orgs     │       │
   │        ─▶ score_text()          sentiment             │       │
   │        ─▶ keyword_verdict()     provisional severity  │       │
   │                                                       │       │
   │ translation runs FIRST because the severity keywords, │       │
   │ the geocoder and the clustering tokeniser all read    │       │
   │ English words. Skip it and a foreign feed scores flat.│       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §7  PUBLICATION-TIME REPAIR — ingest/publication_time │       │
   │ nothing is published in the future. shift or clamp.   │       │
   │ runs BEFORE §8: the old order threw away real news    │       │
   │ over a timezone label.                                │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §8  FRESHNESS GATE — app/ingest/freshness.py          │       │
   │  fresh ──▶ §9        stale ──▶ counted + retained as  │       │
   │                                IngestFailureRow       │       │
   │ live path only. Backfills call upsert_events direct.  │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §9  UPSERT AND DEDUP — app/persistence.py             │       │
   │ ON CONFLICT (source, source_event_id) DO UPDATE       │       │
   │  ├ identity cols  source, source_event_id, category   │       │
   │  │                never updated                       │       │
   │  ├ refresh cols   an ongoing cyclone must not freeze  │       │
   │  │                at first-seen state                 │       │
   │  ├ geo cols       RSS replaces (resolver is           │       │
   │  │                authoritative); others keep nulls   │       │
   │  │                so post-ingest geo survives         │       │
   │  └ ENRICHMENT_PAYLOAD_KEYS — listed explicitly and    │       │
   │    walked by a test, because a 15-minute GDACS        │       │
   │    refresh silently deleted the map's real geometry   │       │
   │    for weeks                                          │       │
   │ 1000 rows per statement · 12 000 bound params         │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §10  OUTCOME CLASSIFICATION — app/ingest/outcome.py   │       │
   │ HTTP 200 with no usable row is NOT a success.         │       │
   │   new_data | unchanged → success_n                    │       │
   │   empty                → empty_n                      │       │
   │   misconfigured        → misconfigured_n              │       │
   │   failed               → failure_n                    │       │
   │ this is how a dead feed stops looking healthy.        │       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
   ┌───────────────────────────────────────────────────────┐       │
   │ §11  THE FAILURE LEDGER                               │       │
   │  ingest_health      per source-day counters           │       │
   │  ingest_failures    error class + message             │       │
   │  source_quarantine  resting until, and why            │       │
   │  dead_letter_queue  work that exhausted its retries   │       │
   │  app/watchdog.py    every 15 min: which source has    │       │
   │                     gone quiet against its own cadence│       │
   └────────────────────────┬──────────────────────────────┘       │
                            ▼                                      │
        ╔══════════════════════════════════════════════════════╗   │
        ║ §12  events — THE CANONICAL TABLE                    ║   │
        ║ app/db_models.py · one row shape for every source    ║   │
        ╟──────────────────────────────────────────────────────╢   │
        ║ id · source · source_event_id  ← UNIQUE together     ║   │
        ║ category · title · severity    ← source-relative     ║   │
        ║ occurred_at   when the world moved                   ║   │
        ║ fetched_at    when this system learned of it         ║   │
        ║               (both kept: the gap is reporting delay ║   │
        ║                and it is a measured bias)            ║   │
        ║ country · lat · lon            ← nullable. unknown   ║   │
        ║                                  is a valid answer   ║   │
        ║ payload JSONB                  ← source-specific     ║   │
        ║                                  detail + enrichment ║   │
        ╚═══════════╤══════════════════════════════════╤═══════╝   │
                    │                                  │           │
                    │                          ┌───────┘           │
                    │                          ▼                   │
                    │   ┌──────────────────────────────────────┐   │
                    │   │ §13  POST-INGEST ENRICHMENT BEATS    │◀──┤
                    │   │ the only paths that MUTATE a row     │   │
                    │   ├──────────────────────────────────────┤   │
                    │   │ enrich_footprints    15min           │   │
                    │   │   real hazard geometry from USGS     │   │
                    │   │   ShakeMap / GDACS; refetched when   │   │
                    │   │   the episode URL moves              │   │
                    │   │ enrich_news_places   30min           │   │
                    │   │   named buildings/streets via cache  │   │
                    │   │ enrich_gdelt_titles  ~5min           │   │
                    │   │   offset from the export download    │   │
                    │   │ grade_news_severity  30min  → §21    │   │
                    │   └──────────────────────────────────────┘   │
                    │                                              │
                    ▼                                              │
   ┌───────────────────────────────────────────────────────┐       │
   │ §14  RETENTION AND CAP — app/housekeeping.py  03:00   │◀──────┤
   │  ~30 days everywhere, per source, env-overridable     │       │
   │  exempt: fred, emdat — history that cannot be rebuilt │       │
   │  uk-police pruned by INGEST time, not occurrence:     │       │
   │    it publishes two months in arrears, so every row   │       │
   │    was 68 days old on arrival and deleted on landing  │       │
   │  hard cap STORAGE_CAP_GB (default 30): delete oldest  │       │
   │    whole event-days, never below the recent floor     │       │
   │  then VACUUM                                          │       │
   │  ⚠ this is why §15 exists — the analysis must outlive │       │
   │    the rows it was computed from                      │       │
   └───────────────────────────────────────────────────────┘       │
                                                                   │
═══════════════════════════ PART II — ANALYSIS ═════════════════════│══════════
                                                                   │
   everything below reads `events` and is published to the         │
   "analytics" queue: one consumer, strictly one job at a time ◀───┘

   ┌─────────────────────────────────────────────────────────────────────┐
   │ §15  THE COMPOSITE INDEX — app/composite/*        hourly at :10     │
   ├─────────────────────────────────────────────────────────────────────┤
   │ (a) aggregation.py    24-month lookback, streamed 10 000 rows at a  │
   │                       time. four domains:                           │
   │       market       strongest event in the month                     │
   │       geopolitical log-scaled COUNT, not severity — every stored    │
   │                    GDELT row is escalatory so severity said the     │
   │                    same thing everywhere (sd 0.0523 → 0.797)        │
   │       hazard       discrete casualty-bearing events                 │
   │       wildfire     total FRP — FIRMS left `hazard` because the      │
   │                    stored value is detection CONFIDENCE, not        │
   │                    intensity, and is non-monotonic against power    │
   │ (b) history.py        merge with composite_signals — the aggregate  │
   │                       that survives §14's deletion of the events    │
   │ (c) normalization.py  rolling z-score, 12-month window              │
   │       MIN_HISTORY = 3        fewer points → emit 0.0, not a z       │
   │       STD_TOLERANCE = 1e-9   a constant history would otherwise     │
   │                              produce a sub-1e-15 sd and a huge z    │
   │ (d) scoring.py        weights 0.25 each, normalised to sum 1        │
   │       ABSENT DOMAINS ARE DROPPED and the rest renormalised.         │
   │       entering z=0 asserts "exactly average", which is a different  │
   │       claim from "we do not know" — and it pulled every score to    │
   │       0.5 hardest for the countries with least data                 │
   │       value = sigmoid(Σ renormalised_weight × z)                    │
   │       components{} records which domains were present, so a stored  │
   │       score is auditable without re-deriving it                     │
   │ (e) degeneracy.py     top_share &gt; 0.90 → this is one number with    │
   │                       noise on it. exact flatness was the old test  │
   │                       and 1 101 forecasts of a constant walked      │
   │                       through it                                    │
   │ method_version v3.0 stamped on every row — never an in-place edit   │
   └───────────────┬─────────────────────────────────────────────────────┘
                   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ §16  CII — app/cii/*                              hourly at :25     │
   │ country instability index, cii.v1.2                                 │
   │ 0.40 × baseline + 0.60 × events, over four components:              │
   │   unrest 0.25 · conflict 0.30 · security 0.20 · information 0.25    │
   └───────────────┬─────────────────────────────────────────────────────┘
                   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ §17  STORIES — app/stories/*                      every 30min :07   │
   │ classical, deterministic, no model:                                 │
   │   tokenize()    lowercase, stopwords, drop calendar words and       │
   │                 bare years, min length 3                            │
   │   build_idf()   inverse document frequency over the window          │
   │   vectorize()   TF-IDF sparse dict                                  │
   │   cosine()      similarity                                          │
   │ join if cosine ≥ 0.35 AND ≥ 2 shared content tokens AND no place    │
   │ conflict (a place named by ≥ 30% of one story's members bars a      │
   │ merge with a story about somewhere else)                            │
   │ → stories · story_members                    stories-v1.0           │
   └───────┬────────────────┬─────────────────┬──────────────────────────┘
           ▼                ▼                 ▼
   ┌───────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐
   │ §18 CORROB-   │ │ §19 DISAGREE-   │ │ §20 VALIDATOR               │
   │ ORATION +     │ │ MENT            │ │ app/validator/*  nightly    │
   │ SENSOR CHECKS │ │ app/disagree-   │ │ 02:45                       │
   │ 30min :17     │ │ ment/* :22      │ │ local LLM extracts factual  │
   │               │ │                 │ │ claims from headlines       │
   │ how many      │ │ how differently │ │ → story_claims              │
   │ INDEPENDENT   │ │ blocs word the  │ │ → story_reviews             │
   │ owners tell   │ │ same story      │ │ claims-qwen3.5-4b-q4_K_M-p1 │
   │ it —          │ │                 │ │                             │
   │ an unmapped   │ │ divergence/     │ │ gated by a hand-filled      │
   │ slug must NOT │ │ scoring.py:     │ │ audit sheet, not by         │
   │ count as      │ │ rolling z,      │ │ assertion                   │
   │ independent   │ │ ±21-day TWO-    │ │                             │
   │ (10 unmapped  │ │ SIDED lead      │ │                             │
   │ sources would │ │ search — one-   │ │                             │
   │ have produced │ │ sided makes a   │ │                             │
   │ 0.998         │ │ positive lead   │ │                             │
   │ confidence)   │ │ the only        │ │                             │
   │               │ │ possible finding│ │                             │
   │ claim vs      │ │                 │ │                             │
   │ physical      │ │ → story_disagr- │ │                             │
   │ sensor:       │ │   eement        │ │                             │
   │ does a quake  │ │ → disagreement_ │ │                             │
   │ story have a  │ │   pairs         │ │                             │
   │ quake under it│ │ disagreement-   │ │                             │
   │ → story_      │ │ v1.0            │ │                             │
   │   sensor_     │ │                 │ │                             │
   │   checks      │ │                 │ │                             │
   └───────┬───────┘ └────────┬────────┘ └──────────────┬──────────────┘
           └────────────────┬─┴─────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ §21  SEVERITY GRADING — app/severity/*             30min :14/:44    │
   │ a local model grades harm-to-people per headline, with a written    │
   │ reason. keyword grading was retired when a strike and a bombing     │
   │ scored identically and 42 of 50 audit findings traced to one        │
   │ function.                                                           │
   │   scale.py   bands · LETHAL_FLOOR 0.60 · MASS_CASUALTY_FLOOR 0.80   │
   │              euphemism_in() rejects a soft rationale on a hard      │
   │              number                                                 │
   │   news-llm-v1, falling back to news-keyword-v2                      │
   │ capacity ≈ 2 400 headlines/day against ≈ 863 arriving, so a         │
   │ backlog drains and the pass idles. without the beat the grade only  │
   │ exists where someone ran it by hand — and §14 deletes it in 30 days │
   └───────────────┬─────────────────────────────────────────────────────┘
                   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ §22  THE BRAIN — app/brain/*                    local Ollama only   │
   ├─────────────────────────────────────────────────────────────────────┤
   │ gate.py      refuses to run when RAM is short or a heavy job holds  │
   │              the box. the model is evicted after use (keep_alive=0) │
   │ narrate      every 15min → brain_narrative, the situation summary   │
   │ enrich       every 20min → story_gist (≤240 chars) + tags,          │
   │              enrich-v1.1 / enrich-prompt-v1.0, categories fixed to  │
   │              conflict·economy·disaster·politics·other               │
   │ embeddings   nomic-embed-text → story_embeddings, embed-v1.0        │
   │ qa.py        the ask box, 1 516 lines, the longest module here:     │
   │   question ─▶ term + country-code extraction                        │
   │            ─▶ semantic retrieval over story_embeddings (cosine)     │
   │            ─▶ sensors.py pulls physical readings for the named      │
   │               place and hazard kind, 72h window                     │
   │            ─▶ coverage_bias built for the answer                    │
   │            ─▶ generate → de-echo → de-refuse → check answer         │
   │            ─▶ answer + (source) chips + (thinking) annotations      │
   │ served two ways: POST /brain/ask and an SSE /brain/ask/stream       │
   └───────────────┬─────────────────────────────────────────────────────┘
                   ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │ §23  THE PREDICTION JOURNAL — app/journal/*     nightly 02:15       │
   │ emit.py    horizons k = 1, 3, 6 months from the composite scores    │
   │            a window overlapping the KNOWN PAST is skipped — grading  │
   │            it would fake a record                                   │
   │            predictions is append-only: ON CONFLICT DO NOTHING, so    │
   │            an issued forecast can never be rewritten. that           │
   │            immutability is the journal's entire integrity claim      │
   │ grade.py   resolve outcome once the horizon closes                  │
   │ scoreboard issued vs graded, per source and method version          │
   └─────────────────────────────────────────────────────────────────────┘

════════════════ PART III — THE OFFLINE EVALUATION TRACK ════════════════════

   run by hand from the Makefile. reads a separate ground truth. never
   touches the live 30-day database, which is exactly why it can span
   thirty years.

   ┌──────────────────────────┐
   │ §24  GROUND TRUTH        │   ACLED weekly aggregates (xlsx)
   │ app/labels/*             │   ─▶ acled_loader.py
   │ make labels              │   ─▶ rules.py  labels-v1.1
   │                          │      P1 political violence
   │                          │      P2 demonstrations
   │                          │      P3 fatality escalation against the
   │                          │         prior month, floor + multiplier;
   │                          │         a country's first observed month
   │                          │         is never labelled — no prior
   │                          │   ─▶ labels table, NEVER joined into
   │                          │      events — inputs and ground truth
   │                          │      must not share a lineage or an
   │                          │      evaluation grades a signal against
   │                          │      itself
   └────────────┬─────────────┘
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ §25  THE PANEL — app/panel/*            make panel               │
   │ spine.py     country × month grid over the coverage window       │
   │ assemble.py  attach label_p1/p2/p3 + market/geopolitical/hazard  │
   │ export.py    → results/data/panel.csv                            │
   │ measured: 31 637 rows · 200 countries · 1996-12 → 2026-06        │
   │           label_any 7 088 · score_rows 17 367 · method v1.0      │
   └────────────┬─────────────────────────────────────────────────────┘
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ §26  THE EXAMS                                                   │
   │ make baselines        B0 random · B1 persistence · B2 base rate  │
   │                       B3/B4/B5 single-domain · B6 composite      │
   │                       metrics.py auroc · aupr · brier            │
   │                       verdict.py decides — a person does not     │
   │ make within-eval      within-country concordance, 1 000          │
   │                       bootstrap resamples OVER COUNTRIES because │
   │                       the country is the unit of independence.   │
   │                       pooled AUROC was retired: 60% of countries │
   │                       are constants, so it rewarded telling a    │
   │                       calm country from a war                    │
   │ make onset-eval       the pre-registered onset exam              │
   │ make indicator-ranking every dashboard indicator ranked by       │
   │                       measured predictive value                  │
   │ make coverage         coverage-bias table                        │
   │ make journal          emit + grade + scoreboard, offline         │
   │ make disagreement · sensor-checks · stories · validator          │
   │ → results/reports/*.json  (artefact of record)                   │
   │ → results/reports/*.md    (rendered view of the json)            │
   └────────────┬─────────────────────────────────────────────────────┘
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ §27  THE HUMAN AUDIT SHEETS — results/audit-sheets/              │
   │ model output is not evidence until a person has checked a sample │
   │ severity-audit-sheet   gates the published 0.860 agreement       │
   │ severity-model-bench   same headlines through five candidates    │
   │ validator-audit-sheet  claims checked against their article      │
   │ stories-audit          are these articles really one story       │
   │ one rater · not chance-corrected · no kappa taken yet            │
   └──────────────────────────────────────────────────────────────────┘

═════════════════════════ PART IV — SERVING ═════════════════════════════════

   ┌──────────────────────────────────────────────────────────────────┐
   │ §28  THE API — app/api.py, FastAPI, 31 routes                    │
   ├──────────────────────────────────────────────────────────────────┤
   │ /events            the map query — bbox, window, category,       │
   │                    readable_only (a row with no readable claim   │
   │                    is excluded from the default response, not    │
   │                    deleted, and returns with readable_only=false)│
   │ /events/stats · /events/coverage · /search · /geo/place          │
   │ /scores · /composite/movers · /journal/monthly · /journal/score- │
   │   board                                                          │
   │ /stories/top · /for-events · /developing · /{id}/members ·       │
   │   /{id}/detail · POST /{id}/deep-read                            │
   │ /disagreement/top                                                │
   │ /brain/narrative/latest · POST /brain/ask · POST /brain/ask/     │
   │   stream (SSE, heartbeat-kept-alive)                             │
   │ /presence/aircraft · /vessels · /upcoming                        │
   │ /ingest-health · /ingest/quarantine · /console/health ·          │
   │   /jobs/recent · /audit/latest · /health                         │
   │ /analytics/baselines · /analytics/coverage  ← serves §26's files │
   │ /stream            SSE, fed by Redis pub/sub on "events:new"     │
   └────────────┬─────────────────────────────────────────────────────┘
                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ §29  THE CONSOLE — osint-frontend/, Next.js + React              │
   ├──────────────────────────────────────────────────────────────────┤
   │ SplitLayout            the shell: map pane + floating card deck  │
   │ MapPane                MapLibre, dynamically imported (no SSR)   │
   │ EventBuffer            lib/realtime.ts — in-memory ring buffer   │
   │                        over an EventSource on /stream, with a    │
   │                        poll armed on stream error                │
   │ 12 zustand stores      filter · place · leftPane · rightPaneMode │
   │                        storyDetail · eventDetail · mapFocus ·    │
   │                        worldDetail · imagery · presence ·        │
   │                        deckExpand · panelLayout                  │
   │ 39 components          Situation · Stories · Trust · Coverage ·  │
   │                        Scoreboard · Briefing · Place · Selection │
   │                        · WorldStatus · SystemMonitor · AskDock   │
   │ 54 lib modules         markers · footprints · hazardSymbols ·    │
   │                        precision · locationProvenance ·          │
   │                        translationNotice · verdicts · …          │
   └──────────────────────────────────────────────────────────────────┘

═════════════════════════ PART V — WHAT COMES OUT ═══════════════════════════

   ┌──────────────────────────────────────────────────────────────────┐
   │ §30  THE ARTEFACTS                                               │
   │ results/data/          panel.csv · coverage-bias.csv · meta      │
   │ results/reports/       9 result sets, json + rendered md         │
   │ results/audit-sheets/  4 hand-filled sheets                      │
   │ docs/supplementary/    figures, hand-written SVG                 │
   │ app/briefing/          the weekly briefing, Monday 06:30 UTC     │
   │ THIS DOCUMENT          every appendix below cites one of the     │
   │                        files above, by path                      │
   └──────────────────────────────────────────────────────────────────┘

═════════════════════════ WHAT KEEPS IT HONEST ══════════════════════════════

   these run across every stage above and are the reason a number here
   can be checked rather than believed:

   ─ 30 Alembic migrations, 28 tables — the schema has a written history
   ─ 237 test modules; the enrichment-key list in §9 is walked by one of
     them, so a refresh that starts clobbering enrichment fails the suite
     instead of quietly emptying the map
   ─ every method carries a frozen version string (v3.0 · cii.v1.2 ·
     stories-v1.0 · labels-v1.1 · disagreement-v1.0 · enrich-v1.1 ·
     embed-v1.0 · news-llm-v1) — a change bumps it, never edits in place
   ─ app/audit/* runs nightly at 03:40, AFTER the retention prune, so its
     findings describe the table as it stands rather than counting rows
     about to be deleted
   ─ every result file names the command that regenerates it</pre>
