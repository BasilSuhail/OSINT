/** Whether a hazard was running at the moment the map is showing.
 *
 *  A three-day window is the right rule for an event that happens. It is the
 *  wrong rule for one that lasts: a flood's onset is the day it began, and a
 *  flood that began last week is still drowning villages this week. Nepal was
 *  in the database, in the news feed, and absent from the map for exactly that
 *  reason — six floods held, none drawn.
 *
 *  The rule this implements is not new and is not ours to set: a hazard may
 *  outlive the window while its source still reports it. What was wrong was
 *  the implementation, in two places, and only those two are changed here.
 *  Nothing decides that a hazard is too small or too routine to show — which
 *  disaster types are worth drawing is a question the type filters already
 *  answer, and answering it again in here would be answering it twice.
 */

import type { EventRow } from "./types"

const GDACS_GRACE_MS = 48 * 60 * 60 * 1000

/** How far a row's `fetched_at` may lag its source's newest before we call it
 *  gone from the feed. GDACS polls every 15 minutes and EONET every 30, and
 *  each poll re-upserts everything it still considers live, so a live row is
 *  never more than one poll behind. Three hours is roughly a dozen misses. */
const FEED_PRESENCE_GRACE_MS = 3 * 60 * 60 * 1000

function payload(ev: EventRow): Record<string, unknown> {
  return (ev.payload ?? {}) as Record<string, unknown>
}

function boolValue(raw: unknown): boolean | null {
  if (typeof raw === "boolean") return raw
  if (typeof raw === "string") {
    const text = raw.trim().toLowerCase()
    if (text === "true") return true
    if (text === "false") return false
  }
  return null
}

function timeMs(raw: unknown): number | null {
  if (typeof raw !== "string" || !raw.trim()) return null
  const ms = new Date(raw).getTime()
  return Number.isFinite(ms) ? ms : null
}

/** Was the source still republishing this row at `atMs`?
 *
 *  Measured against the newest row from the *same source* rather than the wall
 *  clock, so an ingestion outage ages every row together and singles none out —
 *  the map degrades to its last known state instead of emptying.
 *
 *  The reference is clamped to the moment on screen so the same question can be
 *  asked of a past one: feed activity from after that moment says nothing about
 *  whether the hazard had ended by it. Returns null when there is not enough
 *  evidence to judge, and missing evidence must never hide data. */
function isStillInFeed(ev: EventRow, atMs: number, feedLatestMs?: number): boolean | null {
  if (feedLatestMs === undefined || !Number.isFinite(feedLatestMs)) return null
  const fetchedMs = timeMs(ev.fetched_at)
  if (fetchedMs === null) return null
  return fetchedMs >= Math.min(feedLatestMs, atMs) - FEED_PRESENCE_GRACE_MS
}

/**
 * May this hazard be drawn at `momentMs` despite falling outside the window?
 *
 * `momentMs` is the scrubber's window end — the wall clock only on a live map.
 * `feedLatestMs` is the newest `fetched_at` seen for this event's source.
 *
 * Two bounds, each for a fault the earlier version had:
 *
 * 1. It must have started. Nothing bounded this end, so every active hazard was
 *    drawn at every scrubber position, months before it began — the same floods
 *    and fires at every date, which is what a scrubber cannot mean.
 * 2. It must still have been in its feed *at that moment*. GDACS drops
 *    non-current events at ingest, so a stored `is_current` is written once and
 *    can never be falsified — presence is the only thing separating ongoing
 *    from ended, and judging it against today hid July's hazards from July.
 */
export function isPersistentActiveHazard(
  ev: EventRow,
  momentMs = Date.now(),
  feedLatestMs?: number,
): boolean {
  if (ev.category !== "hazard") return false

  const onsetMs = timeMs(ev.occurred_at)
  if (onsetMs !== null && onsetMs > momentMs) return false

  if (isStillInFeed(ev, momentMs, feedLatestMs) === false) return false

  const src = (ev.source ?? "").toLowerCase()
  const p = payload(ev)

  if (src.includes("gdacs")) {
    const current = boolValue(p.is_current)
    if (current === true) return true
    if (current === false) return false
    // Rows stored before `is_current` was kept.
    const toMs = timeMs(p.to_date)
    return toMs !== null && toMs + GDACS_GRACE_MS >= momentMs
  }

  if (src.includes("eonet")) return p.closed == null

  // A quake is not a state. Everything else obeys the window.
  return false
}
