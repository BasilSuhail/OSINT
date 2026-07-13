import { describe, expect, it } from "vitest"

import {
  confirmedClaims,
  corroborationTiers,
  corroborationTone,
  type StoryRow,
} from "@/lib/analytics"

const story = (over: Partial<StoryRow>): StoryRow => ({
  id: "1",
  title: "t",
  first_seen: "2026-07-10T00:00:00Z",
  last_seen: "2026-07-10T00:00:00Z",
  member_count: 1,
  outlet_count: 1,
  owner_count: 1,
  corroboration: 0,
  corroboration_components: null,
  sensor_checks: {},
  method_version: "stories-v1.0",
  gist: null,
  category: null,
  escalating: null,
  ...over,
})

describe("corroborationTone", () => {
  it("dims unverified single-teller stories", () => {
    expect(corroborationTone(0)).toContain("neutral-500")
    expect(corroborationTone(null)).toContain("neutral-500")
  })

  it("steps up with the score", () => {
    expect(corroborationTone(0.5)).toContain("emerald")
    expect(corroborationTone(0.75)).toContain("cyan")
    expect(corroborationTone(0.9)).toContain("cyan")
  })
})

describe("corroborationTiers", () => {
  it("buckets stories into the four named confidence tiers", () => {
    const tiers = corroborationTiers([
      story({ corroboration: 0 }),
      story({ corroboration: 0 }),
      story({ corroboration: 0.5 }),
      story({ corroboration: 0.6 }),
      story({ corroboration: 0.75 }),
      story({ corroboration: null }),
    ])
    expect(tiers.map((t) => t.count)).toEqual([3, 0, 2, 1])
    expect(tiers[0].label).toContain("single teller")
    expect(tiers[3].label).toContain("strong")
  })

  it("empty input gives four zero tiers", () => {
    expect(corroborationTiers([]).map((t) => t.count)).toEqual([0, 0, 0, 0])
  })
})

describe("confirmedClaims", () => {
  it("extracts only confirmed claim types", () => {
    expect(
      confirmedClaims({ earthquake: "confirmed", disaster: "unconfirmed" }),
    ).toEqual(["earthquake"])
  })

  it("empty map means no chips", () => {
    expect(confirmedClaims({})).toEqual([])
  })
})
