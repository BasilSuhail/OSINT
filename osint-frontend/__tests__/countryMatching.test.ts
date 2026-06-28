import { describe, expect, it } from "vitest"
import { countryCodesForEvent, eventMatchesCountry } from "@/lib/countryMatching"
import type { EventRow } from "@/lib/types"

function row(over: Partial<EventRow> = {}): EventRow {
  return {
    id: "x",
    source: "gdacs",
    source_event_id: "TC:1001278",
    occurred_at: "2026-06-22T12:00:00Z",
    fetched_at: null,
    category: "hazard",
    severity: 0.2,
    keywords: [],
    country: "GU",
    lat: 36.4,
    lon: 142.9,
    payload: {},
    ...over,
  }
}

describe("eventMatchesCountry", () => {
  it("matches the canonical country field", () => {
    expect(eventMatchesCountry(row(), new Set(["GU"]))).toBe(true)
  })

  it("matches GDACS affected countries", () => {
    expect(
      eventMatchesCountry(
        row({
          payload: {
            affected_countries: [
              { iso2: "JP", iso3: "JPN", countryname: "Japan" },
              { iso2: "GU", iso3: "GUM", countryname: "Guam" },
            ],
          },
        }),
        new Set(["JP"]),
      ),
    ).toBe(true)
  })

  it("exposes canonical and affected country codes for filter pickers", () => {
    expect(
      countryCodesForEvent(
        row({
          payload: {
            affected_countries: [
              { iso2: "JP", iso3: "JPN", countryname: "Japan" },
              { iso2: "GU", iso3: "GUM", countryname: "Guam" },
            ],
          },
        }),
      ),
    ).toEqual(["GU", "JP"])
  })

  it("does not match unrelated country filters", () => {
    expect(eventMatchesCountry(row(), new Set(["US"]))).toBe(false)
  })
})
