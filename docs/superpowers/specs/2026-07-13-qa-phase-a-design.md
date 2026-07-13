# Q&A Phase A — richer context + cited sources

**Tracking issue:** #413 (pinned, permanent brain Q&A roadmap)
**Status:** design under review
**Phase:** A of A–D (see #413 roadmap comment)
**Scope:** backend context + prompt + endpoint + frontend. Keeps the 1.5b model
(bigger model = Phase C). No question-driven retrieval (Phase B), no streaming (Phase D).

---

## 1. Goal

Make ask-the-brain answers **grounded in the trust signals we already compute and
show their sources**. Today the context is a thin snapshot + 3 headline facts, and the
answer is one key with no provenance. Phase A feeds the top stories *with their
corroboration / contested / sensor signals + outlet sources*, prompts the model to use
and flag them, and returns a **`sources`** list the UI renders under the answer.

Honest expectation: Phase A improves grounding + transparency + citations. Answer
*depth/reasoning* stays capped by the 1.5b until Phase C (bigger model). This phase is
about **trustworthiness and provenance**, not raw eloquence.

## 2. What we add

### 2.1 `build_qa_stories(session, *, limit=6) -> list[dict]`

Top `limit` stories (loudest first, last 72h), each a numbered, provenance-tagged dict:

```python
{
  "n": 1,                          # 1-based citation number
  "story_id": 6420,
  "title": "...",
  "gist": "..." | None,            # Phase-3 gist
  "corroboration": 0.8 | None,     # StoryCorroborationRow.score (independent tellers)
  "outlet_count": 8,
  "owner_count": 3,                # independent owners (10 wire copies = 1)
  "divergence": 0.83 | None,       # StoryDisagreementRow.divergence
  "contested": true,               # divergence >= CONTESTED_THRESHOLD
  "sensor": {"earthquake": "confirmed"} | {},  # StorySensorCheckRow verdicts
  "sources": ["Reuters", "Al Jazeera", "BBC"], # top 3 distinct outlets from members
}
```

Reuses the exact tables `/stories/top` already reads (`StoryRow`,
`StoryCorroborationRow`, `StorySensorCheckRow`, `StoryGistRow`) plus
`StoryDisagreementRow` (divergence) and `StoryMemberRow`→`EventRow` (outlets, top 3
distinct). Bounded to `limit` stories so the prompt stays inside `num_ctx 2048`.

### 2.2 `build_qa_context` gains `stories`

`build_qa_context` adds `"stories": build_qa_stories(session)` alongside the existing
snapshot + headline facts. The rest is unchanged.

### 2.3 `build_qa_prompt` — cite + flag

The prompt is upgraded to instruct (still no-fabrication, still `{"answer": ...}`):

- Answer using the **numbered stories**; when a claim rests on a story, cite it as
  `[n]`.
- **Flag trust**: call out a story that is **single-source** (low corroboration /
  `owner_count == 1`), **contested** (`contested: true`), or **sensor-unconfirmed** vs
  **sensor-confirmed**.
- Prefer **corroborated** stories; do not present a single-teller claim as established
  fact.
- Still: answer only from the context; exact refusal string otherwise.

## 3. Endpoint: `POST /brain/ask` returns `sources`

Response becomes:

```json
{
  "answer": "...",
  "context_digest": "sha256:…",
  "sources": [
    {"n": 1, "story_id": 6420, "title": "...", "outlets": ["Reuters","Al Jazeera"],
     "corroboration": 0.8, "contested": false}
  ]
}
```

- `sources` = the numbered context stories (always real — they are what we grounded on,
  so the UI can always show honest provenance even if the model's prose cites poorly).
- **Citation post-check**: strip any `[n]` in the answer where `n` is out of range
  `1..len(sources)` (cheap regex guard against invented citation numbers). The `answer`
  otherwise passes through the existing busy/offline/malformed guards unchanged.
- Busy / offline / malformed paths return `sources: []`.

## 4. Frontend

The ask box renders, under each answer, a compact **sources** line: the numbered
outlets, with a small marker when a source is **contested** (⚠) or **single-teller**.
Reuses the existing `fetchBrainAsk`; extend `BrainAsk` with `sources`.

## 5. Non-goals (later phases / own issues, per #413)

- Question-driven retrieval (Phase B) — Phase A uses the top-loudest stories, not
  question-matched ones.
- Bigger model (Phase C).
- Streaming (Phase D).
- The **human-eval agreement rate** — needs answers to accumulate first; its own
  follow-up (mirrors the validator's #386 discipline).

## 6. Testing

- `build_qa_stories`: seed stories + corroboration + disagreement + sensor + members;
  assert each story carries the signals + top-3 distinct outlets + `contested` flag;
  bounded to `limit`.
- `build_qa_prompt`: asserts the cite/flag instructions + numbered stories present +
  bounded length.
- endpoint: `sources` present + shaped on the happy path; out-of-range `[n]` stripped
  from the answer; `sources: []` on busy/offline.
- frontend: `fetchBrainAsk` parses `sources`; a `.mts` test.
- **Live smoke**: real model answers a real question and the returned `sources` are the
  genuine top stories with outlets.

## 7. Deliverables

- [ ] `build_qa_stories` + `build_qa_context` extension
- [ ] `build_qa_prompt` cite/flag upgrade
- [ ] `/brain/ask` returns `sources` + citation post-check
- [ ] frontend sources rendering
- [ ] tests + live smoke
- [ ] detailed progress comments on #413
