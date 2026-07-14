# Q&A Phase B — question-driven retrieval

**Tracking issue:** #413
**Base:** Phase A PR #423
**Scope:** make ask-the-brain choose relevant recent stories for the question instead
of always feeding only the loudest fixed snapshot. Keeps the 1.5b model. No new
dependencies. No live web.

## Goal

Phase A made answers source-cited and trust-signal aware, but the story list is still
the top loudest recent stories. Phase B narrows the `stories` context to the user's
question so answers about Iran, quakes, a country code, or a specific phrase get
stories that mention those terms when the local database has them.

## Design

Add deterministic local retrieval in `app/brain/qa.py`:

- Extract meaningful alphanumeric terms from the question.
- Drop common ask-the-brain stopwords.
- Search recent story candidates from the same 72h window Phase A used.
- Score candidates in Python using only local fields:
  - story title
  - Phase 3 gist/category/escalating
  - member event title/description/summary
  - member event keywords/category/country/source
- Return the best matching stories in the same Phase A source shape.

If the question has no useful search terms, keep the Phase A loudest-story fallback.
If it has useful terms but no story matches, return an empty `stories` list so the
closed-world prompt can refuse rather than answer from unrelated loud stories.

## Endpoint

`POST /brain/ask` passes `req.question` into `build_qa_context(...)`. Busy/offline and
malformed-model paths remain graceful HTTP 200 responses with `sources: []`.

## Non-goals

- No embeddings.
- No vector store.
- No new dependencies.
- No bigger model; that remains Phase C.
- No streaming; that remains Phase D.
- No live web search.

## Tests

- Relevant story beats a louder unrelated story.
- Queries can match member event metadata, not just story titles.
- Meaningless/general questions still fall back to loudest stories.
- Endpoint passes the question into context retrieval.
