# The brain, Phase 2 — ask-the-app Q&A

**Issue:** #411 (running log)
**Builds on:** #409 / #410 (Phase 1: the brain runtime + situation narrative)
**Lineage:** #282 (analytical agenda), #400 (productization)
**Status:** design approved, spec under review
**Phase:** 2 of 3

---

## 1. Problem

Phase 1 gave the app a brain that *narrates* on its own schedule. Phase 2 lets a
human *ask* it a question and get a plain-English answer grounded in the live data —
"is anything escalating right now?", "which story is most contested?" — without
reading raw panels.

## 2. The binding constraint (unchanged)

Production is an 8GB Raspberry Pi. The Q&A path loads the same small model
(`qwen2.5:1.5b`) over localhost. Because Q&A is **user-initiated and synchronous**
(the human is actively waiting), it does *not* back off the way the scheduled
narrative does — but it must still refuse gracefully rather than OOM the Pi when RAM
is genuinely low.

## 3. Scope — v1

**In scope:**
- A synchronous `POST /brain/ask` endpoint.
- A Q&A context builder that reuses Phase 1's snapshot plus three lightweight
  headline facts.
- A no-fabrication prompt and a small answer shape.
- An ask box inside the existing Situation card.

**Out of scope (each its own later issue):**
- Multi-turn conversation memory.
- Question-driven retrieval over arbitrary countries/stories (v1 context is fixed,
  not parsed from the question).
- A persisted Q&A audit log (v1 is ephemeral).
- Streaming token responses.

## 4. Architecture

Q&A runs as a **synchronous FastAPI endpoint**, not a Celery job.

- The human is actively waiting, so a few-second blocking response is the right UX;
  async + polling would add a job row and a poll loop for no gain.
- The endpoint calls Ollama over HTTP (`client.generate_json`); the model lives in
  the Ollama process, not the API process, so a blocked API worker is only waiting on
  I/O. Fine for a single-user local dashboard.

New module `app/brain/qa.py`, two pure functions + the endpoint wiring:

### 4.1 `build_qa_context(session) -> dict`

Reuses Phase 1's `context.build_snapshot(session)` verbatim, then adds three
**lightweight** headline facts (each ≤ 1–2 cheap queries — exact queries pinned in
the plan, not full endpoint logic, to keep the prompt small and the Pi cheap):

- **latest composite** — most recent composite `bucket_start` + global mean, and the
  single highest-stress country in that bucket (a headline proxy for "movers").
- **latest scoreboard grade** — the most recent prediction-journal grade headline.
- **most-contested story** — the top `StoryDisagreementRow` by divergence, with its
  title.

Returns one compact dict; the whole thing is small enough to sit inside `num_ctx
2048` alongside the question.

### 4.2 `build_qa_prompt(context, question) -> str`

Instructs the model: *answer the question using ONLY the supplied context; if the
context does not contain the answer, say "I don't have data on that." Invent no
facts.* Same no-fabrication discipline as the narrative. Embeds the compact context
JSON and the user's question.

### 4.3 The gate — RAM floor only

Q&A does **not** call `gate.should_run` (which also backs off on any active heavy
job). Instead it checks only the hard safety floor:

```
if gate.ram_free_mb() < settings.brain_min_free_mb:
    return {"answer": "Brain busy — the box is loaded right now, try again in a moment.",
            "context_digest": None}
```

Rationale: a user asking a question wants an answer even while a routine job ticks;
refusing on every `job_run` would make Q&A feel broken. The RAM floor is the real
OOM guard on the Pi and is sufficient.

## 5. API contract

`POST /brain/ask`

- Request: `{"question": str}` (rejected with 422 if empty/missing; capped length,
  e.g. 500 chars, to bound the prompt).
- Response: `{"answer": str, "context_digest": str | None}` where `context_digest`
  is `context.input_digest`-style hash of the grounding context (null on the busy
  path). No persistence.
- Ollama down / model unpulled → the client raises; the endpoint catches it and
  returns `{"answer": "The brain is offline right now.", "context_digest": None}`
  with HTTP 200 (a graceful, typed answer, not a 500) so the UI degrades cleanly.

## 6. Frontend — ask box in the Situation card

Extend `SituationPanel.tsx`:

- A text input + send button below the narrative.
- On submit → `fetchBrainAsk(question)` (new fetcher in `apiClient.ts`) → append the
  `{question, answer}` pair to a **component-state** list (not persisted; cleared on
  reload). Show a small "thinking…" state while the request is in flight.
- Empty input is a no-op; the input disables while a request is pending.

No new deck slot, no new card — the brain stays one cohesive surface.

## 7. Error handling + degradation

- RAM below floor → graceful "brain busy" answer (§4.3).
- Ollama down/unpulled → graceful "brain offline" answer (§5).
- Model returns malformed JSON → caught, returns "I couldn't form an answer just
  now." (never a 500).
- Empty/oversized question → 422 (validated by the request model).

## 8. Testing

- **qa context:** seed in-memory SQLite; assert `build_qa_context` contains the
  snapshot keys plus the three extra facts, and that the context stays compact.
- **qa prompt:** asserts the no-fabrication instruction and the question are present,
  bounded length.
- **endpoint (TestClient + StaticPool):** happy path returns an answer (model
  mocked); empty question → 422; RAM-below-floor path returns the busy answer without
  calling the model (gate mocked); Ollama-raises path returns the offline answer.
- **frontend (vitest):** `fetchBrainAsk` posts the question and parses the answer.

## 9. Documentation

- README Chapter 4 ("The brain") gains a short **§4.x "Ask the app"** subsection:
  what `POST /brain/ask` does, the RAM-floor behaviour, an example question/answer,
  and that it's grounded + non-fabricating.

## 10. Deliverables checklist

- [ ] `app/brain/qa.py` — `build_qa_context`, `build_qa_prompt`
- [ ] `POST /brain/ask` endpoint + request/response models
- [ ] `fetchBrainAsk` + ask box in `SituationPanel.tsx`
- [ ] tests (qa context, qa prompt, endpoint 4 paths, frontend fetcher)
- [ ] README §4.x "Ask the app"
- [ ] progress comments on #411
