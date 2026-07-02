"use client"

import { createContext, useContext, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react"
import useSWR from "swr"
import { EventBuffer, FIREHOSE_EXCLUDE, type ConnectionDiagnostics, type ConnectionStatus } from "@/lib/realtime"
import { fetchEvents, isApiConfigured } from "@/lib/apiClient"
import type { EventRow } from "@/lib/types"

interface RealtimeContextValue {
  buffer: EventBuffer
  configured: boolean
}

const RealtimeContext = createContext<RealtimeContextValue | null>(null)

const WINDOW_MS = 30 * 24 * 60 * 60 * 1000 // 30 days
const TARGET_ROWS = 20_000

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
async function fetchRecentEvents(): Promise<EventRow[]> {
  const since = new Date(Date.now() - WINDOW_MS).toISOString()
  return fetchEvents({ since, exclude: FIREHOSE_EXCLUDE, limit: TARGET_ROWS })
}

/** abuse.ch cyber (~20k rows) is dense enough to saturate the firehose, so it
 *  is excluded from the main pull and fetched here capped — enough to render
 *  the recent C2 layer on the map without bloating the shared buffer. */
async function fetchCyberEvents(): Promise<EventRow[]> {
  return fetchEvents({ sources: ["abuse-ch-urlhaus", "abuse-ch-feodo"], limit: 2000 })
}

/** NASA FIRMS (100k+ rows) is globe-only; the globe caps at 1500 points, so a
 *  small capped pull keeps the fire layer alive without flooding the buffer. */
async function fetchFirmsEvents(): Promise<EventRow[]> {
  return fetchEvents({ sources: ["nasa-firms"], limit: 1500 })
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
  return fetchEvents({ sources: HAZARD_SOURCES, limit: TARGET_ROWS })
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

  // SWR fallback: poll every 30s (and once on mount) to backfill / recover.
  useSWR(isApiConfigured ? "events-window" : null, fetchRecentEvents, {
    refreshInterval: 30_000,
    revalidateOnFocus: false,
    onSuccess: (rows) => buffer.ingest(rows),
  })

  // Dedicated hazard poll so sparse GDACS / USGS / EONET events are never
  // starved out of the firehose budget by NASA FIRMS volume (#206).
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
  useSWR(isApiConfigured ? "events-firms" : null, fetchFirmsEvents, {
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
