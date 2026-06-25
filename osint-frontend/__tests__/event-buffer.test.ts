import { describe, expect, it } from "vitest"

import { EventBuffer } from "@/lib/realtime"
import type { EventRow } from "@/lib/types"

function row(over: Partial<EventRow> = {}): EventRow {
  return {
    id: "x",
    source: "rss-bbc-world",
    source_event_id: null,
    occurred_at: new Date().toISOString(),
    fetched_at: null,
    category: "news",
    severity: 0.5,
    keywords: null,
    country: "GB",
    lat: null,
    lon: null,
    payload: {},
    ...over,
  }
}

describe("EventBuffer.ingest source filtering", () => {
  it("keeps events that map to a source toggle", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "1", source: "gdelt", category: "geopolitical" }),
      row({ id: "2", source: "rss-bbc-world", category: "news" }),
      row({ id: "3", source: "nasa-firms", category: "hazard" }),
    ])
    expect(buf.getSnapshot()).toHaveLength(3)
  })

  it("drops the opensky-adsb aviation firehose (no source toggle)", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "1", source: "opensky-adsb", category: "tracking" }),
      row({ id: "2", source: "opensky-adsb", category: "tracking" }),
    ])
    expect(buf.getSnapshot()).toHaveLength(0)
  })

  it("does not let aviation evict displayable events", () => {
    const buf = new EventBuffer()
    buf.ingest([
      row({ id: "keep", source: "gdelt", category: "geopolitical" }),
      ...Array.from({ length: 100 }, (_, i) =>
        row({ id: `adsb-${i}`, source: "opensky-adsb", category: "tracking" }),
      ),
    ])
    const snap = buf.getSnapshot()
    expect(snap).toHaveLength(1)
    expect(snap[0]?.id).toBe("keep")
  })
})
