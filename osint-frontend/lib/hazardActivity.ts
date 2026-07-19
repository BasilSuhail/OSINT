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

/** Is this row still being republished by its source?
 *
 *  Compared against the newest row from the *same source* rather than the wall
 *  clock: if ingestion stops, every row ages together and none is singled out,
 *  so an outage degrades the map to its last known state instead of silently
 *  emptying it. Returns null when there is not enough evidence to judge. */
function isStillInFeed(ev: EventRow, feedLatestMs?: number): boolean | null {
  if (feedLatestMs === undefined || !Number.isFinite(feedLatestMs)) return null
  const fetchedMs = timeMs(ev.fetched_at)
  if (fetchedMs === null) return null
  return fetchedMs >= feedLatestMs - FEED_PRESENCE_GRACE_MS
}

/**
 * Should this hazard stay on the map after it falls out of the time window?
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

  const src = (ev.source ?? "").toLowerCase()
  const p = payload(ev)

  // Missing evidence must not hide data, so an unknown verdict falls through to
  // the flag checks below; only a definite "gone from the feed" expires a row.
  if (isStillInFeed(ev, feedLatestMs) === false) return false

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
