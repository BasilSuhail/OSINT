import { describe, expect, it } from "vitest"
import { developingState } from "./developing"

describe("developingState", () => {
  it("shows the stories when the fetch is healthy", () => {
    expect(developingState(3, false)).toBe("live")
  })

  it("renders nothing when nothing qualifies — an empty slot is the finding", () => {
    expect(developingState(0, false)).toBe("hidden")
  })

  it("says unavailable only when a failure leaves nothing to show", () => {
    expect(developingState(0, true)).toBe("unavailable")
  })

  it("keeps the stories it already has when a refresh fails", () => {
    expect(developingState(3, true)).toBe("stale")
  })

  it("keeps the last story rather than blanking on the smallest list", () => {
    expect(developingState(1, true)).toBe("stale")
  })
})
