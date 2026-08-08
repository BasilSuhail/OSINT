import { describe, expect, it } from "vitest"
import { askHistory } from "./situation"
import type { ChatMessage } from "./situation"

const message = (over: Partial<ChatMessage> = {}): ChatMessage => ({
  question: "edinburgh murders",
  answer: "A man accused of killing an aid worker hid a body in a suitcase.",
  sources: [],
  closest: [],
  claims: [],
  reasoning: null,
  draft: false,
  ...over,
})

const source = (story_id: number | null) => ({
  n: 1,
  story_id,
  title: "Suitcase murder suspect appears in court",
  outlets: ["Edinburgh Live"],
  corroboration: null,
  contested: false,
})

describe("askHistory", () => {
  it("carries the story ids a turn cited (#813)", () => {
    const history = askHistory([message({ sources: [source(11), source(12)] })])
    expect(history[0].story_ids).toEqual([11, 12])
  })

  it("drops sensor sources, which are readings rather than stories", () => {
    // #507: an instrument record has no story to open, so there is nothing to
    // move past when the reader asks what else there is.
    const history = askHistory([message({ sources: [source(11), source(null)] })])
    expect(history[0].story_ids).toEqual([11])
  })

  it("sends an empty list when a turn cited nothing", () => {
    expect(askHistory([message()])[0].story_ids).toEqual([])
  })

  it("still carries the question and the answer", () => {
    const history = askHistory([message({ sources: [source(11)] })])
    expect(history[0].question).toBe("edinburgh murders")
    expect(history[0].answer).toContain("suitcase")
  })
})
