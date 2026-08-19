import { describe, expect, it } from "vitest"

import { parseAskEnabled } from "./askFlag"

describe("parseAskEnabled", () => {
  it("defaults to on when the key is absent", () => {
    // A machine that predates the setting keeps the console it had, and so does
    // the laptop that never edits the key: `env.example` ships it empty on
    // purpose, so that a `true` typed into `.env` is unmistakably the
    // operator's answer rather than a copy of the example's own.
    expect(parseAskEnabled(undefined)).toBe(true)
    expect(parseAskEnabled("")).toBe(true)
  })

  it("is off for every word pydantic reads as false", () => {
    // The API parses this same setting through a pydantic bool. Any word it
    // reads as false that the console read as true would draw an ask control
    // for an endpoint that refuses — the dead control the setting exists to
    // prevent — so the two vocabularies are the same vocabulary.
    for (const off of ["false", "f", "no", "n", "off", "0"]) {
      expect(parseAskEnabled(off), off).toBe(false)
      expect(parseAskEnabled(off.toUpperCase()), off.toUpperCase()).toBe(false)
      expect(parseAskEnabled(` ${off} `), `padded ${off}`).toBe(false)
    }
  })

  it("is on for every word pydantic reads as true", () => {
    for (const on of ["true", "t", "yes", "y", "on", "1"]) {
      expect(parseAskEnabled(on), on).toBe(true)
      expect(parseAskEnabled(on.toUpperCase()), on.toUpperCase()).toBe(true)
    }
  })

  it("reads a word neither side knows as on, which no console ever sees", () => {
    // Not a shrug at a typo: pydantic rejects an unrecognised value outright,
    // so the API never starts and there is no console to have got this wrong.
    // The branch exists so the helper is total, not because it is a policy.
    expect(parseAskEnabled("maybe")).toBe(true)
  })
})
