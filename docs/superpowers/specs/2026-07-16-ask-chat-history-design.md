# Ask chat history — anchored follow-ups (#444)

Date: 2026-07-16 · Status: approved (Basil, in-session — "go on whats next")

## Problem

Each ask is stateless: "what do u think that was?" arrives with no link to the
previous Iran exchange. #443 fixed *ranking*; nothing fixed *anchoring* — a
vague follow-up has no topic for retrieval to rank against, and the model
cannot resolve "that".

## Design

- **API**: `AskRequest.history` — optional list of ≤3 `AskExchange`
  (`question` ≤500 chars, `answer` ≤4000), on `/brain/ask` and
  `/brain/ask/stream`. Over-cap → 422.
- **Retrieval anchoring**: `qa.build_retrieval_text(question, history)` =
  question + last exchange (answer truncated to 300 chars). Both the embedding
  and the keyword fallback match on this text, so follow-ups inherit the topic.
- **Prompt**: `RECENT CONVERSATION` block (last 3 turns, answers truncated)
  before CONTEXT, instructing the model to use it only for resolving
  references and to answer only the new question. Same for the text prompt.
- **Frontend**: `askHistory(messages)` picks the last 3 finalized transcript
  turns (skips drafts and offline failures, truncates answers to 2000 chars);
  `fetchBrainAsk`/`streamBrainAsk` gain a `history` parameter; `useBrainChat`
  snapshots history before dispatching the new draft.

## Verified live (dev box, real DB + nomic-embed-text)

2385 window stories backfilled in one batch (0 failures). Anchored
"whatt explosions? what do u think that was?" retrieves six Iran/US/Hormuz
stories; the bare question keeps the Qeshm explosion #1 (semantic fix) but its
tail drifts to unrelated fires.

## Out of scope

- Server-side session state — history rides each request; the transcript
  (sessionStorage, #439) remains the single store.
- Alt-source ingestion (#442).
