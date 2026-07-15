# Q&A Eval Rubric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand `make brain-qa-eval` from citation-syntax checking into a deterministic rubric evaluator (relevance, citation, uncertainty, contested, refusal, usefulness) over a fixed risky-question set, then run 1.5b vs 4b and log results to #413.

**Architecture:** New pure module `app/brain/qa_rubric.py` (question specs + scoring, no DB/model imports) consumed by the existing orchestrator `app/brain/qa_eval.py` (retrieval, model calls, citation repair, report). Spec: `docs/superpowers/specs/2026-07-15-qa-eval-rubric-design.md`.

**Tech Stack:** Python 3.14, pytest, ruff, Ollama (live run only), gh CLI (issue comment).

## Global Constraints

- Branch `feat-qa-eval-rubric` off origin/main; 1 PR referencing #413; Basil merges (squash → 1 commit on main).
- NO `Co-Authored-By` / "Generated with Claude" lines in commits or PR.
- CI gates: `pytest`, `ruff check .`, `ruff format --check .` — all must pass before push.
- `make brain-qa-eval` always exits 0 (measurement tool, not a gate).
- Rubric scoring is pure/deterministic — no LLM-as-judge, no network, no DB in `qa_rubric.py`.
- Sensor verdict strings in this codebase are exactly `"confirmed"` and `"unconfirmed"` (see `app/corroboration/rules.py`).
- `REFUSAL_ANSWER` is exactly `"I don't have data on that."` (`app/brain/qa.py:119`).
- All marker/term matching is lowercase substring matching.

---

### Task 1: `qa_rubric` module — `EvalQuestion`, `EVAL_QUESTIONS`, `relevant_sources`

**Files:**
- Create: `app/brain/qa_rubric.py`
- Test: `tests/test_brain_qa_rubric.py`

**Interfaces:**
- Consumes: nothing new (stdlib + dataclasses).
- Produces: `EvalQuestion(question: str, topic_terms: tuple[str, ...] = (), risky: bool = False, mode: str = "topic")` frozen dataclass; `EVAL_QUESTIONS: tuple[EvalQuestion, ...]` (6 entries); `relevant_sources(spec: EvalQuestion, stories: list[dict]) -> list[int]`; `DIMENSIONS: tuple[str, ...]`. Story dicts are the ones `qa.build_qa_stories` emits: keys `n, story_id, title, gist, corroboration, outlet_count, owner_count, divergence, contested, sensor, sources`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_brain_qa_rubric.py
from app.brain import qa_rubric


def _story(n: int, title: str, **kw):
    return {
        "n": n,
        "story_id": n * 100,
        "title": title,
        "gist": kw.pop("gist", None),
        "corroboration": kw.pop("corroboration", 0.8),
        "outlet_count": kw.pop("outlet_count", 3),
        "owner_count": kw.pop("owner_count", 2),
        "divergence": kw.pop("divergence", None),
        "contested": kw.pop("contested", False),
        "sensor": kw.pop("sensor", {}),
        "sources": kw.pop("sources", ["Reuters"]),
    }


WAR = next(q for q in qa_rubric.EVAL_QUESTIONS if q.question == "is the war back on?")
SENSOR = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "sensor")
CONTESTED = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "contested")
COVERAGE = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "coverage")


def test_eval_questions_cover_issue_set():
    questions = {q.question for q in qa_rubric.EVAL_QUESTIONS}
    assert questions == {
        "is the war back on?",
        "did the ceasefire collapse?",
        "what happened in Iran?",
        "what is sensor confirmed?",
        "where is coverage thin?",
        "what is contested right now?",
    }
    assert all(q.risky for q in qa_rubric.EVAL_QUESTIONS if q.mode == "topic")


def test_relevant_sources_topic_mode_matches_title_and_gist():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes"),
        _story(3, "Markets rally", gist="Ceasefire hopes lift stocks."),
    ]
    assert qa_rubric.relevant_sources(WAR, stories) == [2, 3]


def test_relevant_sources_sensor_mode_needs_sensor_dict():
    stories = [
        _story(1, "Wildfire in Spain", sensor={"fire": "confirmed"}),
        _story(2, "Political speech"),
    ]
    assert qa_rubric.relevant_sources(SENSOR, stories) == [1]


def test_relevant_sources_contested_mode_needs_contested_flag():
    stories = [_story(1, "A", contested=True), _story(2, "B")]
    assert qa_rubric.relevant_sources(CONTESTED, stories) == [1]


def test_relevant_sources_coverage_mode_accepts_all():
    stories = [_story(1, "A"), _story(2, "B")]
    assert qa_rubric.relevant_sources(COVERAGE, stories) == [1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.brain.qa_rubric'` (or ImportError).

- [ ] **Step 3: Write minimal implementation**

```python
# app/brain/qa_rubric.py
"""Deterministic rubric scoring for the brain Q&A eval (#413 roadmap item 1).

Pure functions: no DB access, no model calls. qa_eval orchestrates retrieval
and model answers, then calls score_answer per run. An answer passes only if
every rubric dimension passes; reasons explain each failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DIMENSIONS: tuple[str, ...] = (
    "relevance",
    "citation",
    "uncertainty",
    "contested",
    "refusal",
    "usefulness",
)


@dataclass(frozen=True)
class EvalQuestion:
    """One eval question plus its deterministic relevance ground truth."""

    question: str
    topic_terms: tuple[str, ...] = ()
    risky: bool = False
    mode: str = "topic"  # topic | sensor | contested | coverage


EVAL_QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        question="is the war back on?",
        topic_terms=(
            "war",
            "ceasefire",
            "strike",
            "iran",
            "israel",
            "conflict",
            "attack",
            "truce",
            "mideast",
            "military",
        ),
        risky=True,
    ),
    EvalQuestion(
        question="did the ceasefire collapse?",
        topic_terms=(
            "ceasefire",
            "truce",
            "collapse",
            "war",
            "iran",
            "israel",
            "strike",
            "mideast",
        ),
        risky=True,
    ),
    EvalQuestion(
        question="what happened in Iran?",
        topic_terms=("iran", "iranian", "tehran"),
        risky=True,
    ),
    EvalQuestion(question="what is sensor confirmed?", mode="sensor"),
    EvalQuestion(question="where is coverage thin?", mode="coverage"),
    EvalQuestion(question="what is contested right now?", mode="contested"),
)


def _story_text(story: dict[str, Any]) -> str:
    return " ".join(str(story.get(key) or "") for key in ("title", "gist")).lower()


def relevant_sources(spec: EvalQuestion, stories: list[dict[str, Any]]) -> list[int]:
    """Story numbers that can ground an answer to this question."""
    out: list[int] = []
    for story in stories:
        n = story.get("n")
        if not isinstance(n, int):
            continue
        if spec.mode == "sensor":
            hit = bool(story.get("sensor"))
        elif spec.mode == "contested":
            hit = bool(story.get("contested"))
        elif spec.mode == "coverage":
            hit = True
        else:
            text = _story_text(story)
            hit = any(term in text for term in spec.topic_terms)
        if hit:
            out.append(n)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_rubric.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add app/brain/qa_rubric.py tests/test_brain_qa_rubric.py
git commit -m "feat(brain): #413 eval question specs + relevance ground truth"
```

---

### Task 2: `score_answer` — the six rubric dimensions

**Files:**
- Modify: `app/brain/qa_rubric.py` (append)
- Test: `tests/test_brain_qa_rubric.py` (append)

**Interfaces:**
- Consumes: `qa.REFUSAL_ANSWER`, `qa.valid_citations(answer, n_sources)`, `qa._TERM_RE`, `qa._QUESTION_STOPWORDS` from `app/brain/qa.py`; Task 1's `EvalQuestion`, `relevant_sources`, `DIMENSIONS`.
- Produces: `score_answer(spec: EvalQuestion, *, answer: str | None, stories: list[dict], invalid_citations: list[int], error: str | None = None) -> dict` returning keys: the six dimension bools, `"passed": bool`, `"reasons": list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_brain_qa_rubric.py`:

```python
from app.brain.qa import REFUSAL_ANSWER


def _score(spec, answer, stories, invalid=None, error=None):
    return qa_rubric.score_answer(
        spec, answer=answer, stories=stories, invalid_citations=invalid or [], error=error
    )


def test_wrong_topic_citation_fails_relevance_typhoon_repro():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes"),
    ]
    out = _score(WAR, "The retrieved story is: Typhoon slams Philippines [1].", stories)
    assert out["relevance"] is False
    assert out["passed"] is False
    assert any("relevant" in r for r in out["reasons"])
    # refusal dim passes: relevant evidence exists and the model did answer
    assert out["refusal"] is True


def test_relevant_cited_risky_answer_with_uncertainty_passes():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes", gist="Strikes resumed near Tehran."),
    ]
    answer = (
        "Reported strikes suggest the Iran ceasefire collapsed [2]; "
        "this remains unconfirmed by sensors."
    )
    out = _score(WAR, answer, stories)
    assert out == {
        "relevance": True,
        "citation": True,
        "uncertainty": True,
        "contested": True,
        "refusal": True,
        "usefulness": True,
        "passed": True,
        "reasons": [],
    }


def test_refusal_with_relevant_evidence_fails_refusal_dim():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    out = _score(WAR, REFUSAL_ANSWER, stories)
    assert out["refusal"] is False
    assert out["passed"] is False


def test_refusal_without_relevant_evidence_passes_all():
    stories = [_story(1, "Typhoon slams Philippines")]
    out = _score(WAR, REFUSAL_ANSWER, stories)
    assert out["passed"] is True
    assert out["reasons"] == []


def test_answer_without_relevant_evidence_fails_refusal_dim():
    stories = [_story(1, "Typhoon slams Philippines")]
    out = _score(WAR, "The war restarted yesterday [1].", stories)
    assert out["refusal"] is False


def test_risky_answer_without_uncertainty_marker_fails():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    answer = "Yes. The Iran ceasefire collapses story shows strikes resumed [1]."
    out = _score(WAR, answer, stories)
    assert out["uncertainty"] is False


def test_contested_cited_story_requires_contested_language():
    stories = [_story(1, "Iran ceasefire collapses after strikes", contested=True)]
    answer = "Reported strikes ended the Iran ceasefire [1]; details remain unclear."
    out = _score(WAR, answer, stories)
    assert out["contested"] is False
    answer_flagged = answer + " Coverage of this ceasefire story is disputed."
    assert _score(WAR, answer_flagged, stories)["contested"] is True


def test_invalid_citations_fail_citation_dim():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    answer = "Reported strikes ended the Iran ceasefire [1], sources say unconfirmed."
    out = _score(WAR, answer, stories, invalid=[9])
    assert out["citation"] is False


def test_short_generic_answer_fails_usefulness():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    out = _score(WAR, "Maybe, reported [1].", stories)
    assert out["usefulness"] is False


def test_coverage_mode_needs_coverage_language():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    good = "Coverage is thin: only one outlet reported this ceasefire story [1]."
    bad = "The Iran ceasefire collapses story is the main reported event [1]."
    assert _score(COVERAGE, good, stories)["relevance"] is True
    assert _score(COVERAGE, bad, stories)["relevance"] is False


def test_sensor_mode_relevance():
    stories = [
        _story(1, "Wildfire in Spain kills twelve", sensor={"fire": "confirmed"}),
        _story(2, "Political speech"),
    ]
    answer = "Sensors confirmed the Spain wildfire that reportedly killed twelve [1]."
    out = _score(SENSOR, answer, stories)
    assert out["relevance"] is True
    assert _score(SENSOR, "The main story is a political speech [2].", stories)["relevance"] is False


def test_error_row_fails_every_dimension():
    out = _score(WAR, None, [_story(1, "Iran ceasefire collapses")], error="boom")
    assert out["passed"] is False
    assert all(out[d] is False for d in qa_rubric.DIMENSIONS)
    assert out["reasons"] == ["model error: boom"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_rubric.py -v`
Expected: new tests FAIL with `AttributeError: module 'app.brain.qa_rubric' has no attribute 'score_answer'`; Task 1's 5 still pass.

- [ ] **Step 3: Write the implementation**

Append to `app/brain/qa_rubric.py` (and add `from app.brain import qa` to the imports at top, below `from typing import Any`):

```python
_UNCERTAINTY_MARKERS: tuple[str, ...] = (
    "contested",
    "disputed",
    "single",
    "unconfirmed",
    "not confirmed",
    "unverified",
    "claim",
    "reported",
    "unclear",
    "unknown",
    "no local evidence",
    "insufficient",
)
_CONTESTED_MARKERS: tuple[str, ...] = ("contested", "disputed", "disagree")
_COVERAGE_MARKERS: tuple[str, ...] = ("coverage", "source", "outlet", "thin", "few", "only")
_WEAK_CORROBORATION: float = 0.5
_MIN_ANSWER_CHARS: int = 40
_MIN_SHARED_TOKENS: int = 2
_MIN_TOKEN_LEN: int = 4


def _contains_any(answer: str, markers: tuple[str, ...]) -> bool:
    low = answer.lower()
    return any(marker in low for marker in markers)


def _story_weak(story: dict[str, Any]) -> bool:
    """Single-teller, contested, weakly corroborated, or sensor-unconfirmed."""
    if story.get("contested") or story.get("owner_count") == 1:
        return True
    corroboration = story.get("corroboration")
    if corroboration is not None and float(corroboration) < _WEAK_CORROBORATION:
        return True
    sensor = story.get("sensor") or {}
    return any(str(verdict).lower() != "confirmed" for verdict in sensor.values())


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in qa._TERM_RE.findall(text.lower())
        if len(token) >= _MIN_TOKEN_LEN and token not in qa._QUESTION_STOPWORDS
    }


def score_answer(
    spec: EvalQuestion,
    *,
    answer: str | None,
    stories: list[dict[str, Any]],
    invalid_citations: list[int],
    error: str | None = None,
) -> dict[str, Any]:
    """Six pass/fail dimensions + reasons. `passed` only if every dim passes."""
    if not isinstance(answer, str) or not answer.strip():
        reason = f"model error: {error}" if error else "no answer produced"
        return {**dict.fromkeys(DIMENSIONS, False), "passed": False, "reasons": [reason]}

    reasons: list[str] = []
    refusal = answer.strip() == qa.REFUSAL_ANSWER
    cited = qa.valid_citations(answer, len(stories))
    relevant = relevant_sources(spec, stories)
    by_n = {story.get("n"): story for story in stories}
    cited_stories = [by_n[n] for n in cited if n in by_n]

    # refusal correctness: refuse iff there is no relevant local evidence.
    if refusal:
        refusal_ok = not relevant
        if not refusal_ok:
            reasons.append(f"refused despite relevant sources {relevant}")
    else:
        refusal_ok = bool(relevant)
        if not refusal_ok:
            reasons.append("answered with no relevant local evidence")

    # relevance: at least one citation must point at a relevant source.
    if refusal:
        relevance_ok = True
    else:
        relevance_ok = bool(set(cited) & set(relevant))
        if not relevance_ok:
            reasons.append(f"cited {cited} not among relevant sources {relevant}")
        if spec.mode == "coverage" and not _contains_any(answer, _COVERAGE_MARKERS):
            relevance_ok = False
            reasons.append("coverage question answered without coverage language")

    # citation: production strips invalid [n]; the model still loses the point.
    citation_ok = refusal or (
        qa.citation_compliant(answer, len(stories)) and not invalid_citations
    )
    if not citation_ok:
        reasons.append(f"citation failure (invalid={invalid_citations})")

    # uncertainty: risky questions and weak cited sources demand hedged language.
    required = not refusal and (spec.risky or any(_story_weak(s) for s in cited_stories))
    uncertainty_ok = not required or _contains_any(answer, _UNCERTAINTY_MARKERS)
    if not uncertainty_ok:
        reasons.append("risky/weakly-sourced answer lacks uncertainty language")

    # contested: citing a contested story without flagging it flattens dispute.
    contested_cited = [s for s in cited_stories if s.get("contested")]
    contested_ok = not contested_cited or _contains_any(answer, _CONTESTED_MARKERS)
    if not contested_ok:
        reasons.append("cited contested story without contested/disputed framing")

    # usefulness: engage the cited content, not generic filler.
    if refusal:
        usefulness_ok = True
    else:
        answer_tokens = _content_tokens(answer)
        shared = max(
            (len(answer_tokens & _content_tokens(_story_text(s))) for s in cited_stories),
            default=0,
        )
        usefulness_ok = len(answer.strip()) >= _MIN_ANSWER_CHARS and shared >= _MIN_SHARED_TOKENS
        if not usefulness_ok:
            reasons.append("answer too short or does not engage cited story content")

    scores = {
        "relevance": relevance_ok,
        "citation": citation_ok,
        "uncertainty": uncertainty_ok,
        "contested": contested_ok,
        "refusal": refusal_ok,
        "usefulness": usefulness_ok,
    }
    return {**scores, "passed": all(scores.values()), "reasons": reasons}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_rubric.py -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add app/brain/qa_rubric.py tests/test_brain_qa_rubric.py
git commit -m "feat(brain): #413 six-dimension deterministic answer rubric"
```

---

### Task 3: Wire rubric into `qa_eval.evaluate_answer` / `run_eval`

**Files:**
- Modify: `app/brain/qa_eval.py:23-138`
- Test: `tests/test_brain_qa_eval.py`

**Interfaces:**
- Consumes: `qa_rubric.EvalQuestion`, `qa_rubric.EVAL_QUESTIONS`, `qa_rubric.score_answer`.
- Produces: `evaluate_answer(session, *, spec: qa_rubric.EvalQuestion | str, model, ...)` — accepts a spec or bare string (coerced); every result row gains `"rubric": dict`. `run_eval(session, *, questions: Iterable[EvalQuestion | str] = qa_rubric.EVAL_QUESTIONS, ...)`; `report["questions"]` stays `list[str]`.

- [ ] **Step 1: Update the tests (failing first)**

In `tests/test_brain_qa_eval.py`, rename the keyword `question=` to `spec=` in every `evaluate_answer` call, and add rubric assertions. Full replacement for the first test plus one new test (apply the same `spec=` rename to the other two `evaluate_answer` tests; `run_eval` keeps `questions=["q1", "q2"]` — strings still work):

```python
def test_evaluate_answer_records_latency_and_invalid_citations(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {
            "as_of": "x",
            "stories": [{"n": 1, "story_id": 5, "title": "x", "sources": ["Reuters"]}],
        },
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")
    ticks = iter([1.0, 1.25])

    def _generate(prompt, *, model, keep_alive):
        assert model == "candidate"
        assert keep_alive == "0"
        return {"answer": "Grounded [1], invented [9]."}

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=_generate,
        clock=lambda: next(ticks),
    )

    assert out["ok"] is True
    assert out["elapsed_ms"] == 250
    assert out["cited"] == [1]
    assert out["invalid_citations"] == [9]
    assert out["citation_ok"] is True
    assert out["rubric"]["citation"] is False  # invalid [9] counts against the model
    assert out["rubric"]["passed"] is False


def test_evaluate_answer_scores_rubric_on_error_rows(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {"as_of": "x", "stories": []},
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    def _boom(prompt, *, model, keep_alive):
        raise RuntimeError("ollama down")

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=_boom,
        clock=iter([1.0, 1.5]).__next__,
    )

    assert out["ok"] is False
    assert out["rubric"]["passed"] is False
    assert all(out["rubric"][d] is False for d in qa_eval.qa_rubric.DIMENSIONS)
```

Note: `test_run_eval_crosses_questions_and_models` asserts `all(row["ok"] ...)` — with empty `stories` and answers like `"m1 ok"` the citation flow still passes (no sources → no citation required); rubric will fail (`answered with no relevant local evidence`) but `ok` stays True. Add one assertion there: `assert all("rubric" in row for row in report["results"])`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_eval.py -v`
Expected: FAIL with `TypeError: evaluate_answer() got an unexpected keyword argument 'spec'`.

- [ ] **Step 3: Implement in `app/brain/qa_eval.py`**

Changes:

1. Import: add `qa_rubric` to the `from app.brain import client, context, qa` line → `from app.brain import client, context, qa, qa_rubric`.
2. Delete `DEFAULT_QUESTIONS` (replaced by `qa_rubric.EVAL_QUESTIONS`).
3. Add coercion helper after `candidate_models()`:

```python
def _coerce_spec(question: qa_rubric.EvalQuestion | str) -> qa_rubric.EvalQuestion:
    if isinstance(question, qa_rubric.EvalQuestion):
        return question
    return qa_rubric.EvalQuestion(question=str(question))
```

4. `evaluate_answer`: rename param `question: str` → `spec: qa_rubric.EvalQuestion | str`; first line of body `spec = _coerce_spec(spec)`; replace every use of `question` inside with `spec.question` (context build, prompt build, repair prompt, result rows). In the success return dict add:

```python
            "rubric": qa_rubric.score_answer(
                spec, answer=answer, stories=sources, invalid_citations=invalid
            ),
```

In the except-branch return dict add (note `stories` must be fetched once before the dict via `stories = qa_context.get("stories") or []`):

```python
            "rubric": qa_rubric.score_answer(
                spec,
                answer=None,
                stories=stories,
                invalid_citations=[],
                error=f"{type(exc).__name__}: {exc}",
            ),
```

(and reuse `stories` for the existing `"n_sources": len(...)` line).

5. `run_eval`: signature `questions: Iterable[qa_rubric.EvalQuestion | str] = qa_rubric.EVAL_QUESTIONS`; body:

```python
    spec_list = [_coerce_spec(q) for q in questions if str(getattr(q, "question", q)).strip()]
```

loop `for spec in spec_list:` passing `spec=spec` to `evaluate_answer`; report key `"questions": [s.question for s in spec_list]`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_eval.py tests/test_brain_qa_rubric.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/brain/qa_eval.py tests/test_brain_qa_eval.py
git commit -m "feat(brain): #413 score every eval row against the rubric"
```

---

### Task 4: Rubric columns + failure reasons in the report

**Files:**
- Modify: `app/brain/qa_eval.py:141-178` (`render_markdown`)
- Test: `tests/test_brain_qa_eval.py` (`test_render_markdown_summarizes_models`)

**Interfaces:**
- Consumes: rows with `"rubric"` from Task 3 (`row.get("rubric") or {}` — defensive against old JSON).
- Produces: summary table `| Model | OK | Rubric | relevance | citation | uncertainty | contested | refusal | usefulness | Median latency ms | Invalid citations |`; per-run sections list `rubric_passed`, failed dims, reasons.

- [ ] **Step 1: Update the test (failing first)**

Replace `test_render_markdown_summarizes_models`:

```python
def test_render_markdown_summarizes_models():
    report = {
        "created_at": "2026-07-14T00:00:00+00:00",
        "models": ["m1"],
        "questions": ["q"],
        "results": [
            {
                "question": "q",
                "model": "m1",
                "ok": True,
                "elapsed_ms": 12,
                "answer": "A [1]",
                "n_sources": 1,
                "cited": [1],
                "invalid_citations": [],
                "rubric": {
                    "relevance": True,
                    "citation": True,
                    "uncertainty": False,
                    "contested": True,
                    "refusal": True,
                    "usefulness": True,
                    "passed": False,
                    "reasons": ["risky/weakly-sourced answer lacks uncertainty language"],
                },
            }
        ],
    }

    md = qa_eval.render_markdown(report)

    assert "Brain Q&A model evaluation" in md
    assert "| Rubric | relevance |" in md
    assert "| `m1` | 1/1 | 0/1 |" in md
    assert "- rubric_failed: ['uncertainty']" in md
    assert "risky/weakly-sourced answer lacks uncertainty language" in md
    assert "A [1]" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_eval.py::test_render_markdown_summarizes_models -v`
Expected: FAIL on the `"| Rubric | relevance |"` assertion.

- [ ] **Step 3: Implement**

In `render_markdown`, replace the two header lines and the per-model row build:

```python
    lines = [
        "# Brain Q&A model evaluation",
        "",
        f"Created: `{report['created_at']}`",
        "",
        "| Model | OK | Rubric | " + " | ".join(qa_rubric.DIMENSIONS) + " | Median latency ms | Invalid citations |",
        "|---|---:|---:|" + "---:|" * len(qa_rubric.DIMENSIONS) + "---:|---:|",
    ]
    for model in report["models"]:
        rows = [r for r in report["results"] if r["model"] == model]
        ok_rows = [r for r in rows if r["ok"]]
        latencies = sorted(r["elapsed_ms"] for r in ok_rows)
        median = latencies[len(latencies) // 2] if latencies else None
        invalid = sum(len(r["invalid_citations"]) for r in rows)
        rubrics = [r.get("rubric") or {} for r in rows]
        passed = sum(1 for rub in rubrics if rub.get("passed"))
        dims = " | ".join(
            f"{sum(1 for rub in rubrics if rub.get(d))}/{len(rows)}" for d in qa_rubric.DIMENSIONS
        )
        lines.append(
            f"| `{model}` | {len(ok_rows)}/{len(rows)} | {passed}/{len(rows)} | {dims} "
            f"| {median or 'n/a'} | {invalid} |"
        )
```

And in the per-run section (inside the `for row in report["results"]:` loop, after the `citation_repaired` line):

```python
        rubric = row.get("rubric") or {}
        failed = [d for d in qa_rubric.DIMENSIONS if not rubric.get(d)]
        lines.append(f"- rubric_passed: {bool(rubric.get('passed'))}")
        lines.append(f"- rubric_failed: {failed}")
        for reason in rubric.get("reasons") or []:
            lines.append(f"- reason: {reason}")
```

- [ ] **Step 4: Run the full affected suite**

Run: `.venv/bin/python -m pytest tests/test_brain_qa_eval.py tests/test_brain_qa_rubric.py tests/test_brain_qa.py tests/test_brain_qa_stories.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/brain/qa_eval.py tests/test_brain_qa_eval.py
git commit -m "feat(brain): #413 rubric pass rates + failure reasons in eval report"
```

---

### Task 5: Verify gates, push, open PR

**Files:** none new.

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/python -m pytest`
Expected: all pass, no new failures vs main.

- [ ] **Step 2: Lint + format gates (CI runs both)**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: clean. If `ruff format --check` flags files this branch touched, run `.venv/bin/ruff format <those files>` and amend the relevant commit.

Note: `qa_rubric.py` accesses `qa._TERM_RE` / `qa._QUESTION_STOPWORDS` (private cross-module). If ruff flags SLF001, add targeted `# noqa: SLF001` on those lines — the spec pins this reuse deliberately (same package, single tokenizer).

- [ ] **Step 3: Push + PR**

```bash
git push -u origin feat-qa-eval-rubric
gh pr create --title "feat(brain): #413 rubric-based Q&A answer evaluation" --body "$(cat <<'EOF'
## Summary
- new `app/brain/qa_rubric.py`: deterministic six-dimension answer rubric (relevance, citation, uncertainty, contested, refusal, usefulness) over the fixed risky-question set from the #413 plan comment
- `brain-qa-eval` rows now carry per-dimension pass/fail + failure reasons; report summarizes rubric pass rates per model
- reproduces the live failure: a cited wrong-topic answer (typhoon for "is the war back on?") now fails relevance

Spec: docs/superpowers/specs/2026-07-15-qa-eval-rubric-design.md
Plan: docs/superpowers/plans/2026-07-15-qa-eval-rubric.md

Refs #413 (roadmap item 1)

## Test plan
- [ ] `pytest` green (17 new rubric tests + updated eval tests)
- [ ] `ruff check .` + `ruff format --check .` clean
- [ ] post-merge: `make brain-qa-eval` live run, 1.5b vs 4b results commented on #413
EOF
)"
```

Expected: PR URL printed. **Do not merge — Basil merges.**

---

### Task 6: Live 1.5b vs 4b run + #413 results comment

Prereqs: Ollama running (`make up` starts it), both models pulled, DB populated. Can run on this branch before merge.

- [ ] **Step 1: Run the eval**

Run: `make brain-qa-eval`
Expected: `written: data/exports/brain-qa-model-eval.md (+ .../brain-qa-model-eval.json)`; 6 questions × 2 models ≈ 12 model calls, minutes not seconds.

- [ ] **Step 2: Read the report**

Run: read `data/exports/brain-qa-model-eval.md`. Extract the summary table + notable failure reasons.

- [ ] **Step 3: Post #413 comment**

```bash
gh issue comment 413 --repo BasilSuhail/OSINT --body "$(cat <<'EOF'
## Rubric eval — 1.5b vs 4b (roadmap item 1)

`make brain-qa-eval` now scores six deterministic dimensions per answer
(relevance, citation, uncertainty, contested, refusal, usefulness); an answer
passes only if all six pass. Full report: `data/exports/brain-qa-model-eval.md`.

<summary table pasted here from the report>

Notable failures:
<top failure reasons per model>

Verdict: <one line — which model, which dims dominate the gap>
EOF
)"
```

Fill the three placeholders from the actual report before posting.

- [ ] **Step 4: Commit exported report? NO**

`data/exports/` artifacts are gitignored/runtime outputs — do not commit them. Verify with `git status` (should be clean).
