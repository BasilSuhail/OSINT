"use client"

import { useEffect, useState } from "react"
import { format, formatDistanceToNowStrict } from "date-fns"
import { Copy, ExternalLink, Satellite as SatIcon, X } from "lucide-react"
import type { Satellite } from "@/lib/satellites"
import { cn } from "@/lib/utils"

interface SatelliteDetailCardProps {
  satellite: Satellite
  onClose: () => void
  className?: string
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
          window.setTimeout(() => setDone(false), 1200)
        } catch {
          /* clipboard unavailable */
        }
      }}
      title={label ?? "Copy"}
      className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-neutral-500 hover:text-neutral-200"
    >
      <Copy className="h-3 w-3" />
      {done ? "copied" : label ?? "copy"}
    </button>
  )
}

export function SatelliteDetailCard({ satellite, onClose, className }: SatelliteDetailCardProps) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handleKey)
    return () => window.removeEventListener("keydown", handleKey)
  }, [onClose])

  const ageStale = satellite.tleAgeDays > 7
  const n2yoUrl = `https://www.n2yo.com/satellite/?s=${satellite.noradId}`
  const tleText = `${satellite.name}\n${satellite.line1}\n${satellite.line2}`

  return (
    <div
      className={cn(
        "w-80 max-w-[88vw] rounded-md border border-cyan-900 bg-neutral-950/95 p-3 text-neutral-200 shadow-2xl backdrop-blur-md",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <SatIcon className="h-4 w-4 text-cyan-300" />
          <span className="font-mono text-xs uppercase tracking-wider text-cyan-100">
            {satellite.name}
          </span>
        </div>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="text-neutral-500 hover:text-neutral-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
        <dt className="text-neutral-500">NORAD</dt>
        <dd className="flex items-center gap-2 text-neutral-300">
          <span>{satellite.noradId}</span>
          <CopyButton text={satellite.noradId} label="id" />
        </dd>

        <dt className="text-neutral-500">COSPAR</dt>
        <dd className="text-neutral-300">{satellite.cospar}</dd>

        <dt className="text-neutral-500">position</dt>
        <dd className="flex items-center gap-2 text-neutral-300">
          <span>
            {satellite.lat.toFixed(2)}, {satellite.lon.toFixed(2)}
          </span>
          <CopyButton text={`${satellite.lat},${satellite.lon}`} label="latlon" />
        </dd>

        <dt className="text-neutral-500">altitude</dt>
        <dd className="text-neutral-300">{satellite.altKm.toFixed(0)} km</dd>

        <dt className="text-neutral-500">speed</dt>
        <dd className="text-neutral-300">{satellite.speedKmS.toFixed(2)} km/s</dd>

        <dt className="text-neutral-500">period</dt>
        <dd className="text-neutral-300">{satellite.periodMin.toFixed(1)} min</dd>

        <dt className="text-neutral-500">inclination</dt>
        <dd className="text-neutral-300">{satellite.inclinationDeg.toFixed(2)}°</dd>

        <dt className="text-neutral-500">eccentricity</dt>
        <dd className="text-neutral-300">{satellite.eccentricity.toFixed(5)}</dd>

        <dt className="text-neutral-500">perigee</dt>
        <dd className="text-neutral-300">{satellite.perigeeKm.toFixed(0)} km</dd>

        <dt className="text-neutral-500">apogee</dt>
        <dd className="text-neutral-300">{satellite.apogeeKm.toFixed(0)} km</dd>

        <dt className="text-neutral-500">epoch</dt>
        <dd className="text-neutral-300">{format(satellite.epoch, "yyyy-MM-dd HH:mm 'UTC'")}</dd>

        <dt className="text-neutral-500">TLE age</dt>
        <dd className={cn("text-neutral-300", ageStale ? "text-amber-400" : "")}>
          {formatDistanceToNowStrict(satellite.epoch, { addSuffix: true })}
          {ageStale && " — stale"}
        </dd>
      </dl>

      <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-neutral-800 pt-2">
        <a
          href={n2yoUrl}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-cyan-400 hover:text-cyan-300"
        >
          n2yo <ExternalLink className="h-2.5 w-2.5" />
        </a>
        <CopyButton text={tleText} label="copy tle" />
        <CopyButton text={JSON.stringify(satellite, null, 2)} label="copy json" />
      </div>
    </div>
  )
}
