import { format } from "date-fns"
import { describe, expect, it } from "vitest"

import {
  LIVE_TOLERANCE_MS,
  describeTimeWindow,
  occursWithinWindow,
  type TimeWindowInput,
} from "@/lib/timeWindow"

const HOUR = 3_600_000
const DAY = 24 * HOUR
const DEFAULT_WINDOW = 3 * DAY
const NOW = new Date("2026-06-14T12:00:00Z").getTime()

function input(overrides: Partial<TimeWindowInput> = {}): TimeWindowInput {
  return {
    windowEndOffsetMs: 0,
    windowLengthMs: DEFAULT_WINDOW,
    defaultWindowMs: DEFAULT_WINDOW,
    now: NOW,
    ...overrides,
  }
}

describe("describeTimeWindow", () => {
  it("is live at the default window ending now", () => {
    const d = describeTimeWindow(input())
    expect(d.state).toBe("live")
    expect(d.isLive).toBe(true)
    expect(d.canReturnToNow).toBe(false)
  })

  it("stays live inside the slider's one-minute step", () => {
    // The slider steps by a minute, so sub-step drift is not "the past".
    const d = describeTimeWindow(input({ windowEndOffsetMs: LIVE_TOLERANCE_MS - 1 }))
    expect(d.state).toBe("live")
  })

  it("goes historical as soon as the offset reaches one step", () => {
    const d = describeTimeWindow(input({ windowEndOffsetMs: LIVE_TOLERANCE_MS }))
    expect(d.state).toBe("historical")
    expect(d.isLive).toBe(false)
  })

  it("names the window end so the view is identifiable", () => {
    // The whole bug: a scrubbed-back map is indistinguishable from a live one.
    // Expected string is formatted here rather than hardcoded — the component
    // renders in the viewer's timezone, and so should the assertion.
    const end = format(NOW - 3 * HOUR, "d MMM HH:mm")
    const d = describeTimeWindow(input({ windowEndOffsetMs: 3 * HOUR }))
    expect(d.detail).toContain(end)
    expect(d.title).toContain(end)
  })

  it("offers a way back to now whenever the view is not live", () => {
    expect(describeTimeWindow(input({ windowEndOffsetMs: DAY })).canReturnToNow).toBe(true)
    expect(describeTimeWindow(input({ windowLengthMs: 7 * DAY })).canReturnToNow).toBe(true)
  })

  it("flags a window wider than the default even though it ends now", () => {
    const d = describeTimeWindow(input({ windowLengthMs: 7 * DAY }))
    expect(d.state).toBe("wide")
    expect(d.isLive).toBe(false)
    expect(d.detail).toContain("7d")
  })

  it("does not flag a window narrower than the default", () => {
    expect(describeTimeWindow(input({ windowLengthMs: HOUR })).state).toBe("live")
  })

  it("reports historical rather than wide when both apply", () => {
    // Being in the past is the stronger claim. Two warnings at once teaches
    // people to ignore both.
    const d = describeTimeWindow(input({ windowEndOffsetMs: 2 * HOUR, windowLengthMs: 7 * DAY }))
    expect(d.state).toBe("historical")
  })

  it("scales the age unit with the distance scrubbed", () => {
    expect(describeTimeWindow(input({ windowEndOffsetMs: 30 * 60_000 })).title).toContain("30m")
    expect(describeTimeWindow(input({ windowEndOffsetMs: 5 * HOUR })).title).toContain("5h")
    expect(describeTimeWindow(input({ windowEndOffsetMs: 6 * DAY })).title).toContain("6d")
  })

  it("treats a negative offset as now rather than the future", () => {
    expect(describeTimeWindow(input({ windowEndOffsetMs: -5000 })).state).toBe("live")
  })

  it("falls back to the default window when the length is unusable", () => {
    expect(describeTimeWindow(input({ windowLengthMs: 0 })).state).toBe("live")
    expect(describeTimeWindow(input({ windowLengthMs: Number.NaN })).state).toBe("live")
  })

  it("survives a non-finite offset instead of rendering NaN at the user", () => {
    expect(describeTimeWindow(input({ windowEndOffsetMs: Number.NaN })).state).toBe("live")
  })
})

/** One rule for every category. Hazards were exempt from the window while
 *  their source still listed them, which is why a GDACS wildfire with a 20 Aug
 *  onset sat on a map whose window began on 23 Aug — and why the same hazards
 *  appeared at scrubber positions months before they started. */
describe("occursWithinWindow", () => {
  const START = Date.parse("2026-08-23T23:35:00Z")
  const END = Date.parse("2026-08-26T23:35:00Z")

  it("keeps an event inside the window", () => {
    expect(occursWithinWindow(Date.parse("2026-08-25T12:00:00Z"), START, END)).toBe(true)
  })

  it("refuses an event older than the window", () => {
    // WF:1031065 — a GDACS wildfire still listed by its feed. Being current
    // upstream is no longer permission to outlive the window on screen.
    expect(occursWithinWindow(Date.parse("2026-08-20T01:00:00Z"), START, END)).toBe(false)
  })

  it("refuses an event later than the window", () => {
    expect(occursWithinWindow(Date.parse("2026-08-27T00:00:00Z"), START, END)).toBe(false)
  })

  it("includes both edges", () => {
    expect(occursWithinWindow(START, START, END)).toBe(true)
    expect(occursWithinWindow(END, START, END)).toBe(true)
  })

  it("refuses an event whose date cannot be read", () => {
    expect(occursWithinWindow(Number.NaN, START, END)).toBe(false)
  })
})
