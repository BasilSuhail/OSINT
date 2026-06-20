"use client"

import { useEffect, useState } from "react"
import * as astro from "astronomy-engine"

export interface CelestialBody {
  name: "Sun" | "Moon"
  /** Sub-stellar latitude (degrees, -90..90) — where the body is directly overhead. */
  lat: number
  /** Sub-stellar longitude (degrees, -180..180). */
  lon: number
  /** Rendered globe-radius altitude. Not physical; chosen for visual stage depth. */
  alt: number
  /** Illuminated fraction (0..1). Always 1 for the Sun; 0..1 for the Moon. */
  illumination: number
  /** Lunation angle in degrees (0 = new, 90 = first quarter, 180 = full, 270 = last quarter). */
  phaseAngle: number
}

export interface Ephemeris {
  sun: CelestialBody
  moon: CelestialBody
  /** Greenwich apparent sidereal time (hours) — useful for terminator math. */
  gastHours: number
}

const SUN_RENDER_ALT = 3.5
const MOON_RENDER_ALT = 0.8

function subPoint(body: astro.Body, when: Date, gast: number): { lat: number; lon: number } {
  const eq = astro.Equator(body, when, new astro.Observer(0, 0, 0), true, true)
  let lon = (eq.ra - gast) * 15
  while (lon > 180) lon -= 360
  while (lon < -180) lon += 360
  return { lat: eq.dec, lon }
}

export function computeEphemeris(when: Date = new Date()): Ephemeris {
  const gast = astro.SiderealTime(when)
  const sunPt = subPoint(astro.Body.Sun, when, gast)
  const moonPt = subPoint(astro.Body.Moon, when, gast)
  const moonIllum = astro.Illumination(astro.Body.Moon, when)
  const phaseAngle = astro.MoonPhase(when)

  return {
    sun: {
      name: "Sun",
      lat: sunPt.lat,
      lon: sunPt.lon,
      alt: SUN_RENDER_ALT,
      illumination: 1,
      phaseAngle: 0,
    },
    moon: {
      name: "Moon",
      lat: moonPt.lat,
      lon: moonPt.lon,
      alt: MOON_RENDER_ALT,
      illumination: moonIllum.phase_fraction,
      phaseAngle,
    },
    gastHours: gast,
  }
}

/**
 * Sub-solar + sub-lunar points repropagated on a tick. Default 5 s — the
 * sub-solar point drifts at ~0.25 mrad/sec (≈ 15°/hour); a 5 s tick keeps
 * the dot visibly creeping without burning frames. astronomy-engine is
 * sub-millisecond per call so this is cheap.
 */
export function useEphemeris(enabled: boolean, tickMs: number = 5_000): Ephemeris | null {
  const [eph, setEph] = useState<Ephemeris | null>(() => (enabled ? computeEphemeris() : null))

  useEffect(() => {
    if (!enabled) {
      setEph(null)
      return
    }
    setEph(computeEphemeris())
    const id = window.setInterval(() => setEph(computeEphemeris()), tickMs)
    return () => window.clearInterval(id)
  }, [enabled, tickMs])

  return eph
}

/** Human-readable moon phase from lunation angle. */
export function moonPhaseLabel(phaseAngle: number): string {
  const a = ((phaseAngle % 360) + 360) % 360
  if (a < 22.5 || a >= 337.5) return "New"
  if (a < 67.5) return "Waxing Crescent"
  if (a < 112.5) return "First Quarter"
  if (a < 157.5) return "Waxing Gibbous"
  if (a < 202.5) return "Full"
  if (a < 247.5) return "Waning Gibbous"
  if (a < 292.5) return "Last Quarter"
  return "Waning Crescent"
}
