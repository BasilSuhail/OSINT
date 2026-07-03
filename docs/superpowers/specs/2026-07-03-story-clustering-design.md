# WS-A Story Clustering — Design

**Issue:** #296 · **Part of:** #282 (analytical agenda, WS-A; unlocks WS-B, WS-C)

## Problem

The same real-world event arrives once per feed under different words. Until articles
are grouped into stories, every news count is inflated and outlets cannot be compared.
Two articles can use different words and mean the same thing — the similarity model
finds the common ground.

## Scope

- **In:** `stories` + `story_members` tables (migration 0005), `app/stories/` package,
  30-minute beat task, `make stories` CLI + `$OSINT_DATA_DIR/exports/stories-report.md`.
- **Out:** sentence embeddings (v2 — swap the vectorizer behind the same interface once
  v1 clusters are measured against a hand-checked sample), WS-B tone scoring, WS-C
  corroboration, frontend.

## Method (stories-v1.0 — deliberately basic)

1. **Tokenize** headline (`payload.title`): lowercase, alphanumeric tokens, drop a small
   builtin stopword list and tokens shorter than 3 chars.
2. **Vector** = TF-IDF over the rolling window corpus (titles are short → tf is ~binary;
   idf downweights boilerplate like "news", "live", "update"). Pure Python/numpy.
3. **Cluster** greedily in `occurred_at, id` order: an unassigned article joins the
   existing story with the highest **cosine ≥ 0.35** against the story's token centroid
   (mean of member vectors), else founds a new story. Deterministic given the data.
   (0.35 chosen from worked examples: paraphrase pairs score ~0.6+, same-story
   new-angle headlines ~0.4, unrelated pairs ~0.0–0.1; to be tuned against a
   hand-checked sample in v2.)
4. **Window**: 72 h. Stories close naturally when their members age out of the window;
   membership is never revisited (incremental, append-only).

## Storage (migration 0005)

`stories`: id, method_version, first_seen, last_seen, title (first member's headline),
member_count, outlet_count. `story_members`: event_id (unique), story_id, similarity,
added_at. `outlet_count` = distinct `events.source` among members — the direct input
for WS-C corroboration.

## Components

| File | Responsibility |
|---|---|
| `app/stories/vectorize.py` | Pure: tokenize, idf, tf-idf vectors, cosine. |
| `app/stories/cluster.py` | Pure: (articles, existing assignments) → new assignments + new stories. |
| `app/stories/task.py` | `_cluster_stories_body`: load window news events + assignments, run cluster, persist. Thin task + beat entry (30 min) in `app/tasks.py`. |
| `app/stories/run.py` | CLI: run body once, print top multi-outlet stories of last 24 h, write report. `make stories`. |

## Testing (TDD)

- vectorize: tokenizer (case, punctuation, stopwords, short tokens); cosine on known
  vectors; idf downweights a token present in every title.
- cluster: paraphrase headlines cluster ("Quake strikes Tokyo, dozens injured" /
  "Dozens hurt as earthquake hits Tokyo"); unrelated headlines don't; same story from
  three outlets → one story, outlet_count 3; incremental run assigns a new article to
  the existing story without touching prior assignments; empty input no-op.
- task: persistence round-trip on SQLite (assignments survive, counts updated).

## Verification

`make stories` on live DB: clusters form over the real RSS window; top story list is
plausible (same event, several feeds); rerun without new events → 0 new assignments.
