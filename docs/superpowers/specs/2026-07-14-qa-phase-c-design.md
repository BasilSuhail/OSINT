# Q&A Phase C — bigger model evaluation

**Tracking issue:** #413
**Scope:** compare the current 1.5b Q&A brain model with the validator's 4b model
before changing production defaults.

## Goal

Phase C answers whether the bigger local model is worth the latency and RAM cost on
the 8 GB Pi. This phase adds an evaluation harness and report artifact. It does not
silently switch `/brain/ask` to the 4b.

## Design

`app.brain.qa_eval` runs a small fixed question set through each candidate model:

- current brain model: `settings.brain_model`
- validator 4b model: `settings.ollama_model`

Each run uses the same Phase B question-retrieved context and the same Phase A
source/citation prompt. The harness records:

- model
- question
- elapsed milliseconds
- answer
- context digest
- source count
- cited source numbers
- invalid citation numbers
- error, if the model call failed

The generated artifacts live under `data/exports/`:

- `brain-qa-model-eval.json`
- `brain-qa-model-eval.md`

## Non-goals

- No cloud model calls.
- No new dependencies.
- No production model switch.
- No human-grade quality score yet. The human-eval rate remains its own follow-up.
