/**
 * How a scheduled date reads (#934).
 *
 * The distance to the date is the point of the block — "in 3 days" is the fact
 * a reader acts on, and the date itself is the detail underneath it.
 */
import { describe, expect, it } from "vitest"

import { daysUntil, whenLabel } from "./upcomingFormat"

const TODAY = new Date("2026-08-12T09:00:00Z")

describe("daysUntil", () => {
  it("counts calendar days, not elapsed hours", () => {
    // Late tonight to early tomorrow is one day away, not zero.
    expect(daysUntil("2026-08-13", new Date("2026-08-12T23:00:00Z"))).toBe(1)
  })

  it("is zero on the day itself", () => {
    expect(daysUntil("2026-08-12", TODAY)).toBe(0)
  })

  it("goes negative for something already past", () => {
    expect(daysUntil("2026-08-10", TODAY)).toBe(-2)
  })
})

describe("whenLabel", () => {
  it("names today and tomorrow rather than counting them", () => {
    expect(whenLabel("2026-08-12", TODAY)).toBe("today")
    expect(whenLabel("2026-08-13", TODAY)).toBe("tomorrow")
  })

  it("counts days for the next fortnight", () => {
    expect(whenLabel("2026-08-15", TODAY)).toBe("in 3 days")
    expect(whenLabel("2026-08-26", TODAY)).toBe("in 14 days")
  })

  it("switches to weeks once days stop being useful", () => {
    expect(whenLabel("2026-09-13", TODAY)).toBe("in 5 weeks")
  })

  it("says a date already past is past, rather than counting backwards", () => {
    // Wikidata carries wrong dates — a 2022 election currently claims 2026 —
    // and the screen must not render "in -1400 days" when one turns up.
    expect(whenLabel("2026-08-11", TODAY)).toBe("past")
  })
})
