import { describe, expect, it } from "vitest"
import {
  FRESHNESS_HALF_LIFE_HOURS,
  freshness,
  rankStories,
  relativeAge,
  scoreStory,
} from "./newsRanking"
import type { StoryRow } from "./analytics"

const NOW = Date.parse("2026-08-10T12:00:00Z")

function story(over: Partial<StoryRow> & { id: string }): StoryRow {
  return {
    title: "A headline",
    first_seen: "2026-08-10T06:00:00Z",
    last_seen: "2026-08-10T11:00:00Z",
    member_count: 3,
    outlet_count: 3,
    owner_count: 2,
    corroboration: null,
    corroboration_components: null,
    sensor_checks: {},
    method_version: "stories-v1.0",
    gist: null,
    category: null,
    escalating: null,
    ...over,
  } as StoryRow
}

describe("freshness", () => {
  it("halves over the half-life", () => {
    const half = new Date(NOW - FRESHNESS_HALF_LIFE_HOURS * 3_600_000).toISOString()
    expect(freshness(half, NOW)).toBeCloseTo(0.5, 5)
  })

  it("is 1 for something filed this second and 0 for nonsense", () => {
    expect(freshness(new Date(NOW).toISOString(), NOW)).toBeCloseTo(1, 5)
    expect(freshness("not a date", NOW)).toBe(0)
  })
})

describe("rankStories", () => {
  it("puts independent tellers above a single outlet's repetition", () => {
    const spam = story({ id: "spam", owner_count: 1, outlet_count: 1, member_count: 40 })
    const real = story({ id: "real", owner_count: 6, outlet_count: 9 })

    const [first] = rankStories([spam, real], NOW)

    expect(first.story.id).toBe("real")
  })

  it("prefers the fresher of two otherwise identical stories", () => {
    const older = story({ id: "older", last_seen: "2026-08-09T12:00:00Z" })
    const newer = story({ id: "newer", last_seen: "2026-08-10T11:30:00Z" })

    expect(rankStories([older, newer], NOW).map((r) => r.story.id)).toEqual(["newer", "older"])
  })

  it("lets escalating break a tie between equals", () => {
    const calm = story({ id: "calm" })
    const rising = story({ id: "rising", escalating: "escalating" })

    expect(rankStories([calm, rising], NOW)[0].story.id).toBe("rising")
  })

  it("never lets an unscored story fall behind a scored one on that alone", () => {
    // Corroboration is a tie-break, not a gate: a widely-told story that has
    // not been scored yet must still be readable (#449).
    const unscored = story({ id: "unscored", owner_count: 8, outlet_count: 10 })
    const scored = story({ id: "scored", owner_count: 1, outlet_count: 1, corroboration: 0.9 })

    expect(rankStories([scored, unscored], NOW)[0].story.id).toBe("unscored")
  })

  it("orders the same input the same way every time", () => {
    const rows = [story({ id: "b" }), story({ id: "a" }), story({ id: "c" })]

    const once = rankStories(rows, NOW).map((r) => r.story.id)
    const twice = rankStories([...rows].reverse(), NOW).map((r) => r.story.id)

    expect(once).toEqual(twice)
  })

  it("states the reason it ranked something", () => {
    const [top] = rankStories([story({ id: "x", owner_count: 4, corroboration: 0.62 })], NOW)
    expect(top.reasons).toContain("4 independent owners")
    expect(top.reasons).toContain("corroboration 0.62")
  })
})

describe("scoreStory", () => {
  it("stays inside 0..1", () => {
    const best = story({
      id: "best",
      owner_count: 99,
      outlet_count: 99,
      escalating: "escalating",
      last_seen: new Date(NOW).toISOString(),
    })
    expect(scoreStory(best, NOW)).toBeLessThanOrEqual(1)
    expect(scoreStory(story({ id: "z", owner_count: 0, outlet_count: 0 }), NOW)).toBeGreaterThan(0)
  })
})

describe("relativeAge", () => {
  it("reads in minutes, hours, then days", () => {
    expect(relativeAge(new Date(NOW - 5 * 60_000).toISOString(), NOW)).toBe("5m ago")
    expect(relativeAge(new Date(NOW - 5 * 3_600_000).toISOString(), NOW)).toBe("5h ago")
    expect(relativeAge(new Date(NOW - 5 * 86_400_000).toISOString(), NOW)).toBe("5d ago")
  })
})
