import { describe, expect, it } from "vitest"

import { countryName } from "@/lib/countryName"

describe("countryName", () => {
  it("expands ISO2 codes to full English names", () => {
    expect(countryName("US")).toBe("United States")
    expect(countryName("GB")).toBe("United Kingdom")
    expect(countryName("VE")).toBe("Venezuela")
  })

  it("falls back to the input for malformed codes", () => {
    expect(countryName("1$")).toBe("1$")
    expect(countryName("")).toBe("")
    expect(countryName("USA")).toBe("USA") // only ISO2 expands
  })
})
