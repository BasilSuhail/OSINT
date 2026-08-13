import { describe, expect, it } from "vitest"

import { NARROW_MAX_PX, NARROW_QUERY, narrowInitialPanels } from "@/lib/narrowLayout"

describe("NARROW_QUERY", () => {
  it("is a max-width query, so a narrow desktop window shows the phone layout too", () => {
    expect(NARROW_QUERY).toBe(`(max-width: ${NARROW_MAX_PX}px)`)
  })

  it("sits below the width a laptop window is usually dragged to", () => {
    expect(NARROW_MAX_PX).toBeLessThan(900)
  })
})

describe("narrowInitialPanels", () => {
  it("puts the deck, the rail and the scrubber away, so the map arrives whole", () => {
    expect(narrowInitialPanels()).toEqual({ left: false, bottom: false, right: false })
  })

  it("says nothing about the result list, which is the omnibox's own", () => {
    expect(narrowInitialPanels()).not.toHaveProperty("top")
  })
})
