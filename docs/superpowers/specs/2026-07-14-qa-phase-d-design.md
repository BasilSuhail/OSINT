# Q&A Phase D — streaming ask answers

**Tracking issue:** #413
**Scope:** stream ask-the-brain answer text so slow local model calls do not freeze
the frontend while preserving Phase A citation guardrails.

## Goal

Phase D improves UX latency, not model quality. The API should send source metadata
immediately, stream answer deltas while Ollama is generating, then send one final
citation-checked answer. The final answer remains authoritative because citation
repair/fallback can replace an uncited streamed draft.

## Design

`POST /brain/ask/stream` returns `text/event-stream` with these event types:

- `sources`: `{context_digest, sources}` emitted after retrieval.
- `delta`: `{text}` emitted for each local Ollama text chunk.
- `final`: full `BrainAsk` shape: `{answer, context_digest, sources}`.

The frontend uses `fetch` + `ReadableStream` instead of `EventSource` because the
ask request is a JSON `POST`.

The blocking `POST /brain/ask` remains as a fallback path and compatibility API.

## Guardrails

- Streaming uses the same retrieved Q&A context and citation rules as blocking ask.
- Final answer is post-checked for out-of-range citations.
- If the streamed draft is uncited, the API makes one JSON repair call.
- If repair still fails, the API returns the deterministic cited fallback from the
  retrieved story context.
- Busy/offline/not-working states are returned as `final` events.

## Non-goals

- Does not switch the production model.
- Does not make the 4b faster.
- Does not stream structured source metadata repeatedly; sources are emitted once.
