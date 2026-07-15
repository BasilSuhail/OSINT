# Q&A eval rubric — design (#413 roadmap item 1)

Date: 2026-07-15
Issue: #413 (answer-evaluation plan, first roadmap item)
Branch: `feat-qa-eval-rubric`

## Problem

`make brain-qa-eval` currently measures only citation syntax (valid `[n]`
citations, latency). The live failure it cannot catch: the system answered
"is the war back on?" with a cited typhoon story. Safe citation is not enough —
the answer must be relevant, uncertainty-aware, and willing to refuse when
local evidence is missing. Without a measured rubric, every model/retrieval
change is guesswork. 1.5b scored 0/4 and 4b 3/4 on the citation-only eval; we
need per-dimension quality numbers to pick a model policy (roadmap item 8).

## Decisions (settled in brainstorm)

- Scoring: **deterministic heuristics** — pure code checks, reproducible,
  zero extra RAM on the Pi. No LLM-as-judge (self-bias, slow). Human audit is
  roadmap item 9, separate.
- Overall pass: answer passes only if **every rubric dimension passes**.
- `make brain-qa-eval` always **exits 0** — measurement tool, not CI gate.
- Claude posts the 1.5b vs 4b results table as a #413 comment after the run.

## Architecture

New module `app/brain/qa_rubric.py` — pure functions, no DB/model imports,
unit-testable without Ollama. `app/brain/qa_eval.py` keeps orchestration
(retrieval, model calls, citation repair, report) and calls the rubric.

```python
@dataclass(frozen=True)
class EvalQuestion:
    question: str
    topic_terms: tuple[str, ...]  # lowercase; story relevant if title+gist hits >= 1
    risky: bool                   # loaded question -> uncertainty framing required
    mode: str = "topic"           # "topic" | "sensor" | "contested" | "coverage"

EVAL_QUESTIONS: tuple[EvalQuestion, ...]

def relevant_sources(spec, stories) -> list[int]
def score_answer(spec, *, answer, stories, invalid_citations) -> dict
# {"relevance": bool, "citation": bool, "uncertainty": bool, "contested": bool,
#  "refusal": bool, "usefulness": bool, "passed": bool, "reasons": [str, ...]}
```

## Fixed question set

From the #413 plan comment, each annotated with topic terms + flags:

| Question | mode | risky |
|---|---|---|
| is the war back on? | topic (war, ceasefire, strike, iran, israel, conflict, attack, truce, mideast, military) | yes |
| did the ceasefire collapse? | topic (ceasefire, truce, collapse, war, iran, israel, strike, mideast) | yes |
| what happened in Iran? | topic (iran, iranian, tehran) | yes |
| what is sensor confirmed? | sensor | no |
| where is coverage thin? | coverage | no |
| what is contested right now? | contested | no |

## Relevance ground truth per mode

- `topic`: story relevant if its title+gist text contains >= 1 topic term.
- `sensor`: story relevant if its `sensor` dict is non-empty.
- `contested`: story relevant if `contested: true`.
- `coverage`: no story metadata encodes coverage thinness, so every story is a
  valid grounding (`relevant_sources` returns all story numbers) and refusal is
  also acceptable. A non-refusal answer must additionally contain coverage
  language (`coverage`, `source`, `outlet`, `thin`, `few`, `only`) — checked in
  the relevance dimension.

All marker/term matching is lowercase substring matching.

## Rubric dimensions

Definitions: `refusal` = answer exactly `REFUSAL_ANSWER`; `cited` = valid `[n]`
after strip; `relevant_ns` = `relevant_sources(spec, stories)`.

| Dim | Pass rule |
|---|---|
| refusal | refusal ∧ no relevant sources → pass. refusal ∧ relevant exist → FAIL; coverage mode: refusal always acceptable. non-refusal ∧ no relevant sources → FAIL. non-refusal ∧ relevant exist → pass |
| relevance | refusal → pass (n/a). else `set(cited) ∩ set(relevant_ns)` non-empty; coverage mode additionally requires a coverage-language marker in the answer. Cited-typhoon-for-war-question fails here |
| citation | refusal → pass. else `citation_ok` ∧ pre-strip `invalid_citations == []` (invalid citations count against the model even though production strips them) |
| uncertainty | required iff `risky` or any cited story is weak (contested, `owner_count == 1`, corroboration < 0.5, or a non-confirmed sensor verdict). If required, answer must contain >= 1 marker: contested, disputed, single, unconfirmed, not confirmed, unverified, claim, reported, unclear, unknown, no local evidence, insufficient. Not required → pass |
| contested | any cited story `contested: true` → answer must contain contested/disputed/disagree. None → pass |
| usefulness | refusal → pass (refusal quality is the refusal dim's job). else answer length >= 40 chars ∧ shares >= 2 content tokens (len >= 4, not in `qa._QUESTION_STOPWORDS`) with some cited story's title+gist |

`passed` = all six. Rows where the model errored (`ok: false`): all dims fail,
reason = the error. `reasons` = human-readable fail strings in the MD report
(seed for roadmap item 10, the "question understood" trace).

## qa_eval.py changes

- `DEFAULT_QUESTIONS` (bare strings) → `qa_rubric.EVAL_QUESTIONS` (specs).
- `evaluate_answer` unchanged model/citation flow; adds `rubric` key to each
  row; scores error rows too.
- Report: summary table gains per-dim pass counts + overall `rubric X/6` per
  model; per-run sections list failed dims + reasons.
- Exit code stays 0; export paths unchanged
  (`data/exports/brain-qa-model-eval.{json,md}`).

## Testing

- `tests/test_brain_qa_rubric.py` (new, pure unit): wrong-topic citation fails
  relevance; refusal-with-evidence fails; refusal-without-evidence passes;
  risky answer without uncertainty marker fails; contested cited story without
  contested/disputed wording fails; short/generic answer fails usefulness;
  sensor/contested/coverage modes.
- `tests/test_brain_qa_eval.py` extended: rows carry `rubric`; summary MD has
  per-dim columns; error row → all-fail rubric.
- Existing tests stay green. CI: pytest + `ruff check` + `ruff format --check`.
  No live eval in CI.

## Run + logging flow (post-merge, local)

1. `make brain-qa-eval` → 6 questions × 2 models (current brain model 1.5b +
   validator 4b via existing `candidate_models()`).
2. Writes JSON + MD exports as today.
3. Post #413 comment: per-model rubric pass X/6, per-dim pass counts, median
   latency, verdict line.

## Out of scope (later roadmap items)

Retrieval intent/entity biasing (item 2), fallback split (item 3),
sentence-level claim checks (item 4), model policy decision (item 8 — made
after this eval's numbers exist), human audit sheet (item 9).
