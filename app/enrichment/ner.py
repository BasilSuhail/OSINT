"""News-headline NER (named-entity recognition).

v1 wraps spaCy ``en_core_web_sm`` (~15 MB, MIT). Lazy-loaded so the
Celery worker cold start doesn't pay the ~700 ms model-load tax until
the first row needs enrichment.

spaCy is declared as an **optional** dependency (``[nlp]`` extra).
When the model can't be loaded — wheel missing, model not downloaded,
ImportError — ``extract_entities`` returns an empty list. The fetcher
will then write ``payload.entities = []`` and stamp the meta with
``ner_model = "none"`` so a downstream re-run with the model
available can be told apart from a row that genuinely had no entities.

Method version is stamped on every enriched row so the model
substitution path (transformer NER, FinBERT, etc.) keeps history
reproducible.

See issue #154 (split out of the original #126 umbrella).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

#: Bumped together with any change to model or wrapper. Never edit a
#: prior version in place.
NER_METHOD_VERSION: str = "spacy.en_core_web_sm.v1.0"

#: Entity labels we surface downstream. Filters spaCy's full label set
#: down to the ones useful for the dashboard / future entity graph.
_KEPT_LABELS: frozenset[str] = frozenset({"PERSON", "ORG", "GPE", "LOC", "EVENT", "NORP", "FAC"})

#: Cap on entities returned per row. Headlines rarely have more.
_MAX_ENTITIES: int = 12


@dataclass(frozen=True)
class Entity:
    """One named entity extracted from a headline."""

    text: str
    label: str


@lru_cache(maxsize=1)
def _model():
    """Lazy load spaCy + the small English model. Returns None on failure.

    Wrapped in lru_cache(1) so the import cost is paid once per process.
    """
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        return None


def is_available() -> bool:
    """Whether NER will produce non-empty output. Useful for tests + meta."""
    return _model() is not None


@lru_cache(maxsize=8192)
def extract_entities(text: str) -> tuple[Entity, ...]:
    """Pull named entities out of one text. Returns a tuple so the
    lru_cache stays hashable.

    Strategy:
    - Skip empty input.
    - Run spaCy if available.
    - Filter to ``_KEPT_LABELS``.
    - De-dupe on (text.lower(), label).
    - Trim to ``_MAX_ENTITIES``.

    On model-unavailable, returns an empty tuple so callers can treat
    "no entities" + "model not loaded" uniformly without branching.
    """
    if not text or not text.strip():
        return ()
    nlp = _model()
    if nlp is None:
        return ()
    doc = nlp(text)
    seen: set[tuple[str, str]] = set()
    out: list[Entity] = []
    for ent in doc.ents:
        label = ent.label_
        if label not in _KEPT_LABELS:
            continue
        cleaned = ent.text.strip()
        if not cleaned:
            continue
        key = (cleaned.lower(), label)
        if key in seen:
            continue
        seen.add(key)
        out.append(Entity(text=cleaned, label=label))
        if len(out) >= _MAX_ENTITIES:
            break
    return tuple(out)


def entities_to_payload(entities: tuple[Entity, ...]) -> list[dict[str, str]]:
    """Serialize the entity tuple for the events.payload JSON column."""
    return [{"text": e.text, "label": e.label} for e in entities]
