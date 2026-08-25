"use client"

import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import useSWR from "swr"
import { EventBuffer, FIREHOSE_EXCLUDE, type ConnectionDiagnostics, type ConnectionStatus } from "@/lib/realtime"
import { CLIENT_LIMITS, fetchEvents, fetchSourceCoverage, isApiConfigured } from "@/lib/apiClient"
import { useLeftPaneStore } from "@/stores/leftPaneStore"
import { DEFAULT_SCRUB_SPAN_MS } from "@/stores/createFilterStore"
import { LIVE_TOLERANCE_MS } from "@/lib/timeWindow"
import type { EventRow } from "@/lib/types"

interface RealtimeContextValue {
  buffer: EventBuffer
  configured: boolean
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null)

//: How coarsely the firehose key follows the scrubber. The offset changes on
//: every pointer move and on every playback frame; without a bucket each one
//: would be a new SWR key and a new request. An hour is finer than the 3-day
//: window it scopes, so no reachable position is left unfetched.
const WINDOW_KEY_BUCKET_MS = 60 * 60 * 1000

/**
 * Pull the most-recent events into the buffer in 1000-row pages.
 *
 * The API caps a single response at 1000 rows unless you also page via the
 * Range header. Before this change the buffer only saw whatever fit in the
 * very first 1000 rows — FIRMS dominated that slice and the map effectively
 * showed ~50 GDELT events even though the DB had 90k+ in the last 3 days.
 *
 * We also exclude the `opensky-adsb` aviation feed at the query level: it
 * emits ~190k rows/day (every aircraft, every 2 min) with current timestamps,
 * so without this it saturates the entire `occurred_at`-ordered budget and
 * starves every displayable source — the map renders 0 events. Aviation has
 * no source toggle, so it is never shown from this buffer anyway. See the
 * `sourceKeyForEvent === null` guard in EventBuffer.ingest for the live path.
 */
async function fetchWindowEvents(offsetMs: number, lengthMs: number): Promise<EventRow[]> {
  const windowEnd = Date.now() - offsetMs
  const since = new Date(windowEnd - lengthMs).toISOString()
  //: Live keeps its open end so an event that lands mid-request is not cut off
  //: by a `until` stamped a moment earlier. A scrubbed-back window is closed at
  //: both ends: without that, the budget is spent on rows the map will not draw.
  const until =
    offsetMs < LIVE_TOLERANCE_MS ? undefined : new Date(windowEnd).toISOString()
  return fetchEvents({ since, until, exclude: FIREHOSE_EXCLUDE, limit: CLIENT_LIMITS.eventWindow })
}

async function fetchUpdatedEvents(buffer: EventBuffer): Promise<EventRow[]> {
  const cursor = buffer.getRevisionCursor()
  const updatedSince = cursor?.updatedAt
    ?? new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
  return fetchEvents({
    updatedSince,
    updatedAfterId: cursor?.id,
    exclude: FIREHOSE_EXCLUDE,
    limit: 2000,
  })
}

/** abuse.ch cyber (~20k rows) is dense enough to saturate the firehose, so it
 *  is excluded from the main pull and fetched here capped — enough to render
 *  the recent C2 layer on the map without bloating the shared buffer. */
async function fetchCyberEvents(): Promise<EventRow[]> {
  return fetchEvents({ sources: ["abuse-ch-urlhaus", "abuse-ch-feodo"], limit: CLIENT_LIMITS.cyberEvents })
}

/** Sparse but high-value hazard sources. NASA FIRMS alone emits ~50k rows in
 *  the 30-day window, so the `occurred_at`-ordered firehose budget (5000) is
 *  consumed by fire detections before GDACS floods / cyclones / droughts or
 *  the handful of USGS quakes ever appear — the map silently dropped them
 *  (flash floods were missing despite GDACS showing them). A dedicated fetch
 *  guarantees every hazard event reaches the buffer; the volumes are tiny
 *  (hundreds of rows) so this is cheap. The buffer dedups on ingest. */
const HAZARD_SOURCES = ["gdacs", "usgs-quake", "eonet"]

async function fetchHazardEvents(): Promise<EventRow[]> {
  // No `since` filter: GDACS volcanoes / long-running cyclones can have started
  // months ago yet still be active, so the 30-day window would drop them. The
  // hazard sources are sparse (hundreds of rows), so pulling the lot is cheap.
  return fetchEvents({ sources: HAZARD_SOURCES, limit: CLIENT_LIMITS.hazardEvents })
}

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const bufferRef = useRef<EventBuffer | null>(null)
  if (!bufferRef.current) bufferRef.current = new EventBuffer()
  const buffer = bufferRef.current

  useEffect(() => {
    if (!isApiConfigured) return
    buffer.connect()
    return () => buffer.disconnect()
  }, [buffer])

  //: The firehose follows the scrubber rather than pulling a fixed recent slab.
  //: Below the viewport zoom the map has no other source, so a slab was the
  //: reason dragging past its edge emptied the map instead of showing history.
  //: Scoping to the visible window also spends the row budget on three days
  //: instead of thirty, so a dense feed no longer starves a sparse one.
  const windowOffsetMs = useLeftPaneStore((s) => s.windowEndOffsetMs)
  const windowLengthMs = useLeftPaneStore((s) => s.windowLengthMs)
  const setScrubSpan = useLeftPaneStore((s) => s.setScrubSpan)
  const windowBucket = Math.round(windowOffsetMs / WINDOW_KEY_BUCKET_MS)

  // SWR fallback: poll every 30s (and once on mount) to backfill / recover.
  useSWR(
    isApiConfigured ? ["events-window", windowBucket, windowLengthMs] : null,
    () => fetchWindowEvents(windowOffsetMs, windowLengthMs),
    {
      refreshInterval: 30_000,
      revalidateOnFocus: false,
      keepPreviousData: true,
      onSuccess: (rows) => buffer.ingest(rows),
    },
  )

  //: What the scrubber may reach is what the database still holds. Asked once
  //: an hour rather than once: retention moves the floor up as old rows are
  //: pruned, and a board filling a large disk moves it down as history builds.
  useSWR(isApiConfigured ? "events-earliest" : null, () => fetchSourceCoverage(), {
    refreshInterval: 3_600_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => {
      const earliest = rows
        .map((row) => (row.earliest_occurred_at ? Date.parse(row.earliest_occurred_at) : NaN))
        .filter((ms) => Number.isFinite(ms))
      if (!earliest.length) return
      setScrubSpan(Math.max(DEFAULT_SCRUB_SPAN_MS, Date.now() - Math.min(...earliest)))
    },
  })

  // Enrichment mutates existing rows without changing their event time. Poll
  // the durable database revision so an older row still reaches an open map
  // even after it falls below the recent-window result cap (#762).
  useSWR(isApiConfigured ? "events-updated" : null, () => fetchUpdatedEvents(buffer), {
    refreshInterval: 30_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => buffer.ingestUpdated(rows),
  })

  // Dedicated hazard poll so sparse GDACS / USGS / EONET events are never
  // starved out of the firehose budget by higher-volume feeds (#206).
  useSWR(isApiConfigured ? "events-hazard" : null, fetchHazardEvents, {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => buffer.ingest(rows),
  })

  // High-volume feeds pulled separately + capped so they can't flood the buffer.
  useSWR(isApiConfigured ? "events-cyber" : null, fetchCyberEvents, {
    refreshInterval: 120_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => buffer.ingest(rows),
  })

  const value = useMemo<RealtimeContextValue>(
    () => ({ buffer, configured: isApiConfigured }),
    [buffer],
  )

  return <RealtimeContext.Provider value={value}>{children}</RealtimeContext.Provider>
}

function useRealtime(): RealtimeContextValue {
  const ctx = useContext(RealtimeContext)
  if (!ctx) throw new Error("useRealtime must be used within RealtimeProvider")
  return ctx
}

/** Subscribe to the shared event buffer (re-renders on change). */
export function useEvents(): EventRow[] {
  const { buffer } = useRealtime()
  return useSyncExternalStore(buffer.subscribe, buffer.getSnapshot, () => buffer.getSnapshot())
}

/** Subscribe to the realtime connection status. */
export function useConnectionStatus(): ConnectionStatus {
  return useConnectionDiagnostics().status
}

/** Subscribe to the full realtime diagnostics (status + reconnect count + last seen). */
export function useConnectionDiagnostics(): ConnectionDiagnostics {
  const { buffer, configured } = useRealtime()
  const [diag, setDiag] = useState<ConnectionDiagnostics>(
    configured
      ? buffer.getDiagnostics()
      : {
          status: "disconnected",
          reconnectAttempts: 0,
          lastEventAt: null,
          lastSeenAt: null,
        },
  )
  useEffect(() => {
    if (!configured) return
    setDiag(buffer.getDiagnostics())
    return buffer.subscribeStatus(setDiag)
  }, [buffer, configured])
  return diag
}

export function useConfigured(): boolean {
  return useRealtime().configured
}
