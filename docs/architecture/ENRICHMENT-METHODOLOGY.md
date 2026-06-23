# Enrichment Methodology

How news rows get enriched on ingest, what gets stamped on each row, and
why.

**Modules:** `app.enrichment.sentiment`, `app.enrichment.ner`,
`app.enrichment.city`.

**Wired into:** `app.sources.rss_news_fetcher.entry_to_event` — every RSS
feed shares the same enrichment pass so the contract stays consistent.

## What lands on `payload`

```python
payload = {
    "title": str,
    "summary": str | None,
    "source_url": str | None,
    "feed_name": str,
    "published_at": str,         # ISO 8601
    "city": str | None,          # offline city pinpoint (#113)
    "image_url": str | None,     # thumbnail (#133)
    "sentiment": float | None,   # VADER compound [-1, 1] (#131)
    "sentiment_label": str | None,
    "news_scope": "local" | "world" | "unknown",  # #166
    "entities": list[dict],      # spaCy NER (#154)
    "enrichment_meta": {
        "sentiment_model": "vader.v1.0",
        "ner_model": "spacy.en_core_web_sm.v1.0" | "none",
    },
}
```

Method versions are stamped on every row. A model swap bumps the
version and writes new rows alongside the old, preserving historical
reproducibility for backtests.

## Sentiment — VADER v1.0

`app/enrichment/sentiment.py`. Lexicon + rule-based (Hutto & Gilbert
2014). ~200 KB lexicon ships in-process, deterministic, no GPU, no
model download.

- Cut-offs (VADER published): `compound ≥ +0.05` → positive,
  `compound ≤ -0.05` → negative, else neutral.
- LRU cache (8192 entries) shared by the fetcher + the backfill
  script so repeated text scoring is cheap.

**Why VADER first (not BERT):** the cost calculus:

| Property | VADER | BERT (distilbert SST-2) |
|---|---|---|
| Image cost | ~200 KB | ~500 MB (transformers + onnx) |
| Cold start | <50 ms | ~600 ms |
| Determinism | exact | model-version dependent |
| Headline-level signal | good | better, esp. financial idiom |

VADER gives 80% of the analytical signal for 0.04% of the image cost.
BERT swap tracked as a follow-up (#155) — gates on benchmarking VADER
against CII v1 first.

## NER — spaCy `en_core_web_sm` v1.0

`app/enrichment/ner.py`. Optional dep (`[nlp]` extra). Falls back to
empty list when spaCy or the model wheel aren't installed — so CI
keeps passing without the model + prod ships the real signal.

- Lazy load via `lru_cache(1)` — pay the ~700 ms import once per
  worker process.
- Filter to `PERSON / ORG / GPE / LOC / EVENT / NORP / FAC`. Drops
  `DATE / MONEY / CARDINAL / ORDINAL / PERCENT / QUANTITY` because
  the dashboard chip layer doesn't surface them and they crowd the
  signal.
- De-dupe on `(text.lower(), label)`. Cap at 12 per row.

**Why spaCy small (not transformer-based):** ~15 MB model vs ~440 MB
for a transformer NER, deterministic, no GPU. Wikidata link resolution
is a follow-up (post-NER, depends on this) — separate issue.

## City pinpoint — offline Natural Earth 50m

`app/enrichment/city.py`. ~1.2 k populated places shipped as a
~100 KB JSON. Substring scan against tokenised lowercase headline +
summary, country-hint disambiguation (Cambridge UK > Cambridge MA
when feed's `default_country = "GB"`).

Coverage: ~30% hit rate against RSS headlines. Misses fall back to
the country centroid in the old map path; **post-#166** they get
tagged `news_scope = "unknown"` and skipped by the map (still shown
in the bottom-page news cards).

A NE 10m city upgrade (~1.2 k → ~15 k cities) is tracked as a
follow-up — bigger JSON but better hit rate.

## News scope classifier — `local | world | unknown`

`rss_news_fetcher.entry_to_event` post-city-lookup:

| Case | Scope |
|---|---|
| Feed has `default_country` + city matches that country | `local` |
| Feed has `default_country` + city matches a different country | `world` |
| Feed has no `default_country` + any city match | `local` (to that city) |
| No city match | `unknown` |

Used by `MapPane.positioned` to skip the centroid blob for world-scope
news. See #166 PR text for the screenshot that motivated the rule.

## Impact ranking — frontend

`osint-frontend/components/DashboardSection.tsx`. Mirrors NIP §3:

```
impact = 0.30 × |sentiment|
       + 0.25 × min(clusterSize / 10, 1)
       + 0.25 × sourceWeight
       + 0.20 × recency
```

- `|sentiment|`: falls back to a severity-derived proxy when VADER
  hasn't enriched the row yet.
- `clusterSize`: from the bigram-Jaccard single-link cluster (#172).
  Cap at 10 mirrors NIP.
- `sourceWeight`: per-feed editorial in `NEWS_SOURCE_WEIGHTS`, four
  tiers (wire-service 1.0 → state-mouthpiece 0.55).
- `recency`: 24 h linear decay.

## Open questions / planned bumps

- **`sentiment.v2.0`** = distilbert SST-2 via ONNX (#155). Drops in
  with no payload schema change because the field is just a float.
- **`ner.v1.1`** = Wikidata linking on top of spaCy. Adds a `wikidata`
  field per entity.
- **`city.v2.0`** = NE 10m upgrade (~15 k cities).
- **`news_scope.v2.0`** = BERT-classifier instead of city-match
  heuristic. Higher recall on headlines that don't mention a city
  but clearly localise (e.g. "Karachi blast" already matches; "Sindh
  protest" doesn't because Sindh is a province, not a city).

## References

- Hutto, C.J. & Gilbert, E.E. (2014). VADER: A Parsimonious Rule-based
  Model for Sentiment Analysis of Social Media Text. *ICWSM-14*.
- Honnibal, M., & Montani, I. (2017). spaCy 2: Natural language
  understanding with Bloom embeddings.
- NIP repo `03-IMPACT-SCORE-ALGORITHM.md`.
- WM repo `docs/algorithms.mdx`.
