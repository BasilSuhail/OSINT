# The brain — resource-aware local LLM + live situation narrative

**Issue:** #409 (running log)
**Lineage:** #282 (analytical agenda), #252 (situational-awareness console), #400 (productization)
**Status:** design approved, spec under review
**Phase:** 1 of 3

---

## 1. Problem

The app has no self-awareness. It ingests, scores, and clusters, but a human must read
raw panels to understand *what is going on* — both in the world signal and in the pipeline
itself. We want to give the system "its own brains": a light local model that runs when
there is headroom and narrates the current situation in plain English.

Two coupled pieces:

- **Feature A — brain runtime.** A resource-aware wrapper around a small local model:
  kept warm during idle windows, evicted the instant the box gets busy.
- **Feature B — situation narrative.** A periodic plain-English summary of the world signal
  *and* the system state, surfaced as a dashboard card.

## 2. The binding constraint

Production target is an **8GB Raspberry Pi** (development on a MacBook already ~15GB deep).
A literally-always-resident model fights scraping and the analytical batch for RAM and will
OOM the Pi. Therefore the design is **adaptive keep-alive**, not a pinned model:

- warm during idle windows (answers instantly),
- **evicted the moment a heavy job starts**,
- reloaded when idle returns.

This "feels always-on" in quiet windows without starving the Pi. The word *continuous* is
deliberately avoided for enrichment (Phase 3) for the same reason — continuous LLM load is
exactly the state the backoff rule exists to prevent.

## 3. Scope — Phase 1 only

In scope: Feature A (runtime) + Feature B (situation narrative). Out of scope, deferred to
their own specs/PRs:

- **Phase 2** — ask-the-app Q&A (reuses the runtime + narrative context).
- **Phase 3** — enrichment on incoming items; likely stays nightly-batch or "near-real-time
  on idle", not continuous.

## 4. Architecture decision

The brain runs as a **Celery beat task on the existing `analytics` queue**, not a standalone
daemon and not an on-demand API call.

| Option | Verdict |
|--------|---------|
| A. Standalone `brain/daemon.py` process | Rejected — new supervised process, can overlap heavy jobs, more PID/log plumbing. |
| **B. Celery beat task on `analytics` queue** | **Chosen.** |
| C. On-demand in the API | Rejected — user waits, loads model on the API process (bad on Pi), not always-on. |

Option B wins because the `analytics` queue is **concurrency-1**: the brain task *physically
cannot* run while another heavy job runs — automatic mutual exclusion, no locking. It also
reuses the beat schedule, `job_run` heartbeats, and retention housekeeping already in the
repo. The "always-on" feel comes from Ollama `keep_alive` holding the model warm between the
frequent beat ticks.

## 5. Feature A — brain runtime (`app/brain/`)

### 5.1 `gate.py` — "may the brain run right now?"

```
should_run() -> tuple[bool, str]   # (allowed, human reason)
    allowed = ram_free_mb() >= settings.brain_min_free_mb
              AND not _heavy_job_active()
```

- `ram_free_mb()` — stdlib only. Linux (Pi): parse `MemAvailable` from `/proc/meminfo`.
  macOS (dev): parse `vm_stat` pages × page size. **No `psutil`, no new dependency.**
- `_heavy_job_active()` — a `job_runs` row with `status="running"` and
  `heartbeat_at` within the last 90s. This already tracks every heavy analytical job
  (stories, journal, panel, composite, validator, onset, briefing, …); scraping fetchers are
  I/O-bound and intentionally excluded, so this is a true "heavy work in progress" signal.

Both checks are cheap (one file read, one indexed query). Returns a reason string so the
task log and the degraded card can say *why* the brain skipped.

### 5.2 `client.py` — Ollama call for the brain model

Mirrors `app/validator/client.py` (httpx, localhost, nothing leaves the machine).

- model = `settings.brain_model` (`qwen2.5:1.5b-instruct-q4_K_M`).
- `format:json`, `think:false`, `temperature 0`, `num_ctx 2048`.
- **Adaptive `keep_alive`:** `generate_json(...)` passes `keep_alive="30m"` so the model stays
  warm between ticks. A separate `evict()` posts a trivial request with `keep_alive=0` to
  unload immediately.

### 5.3 Eviction hook in `job_run()`

`app/jobs/heartbeat.py` `job_run()` is the single choke point every heavy job passes through
at start. Add a **best-effort** `brain.evict()` call at row-start (guarded by
`settings.brain_enabled`, wrapped so any failure is swallowed and never affects the job).
Result: the 1.5b model backs off *before* the pandas parse grabs RAM — the "back off when
busy" behaviour, wired where it belongs.

### 5.4 Settings (`app/settings.py`)

- `brain_enabled: bool = True` — kill-switch.
- `brain_model: str = "qwen2.5:1.5b-instruct-q4_K_M"`.
- `brain_min_free_mb: int = 1200` — refuse to load unless this much RAM is free.
- `brain_keep_alive: str = "30m"`.

## 6. Feature B — situation narrative

### 6.1 `context.py` — the snapshot builder

Builds a compact, **pre-digested** snapshot from existing read paths — the functions behind
`/stories/top`, `/composite/movers`, `/disagreement/top`, `/journal/scoreboard`,
`/jobs/recent`, `/ingest-health`. The model is fed **numbers and short labels, not raw rows**,
so the prompt stays inside `num_ctx 2048` and stays cheap on the Pi. A stable `input_digest`
(hash of the snapshot) is stored so we can tell when the narrative is stale vs merely
re-rendered.

### 6.2 The narrative payload

One JSON object per run:

```json
{
  "headline": "one line: the single most important thing right now",
  "world":    "2-4 sentences on the signal (stories, movers, disagreement)",
  "system":   "1-2 sentences: pipeline healthy? what ran or failed?",
  "watch":    ["short bullet", "short bullet"],
  "as_of":    "ISO-8601",
  "model":    "qwen2.5:1.5b-instruct-q4_K_M",
  "input_digest": "sha256:…"
}
```

**Guardrail:** the prompt instructs the model to *describe only the provided numbers and
invent nothing* — the same discipline as the validator. The brain narrates; it never
fabricates facts.

### 6.3 `brain_narrate` beat task

- Registered in `app/tasks.py`, routed to the **`analytics`** queue.
- Cadence: `crontab(minute="*/15")` — every 15 min, gated.
- Body: `gate.should_run()` → if not allowed, log the reason and **skip** (leaving the last
  narrative in place, which the card renders as stale/degraded); if allowed,
  `context.build_snapshot()` → `client.generate_json()` → persist a `brain_narrative` row.
- Wrapped in `job_run("brain-narrate")` for heartbeat visibility like every other job.

### 6.4 Storage + retention

- New `brain_narrative` table: `id`, `created_at`, `model`, `payload` (JSON), `input_digest`.
- **30-day retention** (project storage rule), pruned by the existing housekeeping job.

### 6.5 API + frontend

- `GET /brain/narrative/latest` → newest row (or a well-typed "no narrative yet" shape).
- New **"Situation" card** at the top of the dashboard deck: headline / world / system /
  watch + as-of + model badge. When the latest narrative is older than ~2 ticks or the brain
  is disabled/evicted, the card renders a **degraded state** ("brain resting — box busy") so
  backoff is *visible*, never a silent lie.

## 7. Data flow

```
beat tick (every 15m)
  └─ job_run("brain-narrate")
       └─ gate.should_run()?
            ├─ no  → log reason, skip (last narrative marked stale)
            └─ yes → context.build_snapshot()
                       └─ client.generate_json(prompt, keep_alive=30m)
                            └─ persist brain_narrative row
                                 └─ frontend polls /brain/narrative/latest
heavy job starts anywhere
  └─ job_run(...) start → brain.evict()  (keep_alive=0, best-effort)
```

## 8. Error handling + degradation

- Ollama down / model unpulled → `client` raises → task logs, no row written, card shows the
  last good narrative as stale. No crash, no retry storm.
- `brain_enabled=False` → task returns immediately; eviction hook is a no-op; card shows
  "brain off".
- Malformed model JSON → caught, logged, skipped (no partial row).

## 9. Testing

- **gate:** `/proc/meminfo` and `vm_stat` parse fixtures; `_heavy_job_active` with a seeded
  running row (fresh vs stale heartbeat).
- **client:** mock httpx — assert adaptive `keep_alive` on generate and `keep_alive=0` on
  `evict()`.
- **context:** seed the DB, assert the snapshot is bounded and contains the expected fields.
- **task:** allowed path persists exactly one row; gated path persists none and logs a reason.
- **api:** `/brain/narrative/latest` returns the newest row and the empty shape when none.

## 10. Documentation

- README: insert a **new Chapter 4 "The brain"**; the current Chapter 4 "How to read the
  dashboard" moves to **Chapter 5** (chapters index + heading + internal cross-references
  updated). Chapter 4 documents: what the brain is, the gate rules, the eviction behaviour,
  `ollama pull qwen2.5:1.5b-instruct-q4_K_M`, and a worked **actual vs expected output**
  sample of a situation narrative.

## 11. Deliverables checklist

- [ ] `app/brain/{__init__,gate,client,context}.py`
- [ ] eviction hook in `app/jobs/heartbeat.py`
- [ ] settings additions
- [ ] `brain_narrative` DB model + migration + housekeeping prune
- [ ] `brain_narrate` beat task + schedule
- [ ] `GET /brain/narrative/latest`
- [ ] "Situation" card (frontend) with degraded state
- [ ] tests (gate, client, context, task, api)
- [ ] README Chapter 4 (brain) + Chapter 5 renumber
- [ ] progress comments on #409
