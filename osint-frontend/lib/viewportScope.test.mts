import { describe, expect, it } from "vitest"
import {
  quantizeBounds,
  shouldAnnounceViewportLoading,
  snapshotMatchesWindow,
  VIEWPORT_GRID_DEG,
} from "./viewportScope"

describe("snapping the bounds to a grid", () => {
  //: Every side moves away from the middle, so the box the API is asked for
  //: always contains the box on screen.
  it("grows the box, never shrinks it", () => {
    const snapped = quantizeBounds({
      west: -3.12345,
      south: 51.98765,
      east: 0.54321,
      north: 54.01234,
    })
    expect(snapped.west).toBeLessThanOrEqual(-3.12345)
    expect(snapped.south).toBeLessThanOrEqual(51.98765)
    expect(snapped.east).toBeGreaterThanOrEqual(0.54321)
    expect(snapped.north).toBeGreaterThanOrEqual(54.01234)
  })

  //: The whole point: a nudge smaller than the grid is the same question, so
  //: the request in flight is left alone instead of being cancelled.
  it("gives two nearly identical views the same bounds", () => {
    const a = quantizeBounds({ west: -3.101, south: 51.201, east: 0.301, north: 54.101 })
    const b = quantizeBounds({ west: -3.104, south: 51.204, east: 0.304, north: 54.104 })
    expect(a).toEqual(b)
  })

  it("gives a real pan different bounds", () => {
    const a = quantizeBounds({ west: -3.1, south: 51.2, east: 0.3, north: 54.1 })
    const b = quantizeBounds({ west: -1.1, south: 51.2, east: 2.3, north: 54.1 })
    expect(a).not.toEqual(b)
  })

  it("never asks for ground that is not on the planet", () => {
    const snapped = quantizeBounds({ west: -179.99, south: -89.99, east: 179.99, north: 89.99 })
    expect(snapped.west).toBeGreaterThanOrEqual(-180)
    expect(snapped.south).toBeGreaterThanOrEqual(-90)
    expect(snapped.east).toBeLessThanOrEqual(180)
    expect(snapped.north).toBeLessThanOrEqual(90)
  })

  it("keeps the grid coarse enough to be worth having", () => {
    expect(VIEWPORT_GRID_DEG).toBeGreaterThan(0.01)
  })
})

describe("whether a snapshot still describes the time on screen", () => {
  const windowLengthMs = 60 * 60 * 1000

  it("matches the offset it was taken at", () => {
    expect(snapshotMatchesWindow(0, 0, { playing: false, windowLengthMs })).toBe(true)
  })

  it("does not stand in for a different time when the scrubber is parked", () => {
    expect(snapshotMatchesWindow(0, 5_000, { playing: false, windowLengthMs })).toBe(false)
  })

  //: Playback slides the window continuously, so an exact match never happens
  //: and a strict rule would blank the map on every tick.
  it("tolerates being slightly behind while playing", () => {
    expect(snapshotMatchesWindow(0, 5_000, { playing: true, windowLengthMs })).toBe(true)
    expect(
      snapshotMatchesWindow(0, windowLengthMs + 1, { playing: true, windowLengthMs }),
    ).toBe(false)
  })
})

describe("whether to say loading", () => {
  it("says it when the map has nothing to show", () => {
    expect(shouldAnnounceViewportLoading(true, false)).toBe(true)
  })

  //: A drag is a refresh, not a wait. Marks are already on screen and a banner
  //: over the top of them is the flicker being reported, not information.
  it("stays quiet when marks are already drawn", () => {
    expect(shouldAnnounceViewportLoading(true, true)).toBe(false)
  })

  it("says nothing when nothing is loading", () => {
    expect(shouldAnnounceViewportLoading(false, false)).toBe(false)
  })
})
