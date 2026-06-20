"use client"

import { useEffect, useState } from "react"
import { Moon, Sun } from "lucide-react"
import { moonPhaseLabel, type Ephemeris } from "@/lib/ephemeris"

interface EphemerisChipProps {
  eph: Ephemeris | null
}

function fmtLat(lat: number): string {
  const hemi = lat >= 0 ? "N" : "S"
  return `${Math.abs(lat).toFixed(2)}°${hemi}`
}

function fmtLon(lon: number): string {
  const hemi = lon >= 0 ? "E" : "W"
  return `${Math.abs(lon).toFixed(2)}°${hemi}`
}

function fmtUtc(d: Date): string {
  return d.toISOString().slice(11, 19)
}

/**
 * Bottom-left telemetry overlay for the globe pane. Live-updating UTC clock
 * plus current sub-solar and sub-lunar points so the viewer can cross-check
 * the rendered Sun and Moon positions against an almanac.
 */
export function EphemerisChip({ eph }: EphemerisChipProps) {
  const [now, setNow] = useState<Date>(() => new Date())
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(id)
  }, [])

  if (!eph) return null

  return (
    <div className="pointer-events-none absolute bottom-[calc(8%+12px)] left-3 z-30 rounded-md border border-neutral-800 bg-neutral-950/80 px-2.5 py-1.5 font-mono text-[10px] leading-tight text-neutral-300 backdrop-blur-sm">
      <div className="flex items-baseline gap-2">
        <span className="text-neutral-500">UTC</span>
        <span className="tabular-nums text-neutral-100">{fmtUtc(now)}</span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <Sun className="h-2.5 w-2.5 shrink-0 text-amber-300" />
        <span className="tabular-nums">
          {fmtLat(eph.sun.lat)} {fmtLon(eph.sun.lon)}
        </span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <Moon className="h-2.5 w-2.5 shrink-0 text-neutral-300" />
        <span className="tabular-nums">
          {fmtLat(eph.moon.lat)} {fmtLon(eph.moon.lon)}
        </span>
        <span className="text-neutral-500">
          {(eph.moon.illumination * 100).toFixed(0)}% · {moonPhaseLabel(eph.moon.phaseAngle)}
        </span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-2 text-neutral-500">
        <span>GAST</span>
        <span className="tabular-nums">{eph.gastHours.toFixed(2)}h</span>
      </div>
    </div>
  )
}
