import { describe, expect, it } from "vitest"

import {
  FLICK_PX_PER_S,
  NARROW_QUERY,
  PEEK_PX,
  TOP_STRIP_PX,
  detentHeights,
  narrowInitialPanels,
  snapDetent,
} from "@/lib/narrowLayout"

const PHONE_H = 780

describe("NARROW_QUERY", () => {
  it("is a max-width query, so a narrow desktop window shows the phone layout too", () => {
    expect(NARROW_QUERY).toMatch(/^\(max-width: \d+px\)$/)
  })
})

describe("detentHeights", () => {
  it("orders the three detents", () => {
    const h = detentHeights(PHONE_H)
    expect(h.peek).toBeLessThan(h.half)
    expect(h.half).toBeLessThan(h.full)
  })

  it("leaves the search bar uncovered at full", () => {
    expect(detentHeights(PHONE_H).full).toBe(PHONE_H - TOP_STRIP_PX)
  })

  it("keeps the order on a short screen, where half would otherwise sink below peek", () => {
    // A landscape phone, or the frame mid-rotation where the viewport is
    // briefly a sliver. The sheet must still be a sheet.
    for (const viewportH of [0, 1, 120, 200, 400]) {
      const h = detentHeights(viewportH)
      expect(h.peek).toBeLessThanOrEqual(h.half)
      expect(h.half).toBeLessThanOrEqual(h.full)
    }
  })

  it("never asks for more height than the viewport has", () => {
    for (const viewportH of [0, 200, PHONE_H, 2000]) {
      const h = detentHeights(viewportH)
      expect(h.full).toBeLessThanOrEqual(Math.max(viewportH, PEEK_PX))
    }
  })
})

describe("snapDetent", () => {
  const h = detentHeights(PHONE_H)

  it("takes the nearest detent when the drag was placed, not thrown", () => {
    expect(snapDetent(h.peek + 8, PHONE_H, 0)).toBe("peek")
    expect(snapDetent(h.half - 20, PHONE_H, 0)).toBe("half")
    expect(snapDetent(h.full - 10, PHONE_H, 0)).toBe("full")
  })

  it("moves exactly one detent on a flick, and never skips one", () => {
    // Upward flick: the sheet is growing, so height is increasing.
    expect(snapDetent(h.peek, PHONE_H, FLICK_PX_PER_S + 1)).toBe("half")
    expect(snapDetent(h.half, PHONE_H, FLICK_PX_PER_S + 1)).toBe("full")
    // Downward.
    expect(snapDetent(h.full, PHONE_H, -FLICK_PX_PER_S - 1)).toBe("half")
    expect(snapDetent(h.half, PHONE_H, -FLICK_PX_PER_S - 1)).toBe("peek")
  })

  it("reads a flick from where the drag started, not from where it is nearest", () => {
    // Thrown up hard from peek but barely moved: still opens to half. The
    // gesture said what it meant before the finger had time to travel.
    expect(snapDetent(h.peek + 4, PHONE_H, FLICK_PX_PER_S * 3)).toBe("half")
  })

  it("cannot be thrown past either end", () => {
    expect(snapDetent(h.full, PHONE_H, FLICK_PX_PER_S * 5)).toBe("full")
    expect(snapDetent(h.peek, PHONE_H, -FLICK_PX_PER_S * 5)).toBe("peek")
  })

  it("stays in range for heights outside it", () => {
    expect(snapDetent(-500, PHONE_H, 0)).toBe("peek")
    expect(snapDetent(PHONE_H * 4, PHONE_H, 0)).toBe("full")
  })

  it("is total on a zero-height viewport", () => {
    expect(["peek", "half", "full"]).toContain(snapDetent(0, 0, 0))
  })
})

describe("narrowInitialPanels", () => {
  it("puts the scrubber and the rail away, so the map arrives uncovered", () => {
    expect(narrowInitialPanels()).toEqual({ bottom: false, right: false })
  })
})
