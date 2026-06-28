"""Pure tests for ``app.sources.abuse_ch_fetchers``."""

from __future__ import annotations

from datetime import UTC, datetime

from app.enrichment.ip_geo import IpGeo
from app.models import Category
from app.sources.abuse_ch_fetchers import (
    CYBER_DEFAULT_SEVERITY,
    CYBER_HEAVY_SEVERITY,
    parse_feodo_csv,
    parse_urlhaus_csv,
)

FETCHED_AT = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)
PUBLIC_IP = ".".join(["93", "184", "216", "34"])


# URLhaus
URLHAUS_SAMPLE = """\
# Comments at the top should be skipped
# id,dateadded,url,url_status,last_online,threat,tags,urlhaus_link,reporter
1,2026-06-22 11:45:00,http://example.com/bad.exe,online,2026-06-22 11:46:00,malware_download,trojan,https://urlhaus.abuse.ch/1,reporter1
2,2026-06-22 11:50:00,http://phishy.example/login,online,2026-06-22 11:51:00,phishing,phishing-kit,https://urlhaus.abuse.ch/2,reporter2
3,2026-06-22 11:55:00,http://benign.example/something,online,2026-06-22 11:56:00,malware_download,fakeupdate,https://urlhaus.abuse.ch/3,reporter3
"""


def test_urlhaus_parse_count() -> None:
    events = parse_urlhaus_csv(URLHAUS_SAMPLE, fetched_at=FETCHED_AT)
    assert len(events) == 3


def test_urlhaus_event_shape() -> None:
    events = parse_urlhaus_csv(URLHAUS_SAMPLE, fetched_at=FETCHED_AT)
    ev = events[0]
    assert ev.source == "abuse-ch-urlhaus"
    assert ev.category == Category.CYBER
    assert ev.payload["url"] == "http://example.com/bad.exe"
    assert "trojan" in ev.payload["tags"]


def test_urlhaus_ip_host_gets_geo() -> None:
    body = (
        f"1,2026-06-22 11:45:00,http://{PUBLIC_IP}/bad.exe,online,"
        "2026-06-22 11:46:00,malware_download,trojan,https://urlhaus.abuse.ch/1,reporter1\n"
    )
    events = parse_urlhaus_csv(
        body,
        fetched_at=FETCHED_AT,
        geo_by_ip={PUBLIC_IP: IpGeo(PUBLIC_IP, "US", "Mountain View", 37.4, -122.1)},
    )
    assert events[0].country == "US"
    assert events[0].lat == 37.4
    assert events[0].payload["geo_city"] == "Mountain View"


def test_urlhaus_severity_heavy_on_phishing_kit_tag() -> None:
    events = parse_urlhaus_csv(URLHAUS_SAMPLE, fetched_at=FETCHED_AT)
    phishy = next(e for e in events if "phishing-kit" in e.payload["tags"])
    assert phishy.severity == CYBER_HEAVY_SEVERITY


def test_urlhaus_severity_default_for_unheavy_row() -> None:
    events = parse_urlhaus_csv(URLHAUS_SAMPLE, fetched_at=FETCHED_AT)
    benign = next(e for e in events if "benign" in e.payload["url"])
    assert benign.severity == CYBER_DEFAULT_SEVERITY


def test_urlhaus_skips_short_rows() -> None:
    body = "1,2026-06-22 11:45:00,http://x,online\n"
    assert parse_urlhaus_csv(body, fetched_at=FETCHED_AT) == []


# Feodo Tracker
FEODO_SAMPLE = """\
# Comments
# first_seen_utc,dst_ip,dst_port,c2_status,last_online,malware
2026-06-21 23:00:00,1.2.3.4,443,online,2026-06-22 11:00:00,Emotet
2026-06-22 04:00:00,5.6.7.8,8080,online,2026-06-22 11:30:00,TrickBot
"""


def test_feodo_parse_count() -> None:
    events = parse_feodo_csv(FEODO_SAMPLE, fetched_at=FETCHED_AT)
    assert len(events) == 2


def test_feodo_event_shape() -> None:
    events = parse_feodo_csv(FEODO_SAMPLE, fetched_at=FETCHED_AT)
    ev = events[0]
    assert ev.source == "abuse-ch-feodo"
    assert ev.category == Category.CYBER
    assert ev.payload["dst_ip"] == "1.2.3.4"
    assert ev.payload["dst_port"] == 443
    assert ev.payload["malware"] == "Emotet"


def test_feodo_geo_enrichment() -> None:
    events = parse_feodo_csv(
        FEODO_SAMPLE,
        fetched_at=FETCHED_AT,
        geo_by_ip={"1.2.3.4": IpGeo("1.2.3.4", "GB", "London", 51.5, -0.1)},
    )
    ev = events[0]
    assert ev.country == "GB"
    assert ev.lon == -0.1
    assert ev.payload["geo_country"] == "GB"


def test_feodo_severity_always_heavy() -> None:
    events = parse_feodo_csv(FEODO_SAMPLE, fetched_at=FETCHED_AT)
    for ev in events:
        assert ev.severity == CYBER_HEAVY_SEVERITY


def test_feodo_skips_short_rows() -> None:
    body = "2026-06-21 23:00:00,1.2.3.4,443\n"
    assert parse_feodo_csv(body, fetched_at=FETCHED_AT) == []


def test_feodo_handles_non_integer_port() -> None:
    body = "2026-06-21 23:00:00,1.2.3.4,unknown,online,2026-06-22 11:00:00,Emotet\n"
    events = parse_feodo_csv(body, fetched_at=FETCHED_AT)
    assert len(events) == 1
    assert events[0].payload["dst_port"] is None
