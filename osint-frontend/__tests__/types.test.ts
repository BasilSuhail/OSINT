import { describe, expect, it } from "vitest"
import { sourceKeyForEvent, type EventRow } from "@/lib/types"

function row(over: Partial<EventRow>): EventRow {
  return {
    id: "x",
    source: "gdelt",
    source_event_id: "x",
    occurred_at: "2026-06-28T00:00:00Z",
    fetched_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: [],
    country: null,
    lat: null,
    lon: null,
    payload: {},
    ...over,
  }
}

describe("sourceKeyForEvent", () => {
  it("keeps cyber and Polymarket rows in the frontend buffer", () => {
    expect(sourceKeyForEvent(row({ source: "abuse-ch-urlhaus", category: "cyber" }))).toBe("CYBER")
    expect(sourceKeyForEvent(row({ source: "abuse-ch-feodo", category: "cyber" }))).toBe("CYBER")
    expect(sourceKeyForEvent(row({ source: "polymarket", category: "market" }))).toBe("POLYMARKET")
  })

  it("keeps FRED separate from yfinance market drawdowns", () => {
    expect(sourceKeyForEvent(row({ source: "fred", category: "market" }))).toBe("FRED")
    expect(sourceKeyForEvent(row({ source: "yfinance", category: "market" }))).toBe("yfinance")
  })

  it("keeps ACLED and EM-DAT as first-class source filters", () => {
    expect(sourceKeyForEvent(row({ source: "acled", category: "geopolitical" }))).toBe("ACLED")
    expect(sourceKeyForEvent(row({ source: "emdat", category: "hazard" }))).toBe("EMDAT")
  })
})
