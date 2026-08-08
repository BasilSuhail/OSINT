"""A desk that does not publish in English is invisible here (#835).

Al Jazeera's Arabic desk publishes 218 items a day — 2.7 times its English feed.
Run through the real transform it produced this:

```
entries=25  events=25
with country=0    with coords=0    bases: {'none': 25}
severity: {0.15: 25}
```

Nothing resolved, because nothing here can read it:

```
geo_terms entries: 426    arabic-script: 0
cities: 7,484             with arabic alt spellings: 0
```

Translating the headline first makes the existing resolver, severity and
clustering work unchanged. Measured on real headlines from that feed against
the models already installed:

```
qwen3.5:4b-q4_K_M   134.3 s/headline   3 of 4 responses empty     unusable
llama3.2:3b           2.2 s/headline   4 of 4 accurate            8 min/day
```

## The authenticity rules, which are the whole risk

A machine translation is **not the publisher's words**. Presenting one as an
outlet's headline is a fabrication risk, and this project counts that outlet
as a teller in `owner_count`.

So: the original is stored verbatim and never overwritten; the translation
carries its own provenance — model, method version, when, and what it was
translated from; a failure keeps the original and says so, rather than
producing an empty headline. What a reader sees is English and is labelled as
translated. What an audit reads is both.

`title` carries the English text because every consumer downstream — the geo
resolver, `readable_claim`, the search vector, story clustering — reads that
field, and a translation nothing reads is a translation that changed nothing.
The original lives in `title_original`, which is the field an audit or a
citation must use.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

logger = logging.getLogger(__name__)

#: Bumped when the prompt or the model changes, so a re-run is distinguishable
#: from an old row.
TRANSLATION_METHOD_VERSION: Final[str] = "translate.v1.0"

#: Measured 2.2 s/headline and accurate on this feed's real output, against
#: 134 s and three empty responses of four from the 4B thinking model. Chosen
#: on that measurement, not on size.
TRANSLATION_MODEL: Final[str] = "llama3.2:3b"

#: Scripts that mean the existing English-only gazetteers cannot match. This is
#: a *routing* test, not language detection: it decides whether to spend a
#: model call, and being wrong costs one call rather than a wrong answer.
_NON_LATIN: Final[re.Pattern[str]] = re.compile(
    r"[؀-ۿݐ-ݿ"  # Arabic, Arabic supplement
    r"Ѐ-ӿ"  # Cyrillic
    r"֐-׿"  # Hebrew
    r"ऀ-ॿ"  # Devanagari
    r"一-鿿"  # CJK
    r"぀-ヿ"  # kana
    r"가-힯]"  # Hangul
)

#: Below this share of non-Latin letters a headline is English with a name or
#: a quoted phrase in it, and translating it would rewrite English rather than
#: fix anything.
#:
#: Set from the measured spread, not chosen: across the 25 real headlines on
#: the Arabic desk the share is 1.00 — every one, minimum 1.00. An English
#: control scores 0.00 and an English headline quoting one Arabic
#: organisation name scores 0.25. Half the letters separates those with a very
#: large margin either side.
NON_LATIN_SHARE: Final[float] = 0.50

#: Long enough to be a headline, short enough that a runaway response is
#: visible rather than stored.
MAX_TRANSLATION_CHARS: Final[int] = 400


@dataclass(frozen=True)
class Translation:
    """One translated string and where it came from."""

    text: str
    original: str
    model: str
    method_version: str = TRANSLATION_METHOD_VERSION

    def provenance(self, *, now: datetime | None = None) -> dict[str, Any]:
        return {
            "model": self.model,
            "method_version": self.method_version,
            "translated_at": (now or datetime.now(UTC)).isoformat(),
        }


def non_latin_share(text: str) -> float:
    """Fraction of letters written in a script the gazetteers cannot match."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if _NON_LATIN.match(ch)) / len(letters)


def needs_translation(text: str | None, *, declared_language: str | None) -> bool:
    """Should this string cost a model call?

    A feed's declared language decides it — an outlet that publishes in Arabic
    says so in the registry, and guessing per row would spend calls on English
    headlines that merely quote a name. The script check is the second gate:
    a row from an Arabic desk that happens to be written in Latin script (a
    transliterated wire item) needs nothing.
    """
    if not text or not text.strip():
        return False
    if (declared_language or "en").lower().startswith("en"):
        return False
    return non_latin_share(text) >= NON_LATIN_SHARE


def build_prompt(text: str) -> str:
    """The instruction. Deliberately narrow: a headline, not a conversation.

    "Reply with the translation only" matters — a model that adds "Here is the
    translation:" writes that phrase into a headline a reader will see.
    """
    return (
        "Translate this news headline into English. "
        "Reply with the translation only, no quotes, no commentary, no notes.\n\n" + text
    )


def clean_response(raw: str | None) -> str | None:
    """The model's answer, or None when it did not give a usable one.

    Refusing is a real outcome and must stay visible: an empty translation
    stored as a headline is worse than no translation, because the row then
    looks readable and says nothing. The 4B model returned empty on three of
    four real headlines, so this is not hypothetical.
    """
    if not raw:
        return None
    text = " ".join(raw.strip().split())
    #: Models like to announce themselves. Strip one leading label rather than
    #: every possible phrasing — the prompt already asks for none.
    text = re.sub(r"^(?:here (?:is|'s) the translation:?|translation:)\s*", "", text, flags=re.I)
    text = text.strip().strip('"').strip()
    if not text or len(text) > MAX_TRANSLATION_CHARS:
        return None
    return text


def translate(
    text: str,
    *,
    generate,
    model: str = TRANSLATION_MODEL,
) -> Translation | None:
    """One string → an English `Translation`, or None when it could not be done.

    `generate` is injected so every rule above is testable without a model and
    without a network. A failure here is never fatal: the caller keeps the
    original and records that the translation was attempted.
    """
    try:
        raw = generate(build_prompt(text), model=model)
    except Exception as exc:
        logger.warning("translation failed for a %d-char headline: %s", len(text), exc)
        return None
    cleaned = clean_response(raw)
    if cleaned is None:
        return None
    return Translation(text=cleaned, original=text, model=model)


def apply(
    payload: dict[str, Any],
    *,
    declared_language: str | None,
    generate,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return `payload` with an English title, keeping the original verbatim.

    Untouched when the feed publishes in English, when the text is already
    Latin script, or when the model could not answer — and in that last case
    the payload records the attempt, so a desk that silently stopped
    translating is visible rather than merely quiet.
    """
    title = payload.get("title")
    if not needs_translation(title, declared_language=declared_language):
        return payload

    result = translate(str(title), generate=generate)
    out = dict(payload)
    if result is None:
        out["title_translation"] = {
            "status": "failed",
            "model": TRANSLATION_MODEL,
            "method_version": TRANSLATION_METHOD_VERSION,
            "attempted_at": (now or datetime.now(UTC)).isoformat(),
        }
        return out

    out["title"] = result.text
    out["title_original"] = result.original
    out["title_translation"] = {"status": "ok", **result.provenance(now=now)}
    return out
