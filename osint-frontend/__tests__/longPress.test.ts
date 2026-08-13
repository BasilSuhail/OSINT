import { describe, expect, it } from "vitest"

import {
  LONG_PRESS_MS,
  MOVE_TOLERANCE_PX,
  SUPPRESS_CONTEXTMENU_MS,
  movedTooFar,
  pressSurvives,
  suppressesContextMenu,
} from "@/lib/longPress"

const ORIGIN = { x: 100, y: 200 }

describe("movedTooFar", () => {
  it("allows the wobble a held finger makes", () => {
    expect(movedTooFar(ORIGIN, { x: 103, y: 204 })).toBe(false)
  })

  it("catches a drag in either axis", () => {
    expect(movedTooFar(ORIGIN, { x: 100 + MOVE_TOLERANCE_PX + 1, y: 200 })).toBe(true)
    expect(movedTooFar(ORIGIN, { x: 100, y: 200 - MOVE_TOLERANCE_PX - 1 })).toBe(true)
  })

  it("measures the distance, not each axis on its own", () => {
    //: Nine right and nine down is under the tolerance twice over and still
    //: nearly thirteen pixels away. A pan that leaves at 45 degrees is the
    //: one an axis-wise check lets through.
    const diagonal = { x: 100 + 9, y: 200 + 9 }
    expect(movedTooFar(ORIGIN, diagonal)).toBe(true)
  })
})

describe("pressSurvives", () => {
  it("is a press when one finger stays put for long enough", () => {
    expect(
      pressSurvives({ touches: 1, elapsedMs: LONG_PRESS_MS, from: ORIGIN, to: ORIGIN }),
    ).toBe(true)
  })

  it("is not a press before the time is up", () => {
    expect(
      pressSurvives({ touches: 1, elapsedMs: LONG_PRESS_MS - 1, from: ORIGIN, to: ORIGIN }),
    ).toBe(false)
  })

  it("is not a press once the finger has travelled — that is a pan", () => {
    expect(
      pressSurvives({
        touches: 1,
        elapsedMs: LONG_PRESS_MS * 2,
        from: ORIGIN,
        to: { x: 400, y: 200 },
      }),
    ).toBe(false)
  })

  it("is not a press with a second finger down — that is a pinch", () => {
    expect(
      pressSurvives({ touches: 2, elapsedMs: LONG_PRESS_MS * 2, from: ORIGIN, to: ORIGIN }),
    ).toBe(false)
  })

  it("is not a press with no finger down", () => {
    expect(
      pressSurvives({ touches: 0, elapsedMs: LONG_PRESS_MS * 2, from: ORIGIN, to: ORIGIN }),
    ).toBe(false)
  })
})

describe("suppressesContextMenu", () => {
  it("swallows the native menu Android raises for the press we just handled", () => {
    expect(suppressesContextMenu(1_000, 1_000 + SUPPRESS_CONTEXTMENU_MS - 1)).toBe(true)
  })

  it("lets a real right-click through once the window has passed", () => {
    expect(suppressesContextMenu(1_000, 1_000 + SUPPRESS_CONTEXTMENU_MS + 1)).toBe(false)
  })

  it("lets a right-click through when no press has fired at all", () => {
    expect(suppressesContextMenu(null, 5_000)).toBe(false)
  })
})
