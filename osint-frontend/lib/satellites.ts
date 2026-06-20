"use client"

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import * as satellite from "satellite.js"

export interface Satellite {
  name: string
  noradId: string
  lat: number
  lon: number
  /** Altitude expressed in globe-radius units (1.0 = surface). */
  alt: number
  altKm: number
  speedKmS: number
}

export interface TleRecord {
  name: string
  line1: string
  line2: string
  noradId: string
}

const EARTH_RADIUS_KM = 6371

async function fetchTle(group: string): Promise<TleRecord[]> {
  const res = await fetch(`/api/satellites?group=${group}`)
  if (!res.ok) throw new Error(`tle fetch failed: ${res.status}`)
  const text = await res.text()
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0)
  const out: TleRecord[] = []
  for (let i = 0; i + 2 < lines.length; i += 3) {
    const name = lines[i].trim()
    const line1 = lines[i + 1]
    const line2 = lines[i + 2]
    if (!line1.startsWith("1 ") || !line2.startsWith("2 ")) continue
    const noradId = line1.slice(2, 7).trim()
    out.push({ name, line1, line2, noradId })
  }
  return out
}

function propagate(tle: TleRecord, when: Date): Satellite | null {
  try {
    const rec = satellite.twoline2satrec(tle.line1, tle.line2)
    const pv = satellite.propagate(rec, when)
    if (!pv) return null
    const pos = pv.position
    if (!pos || typeof pos === "boolean") return null
    const gmst = satellite.gstime(when)
    const geo = satellite.eciToGeodetic(pos, gmst)
    const altKm = geo.height
    if (!Number.isFinite(altKm) || altKm < 0 || altKm > 50_000) return null
    const v = pv.velocity
    const speed =
      v && typeof v !== "boolean"
        ? Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        : 0
    return {
      name: tle.name,
      noradId: tle.noradId,
      lat: satellite.degreesLat(geo.latitude),
      lon: satellite.degreesLong(geo.longitude),
      alt: altKm / EARTH_RADIUS_KM,
      altKm,
      speedKmS: speed,
    }
  } catch {
    return null
  }
}

/**
 * Live satellite positions for a CelesTrak GROUP. TLEs refetched hourly;
 * positions repropagated every `tickMs` (default 3 s) so the dots glide
 * along their orbits.
 */
export function useSatellites(
  enabled: boolean,
  group: string = "stations",
  tickMs: number = 3000,
): Satellite[] {
  const { data: tles } = useSWR(
    enabled ? ["tle", group] : null,
    () => fetchTle(group),
    { refreshInterval: 60 * 60 * 1000, revalidateOnFocus: false },
  )

  const [now, setNow] = useState<Date>(() => new Date())
  useEffect(() => {
    if (!enabled) return
    const id = window.setInterval(() => setNow(new Date()), tickMs)
    return () => window.clearInterval(id)
  }, [enabled, tickMs])

  return useMemo(() => {
    if (!enabled || !tles) return []
    const out: Satellite[] = []
    for (const t of tles) {
      const s = propagate(t, now)
      if (s) out.push(s)
    }
    return out
  }, [enabled, tles, now])
}
