import { describe, expect, it } from "vitest"

import type { DatasetHealthSummary } from "@/lib/systemHealth"
import {
  attentionCounts,
  BAND_LABEL,
  formatAge,
  groupByBand,
  insertedByDay,
  sparklinePoints,
  totalRecentRows,
} from "@/lib/systemMonitor"
import type { IngestHealthRow, SourceCoverageRow } from "@/lib/types"

function dataset(
  key: string,
  status: DatasetHealthSummary["status"],
): DatasetHealthSummary {
  return {
    key,
    label: key.toUpperCase(),
    healthy: status === "ok" ? 1 : 0,
    total: 1,
    warn: status === "warn" ? 1 : 0,
    stale: status === "stale" ? 1 : 0,
    offline: status === "offline" ? 1 : 0,
    status,
    detail: `${key} detail`,
    latestIso: null,
  }
}

function ingestRow(day: string, inserted: number | null, accepted?: number): IngestHealthRow {
  return {
    source: `src-${day}-${inserted}`,
    day,
    success_n: 1,
    failure_n: 0,
    inserted_rows: inserted,
    accepted_rows: accepted ?? null,
    last_success: null,
    last_failure: null,
  }
}

describe("groupByBand", () => {
  it("orders groups worst first and drops empty bands", () => {
    const groups = groupByBand([
      dataset("a", "ok"),
      dataset("b", "stale"),
      dataset("c", "offline"),
      dataset("d", "stale"),
    ])
    expect(groups.map((g) => g.band)).toEqual(["offline", "stale", "ok"])
    expect(groups.map((g) => g.count)).toEqual([1, 2, 1])
  })

  it("names warn as degraded so the header reads as a condition", () => {
    const [group] = groupByBand([dataset("a", "warn")])
    expect(group.label).toBe("degraded")
    expect(BAND_LABEL.ok).toBe("online")
  })
})

describe("attentionCounts", () => {
  it("counts only the bands worth opening the panel for", () => {
    const counts = attentionCounts([
      dataset("a", "offline"),
      dataset("b", "warn"),
      dataset("c", "warn"),
      dataset("d", "ok"),
      dataset("e", "ok"),
    ])
    expect(counts).toEqual([
      { band: "offline", count: 1 },
      { band: "warn", count: 2 },
    ])
  })

  it("is empty when every source is online", () => {
    expect(attentionCounts([dataset("a", "ok"), dataset("b", "ok")])).toEqual([])
  })
})

describe("formatAge", () => {
  const now = Date.parse("2026-08-12T12:00:00Z")

  it("uses minutes below the hour", () => {
    expect(formatAge("2026-08-12T11:48:00Z", now)).toBe("12m")
  })

  it("uses hours and padded minutes below the day", () => {
    expect(formatAge("2026-08-12T07:48:00Z", now)).toBe("4h 12m")
  })

  it("uses days and padded hours above the day", () => {
    expect(formatAge("2026-08-11T08:00:00Z", now)).toBe("1d 04h")
  })

  it("shows a dash rather than a number it cannot compute", () => {
    expect(formatAge(null, now)).toBe("—")
    expect(formatAge("not a date", now)).toBe("—")
  })
})

describe("insertedByDay", () => {
  it("sums every source into one series, oldest first", () => {
    const series = insertedByDay([
      ingestRow("2026-08-12", 5),
      ingestRow("2026-08-11", 3),
      ingestRow("2026-08-12", 7),
    ])
    expect(series).toEqual([
      { day: "2026-08-11", inserted: 3 },
      { day: "2026-08-12", inserted: 12 },
    ])
  })

  it("falls back to accepted rows when a source reports no inserts", () => {
    expect(insertedByDay([ingestRow("2026-08-12", null, 4)])).toEqual([
      { day: "2026-08-12", inserted: 4 },
    ])
  })
})

describe("sparklinePoints", () => {
  it("scales to the tallest day and spans the full width", () => {
    const points = sparklinePoints([
      { day: "a", inserted: 0 },
      { day: "b", inserted: 5 },
      { day: "c", inserted: 10 },
    ])
    expect(points).toEqual([
      { x: 0, y: 1 },
      { x: 0.5, y: 0.5 },
      { x: 1, y: 0 },
    ])
  })

  it("draws nothing when nothing was written", () => {
    expect(sparklinePoints([
      { day: "a", inserted: 0 },
      { day: "b", inserted: 0 },
    ])).toEqual([])
  })

  it("draws nothing from a single day, which has no shape", () => {
    expect(sparklinePoints([{ day: "a", inserted: 9 }])).toEqual([])
  })
})

describe("totalRecentRows", () => {
  it("sums the windowed count, not the lifetime total", () => {
    const rows: SourceCoverageRow[] = [
      { source: "a", total: 900, recent: 10, geocoded: 5, latest_occurred_at: null, earliest_occurred_at: null, latest_fetched_at: null },
      { source: "b", total: 100, recent: 4, geocoded: 1, latest_occurred_at: null, earliest_occurred_at: null, latest_fetched_at: null },
    ]
    expect(totalRecentRows(rows)).toBe(14)
  })
})
