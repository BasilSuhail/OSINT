"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"

export interface NeoAsteroid {
  id: string
  name: string
  /** Close-approach date (ISO). */
  date: Date
  /** Closest miss distance in km. Used to pick render altitude + colour. */
  missKm: number
  /** Diameter estimate (max), km. Drives marker size. */
  diameterKm: number
  /** True if NASA flags this as a Potentially Hazardous Asteroid. */
  hazardous: boolean
  /** Pseudo-position over the globe — NEOs don't have ground coordinates,
   *  so we project to a deterministic point on a celestial sphere using the
   *  id as a seed. Mostly cosmetic; the real value is in the close-approach
   *  metadata. */
  lat: number
  lon: number
  /** Render altitude in globe-radius units. Closer approaches → lower alt. */
  alt: number
}

interface NeoFeed {
  near_earth_objects?: Record<
    string,
    {
      id: string
      name: string
      is_potentially_hazardous_asteroid: boolean
      close_approach_data: {
        close_approach_date_full: string
        miss_distance: { kilometers: string }
      }[]
      estimated_diameter: { kilometers: { estimated_diameter_max: number } }
    }[]
  >
}

function seedToLatLon(seed: string): { lat: number; lon: number } {
  // Cheap deterministic hash-ish.
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0
  const a = Math.abs(h) % 360
  const b = (Math.abs(h >> 8) % 180) - 90
  return { lon: a - 180, lat: b }
}

function missToAltitude(missKm: number): number {
  // ~5 lunar distances = 1.9M km. Map that range to [1.5 .. 4.0] alt.
  const lunar = 384_400
  const ratio = Math.max(0.2, Math.min(missKm / (5 * lunar), 5))
  return 1.5 + Math.min(2.5, ratio * 0.5)
}

async function fetchNeos(): Promise<NeoAsteroid[]> {
  const res = await fetch("/api/neos")
  if (!res.ok) return []
  const json = (await res.json()) as NeoFeed
  const out: NeoAsteroid[] = []
  const groups = json.near_earth_objects ?? {}
  for (const items of Object.values(groups)) {
    for (const n of items) {
      const ca = n.close_approach_data?.[0]
      if (!ca) continue
      const missKm = Number(ca.miss_distance.kilometers)
      if (!Number.isFinite(missKm)) continue
      const date = new Date(ca.close_approach_date_full)
      const { lat, lon } = seedToLatLon(n.id)
      out.push({
        id: n.id,
        name: n.name,
        date,
        missKm,
        diameterKm: n.estimated_diameter?.kilometers?.estimated_diameter_max ?? 0.1,
        hazardous: !!n.is_potentially_hazardous_asteroid,
        lat,
        lon,
        alt: missToAltitude(missKm),
      })
    }
  }
  return out.sort((a, b) => a.missKm - b.missKm).slice(0, 40)
}

/** Live NEO list. Refreshes hourly. */
export function useNeos(enabled: boolean): NeoAsteroid[] {
  const { data } = useSWR(enabled ? "neos" : null, fetchNeos, {
    refreshInterval: 60 * 60 * 1000,
    revalidateOnFocus: false,
  })
  return data ?? []
}

/** Convenience: gentle drift each tick so they read as moving. */
export function useDriftedNeos(neos: NeoAsteroid[], tickMs: number = 1000): NeoAsteroid[] {
  const [t, setT] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setT((x) => (x + 1) % 1_000_000), tickMs)
    return () => window.clearInterval(id)
  }, [tickMs])
  // Tiny lon drift per tick — purely cosmetic.
  return neos.map((n) => ({ ...n, lon: ((n.lon + t * 0.4 + 180) % 360) - 180 }))
}
