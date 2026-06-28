import { describe, expect, it } from "vitest"
import {
  isWorldScopeNews,
  worldNewsAggregates,
} from "@/lib/worldNewsAggregates"
import type { EventRow } from "@/lib/types"
import type { VisibleEvent } from "@/lib/queries"

function visible(over: Partial<EventRow>): VisibleEvent {
  return {
    id: "news-1",
    source: "rss-bbc-world",
    source_event_id: "x",
    occurred_at: "2026-06-24T00:00:00Z",
    fetched_at: null,
    category: "news",
    severity: 0.5,
    keywords: [],
    country: "US",
    lat: null,
    lon: null,
    payload: { news_scope: "world", title: "World story" },
    age: 0,
    opacity: 1,
    occurredMs: Date.parse("2026-06-24T00:00:00Z"),
    ...over,
  } as VisibleEvent
}

describe("worldNewsAggregates", () => {
  it("groups world and unknown RSS news by country centroid", () => {
    const rows = [
      visible({ id: "a", country: "US", payload: { news_scope: "world" } }),
      visible({ id: "b", country: "US", payload: { news_scope: "unknown" } }),
      visible({ id: "c", country: "GB", payload: { news_scope: "local" } }),
    ]
    const aggregates = worldNewsAggregates(rows, new Map([["US", [-98, 39]]]))

    expect(aggregates).toHaveLength(1)
    expect(aggregates[0].country).toBe("US")
    expect(aggregates[0].lon).toBe(-98)
    expect(aggregates[0].lat).toBe(39)
    expect(aggregates[0].events.map((ev) => ev.id)).toEqual(["a", "b"])
  })

  it("only treats RSS world or unknown rows as aggregate candidates", () => {
    expect(isWorldScopeNews(visible({ source: "rss-reuters-world", payload: { news_scope: "world" } }))).toBe(true)
    expect(isWorldScopeNews(visible({ source: "rss-reuters-world", payload: { news_scope: "local" } }))).toBe(false)
    expect(isWorldScopeNews(visible({ source: "gdelt", category: "geopolitical", payload: { news_scope: "world" } }))).toBe(false)
  })
})
