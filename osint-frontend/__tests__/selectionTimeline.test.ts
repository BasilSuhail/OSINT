import { describe, expect, it } from "vitest"
import { selectionTimelineGroups } from "@/lib/selectionTimeline"

function localIso(year: number, month: number, day: number, hour: number): string {
  return new Date(year, month - 1, day, hour).toISOString()
}

describe("selectionTimelineGroups", () => {
  const selection = (id: string, occurredAt: string, distanceKm: number) => ({
    event: { id, occurred_at: occurredAt },
    distanceKm,
  })

  it("groups map rows by calendar day with explicit labels", () => {
    const now = new Date(2026, 7, 4, 12)
    const groups = selectionTimelineGroups(
      [
        selection("near-old", localIso(2026, 8, 3, 9), 0.1),
        selection("today", localIso(2026, 8, 4, 8), 4),
        selection("far-old", localIso(2026, 8, 3, 11), 5),
        selection("older", localIso(2026, 8, 1, 18), 1),
      ],
      now,
    )

    expect(groups.map((group) => group.label)).toEqual([
      "today",
      "yesterday",
      "sat 1 aug",
    ])
  })

  it("preserves map-owned ordering within each day", () => {
    const now = new Date(2026, 7, 4, 12)
    const groups = selectionTimelineGroups(
      [
        selection("nearest", localIso(2026, 8, 3, 9), 0.1),
        selection("farther", localIso(2026, 8, 3, 11), 5),
      ],
      now,
    )

    expect(groups[0]?.rows.map((row) => row.selection.event.id)).toEqual([
      "nearest",
      "farther",
    ])
    expect(groups[0]?.rows.map((row) => row.number)).toEqual([1, 2])
  })

  it("keeps invalid timestamps visible in a final explicit group", () => {
    const now = new Date(2026, 7, 4, 12)
    const groups = selectionTimelineGroups(
      [
        selection("unknown", "not-a-date", 0),
        selection("valid", localIso(2026, 8, 4, 8), 1),
      ],
      now,
    )

    expect(groups.map((group) => group.label)).toEqual(["today", "unknown date"])
  })
})
