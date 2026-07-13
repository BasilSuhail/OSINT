# The brain, Phase 3 — story enrichment (gist + tags)

**Issue:** #413 (running log)
**Builds on:** #409/#410 (Phase 1 runtime + narrative), #411/#412 (Phase 2 Q&A)
**Lineage:** #282 (analytical agenda), #400 (productization)
**Status:** design approved, spec under review
**Phase:** 3 of 3

---

## 1. Problem

The nightly validator (#378) extracts full structured claims from stories, but only
once a night, with the heavy 4b model. A story that forms at 09:00 waits until ~03:00
for any LLM read. Phase 3 gives each new story a **timely, light first-look**: a
one-line "what this is" gist plus two constrained tags, produced by the 1.5b brain on
idle windows through the day. It complements — never replaces — the nightly claim
layer.

## 2. The binding constraint

Production is an 8GB Pi. Enrichment is **background** (no human waiting), so unlike
Phase 2's Q&A it uses the **strict** gate (`gate.should_run`: RAM headroom AND no
heavy job) and backs off politely. It is **batch-capped and idle-driven, never
continuous** — the constraint that has governed the brain since Phase 1.

## 3. Scope — v1

**In scope:** a `story_gist` table; an idle-gated `brain_enrich` beat task that gists
window stories lacking a gist; the enum-validated prompt/parse; gist surfaced on
`/stories/top` and the Stories card; README §4.6.

**Out of scope (own later issues):** per-event enrichment (higher volume); feeding
gists into the Q&A/narrative context; tag-based filtering UI; backfilling old stories.

## 4. Architecture

Mirrors the Phase 1 narrate task and the validator's idempotency.

### 4.1 The self-block fix (generalize the gate exemption)

Phase 1 fixed a Critical where the narrate task's own `job_run("brain-narrate")` row
made `gate.heavy_job_active` report "heavy job in flight", self-blocking the brain.
It self-exempts via `BRAIN_JOB_NAME = "brain-narrate"`.

`brain_enrich` also runs under `job_run("brain-enrich")` and calls `gate.should_run`.
So the exemption **must generalize to all brain jobs**, or enrich re-introduces the
same Critical. Change `gate.heavy_job_active` to exclude every `brain-`-prefixed job
(e.g. `JobRunRow.job.not_like("brain-%")`), and keep a `BRAIN_JOB_PREFIX = "brain-"`
constant that both `brain-narrate` and `brain-enrich` job names share. Enrich runs
with `evict_brain=False` (it uses the very model it would otherwise evict).

### 4.2 `app/brain/enrich.py`

- `build_gist_prompt(titles: list[str]) -> str` — from a story's member headlines
  (same source the validator uses). Instructs: one short gist describing ONLY what
  the headlines say (no invention); a `category` from the fixed enum; an `escalating`
  from the fixed enum. `format:json`, temperature 0.
- `parse_gist(raw: dict) -> dict` — coerces to
  `{"gist": str, "category": <enum>, "escalating": <enum>}`; any off-enum or missing
  value falls back to `category="other"`, `escalating="unclear"`; gist is truncated
  to a sane length.
- `_enrich_body(*, now=None, batch_limit=None) -> dict` — the worker (below).

### 4.3 The worker

Under `job_run("brain-enrich", evict_brain=False)`:
1. `allowed, reason = gate.should_run(session)` → if not allowed, return a skip
   result (no rows written), leaving stories for the next idle window.
2. Select window stories (last `WINDOW_HOURS`, reuse `app.stories.task.WINDOW_HOURS`)
   with **no `story_gist` row at the current method version**, newest first, capped
   at `batch_limit` (default 20).
3. For each: fetch up to 5 member titles (same query the validator uses), build the
   prompt, call `client.generate_json`, parse, idempotent-insert a `story_gist` row
   (`ON CONFLICT (story_id, method_version) DO NOTHING`, dialect-aware like the
   validator).
4. Return counters (`window_stories`, `enriched`, `skipped_existing`, `failed`).

A model/HTTP failure on one story increments `failed` and continues — one bad story
never aborts the batch.

### 4.4 `story_gist` table + migration 0015

Columns: `id, story_id, gist (Text), category (Text), escalating (Text), model
(Text), method_version (Text), created_at (tz, default now)`. Unique
`(story_id, method_version)`. Index on `created_at`. **30-day retention**, pruned by
housekeeping like `brain_narrative`.

### 4.5 Beat + routing

`brain_enrich` task registered in `app/tasks.py`, `crontab(minute="*/20")`, routed to
the `analytics` queue in `app/celery_app.py`. `make enrich` one-shot
(`app/brain/enrich_run.py`).

## 5. Surface

- `/stories/top` gains `gist / category / escalating` per story: outer-join the
  latest `story_gist` row (current method version) per story. Null until enriched.
- Stories card renders the gist line under the story title and a small tag chip
  (`category` + an "escalating" marker when `escalating == "yes"`). Absent gist →
  nothing shown (graceful).

## 6. Error handling + degradation

- Gate not allowed → skip cleanly, no rows, reason logged.
- Ollama down / model unpulled → per-story `failed`, batch continues; Celery
  `autoretry_for` retries the task, then gives up (logged). No crash.
- Malformed / off-enum model output → `parse_gist` coerces to safe fallbacks; never a
  crash, never an invalid enum in the DB.

## 7. Testing

- **gate:** `heavy_job_active` ignores a `brain-enrich` running row (and any
  `brain-*`) but still detects a `cluster` row — the generalized exemption.
- **enrich prompt/parse:** prompt carries the enum instruction + titles; `parse_gist`
  coerces off-enum/missing to fallbacks and keeps valid values.
- **worker:** seeded stories without gists get exactly one row each (idempotent on
  re-run); gated path writes nothing; a `generate_json` raise marks that story
  `failed` and the batch continues.
- **api:** `/stories/top` includes gist fields; null when unenriched.
- **frontend:** the Stories card renders a gist + tag when present, nothing when
  absent (vitest on the query/parse; component render if a Stories test harness
  exists).

## 8. Documentation

README Chapter 4 gains **§4.6 "Enriching new stories"**: what the gist/tags are, the
idle-gated cadence, the enum vocabulary, and an example story row.

## 9. Deliverables checklist

- [ ] generalize `gate.heavy_job_active` (`brain-` prefix exemption) + `BRAIN_JOB_PREFIX`
- [ ] `app/brain/enrich.py` (prompt, parse, worker) + `enrich_run.py`
- [ ] `story_gist` model + migration 0015 + 30-day retention prune
- [ ] `brain_enrich` task + beat (`*/20`) + analytics routing + `make enrich`
- [ ] `/stories/top` carries gist/category/escalating
- [ ] Stories card shows gist + tag chip
- [ ] tests (gate, prompt/parse, worker, api, frontend)
- [ ] README §4.6
- [ ] progress comments on #413
