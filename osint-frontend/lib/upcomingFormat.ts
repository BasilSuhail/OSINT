/**
 * Reading a scheduled date (#934).
 *
 * The distance is what a reader acts on — "in 3 days" — and the date is the
 * detail beneath it. Both are computed in UTC, matching the dates the upstream
 * publishes: an election day is a calendar fact, not a moment, and shifting it
 * into the reader's timezone would move some of them by a day.
 */

const MS_PER_DAY = 86_400_000

/** Whole calendar days from today to the given date, in UTC. */
export function daysUntil(startsOn: string, now: Date = new Date()): number {
  const target = Date.parse(`${startsOn}T00:00:00Z`)
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return Math.round((target - today) / MS_PER_DAY)
}

/** "today", "in 3 days", "in 5 weeks", or "past".
 *
 *  Past is a real case rather than a defensive one: Wikidata carries wrong
 *  dates — one 2022 election currently claims a 2026 one — and "in -1,400 days"
 *  would read as a bug in this console rather than a mistake in the source.
 */
export function whenLabel(startsOn: string, now: Date = new Date()): string {
  const days = daysUntil(startsOn, now)
  if (days < 0) return "past"
  if (days === 0) return "today"
  if (days === 1) return "tomorrow"
  if (days <= 14) return `in ${days} days`
  return `in ${Math.round(days / 7)} weeks`
}
