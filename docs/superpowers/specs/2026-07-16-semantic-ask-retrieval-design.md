# Semantic ask retrieval (retrieval v2)

Date: 2026-07-16 · Status: approved (Basil, in-session)

## Problem

`/brain/ask` picks its 6 context stories with a keyword ranker
(`qa._question_terms` + `qa._rank_story_rows`) that fails exactly the user this
product is for — someone who types fast, vague, and with typos, and just wants
answers ("whatt explosions? what do u think that was?"):

- The stopword list is tiny: `was`, `are`, `any`, `think`, `sources`, `theories`
  all survive as "terms"; typos like `whatt` sail through.
- Scoring is substring containment: `'any' in 'germany…'` scores, `'was'` hits
  nearly every gist — junk terms drown the one real term.
- No stemming: `explosions` does not match a title containing `explosion`,
  so the right story loses its 4× title boost.

Net effect: the 6 selected stories are irrelevant, and the QA prompt then
(correctly) forces "I don't have data on that." The model isn't dumb — the
retrieval starves it.

## Decisions (confirmed with Basil)

- **Real fix now: embedding-based retrieval.** Backend-only (issue A); passing
  chat history into ask is issue B, after PR #440's transcript merged (it has).
  Alt/low-level source ingestion is issue C, its own design round.
- **Embed model: `nomic-embed-text`** (274 MB, 768-dim) as the settings default
  (`embed_model`), so swapping to e.g. `embeddinggemma` is an env change only.
  Pi 8 GB discipline: every embed call uses `keep_alive=0`.

## Design

### `client.embed(texts) -> list[vector]` (app/brain/client.py)

Ollama `POST /api/embed` with `input: [texts]` (one HTTP call per batch),
`keep_alive=0`. Raises on HTTP failure like the other client fns.

### `story_embeddings` table (+ migration 0016)

`id, story_id, model, method_version, vector (JSON list of floats), created_at`,
unique on `(story_id, method_version)` — same idempotency shape as `story_gist`.
Size: 768 floats ≈ 3 KB/story ≈ 5 MB/month. Irrelevant vs the 30 GB cap;
30-day retention rides the existing story cleanup.

### Embedding beat (app/brain/embeddings.py, called from the enrich job)

After the gist pass, embed stories in the window that lack a vector for the
current `EMBED_METHOD_VERSION`: text = `title · gist · top member keywords`
(pure fn `story_embed_text`). One batched `client.embed` call per enrich tick,
counters reported alongside the gist counters. Embed failure increments a
counter and never fails the job.

### Ask-time retrieval (qa.build_qa_stories)

1. Load vectors for the ≤120 candidates.
2. `client.embed([question])` → cosine (numpy, in-process — no pgvector) →
   rank candidates that have vectors; take top `limit`, tie-break
   `outlet_count`.
3. Candidates without vectors can only fill remaining slots (loudness order).
4. Any embed failure → **fallback keyword ranker**, which this change also
   repairs: word-boundary matching (regex `\b`), naive plural folding
   (`term` matches `terms` and vice versa), and the stopword list extended with
   the junk observed live (`was are any think sources theories does know…`).

Unbiasedness: retrieval only chooses *which* stories the model sees; the
corroboration / contested / sensor machinery still labels trust. No side-taking
enters the answer path.

### Tests (pytest, TDD)

- `client.embed`: request shape (`keep_alive=0`, batched input), error raise.
- `story_embed_text`: composition, missing gist/keywords.
- Cosine ranking: right story wins on a paraphrase; typo question still ranks
  the semantically-close vector first (fixtures with hand-built vectors).
- Fallback ranker: `explosions` matches `explosion` title; `any` no longer
  matches `germany`; junk-term question no longer beats the real match.
- Enrich beat: inserts missing vectors, skips existing, survives embed failure.
- `build_qa_stories`: semantic path picks by cosine; fallback path used when
  embed raises.

## Out of scope

- Chat history in ask (issue B).
- Alt-source ingestion (issue C).
- pgvector / ANN indexes — pointless at ≤120 candidates.
- Re-embedding old stories on model swap (method_version bump handles it
  gradually; backfill is the enrich beat's normal behaviour).
