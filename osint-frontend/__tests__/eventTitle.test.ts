import { describe, expect, it } from "vitest"
import { eventHeadline, sourceHost } from "@/lib/eventTitle"
import type { EventRow } from "@/lib/types"

function row(payload: Record<string, unknown>, source = "gdelt"): EventRow {
  return {
    id: "1",
    source,
    source_event_id: null,
    occurred_at: "2026-08-04T21:00:00Z",
    fetched_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: null,
    country: "GB",
    lat: 55.95,
    lon: -3.19,
    payload,
  } as EventRow
}

describe("sourceHost", () => {
  it("says the domain the way a person would", () => {
    expect(sourceHost("https://www.rte.ie/news/2026/0803/1586235-pakistan/")).toBe("rte.ie")
  })

  it("refuses a timestamp where a URL belongs", () => {
    // Every GDELT row stored before #733 has a 14-digit DATEADDED here.
    expect(sourceHost("20260803094500")).toBeNull()
  })

  it("refuses junk rather than throwing", () => {
    expect(sourceHost("://///")).toBeNull()
    expect(sourceHost(null)).toBeNull()
  })
})

describe("eventHeadline", () => {
  it("uses the article's own headline once the beat has fetched it", () => {
    expect(
      eventHeadline(row({ title: "Two villages evacuated as wildfire jumps the ridge" })),
    ).toBe("Two villages evacuated as wildfire jumps the ridge")
  })

  it("never prints the CAMEO label as a headline", () => {
    // The whole point of #788: `Coerce` covered a credit union's tornado
    // donation, a missing-boy rescue and a guilty-plea reversal.
    const headline = eventHeadline(
      row({
        action_label: "Coerce",
        event_root_code: "17",
        geo_name: "Edinburgh, Edinburgh, City of, United Kingdom",
        source_url: "https://www.bbc.co.uk/news/uk-scotland-123",
      }),
    )
    expect(headline).not.toMatch(/coerce/i)
    expect(headline).toBe("bbc.co.uk · Edinburgh")
  })

  it("names the place by its first part, not the whole geo string", () => {
    expect(
      eventHeadline(
        row({ geo_name: "Neenah, Wisconsin, United States", source_url: "https://fox11online.com/a" }),
      ),
    ).toBe("fox11online.com · Neenah")
  })

  it("falls back to the source when the URL is the old timestamp", () => {
    expect(eventHeadline(row({ source_url: "20260803094500", geo_name: "Kyiv, Ukraine" }))).toBe(
      "gdelt · Kyiv",
    )
  })

  it("says the source alone rather than inventing a place", () => {
    expect(eventHeadline(row({}, "gdelt"))).toBe("gdelt")
  })

  it("keeps working for feed rows, which always have a title", () => {
    expect(eventHeadline(row({ title: "Oil prices fall on Hormuz hopes" }, "rss-reuters"))).toBe(
      "Oil prices fall on Hormuz hopes",
    )
  })
})
