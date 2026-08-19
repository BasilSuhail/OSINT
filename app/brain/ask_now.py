"""Ask a question from the command line — `make ask Q="..."`.

The console reports every model failure as one short sentence: the brain is
offline, or busy, or slow. That is right for a reader and useless for anyone
trying to fix it, because the API turns the exception into a typed answer and
returns HTTP 200. Three rounds of diagnosis went into an ask that answered
"offline" while the cause was never written down anywhere.

This runs the same retrieval, the same prompt and the same model call as the
console, with nothing catching the exception, and reports the sizes that decide
whether a small model can do the work at all: how long the prompt is, how much
of the context window it uses, and how far the RAM floor is from what is free.

The memory gate is reported, not enforced. A blocked gate is the answer on the
console, so this says so and carries on — refusing here would hide the failure
this exists to show.
"""

from __future__ import annotations

import argparse
import sys

from app.brain import client, gate, qa
from app.db import get_session_factory
from app.settings import settings

DEFAULT_QUESTION = "what is happening in Indonesia?"


def _report_environment() -> None:
    local = gate.ollama_is_local()
    print(f"model          {settings.qa_model}")
    print(f"ollama         {settings.ollama_url}")
    print(f"same machine   {local}")
    #: The reading only means something when the model will be held in the memory
    #: this process can see. Reached over Docker Desktop it is the container's
    #: share, not the machine's — 724 MB against a 3800 MB floor on a Mac with far
    #: more than either, printed beside an open gate. Three numbers that look like
    #: a contradiction, and the guard was right: it declines to judge a machine it
    #: cannot measure, so the floor is not what it is being compared against.
    if local:
        print(f"free RAM       {gate.ram_free_mb()} MB (floor {settings.qa_min_free_mb} MB)")
    else:
        print("free RAM       not measured — Ollama runs outside this container")
        print(f"               (floor {settings.qa_min_free_mb} MB does not apply)")
    if gate.qa_ram_blocked():
        print("gate           BLOCKED — the console would answer 'brain busy'")
    else:
        print("gate           open")
    #: This command goes past the flag on purpose — somebody typing it has asked
    #: deliberately, and a build without the box is exactly when the terminal
    #: route matters most. Printed anyway, beside the gate and the floor, so an
    #: answer here and no ask control on screen is one line of output rather
    #: than a puzzle about which of the two is broken.
    if settings.ask_enabled:
        print("ask_enabled    true — the console draws the ask control")
    else:
        print("ask_enabled    false — the console draws no ask control; this asks anyway")


def _report_prompt(prompt: str) -> None:
    tokens = client.estimated_tokens(prompt)
    print(f"prompt         {len(prompt)} chars, about {tokens} tokens")
    print(f"context window {client._NUM_CTX} tokens")
    if tokens > client._NUM_CTX:
        #: Ollama truncates rather than refusing, so this never raises — it
        #: quietly answers from part of the prompt, which reads as a bad model
        #: rather than a prompt that did not fit.
        print("               TRUNCATED — the model sees only part of this")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="*", default=[], help="what to ask")
    parser.add_argument(
        "--json",
        action="store_true",
        help="use the JSON prompt path the non-stream endpoint uses",
    )
    args = parser.parse_args(argv)
    question = " ".join(args.question) or DEFAULT_QUESTION

    _report_environment()
    print(f"question       {question}")
    print()

    session = get_session_factory()()
    try:
        qa_context = qa.build_qa_context(session, question=question)
    finally:
        session.close()

    stories = qa_context.get("stories") or []
    sensors = qa_context.get("sensors") or []
    print(f"retrieved      {len(stories)} stories, {len(sensors)} sensor rows")

    if args.json:
        prompt = qa.build_qa_prompt(qa_context, question)
    else:
        prompt = qa.build_qa_text_prompt(qa_context, question)
    _report_prompt(prompt)
    print()

    #: Deliberately unguarded. A traceback here is the point of the command.
    if args.json:
        payload = client.generate_json(
            prompt, model=settings.qa_model, keep_alive=settings.qa_keep_alive
        )
        print(payload)
        return 0

    for chunk in client.generate_text_stream(
        prompt, model=settings.qa_model, keep_alive=settings.qa_keep_alive
    ):
        sys.stdout.write(chunk)
        sys.stdout.flush()
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
