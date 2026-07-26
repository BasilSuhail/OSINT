"""Who counts as an independent teller of a story (#641).

`corroboration-v1.0` is exponential in `owner_count` —
`doubt = 2^-(owner_count - 1 + sensor_flag)` — so this count is the single
largest lever on how confident the system claims to be about a story.

It used to be computed as `owner_map.get(source, source)`: a source with no
ownership record fell back to its own slug and therefore counted as a distinct
independent owner. That reads absence of evidence as evidence of independence.

Harmless while every feed in the registry carries an owner, and exactly what
#442 breaks — it admits blogs, small outlets and archived articles, which by
definition arrive with no ownership record. Ten such sources on one story would
have produced `owner_count = 10`, `doubt = 2^-9`, a score of **0.998**: ten
anonymous blogs outranking two wire services, and the components would have
reported it proudly.

The rule, stated once:

    Independence is positively established, never inferred from a missing
    record.

Unrecorded sources are still ingested, stored, retrieved and displayed — #442
wants exactly that, so the brain can weigh angles. They simply contribute
nothing to the confidence number. "Ten anonymous blogs said it" is one
unverified claim told ten times.

Promotion is deliberate: writing an owner into the registry is how a source
becomes counted. Admitting a source stays frictionless; trusting one does not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


def recorded_owner(source: str, owner_map: Mapping[str, str]) -> str | None:
    """The source's recorded content owner, or None when nobody wrote one down.

    Deliberately no slug fallback. Returning the slug is what let an unvetted
    source assert its own independence.
    """
    owner = owner_map.get(source)
    if owner is None:
        return None
    cleaned = owner.strip()
    return cleaned or None


def independent_owners(sources: Iterable[str], owner_map: Mapping[str, str]) -> set[str]:
    """The distinct recorded owners among these sources.

    Sources with no record are dropped rather than counted as themselves.
    """
    owners = (recorded_owner(source, owner_map) for source in sources)
    return {owner for owner in owners if owner is not None}


def owner_count(sources: Iterable[str], owner_map: Mapping[str, str]) -> int:
    """How many independent tellers a story has, for the corroboration score.

    Zero when nothing is recorded. `corroboration_score` clamps that to 1 and
    yields 0.0, which is the honest reading: a story told only by sources whose
    independence nobody has established has not been corroborated at all.
    """
    return len(independent_owners(sources, owner_map))
