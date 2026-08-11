import { describe, expect, it } from "vitest"
import {
  feedCategories,
  feedCountries,
  filterByCategory,
  filterByCountry,
  type Placeable,
  type Taggable,
} from "./newsFeed"

const rows = (...categories: (string | null)[]): (Taggable & { id: string })[] =>
  categories.map((category, i) => ({ id: String(i), category }))

describe("feedCategories", () => {
  it("lists each category once, alphabetically, so the chips do not reorder as news arrives", () => {
    expect(feedCategories(rows("other", "disaster", "other", "conflict"))).toEqual([
      "conflict",
      "disaster",
      "other",
    ])
  })

  it("ignores stories with no category rather than inventing a chip for them", () => {
    expect(feedCategories(rows("disaster", null, null))).toEqual(["disaster"])
  })

  it("has nothing to offer when nothing is tagged", () => {
    expect(feedCategories(rows(null, null))).toEqual([])
  })
})

describe("filterByCategory", () => {
  const feed = rows("disaster", "other", "disaster", null)

  it("returns everything when no category is chosen", () => {
    expect(filterByCategory(feed, null)).toHaveLength(4)
  })

  it("keeps only the chosen category", () => {
    expect(filterByCategory(feed, "disaster").map((s) => s.id)).toEqual(["0", "2"])
  })

  it("returns nothing for a category that has left the window", () => {
    expect(filterByCategory(feed, "conflict")).toEqual([])
  })

  it("never returns untagged stories under a named category", () => {
    expect(filterByCategory(feed, "other").map((s) => s.id)).toEqual(["1"])
  })
})

const placed = (...lists: string[][]): (Placeable & { id: string })[] =>
  lists.map((countries, i) => ({ id: String(i), countries }))

describe("feedCountries", () => {
  it("puts the place most of the window is about first", () => {
    expect(feedCountries(placed(["IN"], ["IN"], ["GB"], ["IN"], ["GB"], ["US"]))).toEqual([
      "IN",
      "GB",
      "US",
    ])
  })

  it("breaks ties alphabetically so the strip does not reshuffle on refresh", () => {
    expect(feedCountries(placed(["PK"], ["KE"], ["ZA"]))).toEqual(["KE", "PK", "ZA"])
  })

  it("counts a multi-country story under each of its countries", () => {
    expect(feedCountries(placed(["CO", "IL"], ["IL"]))).toEqual(["IL", "CO"])
  })

  it("offers nothing when no story has a resolved country", () => {
    expect(feedCountries(placed([], []))).toEqual([])
  })
})

describe("filterByCountry", () => {
  const feed = placed(["CO", "IL"], ["IL"], ["KE"], [])

  it("returns everything when no place is chosen", () => {
    expect(filterByCountry(feed, null)).toHaveLength(4)
  })

  it("matches a story on any of its countries, not just the first", () => {
    expect(filterByCountry(feed, "IL").map((s) => s.id)).toEqual(["0", "1"])
  })

  it("never keeps a story with no resolved country under a named place", () => {
    expect(filterByCountry(feed, "KE").map((s) => s.id)).toEqual(["2"])
  })

  it("returns nothing for a place that has left the window", () => {
    expect(filterByCountry(feed, "JP")).toEqual([])
  })
})
