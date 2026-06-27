"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import useSWR from "swr"
import { useEvents } from "@/app/providers"
import { fetchEvents, fetchScores as apiFetchScores } from "./apiClient"
import { paneForEvent, sourceKeyForEvent, type EventRow, type HazardTypeKey, type Pane, type ScoreRow } from "./types"
import { hazardKind } from "./hazardSymbols"
import { isPersistentActiveHazard } from "./hazardActivity"
import type { FilterStore } from "@/stores/createFilterStore"

export interface VisibleEvent extends EventRow {
  /** 0 (new) .. 1 (about to expire) */
  age: number
  opacity: number
  occurredMs: number
}

export interface WindowState {
  events: VisibleEvent[]
  windowStart: number
  windowEnd: number
  total: number
}

/**
 * Computes the set of events visible in a pane's time window, honouring all
 * filters in the supplied store. Owns the scrubber clock: when `playing`, the
 * window end advances toward real-time at `speed`x.
 *
 * When `pane` is supplied, events whose source does not belong to that pane
 * are dropped (e.g. satellite/NASA-derived events live on the globe; the rest
 * on the flat map). This keeps the two panes from rendering duplicate markers.
 */
export function useEventsInWindow(useStore: FilterStore, pane?: Pane): WindowState {
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

    const visible: VisibleEvent[] = []
    for (const ev of allEvents) {
      const sk = sourceKeyForEvent(ev)
      if (!sk || !sources[sk]) continue
      if (pane && paneForEvent(ev) !== pane) continue
      // Hazards are filtered by disaster TYPE, not their lump-sum source: hide
      // just the volcanoes / cyclones / quakes the user muted. Unknown ("other")
      // hazards always pass so nothing silently disappears.
      if (ev.category === "hazard") {
        const kind = hazardKind(ev)
        if (kind !== "other" && hazardTypes[kind as HazardTypeKey] === false) continue
      }
      if (ev.severity < severity[0] || ev.severity > severity[1]) continue
      if (countrySet.size > 0 && (!ev.country || !countrySet.has(ev.country))) continue
      if (kw) {
        const hay = `${ev.keywords?.join(" ") ?? ""} ${ev.category} ${JSON.stringify(ev.payload)}`.toLowerCase()
        if (!hay.includes(kw)) continue
      }
      const occurredMs = +new Date(ev.occurred_at)
      // Only active, stateful hazards are persistent. Closed GDACS cyclones /
      // volcanoes and point-in-time hazards should obey the scrubber window.
      const isPersistentHazard = isPersistentActiveHazard(ev, windowEnd)
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
      })
    }
    return { events: visible, windowStart, windowEnd, total: visible.length }
  }, [allEvents, sources, hazardTypes, severity, countries, keyword, windowLengthMs, windowEndOffsetMs, pane])
}

async function fetchScores(): Promise<ScoreRow[]> {
  return apiFetchScores(5000)
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
