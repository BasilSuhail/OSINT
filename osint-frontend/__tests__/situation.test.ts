import { describe, expect, it } from "vitest"
import {
  groupByOrigin,
  OFFLINE_ANSWER,
  askHistory,
  MAX_CHAT_MESSAGES,
  chatReducer,
  dayMarkers,
  parseChatStorage,
  sortByActivity,
  splitRecent,
  type ChatMessage,
} from "@/lib/situation"

const msg = (over: Partial<ChatMessage> = {}): ChatMessage => ({
  question: "q",
  answer: "a",
  sources: [],
  draft: false,
  ...over,
})

describe("sortByActivity", () => {
  it("orders by last_seen descending", () => {
    const rows = [
      { id: "a", last_seen: "2026-07-16T09:00:00+00:00" },
      { id: "b", last_seen: "2026-07-16T12:05:00+00:00" },
      { id: "c", last_seen: "2026-07-16T11:30:00+00:00" },
    ]
    expect(sortByActivity(rows).map((r) => r.id)).toEqual(["b", "c", "a"])
  })

  it("keeps input (loudness) order for equal timestamps", () => {
    const rows = [
      { id: "loud", last_seen: "2026-07-16T10:00:00+00:00" },
      { id: "quiet", last_seen: "2026-07-16T10:00:00+00:00" },
    ]
    expect(sortByActivity(rows).map((r) => r.id)).toEqual(["loud", "quiet"])
  })

  it("does not mutate the input array", () => {
    const rows = [
      { id: "a", last_seen: "2026-07-16T09:00:00+00:00" },
      { id: "b", last_seen: "2026-07-16T12:00:00+00:00" },
    ]
    sortByActivity(rows)
    expect(rows.map((r) => r.id)).toEqual(["a", "b"])
  })
})

describe("splitRecent", () => {
  const now = new Date("2026-07-16T20:00:00")
  const at = (id: string, iso: string) => ({ id, last_seen: iso })

  it("keeps today and yesterday, splits older off", () => {
    const rows = [
      at("today", "2026-07-16T18:00:00"),
      at("yday", "2026-07-15T09:00:00"),
      at("older1", "2026-07-14T22:00:00"),
      at("older2", "2026-07-13T08:00:00"),
    ]
    const { recent, older } = splitRecent(rows, now)
    expect(recent.map((r) => r.id)).toEqual(["today", "yday"])
    expect(older.map((r) => r.id)).toEqual(["older1", "older2"])
  })

  it("all older when nothing is from today or yesterday", () => {
    const rows = [at("a", "2026-07-13T10:00:00")]
    const { recent, older } = splitRecent(rows, now)
    expect(recent).toEqual([])
    expect(older.map((r) => r.id)).toEqual(["a"])
  })

  it("empty input", () => {
    expect(splitRecent([], now)).toEqual({ recent: [], older: [] })
  })
})

describe("dayMarkers", () => {
  const now = new Date("2026-07-16T20:00:00")
  const at = (iso: string) => ({ last_seen: iso })

  it("no markers when every row is from today", () => {
    const rows = [at("2026-07-16T18:00:00"), at("2026-07-16T09:00:00")]
    expect(dayMarkers(rows, now)).toEqual([null, null])
  })

  it("marks the boundary into yesterday", () => {
    const rows = [
      at("2026-07-16T18:00:00"),
      at("2026-07-15T23:50:00"),
      at("2026-07-15T08:00:00"),
    ]
    expect(dayMarkers(rows, now)).toEqual([null, "yesterday", null])
  })

  it("marks the top when the list starts before today", () => {
    const rows = [at("2026-07-15T22:00:00"), at("2026-07-15T07:00:00")]
    expect(dayMarkers(rows, now)).toEqual(["yesterday", null])
  })

  it("labels older days with weekday and date", () => {
    const rows = [
      at("2026-07-16T10:00:00"),
      at("2026-07-15T10:00:00"),
      at("2026-07-08T12:00:00"),
    ]
    expect(dayMarkers(rows, now)).toEqual([null, "yesterday", "wed 8 jul"])
  })

  it("empty list yields no markers", () => {
    expect(dayMarkers([], now)).toEqual([])
  })
})

describe("chatReducer", () => {
  it("ask appends a draft message", () => {
    const next = chatReducer([msg()], { type: "ask", question: "will iran fight back?" })
    expect(next).toHaveLength(2)
    expect(next[1]).toEqual({
      question: "will iran fight back?",
      answer: "",
      sources: [],
      draft: true,
    })
  })

  it("delta appends text to the last message", () => {
    const state = chatReducer([], { type: "ask", question: "q" })
    const a = chatReducer(state, { type: "delta", text: "Yes, " })
    const b = chatReducer(a, { type: "delta", text: "Iran…" })
    expect(b[0].answer).toBe("Yes, Iran…")
    expect(b[0].draft).toBe(true)
  })

  it("delta on empty state is a no-op", () => {
    expect(chatReducer([], { type: "delta", text: "x" })).toEqual([])
  })

  it("sources set on the last message while drafting", () => {
    const state = chatReducer([], { type: "ask", question: "q" })
    const src = { n: 1, story_id: 7, title: "t", outlets: ["BBC"], corroboration: null, contested: false }
    const next = chatReducer(state, { type: "sources", sources: [src] })
    expect(next[0].sources).toEqual([src])
    expect(next[0].draft).toBe(true)
  })

  it("finalize replaces answer and sources and ends draft", () => {
    const state = chatReducer([], { type: "ask", question: "q" })
    const src = { n: 1, story_id: 7, title: "t", outlets: ["BBC"], corroboration: 0.8, contested: true }
    const next = chatReducer(state, { type: "finalize", answer: "full answer", sources: [src] })
    expect(next[0]).toEqual({ question: "q", answer: "full answer", sources: [src], draft: false })
  })

  it("fail ends draft with offline message", () => {
    const state = chatReducer([], { type: "ask", question: "q" })
    const next = chatReducer(state, { type: "fail" })
    expect(next[0].draft).toBe(false)
    expect(next[0].answer).toMatch(/offline/)
  })

  it("clear empties the transcript", () => {
    expect(chatReducer([msg(), msg()], { type: "clear" })).toEqual([])
  })

  it("restore replaces state with the stored transcript", () => {
    const stored = [msg({ question: "restored" })]
    expect(chatReducer([msg()], { type: "restore", messages: stored })).toEqual(stored)
  })

  it("earlier messages never change", () => {
    const first = msg({ question: "old", answer: "kept" })
    let state = chatReducer([first], { type: "ask", question: "new" })
    state = chatReducer(state, { type: "delta", text: "typing" })
    state = chatReducer(state, { type: "finalize", answer: "done", sources: [] })
    expect(state[0]).toEqual(first)
  })
})

describe("parseChatStorage", () => {
  it("returns [] for null", () => {
    expect(parseChatStorage(null)).toEqual([])
  })

  it("returns [] for corrupt JSON", () => {
    expect(parseChatStorage("{not json")).toEqual([])
  })

  it("returns [] for wrong shapes", () => {
    expect(parseChatStorage('{"a":1}')).toEqual([])
    expect(parseChatStorage('[{"question":1,"answer":2}]')).toEqual([])
  })

  it("parses a valid transcript and forces drafts final", () => {
    const stored = [
      msg({ question: "q1", answer: "a1" }),
      msg({ question: "q2", answer: "partial", draft: true }),
    ]
    const parsed = parseChatStorage(JSON.stringify(stored))
    expect(parsed).toHaveLength(2)
    expect(parsed[1].answer).toBe("partial")
    expect(parsed[1].draft).toBe(false)
  })

  it("keeps only the newest MAX_CHAT_MESSAGES entries", () => {
    const stored = Array.from({ length: MAX_CHAT_MESSAGES + 5 }, (_, i) =>
      msg({ question: `q${i}` }),
    )
    const parsed = parseChatStorage(JSON.stringify(stored))
    expect(parsed).toHaveLength(MAX_CHAT_MESSAGES)
    expect(parsed[0].question).toBe("q5")
    expect(parsed[parsed.length - 1].question).toBe(`q${MAX_CHAT_MESSAGES + 4}`)
  })
})

describe("askHistory", () => {
  const finalized = (q: string, a: string) => msg({ question: q, answer: a })

  it("keeps the last three finalized exchanges in order", () => {
    const messages = [
      finalized("q1", "a1"),
      finalized("q2", "a2"),
      finalized("q3", "a3"),
      finalized("q4", "a4"),
    ]
    expect(askHistory(messages)).toEqual([
      { question: "q2", answer: "a2" },
      { question: "q3", answer: "a3" },
      { question: "q4", answer: "a4" },
    ])
  })

  it("skips drafts and offline failures", () => {
    const messages = [
      finalized("good", "real answer"),
      msg({ question: "failed", answer: OFFLINE_ANSWER }),
      msg({ question: "typing", answer: "partial", draft: true }),
    ]
    expect(askHistory(messages)).toEqual([{ question: "good", answer: "real answer" }])
  })

  it("truncates long answers", () => {
    const messages = [finalized("q", "x".repeat(5000))]
    const [entry] = askHistory(messages)
    expect(entry.answer.length).toBeLessThanOrEqual(2000)
  })
})

describe("groupByOrigin", () => {
  const member = (outlet: string, origin: string | null) => ({
    title: `${outlet} headline`,
    source: outlet.toLowerCase(),
    outlet,
    owner: outlet,
    origin_country: origin,
    occurred_at: "2026-07-17T10:00:00+00:00",
    similarity: 0.9,
  })

  it("groups members by origin country, biggest bloc first", () => {
    const groups = groupByOrigin([
      member("Dawn", "PK"),
      member("Egypt Independent", "EG"),
      member("Geo English", "PK"),
    ])
    expect(groups.map((g) => g.origin)).toEqual(["PK", "EG"])
    expect(groups[0].members).toHaveLength(2)
  })

  it("collects unknown origins under null, sorted last", () => {
    const groups = groupByOrigin([
      member("Mystery Wire", null),
      member("Dawn", "PK"),
    ])
    expect(groups.map((g) => g.origin)).toEqual(["PK", null])
  })

  it("empty input yields no groups", () => {
    expect(groupByOrigin([])).toEqual([])
  })
})
