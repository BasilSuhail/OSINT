import { format, isSameDay, startOfDay, subDays } from "date-fns"

export interface SelectionTimelineGroup<T> {
  key: string
  label: string
  rows: Array<{ number: number; selection: T }>
}

/** Calendar sections for a map selection. Groups are newest-day first while
 * preserving the map-owned order inside each day (nearest-first for areas). */
export function selectionTimelineGroups<
  T extends { event: { occurred_at: string } },
>(selections: T[], now: Date = new Date()): SelectionTimelineGroup<T>[] {
  const groups = new Map<
    string,
    { key: string; day: Date | null; selections: T[] }
  >()

  for (const selection of selections) {
    const occurredAt = new Date(selection.event.occurred_at)
    const valid = Number.isFinite(occurredAt.getTime())
    const key = valid ? format(occurredAt, "yyyy-MM-dd") : "unknown"
    const existing = groups.get(key)
    if (existing) {
      existing.selections.push(selection)
    } else {
      groups.set(key, {
        key,
        day: valid ? startOfDay(occurredAt) : null,
        selections: [selection],
      })
    }
  }

  const ordered = [...groups.values()].sort((a, b) => {
    if (!a.day) return 1
    if (!b.day) return -1
    return b.day.getTime() - a.day.getTime()
  })
  let number = 0
  return ordered.map((group) => ({
    key: group.key,
    label: !group.day
      ? "unknown date"
      : isSameDay(group.day, now)
        ? "today"
        : isSameDay(group.day, subDays(now, 1))
          ? "yesterday"
          : format(group.day, "EEE d MMM").toLowerCase(),
    rows: group.selections.map((selection) => ({
      number: ++number,
      selection,
    })),
  }))
}
