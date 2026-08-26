import type { EventRow } from "./types"

const GDACS_GRACE_MS = 48 * 60 * 60 * 1000

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

/** How far a row's `fetched_at` may lag the newest row from the same source
 *  before we treat it as having left the feed. GDACS polls every 15 min and
 *  EONET every 30, and each poll re-upserts every event it still considers
 *  live, so a live row is never more than one poll behind. Three hours is
 *  roughly a dozen missed polls — generous enough to absorb transient fetch
 *  failures, tight enough that an ended hazard clears the map the same day. */
const FEED_PRESENCE_GRACE_MS = 3 * 60 * 60 * 1000

/** Was this row still being republished by its source at `atMs`?
 *
 *  Compared against the newest row from the *same source* rather than the wall
 *  clock: if ingestion stops, every row ages together and none is singled out,
 *  so an outage degrades the map to its last known state instead of silently
 *  emptying it. Returns null when there is not enough evidence to judge.
 *
 *  The reference is clamped to the moment on screen so the same question can be
 *  asked of a past one. Feed activity from after that moment says nothing about
 *  whether the hazard had ended by it: a hazard last seen in the feed in August
 *  was plainly still running in July, and judging it against August's newest
 *  row hid it from July for having ended since. On a live map the window end is
 *  now, which is at or after any observed fetch, so the clamp does nothing and
 *  the outage tolerance above is what applies. */
function isStillInFeed(ev: EventRow, atMs: number, feedLatestMs?: number): boolean | null {
  if (feedLatestMs === undefined || !Number.isFinite(feedLatestMs)) return null
  const fetchedMs = timeMs(ev.fetched_at)
  if (fetchedMs === null) return null
  return fetchedMs >= Math.min(feedLatestMs, atMs) - FEED_PRESENCE_GRACE_MS
}

/**
 * Was this hazard running at the moment the map is showing?
 *
 * `nowMs` is that moment — the scrubber's window end, which is the wall clock
 * only on a live map. Answering it as a question about a moment rather than
 * about now is what lets the same rule serve a scrubbed-back view: the answer
 * is a reason to draw a hazard whose onset is older than the window, and never
 * a reason to draw one that had not begun.
 *
 * `feedLatestMs` is the newest `fetched_at` observed for this event's source.
 *
 * GDACS and EONET only publish events while they are live, and the GDACS
 * fetcher drops non-current ones at ingest (`gdacs_fetcher.py`), so a stored
 * row's `is_current` flag is written once and can never be falsified — every
 * GDACS row in the database reads `is_current: true` forever. Trusting the flag
 * alone kept ended hazards pinned to the map until 30-day retention removed
 * them (#340). Feed presence is what actually distinguishes ongoing from ended.
 */
export function isPersistentActiveHazard(
  ev: EventRow,
  nowMs = Date.now(),
  feedLatestMs?: number,
): boolean {
  if (ev.category !== "hazard") return false

  //: Persistence is permission to outlive the window, not to precede it. It
  //: exists for a hazard whose onset has fallen off the back of the three-day
  //: view while the hazard itself runs on, and nothing bounded the other end:
  //: every currently-active hazard was drawn at full opacity at any scrubber
  //: position, including months before it began. A hazard that had not started
  //: at the moment on screen is not persistently active at it.
  const onsetMs = timeMs(ev.occurred_at)
  if (onsetMs !== null && onsetMs > nowMs) return false

  const src = (ev.source ?? "").toLowerCase()
  const p = payload(ev)

  // Missing evidence must not hide data, so an unknown verdict falls through to
  // the flag checks below; only a definite "gone from the feed" expires a row.
  if (isStillInFeed(ev, nowMs, feedLatestMs) === false) return false

  if (src.includes("gdacs")) {
    const current = boolValue(p.is_current)
    if (current === true) return true
    if (current === false) return false

    // Backward compatibility for rows ingested before `is_current` was stored.
    const toMs = timeMs(p.to_date)
    return toMs !== null && toMs + GDACS_GRACE_MS >= nowMs
  }

  if (src.includes("eonet")) {
    return p.closed == null
  }

  return false
}
