import { describe, expect, it } from "vitest"
import {
  translationDetail,
  translationLabel,
  translationNotice,
} from "./translationNotice"
import type { EventRow } from "./types"

/** The payload shape #835 actually writes. */
const row = (payload: Record<string, unknown>): EventRow =>
  ({
    id: "1",
    source: "rss-aljazeera-arabic",
    source_event_id: "a1",
    occurred_at: "2026-08-09T12:00:00Z",
    fetched_at: null,
    category: "geopolitical",
    severity: 0.5,
    keywords: [],
    country: "PS",
    lat: 31.5,
    lon: 34.4,
    payload,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any as EventRow

const TRANSLATED = row({
  title: "Barcelona's next candidate",
  title_original: "رودري المرشح التالي",
  title_translation: {
    status: "ok",
    model: "llama3.2:3b",
    method_version: "translate.v1.0",
    translated_at: "2026-08-09T11:59:00Z",
  },
})

const FAILED = row({
  title: "رودري المرشح التالي",
  title_translation: {
    status: "failed",
    model: "llama3.2:3b",
    method_version: "translate.v1.0",
    attempted_at: "2026-08-09T11:59:00Z",
  },
})

describe("translationNotice", () => {
  it("reports a translated row with the model that wrote it", () => {
    const notice = translationNotice(TRANSLATED)
    expect(notice?.status).toBe("ok")
    expect(notice?.model).toBe("llama3.2:3b")
  })

  it("keeps the publisher's actual words reachable", () => {
    expect(translationNotice(TRANSLATED)?.original).toBe("رودري المرشح التالي")
  })

  it("reports a failed attempt separately from a successful one", () => {
    // The reader is looking at a script they may not read. "We could not
    // translate this" is a different statement from "this is what they said".
    expect(translationNotice(FAILED)?.status).toBe("failed")
  })

  it("does not claim an original on a failure, where the headline is the original", () => {
    expect(translationNotice(FAILED)?.original).toBeNull()
  })

  it("says nothing about the great majority of rows", () => {
    // English rows must not gain furniture.
    expect(translationNotice(row({ title: "Police make 49 arrests in Edinburgh" }))).toBeNull()
    expect(translationNotice(row({}))).toBeNull()
  })

  it("ignores a malformed note rather than inventing a status", () => {
    expect(translationNotice(row({ title_translation: "yes" }))).toBeNull()
    expect(translationNotice(row({ title_translation: { status: "maybe" } }))).toBeNull()
  })
})

describe("what the reader is told", () => {
  it("labels a translation in words, not a glyph needing a legend", () => {
    expect(translationLabel({ status: "ok", model: "m", original: "x" })).toBe("machine-translated")
    expect(translationLabel({ status: "failed", model: "m", original: null })).toBe("not translated")
  })

  it("names the model, so a bad translation traces to a version not an outlet", () => {
    const detail = translationDetail(translationNotice(TRANSLATED)!)
    expect(detail).toContain("llama3.2:3b")
    expect(detail).toContain("not the publisher's own wording")
  })

  it("offers the original so a reader of the language can check it", () => {
    expect(translationDetail(translationNotice(TRANSLATED)!)).toContain("رودري المرشح التالي")
  })

  it("explains an untranslated row as the publisher's own words", () => {
    const detail = translationDetail(translationNotice(FAILED)!)
    expect(detail).toContain("publisher's own words")
  })
})
