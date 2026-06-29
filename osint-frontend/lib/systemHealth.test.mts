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
})
