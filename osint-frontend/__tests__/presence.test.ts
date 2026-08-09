import { describe, expect, it } from "vitest"
import { ageLabel, shouldPoll, windowIsNow } from "../lib/presence"

describe("when presence may be shown", () => {
  it("is shown at now", () => {
    expect(windowIsNow(0)).toBe(true)
  })

  it("is hidden once the scrubber leaves now", () => {
    // Nothing is stored, so there is no past to draw. Leaving live dots over a
    // three-week-old map would make them look like history.
    expect(windowIsNow(3 * 24 * 60 * 60 * 1000)).toBe(false)
  })

  it("tolerates the small offset a live window naturally carries", () => {
    expect(windowIsNow(60_000)).toBe(true)
  })
})

describe("when to ask", () => {
  it("asks only when switched on, visible, and at now", () => {
    expect(shouldPoll(true, 0, true)).toBe(true)
  })

  it("does not ask while the layer is off", () => {
    expect(shouldPoll(false, 0, true)).toBe(false)
  })

  it("does not ask from a background tab", () => {
    // A free community service should not pay for a tab nobody is looking at.
    expect(shouldPoll(true, 0, false)).toBe(false)
  })

  it("does not ask while scrubbed into the past", () => {
    expect(shouldPoll(true, 86_400_000, true)).toBe(false)
  })
})

describe("ageLabel", () => {
  it("counts seconds while it is seconds", () => {
    expect(ageLabel("2026-08-09T12:00:00+00:00", Date.parse("2026-08-09T12:00:08Z"))).toBe(
      "as of 8s ago",
    )
  })

  it("switches to minutes once it matters", () => {
    expect(ageLabel("2026-08-09T12:00:00+00:00", Date.parse("2026-08-09T12:03:00Z"))).toBe(
      "as of 3m ago",
    )
  })

  it("never reports the future", () => {
    expect(ageLabel("2026-08-09T12:00:10+00:00", Date.parse("2026-08-09T12:00:00Z"))).toBe(
      "as of 0s ago",
    )
  })
})
