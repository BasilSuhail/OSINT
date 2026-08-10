import { describe, expect, it } from "vitest"
import { feedCategories, filterByCategory, type Taggable } from "./newsFeed"

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
