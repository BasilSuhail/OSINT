"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Globe, { type GlobeMethods } from "react-globe.gl"
import { formatDistanceToNowStrict } from "date-fns"
import { ExternalLink, Orbit, Satellite as SatelliteIcon, X } from "lucide-react"
import * as THREE from "three"
import { useEventsInWindow, type VisibleEvent } from "@/lib/queries"
import { colorForEvent } from "@/lib/types"
import { pointAltitude } from "@/lib/markers"
import { useSatellites, type Satellite } from "@/lib/satellites"
import type { FilterStore } from "@/stores/createFilterStore"
import { cn } from "@/lib/utils"
import { FilterRail } from "./FilterRail"
import { TimeScrubber } from "./TimeScrubber"

const GLOBE_IMG = "//unpkg.com/three-globe/example/img/earth-night.jpg"
const BUMP_IMG = "//unpkg.com/three-globe/example/img/earth-topology.png"
const MAX_POINTS = 1500
const MAX_SATS = 2500

const SAT_GEOMETRY = new THREE.SphereGeometry(0.6, 6, 6)
const SAT_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0x22d3ee,
  transparent: true,
  opacity: 0.85,
})
function makeSatMesh(): THREE.Object3D {
  const mesh = new THREE.Mesh(SAT_GEOMETRY, SAT_MATERIAL)
  // Pin a clone of the material so individual mesh tint can drift in future
  // without affecting the shared one.
  mesh.material = SAT_MATERIAL
  return mesh
}

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "")
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha.toFixed(3)})`
}

interface GlobePaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onSelectCountry: (iso: string) => void
  onCount: (n: number) => void
}

export function GlobePane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount }: GlobePaneProps) {
  const { events, windowEnd, total } = useEventsInWindow(useStore, "globe")
  const showSatellites = useStore((s) => s.showSatellites)
  const satelliteGroup = useStore((s) => s.satelliteGroup)
  const sats = useSatellites(showSatellites, satelliteGroup, 3000)
  const globeRef = useRef<GlobeMethods | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [autoRotate, setAutoRotate] = useState(true)
  const [selected, setSelected] = useState<VisibleEvent | null>(null)
  const [selectedSat, setSelectedSat] = useState<Satellite | null>(null)

  const satsCapped = useMemo(() => (sats.length > MAX_SATS ? sats.slice(0, MAX_SATS) : sats), [sats])

  useEffect(() => onCount(total), [total, onCount])

  // Size to container.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const r = entries[0].contentRect
      setSize({ width: r.width, height: r.height })
    })
    ro.observe(el)
    setSize({ width: el.clientWidth, height: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  // Auto-rotation controls.
  useEffect(() => {
    const globe = globeRef.current
    if (!globe) return
    const controls = globe.controls() as unknown as {
      autoRotate: boolean
      autoRotateSpeed: number
    }
    controls.autoRotate = autoRotate
    controls.autoRotateSpeed = 0.5
    // Pull the camera back a touch so the future satellite/moon/sun layer has
    // room to breathe, while keeping LEO altitudes visible above the surface.
    globe.pointOfView({ altitude: 3.0 }, 0)
  }, [autoRotate, size.width])

  const points = useMemo(() => {
    const out: VisibleEvent[] = []
    for (const ev of events) {
      if (ev.lat == null || ev.lon == null) continue
      out.push(ev)
      if (out.length >= MAX_POINTS) break
    }
    return out
  }, [events])

  const handlePointClick = useCallback((pt: object) => {
    setSelected(pt as VisibleEvent)
  }, [])

  const selectedUrl = selected
    ? ((selected.payload as { source_url?: string; link?: string })?.source_url ??
      (selected.payload as { link?: string })?.link)
    : undefined

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden" style={{ backgroundColor: "#000010" }}>
      {size.width > 0 && (
        <Globe
          ref={globeRef}
          width={size.width}
          height={size.height}
          backgroundColor="#000010"
          globeImageUrl={GLOBE_IMG}
          bumpImageUrl={BUMP_IMG}
          showAtmosphere
          atmosphereColor="#3a86ff"
          atmosphereAltitude={0.18}
          pointsData={points}
          pointLat={(d) => (d as VisibleEvent).lat as number}
          pointLng={(d) => (d as VisibleEvent).lon as number}
          pointColor={(d) => {
            const ev = d as VisibleEvent
            return hexToRgba(colorForEvent(ev), ev.opacity)
          }}
          pointAltitude={(d) => pointAltitude((d as VisibleEvent).severity)}
          pointRadius={(d) => 0.15 + (d as VisibleEvent).severity * 0.35}
          pointResolution={6}
          pointsMerge={false}
          onPointClick={handlePointClick}
          arcsData={[]}
          objectsData={satsCapped}
          objectLat={(d) => (d as Satellite).lat}
          objectLng={(d) => (d as Satellite).lon}
          objectAltitude={(d) => (d as Satellite).alt}
          objectThreeObject={makeSatMesh}
          onObjectClick={(o) => setSelectedSat(o as Satellite)}
          enablePointerInteraction
        />
      )}

      {/* Rotation toggle */}
      <button
        type="button"
        onClick={() => setAutoRotate((r) => !r)}
        aria-label={autoRotate ? "Pause rotation" : "Resume rotation"}
        className={cn(
          "absolute right-14 top-3 z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
          autoRotate
            ? "border-neutral-700 bg-neutral-900/70 text-neutral-300 hover:text-neutral-100"
            : "border-emerald-700 bg-emerald-950/40 text-emerald-300",
        )}
      >
        <Orbit className="h-4 w-4" />
      </button>

      {/* Live satellite count chip */}
      {showSatellites && satsCapped.length > 0 && (
        <div className="absolute left-3 top-3 z-30 flex items-center gap-1.5 rounded-md border border-cyan-900/70 bg-cyan-950/30 px-2 py-1 font-mono text-[10px] uppercase tracking-widest text-cyan-200 backdrop-blur-sm">
          <SatelliteIcon className="h-3 w-3" />
          {satsCapped.length} live · {satelliteGroup}
        </div>
      )}

      {points.length === 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <p className="font-mono text-xs uppercase tracking-widest text-neutral-600">
            No events match the current filters
          </p>
        </div>
      )}

      {/* Floating event card */}
      {selected && (
        <div className="absolute left-1/2 top-4 z-40 w-64 -translate-x-1/2 rounded-lg border border-neutral-700 bg-neutral-950/95 p-3 backdrop-blur-md">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: colorForEvent(selected) }}
              />
              <span className="font-mono text-xs uppercase tracking-wider text-neutral-200">
                {selected.source}
              </span>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setSelected(null)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
            <dt className="text-neutral-500">when</dt>
            <dd className="text-neutral-300">
              {formatDistanceToNowStrict(new Date(selected.occurred_at), { addSuffix: true })}
            </dd>
            <dt className="text-neutral-500">category</dt>
            <dd className="text-neutral-300">{selected.category}</dd>
            <dt className="text-neutral-500">severity</dt>
            <dd className="text-neutral-300">{selected.severity.toFixed(2)}</dd>
            {selected.country && (
              <>
                <dt className="text-neutral-500">country</dt>
                <dd className="text-neutral-300">{selected.country}</dd>
              </>
            )}
          </dl>
          <div className="mt-2 flex items-center gap-3">
            {selected.country && (
              <button
                type="button"
                onClick={() => onSelectCountry(selected.country as string)}
                className="font-mono text-[10px] uppercase tracking-widest text-emerald-400 hover:text-emerald-300"
              >
                Country detail
              </button>
            )}
            {selectedUrl && (
              <a
                href={selectedUrl}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest text-neutral-400 hover:text-neutral-200"
              >
                source <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>
        </div>
      )}

      {/* Satellite floating card */}
      {selectedSat && (
        <div className="absolute right-1/2 top-4 z-40 w-64 translate-x-1/2 rounded-lg border border-cyan-900 bg-neutral-950/95 p-3 backdrop-blur-md">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <SatelliteIcon className="h-3.5 w-3.5 text-cyan-300" />
              <span className="font-mono text-xs uppercase tracking-wider text-cyan-100">
                {selectedSat.name}
              </span>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setSelectedSat(null)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
            <dt className="text-neutral-500">NORAD</dt>
            <dd className="text-neutral-300">{selectedSat.noradId}</dd>
            <dt className="text-neutral-500">altitude</dt>
            <dd className="text-neutral-300">{selectedSat.altKm.toFixed(0)} km</dd>
            <dt className="text-neutral-500">speed</dt>
            <dd className="text-neutral-300">{selectedSat.speedKmS.toFixed(2)} km/s</dd>
            <dt className="text-neutral-500">lat / lon</dt>
            <dd className="text-neutral-300">
              {selectedSat.lat.toFixed(2)}, {selectedSat.lon.toFixed(2)}
            </dd>
          </dl>
        </div>
      )}

      <FilterRail pane="globe" side="right" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
