"use client"

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import * as satellite from "satellite.js"

export interface Satellite {
  name: string
  noradId: string
  /** International designator from TLE line 1 (e.g. "98067A" for ISS). */
  cospar: string
  lat: number
  lon: number
  /** Altitude expressed in globe-radius units (1.0 = surface). */
  alt: number
  altKm: number
  speedKmS: number
  /** Orbital inclination in degrees. */
  inclinationDeg: number
  /** Orbital eccentricity (0 = circular). */
  eccentricity: number
  /** Orbital period in minutes. */
  periodMin: number
  /** Perigee altitude in km. */
  perigeeKm: number
  /** Apogee altitude in km. */
  apogeeKm: number
  /** Epoch UTC when the TLE was generated. */
  epoch: Date
  /** Age of the TLE in days (now - epoch). */
  tleAgeDays: number
  /** Raw TLE for copy-to-clipboard. */
  line1: string
  line2: string
}

export interface TleRecord {
  name: string
  line1: string
  line2: string
  noradId: string
}

const EARTH_RADIUS_KM = 6371
const EARTH_MU = 398_600.4418  // km^3 / s^2

/** TLE line 1 chars 9-17 hold the international designator (COSPAR). */
function parseCospar(line1: string): string {
  const raw = line1.slice(9, 17).trim()
  return raw || "unknown"
}

/** TLE epoch (line 1 chars 18-32) → Date. yy is 2000-relative if < 57. */
function tleEpochToDate(epochyr: number, epochdays: number): Date {
  const year = epochyr < 57 ? 2000 + epochyr : 1900 + epochyr
  const jan1 = Date.UTC(year, 0, 1)
  const ms = jan1 + (epochdays - 1) * 86_400_000
  return new Date(ms)
}

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

    // Derived orbital elements from the satrec. `no` is mean motion in rad/min.
    const periodMin = (2 * Math.PI) / rec.no
    const nRadSec = rec.no / 60
    const semiMajorKm = Math.cbrt(EARTH_MU / (nRadSec * nRadSec))
    const eccentricity = rec.ecco
    const perigeeKm = semiMajorKm * (1 - eccentricity) - EARTH_RADIUS_KM
    const apogeeKm = semiMajorKm * (1 + eccentricity) - EARTH_RADIUS_KM
    const inclinationDeg = (rec.inclo * 180) / Math.PI
    const epoch = tleEpochToDate(rec.epochyr, rec.epochdays)
    const tleAgeDays = (when.getTime() - epoch.getTime()) / 86_400_000

    return {
      name: tle.name,
      noradId: tle.noradId,
      cospar: parseCospar(tle.line1),
      lat: satellite.degreesLat(geo.latitude),
      lon: satellite.degreesLong(geo.longitude),
      alt: altKm / EARTH_RADIUS_KM,
      altKm,
      speedKmS: speed,
      inclinationDeg,
      eccentricity,
      periodMin,
      perigeeKm,
      apogeeKm,
      epoch,
      tleAgeDays,
      line1: tle.line1,
      line2: tle.line2,
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
