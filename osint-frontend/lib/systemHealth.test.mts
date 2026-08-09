import { describe, expect, it } from "vitest"
import { summarizeSystemHealth } from "./systemHealth"
import type { IngestHealthRow, SourceCoverageRow } from "./types"

describe("summarizeSystemHealth", () => {
  it("summarizes single-source health", () => {
    const ingestRows: IngestHealthRow[] = [
      {
        source: "acled",
        day: "2026-06-29",
        success_n: 2,
        failure_n: 0,
        last_success: "2026-06-29T11:00:00Z",
        last_failure: null,
      },
    ]
    const coverageRows: SourceCoverageRow[] = [
      {
        source: "acled",
        total: 253172,
        recent: 500,
        geocoded: 253172,
        latest_occurred_at: "2026-06-13T00:00:00Z",
        latest_fetched_at: "2026-06-29T11:00:00Z",
      },
    ]

    const rows = summarizeSystemHealth(ingestRows, coverageRows, Date.parse("2026-06-29T12:00:00Z"))
    const acled = rows.find((row) => row.key === "acled")

    expect(acled).toMatchObject({
      label: "ACLED",
      status: "ok",
      healthy: 1,
      total: 1,
    })
  })

  it("groups rss feeds into a single news chip", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "rss-bbc-world",
          day: "2026-06-29",
          success_n: 1,
          failure_n: 0,
          last_success: "2026-06-29T11:00:00Z",
          last_failure: null,
        },
      ],
      [],
      Date.parse("2026-06-29T12:00:00Z"),
    )

    const news = rows.find((row) => row.key === "news")
    expect(news).toBeDefined()
    expect(news?.label).toBe("News")
    expect(news?.total).toBeGreaterThan(1)
  })

  it("does not call a recent zero-output check healthy", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "gdelt",
          day: "2026-06-29",
          success_n: 1,
          failure_n: 0,
          last_success: "2026-06-29T11:55:00Z",
          last_failure: null,
          last_state: "empty",
          last_checked: "2026-06-29T11:55:00Z",
          last_output: "2026-06-29T11:00:00Z",
        },
      ],
      [],
      Date.parse("2026-06-29T12:00:00Z"),
    )

    expect(rows.find((row) => row.key === "gdelt")).toMatchObject({
      status: "stale",
      latestIso: "2026-06-29T11:00:00Z",
    })
  })

  it("surfaces current configuration failures as offline", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "fred",
          day: "2026-06-29",
          success_n: 0,
          failure_n: 0,
          last_success: null,
          last_failure: null,
          last_state: "misconfigured",
          last_checked: "2026-06-29T11:59:00Z",
          last_output: null,
        },
      ],
      [],
      Date.parse("2026-06-29T12:00:00Z"),
    )

    expect(rows.find((row) => row.key === "fred")).toMatchObject({
      status: "offline",
      latestIso: null,
    })
  })

  it("uses a verified unchanged check for static file sources", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "acled",
          day: "2026-06-29",
          success_n: 1,
          failure_n: 0,
          last_success: "2026-06-29T11:55:00Z",
          last_failure: null,
          last_state: "unchanged",
          last_checked: "2026-06-29T11:55:00Z",
          last_output: "2026-06-01T00:00:00Z",
        },
      ],
      [],
      Date.parse("2026-06-29T12:00:00Z"),
    )

    expect(rows.find((row) => row.key === "acled")).toMatchObject({
      status: "ok",
      latestIso: "2026-06-29T11:55:00Z",
    })
  })

  it("retains usable output across a daily health-row boundary", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "gdelt",
          day: "2026-06-29",
          success_n: 1,
          failure_n: 0,
          last_success: "2026-06-29T23:59:00Z",
          last_failure: null,
          last_state: "new_data",
          last_checked: "2026-06-29T23:59:00Z",
          last_output: "2026-06-29T23:59:00Z",
        },
        {
          source: "gdelt",
          day: "2026-06-30",
          success_n: 0,
          failure_n: 0,
          last_success: null,
          last_failure: null,
          last_state: "empty",
          last_checked: "2026-06-30T00:01:00Z",
          last_output: null,
        },
      ],
      [],
      Date.parse("2026-06-30T00:02:00Z"),
    )

    expect(rows.find((row) => row.key === "gdelt")).toMatchObject({
      status: "warn",
      latestIso: "2026-06-29T23:59:00Z",
    })
  })

  it("ages an empty static source from its last successful check", () => {
    const rows = summarizeSystemHealth(
      [
        {
          source: "acled",
          day: "2026-06-29",
          success_n: 1,
          failure_n: 0,
          last_success: "2026-06-29T10:00:00Z",
          last_failure: null,
          last_state: "empty",
          last_checked: "2026-06-29T13:59:00Z",
          last_output: "2026-06-01T00:00:00Z",
        },
      ],
      [],
      Date.parse("2026-06-29T14:00:00Z"),
    )

    expect(rows.find((row) => row.key === "acled")).toMatchObject({
      status: "stale",
      latestIso: "2026-06-29T10:00:00Z",
    })
  })
})
