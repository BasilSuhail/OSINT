"use client"

import { useEffect, useState } from "react"
import * as astro from "astronomy-engine"

export interface PlanetMarker {
  name: string
  /** Sub-point on Earth's celestial sphere where the planet appears overhead. */
  lat: number
  lon: number
  /** Stage altitude — far enough to not clip Earth, close enough to read. */
  alt: number
  /** Hex colour for visual identification. */
  color: string
}

const PLANET_RENDER_ALT = 1.4

const PALETTE: Record<string, string> = {
  Mercury: "#a3a3a3",
  Venus: "#fde68a",
  Mars: "#ef4444",
  Jupiter: "#f97316",
  Saturn: "#fbbf24",
  Uranus: "#7dd3fc",
  Neptune: "#3b82f6",
}

const PLANET_BODIES: { name: string; body: astro.Body }[] = [
  { name: "Mercury", body: astro.Body.Mercury },
  { name: "Venus", body: astro.Body.Venus },
  { name: "Mars", body: astro.Body.Mars },
  { name: "Jupiter", body: astro.Body.Jupiter },
  { name: "Saturn", body: astro.Body.Saturn },
]

function subPoint(body: astro.Body, when: Date, gast: number): { lat: number; lon: number } {
  const eq = astro.Equator(body, when, new astro.Observer(0, 0, 0), true, true)
  let lon = (eq.ra - gast) * 15
  while (lon > 180) lon -= 360
  while (lon < -180) lon += 360
  return { lat: eq.dec, lon }
}

export function computePlanets(when: Date = new Date()): PlanetMarker[] {
  const gast = astro.SiderealTime(when)
  return PLANET_BODIES.map(({ name, body }) => {
    const { lat, lon } = subPoint(body, when, gast)
    return { name, lat, lon, alt: PLANET_RENDER_ALT, color: PALETTE[name] ?? "#a3a3a3" }
  })
}

/** Repropagated every tickMs. 60 s is way more than enough — planets move
 *  fractions of a degree per minute. */
export function usePlanets(enabled: boolean, tickMs: number = 60_000): PlanetMarker[] {
  const [planets, setPlanets] = useState<PlanetMarker[]>(() =>
    enabled ? computePlanets() : [],
  )
  useEffect(() => {
    if (!enabled) {
      setPlanets([])
      return
    }
    setPlanets(computePlanets())
    const id = window.setInterval(() => setPlanets(computePlanets()), tickMs)
    return () => window.clearInterval(id)
  }, [enabled, tickMs])
  return planets
}
