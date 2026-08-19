# A build for a small board, without the Ask panel

## The problem

The console asks a local model questions. On a 9 GB board that is the most
expensive thing it does: a couple of minutes an answer, and the model that
answers has to be resident alongside the one that writes the news summaries.
The small-machine profile already handles this by pointing every model setting
at the same model, so Ollama loads it once — but the answer still costs minutes,
and the board is doing nothing else while it runs.

Everything else the board does is cheap and useful: it fetches, it stores, it
scores, it writes gists and tags, it draws the map, and both search boxes
answer instantly because neither one has ever gone near the model.

So the small board should run all of that and not offer the one control that
cannot serve it well. Not a fork, not a branch — the same repository, with a
setting that the environment writer turns off for it.

## What it is not

Not `brain_enabled=false`. That setting exists and it stops the whole brain:
gists, tags, severity, the situation summary, the embeddings. The board wants
all of those. The question path is what has to go, and nothing else.

## The flag

`ASK_ENABLED`, default `true`, mirrored to `NEXT_PUBLIC_ASK_ENABLED` for the
dashboard the way `API_AUTH_TOKEN` is already mirrored to
`NEXT_PUBLIC_API_TOKEN`. Two keys rather than one because the dashboard is a
separate process with its own build-time environment, and `make env` copies the
value across so they cannot drift by hand.

`scripts/env_setup.py` writes `ASK_ENABLED=false` in `_SMALL_MACHINE_PROFILE`
and the mirror carries it to the dashboard key, so a board of 9 GB or less gets
this build with nothing to edit and the `make env` summary line says so. The key
sits in the profile set, which means it is overridable: an operator who wants
the Ask panel on a small board sets it to `true`, and `make env` leaves the
answer alone from then on. That last promise is why `env.example` ships the key
blank rather than spelling out its default — a profile key still holding the
example's own value counts as the example's answer, not the operator's, and
would be written over on the next run. Blank means on for the API and for the
console both, so a machine above the threshold is untouched.

## What changes

**Backend.** `app/settings.py` gains `ask_enabled: bool = Field(default=True)`.
`POST /brain/ask` and `POST /brain/ask/stream` check it first — before the RAM
gate, before retrieval, before any model call — and return a typed answer at
HTTP 200 saying the question path is off on this build. That matches the
endpoint's existing contract, where every failure is a typed answer and only a
malformed request is a 422. A client that has the flag wrong still gets a
sentence it can show rather than an error it has to interpret.

**Dashboard.** `Omnibox.tsx` is one box that does two jobs: typing runs the
cheap search, the ask button runs the model. With the flag off the button and
the brain half of the dropdown are not rendered, and the box is a search box.
`app/news/page.tsx` stops mounting `AskDock`. The Situation panel needs nothing:
its composer moved into the Omnibox in #938 and the panel holds only a comment
saying so. `useBrainChat` is left in place, unimported where it is not
wanted — dormant, not deleted, because the flag is a setting and a setting can
be turned back on.

Nothing renders a disabled control. A reader on this build never sees a button
that will not work.

**Documentation.** The small-board section of `README.md` loses the paragraphs
that only exist to explain a slow answer: the ask timing, the stream-idle
reasoning, the `QA_*` floors, the model-choice story about fabrication. What
replaces them is one short passage saying which build this is and why — the
board runs everything except the question box, and the setting that decides it.
The model pull list keeps both models, for the reason below.

## What does not change

The board still runs Ollama, and still runs it for:

- news enrichment — gists, keywords, tags, categories, on `BRAIN_MODEL`
- severity grading
- the category audit
- the scheduled situation summary, which is news-side: it is scheduled rather
  than user-triggered, RAM-gated, and backs off under load
- story embeddings, written by the enrichment run

Embeddings are the one that needs saying out loud, because with the question
path off nothing reads them: retrieval is their only consumer, and `/search` is
full-text plus gazetteer, which never touched a vector. They keep being written
anyway. The cost is some CPU per enrichment run; the thing bought is that
turning the flag back on gives a working index immediately rather than a cold
one that fills in over the next several runs. Within the 30-day retention this
is a bounded amount of storage.

Both search boxes work exactly as they do on a laptop — the one on the
dashboard and the one on the news page — because neither has ever called the
model.

## Testing

Backend, pytest:

- flag off — `/brain/ask` returns the disabled payload at 200, and no model
  call is made (assert on the client, not on timing)
- flag off — `/brain/ask/stream` does the same over the stream shape
- flag on — both endpoints behave exactly as they do now
- `env_setup` — a small machine writes both keys as `false`; a large one writes
  neither; an operator's `true` on a small machine survives a re-sync

Dashboard, vitest (`.mts`):

- flag off — `Omnibox` renders the search input and no ask control
- flag on — the ask control is present

The rendered appearance is not verified here. There is no browser automation in
this repository, so the visual result of removing the control is something the
operator confirms on screen.

## Out of scope

Reaching the board from anywhere — boot-time start, a tunnel or reverse proxy,
authentication for a machine that is no longer only on the desk — is a separate
piece of work with its own spec. This one is the build; that one is the server.
