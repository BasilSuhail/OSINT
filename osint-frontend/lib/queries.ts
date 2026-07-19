"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import useSWR from "swr"
import { useEvents } from "@/app/providers"
import {
  CLIENT_LIMITS,
  fetchEvents,
  fetchEventStats,
  fetchScores as apiFetchScores,
  type EventStats,
} from "./apiClient"
import { sourceKeyForEvent, type EventRow, type HazardTypeKey, type ScoreRow } from "./types"
import { hazardKind } from "./hazardSymbols"
import { isPersistentActiveHazard } from "./hazardActivity"
import { eventMatchesCountry } from "./countryMatching"
import type { FilterStore } from "@/stores/createFilterStore"

export interface VisibleEvent extends EventRow {
  /** 0 (new) .. 1 (about to expire) */
  age: number
  opacity: number
  occurredMs: number
  /** Rendered outside the time window because its source still publishes it
   *  as live. Drives the map's "ongoing" treatment (#340). */
  ongoing: boolean
}

export interface WindowState {
  events: VisibleEvent[]
  windowStart: number
  windowEnd: number
  total: number
}

/**
 * Computes the set of events visible in the map's time window, honouring all
 * filters in the supplied store. Owns the scrubber clock: when `playing`, the
 * window end advances toward real-time at `speed`x.
 */
export function useEventsInWindow(useStore: FilterStore): WindowState {
  const allEvents = useEvents()

  const sources = useStore((s) => s.sources)
  const hazardTypes = useStore((s) => s.hazardTypes)
  const severity = useStore((s) => s.severity)
  const countries = useStore((s) => s.countries)
  const keyword = useStore((s) => s.keyword)
  const windowLengthMs = useStore((s) => s.windowLengthMs)
  const playing = useStore((s) => s.playing)
  const speed = useStore((s) => s.speed)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const setWindowEndOffset = useStore((s) => s.setWindowEndOffset)

  // A ticking clock to re-evaluate fades; advances the window when playing.
  const [, force] = useState(0)
  const lastTickRef = useRef<number>(Date.now())

  useEffect(() => {
    lastTickRef.current = Date.now()
    const id = window.setInterval(() => {
      const now = Date.now()
      const dt = now - lastTickRef.current
      lastTickRef.current = now
      if (playing) {
        // advance forward => reduce the past-offset
        const next = Math.max(0, windowEndOffsetMs - dt * speed)
        if (next !== windowEndOffsetMs) setWindowEndOffset(next)
      }
      force((n) => (n + 1) % 1_000_000)
    }, 250)
    return () => window.clearInterval(id)
  }, [playing, speed, windowEndOffsetMs, setWindowEndOffset])

  return useMemo<WindowState>(() => {
    const realNow = Date.now()
    const windowEnd = realNow - windowEndOffsetMs
    const windowStart = windowEnd - windowLengthMs
    const kw = keyword.trim().toLowerCase()
    const countrySet = new Set(countries)

    //: Newest fetched_at per source. A hazard that has ended drops out of its
    //: upstream feed and stops being re-upserted, which is the only signal that
    //: distinguishes it from one that is still running — its `is_current` flag
    //: never changes (#340). Measured per source so one stalled feed cannot
    //: expire another's events.
    const feedLatest = new Map<string, number>()
    for (const ev of allEvents) {
      if (!ev.source || !ev.fetched_at) continue
      const t = +new Date(ev.fetched_at)
      if (!Number.isFinite(t)) continue
      const seen = feedLatest.get(ev.source)
      if (seen === undefined || t > seen) feedLatest.set(ev.source, t)
    }

    const visible: VisibleEvent[] = []
    for (const ev of allEvents) {
      const sk = sourceKeyForEvent(ev)
      if (!sk || !sources[sk]) continue
      // Hazards are filtered by disaster TYPE, not their lump-sum source: hide
      // just the volcanoes / cyclones / quakes the user muted. Unknown ("other")
      // hazards always pass so nothing silently disappears.
      if (ev.category === "hazard") {
        const kind = hazardKind(ev)
        if (kind !== "other" && hazardTypes[kind as HazardTypeKey] === false) continue
      }
      if (ev.severity < severity[0] || ev.severity > severity[1]) continue
      if (!eventMatchesCountry(ev, countrySet)) continue
      if (kw) {
        const hay = `${ev.keywords?.join(" ") ?? ""} ${ev.category} ${JSON.stringify(ev.payload)}`.toLowerCase()
        if (!hay.includes(kw)) continue
      }
      const occurredMs = +new Date(ev.occurred_at)
      // Only active, stateful hazards are persistent. Closed GDACS cyclones /
      // volcanoes and point-in-time hazards should obey the scrubber window.
      const isPersistentHazard = isPersistentActiveHazard(
        ev,
        windowEnd,
        ev.source ? feedLatest.get(ev.source) : undefined,
      )
      const age = windowLengthMs > 0 ? (windowEnd - occurredMs) / windowLengthMs : 0
      if (!isPersistentHazard) {
        if (occurredMs > windowEnd || occurredMs < windowStart) continue
        if (age > 1) continue
      }
      visible.push({
        ...ev,
        age: isPersistentHazard ? 0 : age,
        opacity: isPersistentHazard ? 1 : Math.max(0.1, 1 - age),
        occurredMs,
        //: Only flag it "ongoing" when persistence is what kept it visible —
        //: a live hazard inside the window is just a normal marker.
        ongoing: isPersistentHazard && (occurredMs < windowStart || occurredMs > windowEnd),
      })
    }
    return { events: visible, windowStart, windowEnd, total: visible.length }
  }, [allEvents, sources, hazardTypes, severity, countries, keyword, windowLengthMs, windowEndOffsetMs])
}

/** Server-side world stats for the status panel (#499).
 *
 *  Replaces aggregating the client buffer: the buffer is capped, so counting it
 *  reported the cap. Polls on the same 60s cadence as the scores query; the
 *  payload is a couple of dozen integers regardless of how much data is behind
 *  it. Returns undefined until the first response lands. */
export function useWorldStats(days = 30): { stats: EventStats | undefined; isLoading: boolean } {
  const { data, isLoading } = useSWR(["event-stats", days], () => fetchEventStats(days), {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
  })
  return { stats: data, isLoading }
}

async function fetchScores(): Promise<ScoreRow[]> {
  return apiFetchScores(CLIENT_LIMITS.scoreRows)
}

export interface LatestScore {
  country: string
  score: number
  components: ScoreRow["components"]
  bucketStart: string
}

/** Latest composite score per country (by bucket_start). */
export function useLatestScores(): {
  byCountry: Map<string, LatestScore>
  isLoading: boolean
} {
  const { data, isLoading } = useSWR("scores-latest", fetchScores, {
    refreshInterval: 60_000,
    revalidateOnFocus: false,
  })

  const byCountry = useMemo(() => {
    const map = new Map<string, LatestScore>()
    for (const row of data ?? []) {
      const existing = map.get(row.country)
      if (!existing || +new Date(row.bucket_start) > +new Date(existing.bucketStart)) {
        map.set(row.country, {
          country: row.country,
          score: row.score_value,
          components: row.components,
          bucketStart: row.bucket_start,
        })
      }
    }
    return map
  }, [data])

  return { byCountry, isLoading }
}

/** Fetch the most-recent N events for a single country (for the side panel). */
export function useCountryEvents(country: string | null): { events: EventRow[]; isLoading: boolean } {
  const { data, isLoading } = useSWR(
    country ? ["country-events", country] : null,
    async () => {
      if (!country) return []
      return fetchEvents({ country, exclude: ["opensky-adsb"], limit: 50 })
    },
    { revalidateOnFocus: false },
  )
  return { events: data ?? [], isLoading }
}
