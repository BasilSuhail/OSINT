/**
 * The allow-list is derived, so the default stays empty (#930).
 *
 * `make up` needs no extra origin. An allow-list that grows on its own, or that
 * an operator has to remember to shrink, is not one.
 */
import { describe, expect, it } from "vitest"

import { parseDevOrigins } from "./devOrigins.mjs"

describe("parseDevOrigins", () => {
  it("allows nothing when the stack is not being shared", () => {
    expect(parseDevOrigins(undefined)).toEqual([])
  })

  it("allows nothing when the variable is present but blank", () => {
    expect(parseDevOrigins("")).toEqual([])
  })

  it("allows the address share mode is publishing on", () => {
    expect(parseDevOrigins("203.0.113.42")).toEqual(["203.0.113.42"])
  })

  it("takes several hosts and ignores the gaps between them", () => {
    expect(parseDevOrigins("203.0.113.42, 203.0.113.43 ,")).toEqual([
      "203.0.113.42",
      "203.0.113.43",
    ])
  })
})
