# A build for a small board, without the Ask panel — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One setting, `ASK_ENABLED`, that turns off the console's question path and nothing else, written as `false` automatically for a machine of 9 GB or less.

**Architecture:** A boolean on `Settings`, checked as the first line of both ask endpoints, returning the same typed-answer-at-200 shape every other ask failure returns. The dashboard reads a mirrored `NEXT_PUBLIC_ASK_ENABLED` through a small pure helper and stops rendering the ask control. `scripts/env_setup.py` writes both keys in the small-machine profile, so the board configures itself.

**Tech Stack:** FastAPI + pydantic-settings, pytest, Next.js 15 + React, vitest (node environment), `scripts/env_setup.py`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-19-small-board-build-without-ask-design.md`.
- Branch is already made and holds the spec commit: `feat/small-board-build-without-ask`. Do not branch again.
- Repository is public. No personal names, no institution, no contact details, no assessment vocabulary — in code, comments, commit messages or PR text. Write the role: "the operator", "the reader", "the maintainer".
- Commit messages carry no attribution trailers: no `Co-Authored-By`, no "generated with" line.
- Python: run everything through the repo venv by absolute path — `.venv/bin/pytest`, `.venv/bin/python`, `.venv/bin/ruff`. Never bare `python`, never bare `timeout`.
- CI runs both `ruff check` and `ruff format --check`. Both must pass before the PR.
- Frontend tests are `.mts` under `lib/`, or `.test.ts` under `__tests__/`. The vitest environment is `node` and there is no testing-library and no jsdom in this repo — component rendering cannot be asserted. Test pure helpers, not components.
- Run only the tests a task touches while implementing. Full suites belong to CI.
- Comment style in this repo: `#:` for Python explanatory comments above a definition, `//:` inside TypeScript function bodies, `/*: … */` inside JSX. Match the surrounding density — these files explain *why*, at length, and a bare one-line change in them reads as foreign.

## Files

- Modify `app/settings.py` — add `ask_enabled`.
- Modify `app/brain/qa.py:214-243` — add `ASK_DISABLED_ANSWER`, add it to `OPERATIONAL_ANSWERS`.
- Modify `app/api.py:1669-1683` and `app/api.py:1762-1773` — guard both ask endpoints.
- Modify `tests/test_brain_ask_api.py` — flag-off tests for both endpoints.
- Modify `env.example` — document both keys.
- Modify `scripts/env_setup.py:358-377` — both keys in `_SMALL_MACHINE_PROFILE`.
- Modify `tests/test_env_setup.py` — profile writes the keys; an operator's `true` survives.
- Create `osint-frontend/lib/askFlag.ts` — `parseAskEnabled` + `ASK_ENABLED`.
- Create `osint-frontend/lib/askFlag.test.mts` — parser tests.
- Modify `osint-frontend/components/Omnibox.tsx` — ask button, Enter-to-ask, transcript section behind the flag.
- Modify `osint-frontend/app/news/page.tsx:44,421` — `AskDock` behind the flag.
- Modify `README.md` — the small-board section.

**Not in scope.** `POST /stories/{id}/deep-read` is a different user-triggered model call — the reasoned "why" behind a contested story, reached from a story card, not from the question box. The spec turns off the question path only, so deep-read is left alone. The Situation panel has no composer to hide: it moved into the Omnibox in #938 and the panel holds only a comment saying so.

---

### Task 1: The flag, and the two endpoints that honour it

**Files:**
- Modify: `app/settings.py:45`
- Modify: `app/brain/qa.py:214-243`
- Modify: `app/api.py:1669-1683`, `app/api.py:1762-1773`
- Test: `tests/test_brain_ask_api.py`

**Interfaces:**
- Produces: `settings.ask_enabled: bool` (default `True`); `qa.ASK_DISABLED_ANSWER: str`; both ask endpoints returning `_ask_payload(qa.ASK_DISABLED_ANSWER, None, [])` when the flag is false.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_brain_ask_api.py`:

```python
def test_ask_returns_typed_answer_when_disabled(monkeypatch):
    #: The question path is off on this build (small-board profile). The reply
    #: is an answer, not an error: the console shows a sentence either way, and
    #: a 500 here would be read as a broken install rather than a setting.
    client = _client()
    monkeypatch.setattr(api.settings, "ask_enabled", False)

    def _boom(*a, **kw):
        raise AssertionError("no model call may be made when ask is disabled")

    monkeypatch.setattr(api.client, "generate_json", _boom)
    resp = client.post("/brain/ask", json={"question": "what is loudest?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == api.qa.ASK_DISABLED_ANSWER
    assert body["sources"] == []
    assert body["context_digest"] is None
    app.dependency_overrides.clear()


def test_ask_disabled_answer_is_operational():
    #: Operational messages are not model output, so the claim checks must skip
    #: it exactly as they skip "brain busy".
    assert api.qa.ASK_DISABLED_ANSWER in api.qa.OPERATIONAL_ANSWERS


def test_ask_disabled_is_checked_before_the_ram_gate(monkeypatch):
    #: A board with no free memory and ask switched off should say ask is off,
    #: not "brain busy" — the second sends the operator looking at memory for a
    #: refusal that has nothing to do with it.
    client = _client()
    monkeypatch.setattr(api.settings, "ask_enabled", False)
    monkeypatch.setattr(api.gate, "qa_ram_blocked", lambda: True)
    body = client.post("/brain/ask", json={"question": "what is loudest?"}).json()
    assert body["answer"] == api.qa.ASK_DISABLED_ANSWER
    app.dependency_overrides.clear()


def test_ask_stream_returns_typed_answer_when_disabled(monkeypatch):
    client = _client()
    monkeypatch.setattr(api.settings, "ask_enabled", False)

    def _boom(*a, **kw):
        raise AssertionError("no model call may be made when ask is disabled")

    monkeypatch.setattr(api.client, "generate_text_stream", _boom)
    resp = client.post("/brain/ask/stream", json={"question": "what is loudest?"})
    assert resp.status_code == 200
    finals = [
        json.loads(line.removeprefix("data: "))
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    answers = [f.get("answer") for f in finals if "answer" in f]
    assert answers == [api.qa.ASK_DISABLED_ANSWER]
    app.dependency_overrides.clear()
```

Note on the stream assertion: `_sse` writes `event:` and `data:` lines. Read the
existing streaming test in this file first and match however it already parses
the stream — if it has a helper, use the helper instead of the parsing above.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/pytest tests/test_brain_ask_api.py -k disabled -v`
Expected: FAIL — `AttributeError` on `ask_enabled` / `ASK_DISABLED_ANSWER`.

- [ ] **Step 3: Add the setting**

In `app/settings.py`, directly under `brain_enabled` (line 45):

```python
    #: The question path only. `brain_enabled` above stops the whole brain —
    #: gists, tags, severity, the situation summary, the embeddings — and a
    #: small board wants every one of those; what it cannot afford is a
    #: user-triggered generation that takes minutes and holds the box while it
    #: runs. `make env` writes this false at 9 GB or less.
    ask_enabled: bool = Field(default=True)
```

- [ ] **Step 4: Add the answer**

In `app/brain/qa.py`, beside the other operational messages (after
`BRAIN_SLOW_ANSWER`, before the `OPERATIONAL_ANSWERS` tuple):

```python
#: Not a failure. This build does not answer questions — the search box beside
#: it does, instantly, and saying which one works is more use than an apology.
ASK_DISABLED_ANSWER = (
    "This build does not answer questions. Search still works — type to find "
    "places, stories and events."
)
```

and add `ASK_DISABLED_ANSWER,` to `OPERATIONAL_ANSWERS`.

- [ ] **Step 5: Guard both endpoints**

`app/api.py`, first line of the `brain_ask` body, above the `qa_ram_blocked` check:

```python
    if not settings.ask_enabled:
        return _ask_payload(qa.ASK_DISABLED_ANSWER, None, [])
```

and the same inside `gen()` in `brain_ask_stream`, above its `qa_ram_blocked` check:

```python
        if not settings.ask_enabled:
            yield _sse("final", _ask_payload(qa.ASK_DISABLED_ANSWER, None, []))
            return
```

Extend the `brain_ask` docstring with one sentence: the flag is checked before
the RAM gate so a board with the question path off never reports a memory
refusal for a setting.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/pytest tests/test_brain_ask_api.py -v`
Expected: PASS — the new tests and every test already in the file.

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check app tests scripts && .venv/bin/ruff format --check app tests scripts`
Expected: both clean.

- [ ] **Step 8: Commit**

```bash
git add app/settings.py app/brain/qa.py app/api.py tests/test_brain_ask_api.py
git commit -m "feat(api): a build without the question box says so, and answers"
```

---

### Task 2: A small board writes the setting for itself

**Files:**
- Modify: `env.example` (the brain block, around line 118)
- Modify: `scripts/env_setup.py:358-377`
- Test: `tests/test_env_setup.py`

**Interfaces:**
- Consumes: `ASK_ENABLED` from Task 1.
- Produces: `ASK_ENABLED` and `NEXT_PUBLIC_ASK_ENABLED` keys in `env.example`; both present in `_SMALL_MACHINE_PROFILE` with value `"false"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_env_setup.py` tests the profile through `originate(example, env,
machine, small=...)`, against a small fixture string `PROFILE_EXAMPLE` that
holds only the model keys. `originate` will not write a key the example does not
document, so the fixture gains the two new lines first — at the top of
`PROFILE_EXAMPLE`:

```python
PROFILE_EXAMPLE = """ASK_ENABLED=true
NEXT_PUBLIC_ASK_ENABLED=true
BRAIN_MODEL=llama3.2:3b
```

(the rest of the fixture is unchanged). Then append to
`class TestTheSmallMachineProfile`:

```python
    #: The build this profile now describes. Everything else the board does is
    #: cheap; a typed question is minutes of a box that has other work, so the
    #: profile removes that one control rather than tuning it.
    def test_a_small_board_gets_the_build_without_the_question_box(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["ASK_ENABLED"] == "false"

    #: Both halves, because the dashboard is a separate process with its own
    #: build-time environment. One of the two alone is a console drawing a
    #: button for an endpoint that refuses, or hiding one that works.
    def test_the_dashboard_is_told_the_same_thing(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=True)
        assert written["NEXT_PUBLIC_ASK_ENABLED"] == written["ASK_ENABLED"]

    #: A laptop keeps the console it has.
    def test_a_big_machine_keeps_the_question_box(self):
        written = originate(PROFILE_EXAMPLE, PROFILE_EXAMPLE, MACHINE, small=False)
        assert "ASK_ENABLED" not in written

    #: The line the profile must not cross, for this key like every other: an
    #: operator who wants questions answered on a board has said so, and a
    #: re-sync is not the place to disagree.
    def test_it_leaves_the_question_box_on_where_somebody_turned_it_on(self):
        env = PROFILE_EXAMPLE.replace("ASK_ENABLED=true", "ASK_ENABLED=on", 1)
        written = originate(PROFILE_EXAMPLE, env, MACHINE, small=True)
        assert "ASK_ENABLED" not in written
```

The last test uses `on` rather than `true` deliberately: `true` is the example's
own value, which the profile is allowed to write over, and the test would then
be asserting the opposite of what it says. Check this against the file's own
`test_it_leaves_an_answer_somebody_gave`, which makes the same distinction, and
note that `parseAskEnabled` in Task 3 reads `on` as enabled.

Both keys sit in the profile rather than in `_MIRRORED`. `_MIRRORED` fills a
mirror from its source and its mismatch report is written about the API token,
whose drift refuses every request; these two drifting costs nothing worse than a
button that returns the typed sentence from Task 1. The API is authoritative,
the dashboard key is cosmetic, and the endpoint answers correctly either way.

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/pytest tests/test_env_setup.py -k ask -v`
Expected: FAIL — `KeyError: 'ASK_ENABLED'`.

- [ ] **Step 3: Document both keys in `env.example`**

In the brain block, above `BRAIN_MODEL`:

```
# Whether the console answers questions. The search boxes are unaffected —
# they ask the full-text index and the gazetteer, and have never gone near a
# model. Off, the ask control is not drawn and the endpoint returns a sentence
# saying so. `make env` writes false on a machine of 9 GB or less, where an
# answer costs minutes and holds the box for all of them; set it back to true
# and `make env` leaves your answer alone from then on.
ASK_ENABLED=true
NEXT_PUBLIC_ASK_ENABLED=true
```

- [ ] **Step 4: Add both keys to the profile**

In `scripts/env_setup.py`, inside `_SMALL_MACHINE_PROFILE`:

```python
    "ASK_ENABLED": "false",
    "NEXT_PUBLIC_ASK_ENABLED": "false",
```

Extend the docstring comment above the profile with a paragraph in its voice —
the entries above it explain what was measured and why. Say: everything the
board does apart from answering is cheap, an answer is minutes of a box that
has other work, and the question box is the one control the profile removes
rather than tunes. Note that both keys are set because the dashboard is a
separate process with its own build-time environment.

- [ ] **Step 5: Run the tests**

Run: `.venv/bin/pytest tests/test_env_setup.py -v`
Expected: PASS.

- [ ] **Step 6: Check the report reads right**

Run: `.venv/bin/python scripts/env_setup.py check`
Expected: no complaint about the two new keys. It is reporting on the real
`.env` in this working copy, so a mention of them as missing is the expected
output on a machine whose `.env` predates them — read it, do not act on it.

- [ ] **Step 7: Lint**

Run: `.venv/bin/ruff check scripts tests && .venv/bin/ruff format --check scripts tests`

- [ ] **Step 8: Commit**

```bash
git add env.example scripts/env_setup.py tests/test_env_setup.py
git commit -m "feat(env): a small board writes itself the build without the question box"
```

---

### Task 3: The dashboard stops drawing a control it cannot serve

**Files:**
- Create: `osint-frontend/lib/askFlag.ts`
- Create: `osint-frontend/lib/askFlag.test.mts`
- Modify: `osint-frontend/components/Omnibox.tsx:242-258, 319-360, 543-570`
- Modify: `osint-frontend/app/news/page.tsx:44, 421`

**Interfaces:**
- Consumes: `NEXT_PUBLIC_ASK_ENABLED` from Task 2.
- Produces: `parseAskEnabled(raw: string | undefined): boolean` and `ASK_ENABLED: boolean`, both exported from `@/lib/askFlag`.

- [ ] **Step 1: Write the failing test**

Create `osint-frontend/lib/askFlag.test.mts`:

```typescript
import { describe, expect, it } from "vitest"

import { parseAskEnabled } from "./askFlag"

describe("parseAskEnabled", () => {
  it("defaults to on when the key is absent", () => {
    // A machine that predates the setting keeps the console it had.
    expect(parseAskEnabled(undefined)).toBe(true)
    expect(parseAskEnabled("")).toBe(true)
  })

  it("is off only for an explicit false", () => {
    expect(parseAskEnabled("false")).toBe(false)
    expect(parseAskEnabled("FALSE")).toBe(false)
    expect(parseAskEnabled(" false ")).toBe(false)
    expect(parseAskEnabled("0")).toBe(false)
  })

  it("treats anything else as on", () => {
    // Fail toward the working console: a typo should not silently remove a
    // control, it should leave the console as the operator last knew it.
    expect(parseAskEnabled("true")).toBe(true)
    expect(parseAskEnabled("yes")).toBe(true)
    expect(parseAskEnabled("maybe")).toBe(true)
  })
})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd osint-frontend && pnpm vitest run lib/askFlag.test.mts`
Expected: FAIL — cannot resolve `./askFlag`.

- [ ] **Step 3: Write the helper**

Create `osint-frontend/lib/askFlag.ts`:

```typescript
/**
 * Whether this build answers questions.
 *
 * Read once, at module scope, because Next inlines `process.env.NEXT_PUBLIC_*`
 * at build time — there is nothing to re-read later and nothing to react to.
 * The parse is separate from the read so it can be tested without a build.
 *
 * Off is explicit. An absent key, an empty one or a typo all leave the console
 * as it was: removing a control is the surprising outcome, and a setting
 * nobody wrote should never be the thing that causes it.
 */
export function parseAskEnabled(raw: string | undefined): boolean {
  const value = (raw ?? "").trim().toLowerCase()
  if (!value) return true
  return value !== "false" && value !== "0"
}

export const ASK_ENABLED = parseAskEnabled(process.env.NEXT_PUBLIC_ASK_ENABLED)
```

- [ ] **Step 4: Run the test**

Run: `cd osint-frontend && pnpm vitest run lib/askFlag.test.mts`
Expected: PASS.

- [ ] **Step 5: Take the ask control out of the Omnibox**

In `osint-frontend/components/Omnibox.tsx`:

- import `ASK_ENABLED` from `@/lib/askFlag`
- `submitAsk` returns immediately unless `ASK_ENABLED` — belt and braces, so no
  code path can reach the endpoint with the flag off
- the `onKeyDown` Enter handler only calls `submitAsk` when `ASK_ENABLED`
- wrap the ask `<button>` (the one with `aria-label="Ask the brain"`) in
  `{ASK_ENABLED && ( … )}` — not `disabled`, gone; the spec is explicit that no
  dead control is drawn
- wrap the `{messages.length > 0 && ( … )}` transcript `<section>` in the same
  condition
- the placeholder and the `aria-label` on the input both promise an ask. With
  the flag off they must not: use `narrow ? "find…" : "find anything…"` and
  `aria-label="Search the console"`. Pick between the two forms with
  `ASK_ENABLED`, keeping the existing wording unchanged when it is on.

Update the file's header comment. It opens by explaining that there used to be
two boxes and that this one asks both — add a short paragraph saying that a
build with `ASK_ENABLED=false` is the one box doing the cheap half only, and
that the transcript and the button are not drawn rather than disabled.

- [ ] **Step 6: Take the dock off the reading page**

In `osint-frontend/app/news/page.tsx`, import `ASK_ENABLED` and change line 421 to:

```tsx
      {ASK_ENABLED && <AskDock onOpenStory={setOpenId} />}
```

Leave the `AskDock` import and the component file exactly as they are — the flag
is a setting, and the code behind it stays ready for the setting to change.

- [ ] **Step 7: Typecheck, lint and run the suite**

Run: `cd osint-frontend && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm vitest run`
Expected: all clean. If eslint reports `AskDock` or `useBrainChat` as unused in
a file, that is a real finding — the import must still be used inside the guard.

- [ ] **Step 8: Commit**

```bash
git add osint-frontend/lib/askFlag.ts osint-frontend/lib/askFlag.test.mts osint-frontend/components/Omnibox.tsx osint-frontend/app/news/page.tsx
git commit -m "feat(console): a build that cannot answer draws no question button"
```

---

### Task 4: The small-board section says which build it is

**Files:**
- Modify: `README.md` (the `Raspberry Pi 5 (8 GB)` block, roughly lines 44-190)

**Interfaces:**
- Consumes: everything above. No code.

- [ ] **Step 1: Read the whole block first**

Run: `sed -n '44,195p' README.md`

It is one continuous argument — power supply, Docker group, Ollama, `make env`,
models, `earlyoom`, start, fill. Several paragraphs exist only to explain a slow
answer, and those are the ones this task removes.

- [ ] **Step 2: Cut what only existed for the ask**

Remove from the block:

- the paragraph beginning "Those numbers matter more than they look" through
  "the board locks up while you are looking at something else" — it is about
  the Ask panel having nowhere to load a third model
- the paragraph beginning "One model rather than a smaller one" — the 1b
  fabrication story is about answering questions. It stays in
  `scripts/env_setup.py`, where it is the reason the profile names a 3b, and
  that is the right home for it
- "An ask on this board takes a couple of minutes; the console streams the
  answer as it arrives rather than appearing to hang"
- the "Worth watching the first time you ask the console a question" passage
  and its `watch -n5` block

Keep: the power supply and `vcgencmd`, the Docker group and the reboot, the
whole Ollama systemd section, `make env`, `earlyoom`, both `ollama pull` lines,
the model check, `make up`, `make share`, `make fetch`, `make news`.

- [ ] **Step 3: Say what this build is**

Where the removed "Those numbers matter" paragraph was, in the README's voice —
plain, second person, explaining the reason rather than listing the setting:

> `make env` also turns the question box off on a board this size. Everything
> else runs: it fetches, it stores, it scores, it writes the gists and the tags
> and the situation summary, and both search boxes answer as fast as they do on
> a laptop, because neither has ever gone near a model. What it does not do is
> answer typed questions — that costs minutes of a board that has other work,
> and the box is not drawn rather than left there to disappoint. `ASK_ENABLED`
> in `.env` is the setting; put it back to `true` if you want it and `make env`
> will leave your answer alone.

- [ ] **Step 4: Fix the two model lines that now over-explain**

The models passage says one model "answers" and one "turns text into vectors so
the Ask panel can find the right stories". On this build the first writes the
summaries and the tags, and the second is written now so retrieval is warm if
the setting is ever turned back on. Rewrite those two clauses. Both pulls stay.

- [ ] **Step 5: Read it back whole**

Run: `sed -n '44,180p' README.md`

Check: no dangling reference to a control that is no longer there, no paragraph
whose subject was removed above it, and the numbered flow still reads start to
finish with nothing to look up elsewhere.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs(readme): a small board's section describes the build it gets"
```

---

### Task 5: Verify, squash, and open the pull request

- [ ] **Step 1: Run the backend gates**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
Expected: all pass. Anything failing that this branch did not touch: say so
rather than fixing it here.

- [ ] **Step 2: Run the frontend gates**

Run: `cd osint-frontend && pnpm exec tsc --noEmit && pnpm exec eslint . && pnpm vitest run`

- [ ] **Step 3: Squash to one commit**

One issue, one branch, one pull request, one commit.

```bash
git reset --soft $(git merge-base HEAD main) && git status
```

Read the staged list before committing — it should hold exactly the files named
in this plan plus the spec and this plan document, and nothing else.

```bash
git commit -m "feat(console): a small board runs everything except the question box"
```

- [ ] **Step 4: Open the issue and the pull request**

The maintainer merges. An agent never does. The PR body says what the setting
does, what stays working, and that the console's appearance with the control
removed has not been verified on screen — there is no browser automation here.

- [ ] **Step 5: Say what was not verified**

Report to the operator: the rendered console was not looked at. The Omnibox
without its ask button, and the reading page without its dock, need eyes.
