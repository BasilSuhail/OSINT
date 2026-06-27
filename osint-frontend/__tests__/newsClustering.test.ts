import { describe, expect, it } from "vitest"
import {
  clusterNews,
  entitySet,
  jaccard,
  newsSourceLabel,
  pickRepresentative,
  sourceWeightFor,
  storyImpact,
  titleBigrams,
} from "@/lib/newsClustering"
import type { EventRow } from "@/lib/types"

const T = new Date().toISOString()

function row(p: Partial<EventRow>): EventRow {
  return {
    id: "1",
    source: "rss-bbc-world",
    occurred_at: T,
    category: "news",
    severity: 0.3,
    payload: {},
    ...p,
  } as EventRow
}

const mk = (
  id: string,
  source: string,
  title: string,
  entities: { text: string; label: string }[] = [],
): EventRow =>
  ({ id, source, occurred_at: T, category: "news", severity: 0.3, payload: { title, entities } }) as unknown as EventRow

describe("entitySet", () => {
  it("keeps org/place/person entity texts, lowercased; drops dates", () => {
    const s = entitySet(
      row({
        payload: {
          entities: [
            { text: "Japan", label: "GPE" },
            { text: "NATO", label: "ORG" },
            { text: "Tuesday", label: "DATE" },
          ],
        },
      }),
    )
    expect(s.has("japan")).toBe(true)
    expect(s.has("nato")).toBe(true)
    expect(s.has("tuesday")).toBe(false)
  })
  it("empty when no entities", () => expect(entitySet(row({ payload: {} })).size).toBe(0))
})

describe("shared helpers", () => {
  it("titleBigrams + jaccard agree on near-identical titles", () => {
    const a = titleBigrams("strong earthquake japan")
    const b = titleBigrams("strong earthquake japan today")
    expect(jaccard(a, b)).toBeGreaterThan(0.4)
  })
  it("sourceWeightFor known outlet > unknown", () => {
    expect(sourceWeightFor(row({ source: "rss-bbc-world" }))).toBeGreaterThan(
      sourceWeightFor(row({ source: "rss-unknown-blog" })),
    )
  })
  it("newsSourceLabel strips rss- and dashes", () => {
    expect(newsSourceLabel(row({ source: "rss-bbc-world" }))).toBe("bbc world")
  })
})

describe("clusterNews", () => {
  it("merges the same headline across two outlets into one story", () => {
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Strong earthquake strikes Japan"),
      mk("2", "rss-reuters-world", "Strong earthquake strikes Japan"),
    ])
    expect(stories).toHaveLength(1)
    expect(stories[0].outletCount).toBe(2)
    expect(stories[0].outlets).toContain("bbc world")
    expect(stories[0].outlets).toContain("reuters world")
  })
  it("merges reworded headlines that share entities", () => {
    const ents = [
      { text: "Japan", label: "GPE" },
      { text: "Honshu", label: "GPE" },
    ]
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Quake hits coast", ents),
      mk("2", "rss-cnn-world", "Powerful tremor rattles region", ents),
    ])
    expect(stories).toHaveLength(1)
  })
  it("keeps unrelated headlines as separate stories", () => {
    const stories = clusterNews([
      mk("1", "rss-bbc-world", "Election results announced in Brazil"),
      mk("2", "rss-cnn-world", "Tech stocks rally on Wall Street"),
    ])
    expect(stories).toHaveLength(2)
  })
})

describe("pickRepresentative", () => {
  it("prefers a member with an image, then source weight", () => {
    const withImg = mk("1", "rss-unknown-blog", "X")
    ;(withImg.payload as Record<string, unknown>).image_url = "http://x/a.jpg"
    const noImg = mk("2", "rss-bbc-world", "X")
    expect(pickRepresentative([noImg, withImg]).id).toBe("1")
  })
  it("falls back to highest source weight when no images", () => {
    const bbc = mk("1", "rss-bbc-world", "X")
    const blog = mk("2", "rss-unknown-blog", "X")
    expect(pickRepresentative([blog, bbc]).id).toBe("1")
  })
})

describe("storyImpact", () => {
  it("ranks a multi-outlet story above a single-outlet one", () => {
    const now = Date.now()
    const big = clusterNews([
      mk("1", "rss-bbc-world", "Same big story"),
      mk("2", "rss-reuters-world", "Same big story"),
      mk("3", "rss-cnn-world", "Same big story"),
    ])[0]
    const small = clusterNews([mk("4", "rss-bbc-world", "Lonely story")])[0]
    expect(storyImpact(big, now)).toBeGreaterThan(storyImpact(small, now))
  })
})

describe("topEntity", () => {
  it("is the most frequent shared entity, title-cased", () => {
    const ents = [{ text: "Ukraine", label: "GPE" }]
    const s = clusterNews([
      mk("1", "rss-bbc-world", "War update front", ents),
      mk("2", "rss-cnn-world", "Front line shifts again", ents),
    ])[0]
    expect(s.topEntity).toBe("Ukraine")
  })
})
