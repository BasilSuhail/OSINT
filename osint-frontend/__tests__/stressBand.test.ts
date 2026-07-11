import { describe, expect, it } from "vitest"

import { stressBand } from "@/lib/analytics"

describe("stressBand", () => {
  it("maps the global mean to plain words with fixed thresholds", () => {
    expect(stressBand(0.3).word).toBe("calm")
    expect(stressBand(0.6).word).toBe("elevated")
    expect(stressBand(0.8).word).toBe("high stress")
    expect(stressBand(null).word).toBe("no data")
  })
})
