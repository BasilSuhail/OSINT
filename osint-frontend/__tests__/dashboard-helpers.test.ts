import { describe, expect, it } from "vitest"

import {
  impactScoreFor,
  buildNewsStories,
  jaccard,
  NEWS_SOURCE_WEIGHTS,
  recencyFor,
  sentimentBarColor,
  severityBarColor,
  sourceWeightFor,
  titleBigrams,
} from "@/lib/dashboardHelpers"
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

describe("severityBarColor", () => {
  it("returns the red band for high values", () => {
    expect(severityBarColor(0.9)).toBe("#ef4444")
  })
  it("returns the green band for low values", () => {
    expect(severityBarColor(0.1)).toBe("#22c55e")
  })
  it("steps through orange + yellow in between", () => {
    expect(severityBarColor(0.7)).toBe("#f97316")
    expect(severityBarColor(0.45)).toBe("#eab308")
  })
})

describe("sentimentBarColor", () => {
  it("rose at strongly negative", () => {
    expect(sentimentBarColor(-0.8)).toBe("#e11d48")
  })
  it("emerald at strongly positive", () => {
    expect(sentimentBarColor(0.8)).toBe("#10b981")
  })
  it("neutral grey at near-zero", () => {
    expect(sentimentBarColor(0)).toBe("#737373")
  })
})

describe("sourceWeightFor", () => {
  it("looks up known feeds", () => {
    expect(sourceWeightFor(row({ source: "rss-bbc-world" }))).toBeCloseTo(1.0)
    expect(sourceWeightFor(row({ source: "rss-tass-en" }))).toBeCloseTo(0.55)
  })
  it("falls back to 0.5 on unknown source", () => {
    expect(sourceWeightFor(row({ source: "unknown-feed" }))).toBe(0.5)
  })
  it("table covers every wire-service feed at 1.0", () => {
    const ones = Object.values(NEWS_SOURCE_WEIGHTS).filter((w) => w === 1.0)
    expect(ones.length).toBeGreaterThanOrEqual(2)
  })
})

describe("recencyFor", () => {
  it("returns 1 for a row that just landed", () => {
    expect(recencyFor(row({ occurred_at: new Date().toISOString() }))).toBeCloseTo(1, 1)
  })
  it("returns 0 for a row from a day ago", () => {
    const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    expect(recencyFor(row({ occurred_at: yesterday }))).toBeCloseTo(0, 1)
  })
  it("decays linearly through the window", () => {
    const sixHoursAgo = new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString()
    expect(recencyFor(row({ occurred_at: sixHoursAgo }))).toBeCloseTo(0.75, 1)
  })
})

describe("titleBigrams", () => {
  it("returns empty for short input", () => {
    expect(titleBigrams("a").size).toBe(0)
  })
  it("includes word-pair shingles + unigrams", () => {
    const out = titleBigrams("Trump warns Iran from Washington")
    expect(out.has("trump_warns")).toBe(true)
    expect(out.has("warns_iran")).toBe(true)
    expect(out.has("washington")).toBe(true)
  })
  it("normalises case + strips punctuation", () => {
    const out = titleBigrams("Trump warns, Iran!!")
    expect(out.has("trump_warns")).toBe(true)
    expect(out.has("warns_iran")).toBe(true)
  })
})

describe("jaccard", () => {
  it("returns 1 for identical sets", () => {
    expect(jaccard(new Set(["a", "b"]), new Set(["a", "b"]))).toBe(1)
  })
  it("returns 0 for disjoint sets", () => {
    expect(jaccard(new Set(["a"]), new Set(["b"]))).toBe(0)
  })
  it("returns 0 when either set is empty", () => {
    expect(jaccard(new Set(["a"]), new Set())).toBe(0)
    expect(jaccard(new Set(), new Set(["a"]))).toBe(0)
  })
  it("computes intersection / union correctly", () => {
    expect(jaccard(new Set(["a", "b", "c"]), new Set(["b", "c", "d"]))).toBeCloseTo(2 / 4)
  })
})

describe("impactScoreFor", () => {
  it("uses sentiment when present", () => {
    const ev = row({
      payload: { sentiment: -0.8 },
      occurred_at: new Date().toISOString(),
    })
    expect(impactScoreFor(ev)).toBeGreaterThan(0.5)
  })
  it("falls back to severity proxy when sentiment is missing", () => {
    const ev = row({ severity: 0.85, payload: {} })
    expect(impactScoreFor(ev)).toBeGreaterThan(0.4)
  })
  it("cluster term caps at 10", () => {
    const ev = row({
      payload: { sentiment: 0 },
      occurred_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    })
    const a = impactScoreFor(ev, 10)
    const b = impactScoreFor(ev, 100)
    expect(a).toBeCloseTo(b, 5)
  })
  it("output always within [0, 1]", () => {
    const ev = row({ payload: { sentiment: -1 } })
    const v = impactScoreFor(ev, 100)
    expect(v).toBeGreaterThanOrEqual(0)
    expect(v).toBeLessThanOrEqual(1)
  })
})

describe("buildNewsStories", () => {
  it("collapses reworded headlines when entities match", () => {
    const stories = buildNewsStories([
      row({
        id: "a",
        source: "rss-bbc-world",
        payload: {
          title: "Strong earthquake strikes Honshu",
          entities: [{ text: "Honshu", label: "GPE" }, { text: "Japan", label: "GPE" }],
        },
      }),
      row({
        id: "b",
        source: "rss-reuters-world",
        payload: {
          title: "Japan quake disrupts rail services",
          entities: [{ text: "Honshu", label: "GPE" }, { text: "Japan", label: "GPE" }],
        },
      }),
    ])

    expect(stories).toHaveLength(1)
    expect(stories[0].members).toHaveLength(2)
    expect(stories[0].outlets).toEqual(["rss-bbc-world", "rss-reuters-world"])
  })

  it("ranks broad pickup above an otherwise similar single outlet story", () => {
    const pickedUp = [
      row({ id: "a", source: "rss-bbc-world", payload: { title: "Leaders meet in Geneva", entities: [{ text: "Geneva", label: "GPE" }] } }),
      row({ id: "b", source: "rss-reuters-world", payload: { title: "Geneva talks begin", entities: [{ text: "Geneva", label: "GPE" }] } }),
      row({ id: "c", source: "rss-aljazeera", payload: { title: "Diplomats gather in Geneva", entities: [{ text: "Geneva", label: "GPE" }] } }),
    ]
    const oneOff = row({
      id: "d",
      source: "rss-bbc-world",
      payload: { title: "Unrelated market note", entities: [{ text: "London", label: "GPE" }] },
    })

    const stories = buildNewsStories([...pickedUp, oneOff])

    expect(stories[0].members.map((ev) => ev.id).sort()).toEqual(["a", "b", "c"])
    expect(stories[0].score).toBeGreaterThan(stories[1].score)
  })
})
