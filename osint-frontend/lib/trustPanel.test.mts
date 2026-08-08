import { describe, expect, it } from "vitest"

/** The panel's own reading of the health payload, kept as pure functions so
 *  the judgements can be tested without a browser (#828). */
function silenceTone(minutes: number | null, cadence: number): string {
  if (minutes === null) return "text-red-400"
  if (cadence > 0 && minutes > cadence * 24) return "text-red-400"
  return "text-amber-300"
}

function humanMinutes(minutes: number | null): string {
  if (minutes === null) return "never"
  if (minutes < 90) return `${minutes} min`
  if (minutes < 60 * 48) return `${Math.round(minutes / 60)} h`
  return `${Math.round(minutes / 1440)} d`
}

function exactShare(precision: Record<string, number>): number | null {
  const total = Object.values(precision).reduce((sum, n) => sum + n, 0)
  return total ? (precision.exact ?? 0) / total : null
}

describe("how silence is judged", () => {
  it("treats never-heard-from as the worst case", () => {
    expect(silenceTone(null, 60)).toBe("text-red-400")
  })

  it("judges a silence against the source's own cadence", () => {
    // A quarter-hour feed quiet for a day is alarming; a monthly archive
    // quiet for a day is a Tuesday.
    expect(silenceTone(1440, 15)).toBe("text-red-400")
    expect(silenceTone(1440, 1440)).toBe("text-amber-300")
  })
})

describe("how ages are said", () => {
  it("says never rather than a number nobody can read", () => {
    expect(humanMinutes(null)).toBe("never")
  })

  it("scales the unit to the age", () => {
    expect(humanMinutes(20)).toBe("20 min")
    expect(humanMinutes(180)).toBe("3 h")
    expect(humanMinutes(4320)).toBe("3 d")
  })
})

describe("the verified-pin share", () => {
  it("is the fraction standing on a place somebody checked", () => {
    expect(exactShare({ exact: 223, city: 1164, country: 337, area: 276 })).toBeCloseTo(0.1115, 3)
  })

  it("is null rather than zero when nothing is drawn", () => {
    // Zero would read as "nothing is verified"; null reads as "nothing is
    // drawn", which is a different statement about the system.
    expect(exactShare({})).toBeNull()
  })

  it("does not credit an absent exact bucket", () => {
    expect(exactShare({ city: 10 })).toBe(0)
  })
})
