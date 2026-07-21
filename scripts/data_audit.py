"""Audit every source: does its severity parse, vary, and reach anything (#580).

Report-only. It reads, prints, and always exits 0 — a tool, not a gate. Every
finding is an existing defect, so a long list on the first run is the intended
outcome rather than a regression.

    uv run python scripts/data_audit.py            # findings only
    uv run python scripts/data_audit.py --all      # every source, including clean ones
"""

import argparse
from collections import defaultdict

from app.audit import expectations, run
from app.db import session_scope


def _describe(stats) -> str:
    severity = "no severity"
    if stats.severity_present:
        severity = (
            f"severity {stats.severity_distinct} distinct, "
            f"top {stats.severity_top_share * 100:.0f}%, std {stats.severity_std:.4f}"
        )
    return f"{stats.rows:,} rows, {severity}, {stats.composite_eligible:,} reach the composite"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="include sources with no findings")
    args = parser.parse_args()

    with session_scope() as session:
        stats_by_source = {s.source: s for s in run.gather_stats(session)}
        findings = run.audit(session)

    grouped = defaultdict(list)
    for finding in findings:
        grouped[finding.source].append(finding)

    for source in sorted(stats_by_source):
        source_findings = grouped.get(source, [])
        if not source_findings and not args.all:
            continue
        declared = expectations.for_source(source)
        print(f"\n{source}")
        print(f"  {_describe(stats_by_source[source])}")
        if declared is not None:
            print(
                f"  declared: severity={declared.severity} country={declared.country} "
                f"composite={declared.feeds_composite}"
            )
        for finding in source_findings:
            print(f"  [{finding.check}] {finding.detail}")
        if not source_findings:
            print("  ok")

    by_check = defaultdict(int)
    for finding in findings:
        by_check[finding.check] += 1

    print(f"\n{len(findings)} finding(s) across {len(grouped)} source(s):")
    for check, count in sorted(by_check.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>3}  {check}")


if __name__ == "__main__":
    main()
