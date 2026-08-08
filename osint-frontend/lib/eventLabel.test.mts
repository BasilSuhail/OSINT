import { describe, expect, it } from "vitest"
import { machineAction, publisherOf, sourceUrlOf } from "./eventLabel"
import type { EventRow } from "./types"

const row = (over: Partial<EventRow> = {}): EventRow =>
  ({
    id: "1",
    source: "gdelt",
    source_event_id: "g1",
    occurred_at: "2026-08-08T12:00:00Z",
    fetched_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: [],
    country: "US",
    lat: 1,
    lon: 1,
    payload: {},
    ...over,
  }) as EventRow

describe("machineAction", () => {
  it("returns the coded action so it can be shown as one", () => {
    expect(machineAction(row({ payload: { action_label: "Coerce" } as never }))).toBe("Coerce")
  })

  it("is null when the row has none, rather than inventing a label", () => {
    expect(machineAction(row())).toBeNull()
    expect(machineAction(row({ payload: { action_label: "  " } as never }))).toBeNull()
  })
})

describe("publisherOf", () => {
  it("prefers what the API decided", () => {
    expect(publisherOf(row({ publisher: "postbulletin.com" }))).toBe("postbulletin.com")
  })

  it("falls back to the article domain for an older API or a cached row", () => {
    const ev = row({ payload: { source_url: "https://www.bbc.co.uk/news/a" } as never })
    expect(publisherOf(ev)).toBe("bbc.co.uk")
  })

  it("credits nobody when there is nobody to credit", () => {
    expect(publisherOf(row({ source: "usgs-quake" }))).toBeNull()
    expect(publisherOf(row({ payload: { source_url: "20260806121500" } as never }))).toBeNull()
  })
})

describe("sourceUrlOf", () => {
  it("returns the article link", () => {
    const ev = row({ payload: { source_url: "https://example.com/a" } as never })
    expect(sourceUrlOf(ev)).toBe("https://example.com/a")
  })

  it("rejects the pre-#733 timestamp payloads", () => {
    expect(sourceUrlOf(row({ payload: { source_url: "20260806121500" } as never }))).toBeNull()
  })
})
