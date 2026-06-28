import { describe, expect, it } from "vitest"
import { hazardFootprintCollections } from "@/lib/mapFootprints"
import type { EventRow } from "@/lib/types"
import type { VisibleEvent } from "@/lib/queries"

function visible(over: Partial<EventRow>): VisibleEvent {
  return {
    id: "hazard-1",
    source: "gdacs",
    source_event_id: "x",
    occurred_at: "2026-06-24T00:00:00Z",
    fetched_at: null,
    category: "hazard",
    severity: 0.7,
    keywords: [],
    country: "US",
    lat: 29,
    lon: -90,
    payload: { event_type: "FL", alert_level: "Orange" },
    age: 0,
    opacity: 1,
    occurredMs: Date.parse("2026-06-24T00:00:00Z"),
    ...over,
  } as VisibleEvent
}

describe("hazardFootprintCollections", () => {
  it("keeps the selected event footprint in the selected collection", () => {
    const selected = visible({ id: "selected" })
    const other = visible({ id: "other", lon: -80 })

    const collections = hazardFootprintCollections([{ ev: selected }, { ev: other }], "selected")

    expect(collections.selected.features).toHaveLength(1)
    expect(collections.selected.features[0].properties.selected).toBe(true)
    expect(collections.ambient.features).toHaveLength(1)
    expect(collections.ambient.features[0].properties.selected).toBe(false)
  })
})
