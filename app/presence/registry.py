"""What presence sources exist, and where they are read from.

A presence source is described here and nowhere else, so adding the next one is
a configuration change rather than an architectural argument. That is the whole
point of the tier: the decision about whether something may be stored is made
once, in the boundary, not again per sensor.

Endpoints are listed in priority order. Two further aggregators serve this same
data and would make good fallbacks, but both refused a request to read their
terms of use, so neither is configured. A fallback whose licence nobody has
read is not a fallback — it is an unexamined dependency waiting to be noticed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PresenceSource:
    """One live, unstored source."""

    id: str
    label: str
    #: Base URLs, tried in order until one answers.
    endpoints: tuple[str, ...]
    #: How long an answer may be reused. Positions go stale in seconds, but a
    #: map redrawn every few seconds is not more truthful, only more expensive
    #: for somebody else's server.
    ttl_s: float
    #: Rendered wherever the layer is visible. ODbL requires the notice.
    attribution: str


SOURCES: dict[str, PresenceSource] = {
    "aircraft": PresenceSource(
        id="aircraft",
        label="Military air",
        endpoints=("https://api.adsb.lol",),
        ttl_s=30.0,
        attribution="adsb.lol · ODbL",
    ),
    #: Vessels broadcasting AIS (#954). A national authority's own terrestrial
    #: receivers, published openly under CC BY 4.0 — the terms were read, and
    #: they require the notice and a link, which the layer renders.
    #:
    #: One source, one sea area. Every other open feed found either wanted an
    #: account, wanted a receiver contributed, or published files rather than a
    #: live picture, and satellite AIS — the only thing that would cover the
    #: open ocean — is a paid product. So this layer is honest about being
    #: coastal rather than pretending to be global.
    "vessels": PresenceSource(
        id="vessels",
        label="Vessels",
        endpoints=("https://meri.digitraffic.fi",),
        ttl_s=45.0,
        attribution="Fintraffic / digitraffic.fi · CC BY 4.0",
    ),
    #: A second sea area (#954). Open data, but behind an account and an OAuth
    #: client, so it only contributes when credentials are configured — see
    #: `app/presence/vessels_no.py`. Two sea areas is still a coastline: the
    #: limit moves, it does not go away, and the copy on the layer says so.
    "vessels_no": PresenceSource(
        id="vessels_no",
        label="Vessels (Norwegian waters)",
        endpoints=("https://live.ais.barentswatch.no",),
        ttl_s=45.0,
        attribution="BarentsWatch · NLOD",
    ),
}


def source_for(source_id: str) -> PresenceSource:
    source = SOURCES.get(source_id)
    if source is None:
        raise KeyError(f"no presence source named {source_id!r}")
    return source
