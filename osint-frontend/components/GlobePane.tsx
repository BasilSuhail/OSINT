"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Globe, { type GlobeMethods } from "react-globe.gl"
import { Orbit, Satellite as SatelliteIcon, X } from "lucide-react"
import * as THREE from "three"
import { useConfigured, useEvents } from "@/app/providers"
import { useEventsInWindow, type VisibleEvent } from "@/lib/queries"
import { colorForEvent } from "@/lib/types"
import { pointAltitude } from "@/lib/markers"
import { useSatellites, type Satellite } from "@/lib/satellites"
import { moonPhaseLabel, useEphemeris, type CelestialBody } from "@/lib/ephemeris"
import type { FilterStore } from "@/stores/createFilterStore"
import { cn } from "@/lib/utils"
import { EphemerisChip } from "./EphemerisChip"
import { EventDetailCard } from "./EventDetailCard"
import { FilterRail } from "./FilterRail"
import { PaneStatus } from "./PaneStatus"
import { SatelliteDetailCard } from "./SatelliteDetailCard"
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
  mesh.material = SAT_MATERIAL
  return mesh
}

const SUN_GEOMETRY = new THREE.SphereGeometry(8, 24, 24)
const SUN_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0xfde68a,
  transparent: true,
  opacity: 0.95,
})
const SUN_HALO_GEOMETRY = new THREE.SphereGeometry(14, 24, 24)
const SUN_HALO_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0xfacc15,
  transparent: true,
  opacity: 0.18,
})
const MOON_GEOMETRY = new THREE.SphereGeometry(3, 18, 18)
const MOON_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0xe5e7eb,
  transparent: true,
  opacity: 0.9,
})
const MOON_HALO_GEOMETRY = new THREE.SphereGeometry(5, 18, 18)
const MOON_HALO_MATERIAL = new THREE.MeshBasicMaterial({
  color: 0xa3a3a3,
  transparent: true,
  opacity: 0.15,
})

function makeCelestialObject(body: CelestialBody): THREE.Object3D {
  const group = new THREE.Group()
  if (body.name === "Sun") {
    group.add(new THREE.Mesh(SUN_HALO_GEOMETRY, SUN_HALO_MATERIAL))
    group.add(new THREE.Mesh(SUN_GEOMETRY, SUN_MATERIAL))
  } else {
    group.add(new THREE.Mesh(MOON_HALO_GEOMETRY, MOON_HALO_MATERIAL))
    const mesh = new THREE.Mesh(MOON_GEOMETRY, MOON_MATERIAL)
    // Dim the moon disc by current illuminated fraction so phase reads visually.
    const matClone = MOON_MATERIAL.clone()
    matClone.opacity = 0.4 + body.illumination * 0.55
    mesh.material = matClone
    group.add(mesh)
  }
  return group
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
  const configured = useConfigured()
  const allEvents = useEvents()
  const showSatellites = useStore((s) => s.showSatellites)
  const satelliteGroup = useStore((s) => s.satelliteGroup)
  const showCelestial = useStore((s) => s.showCelestial)
  const sats = useSatellites(showSatellites, satelliteGroup, 3000)
  const eph = useEphemeris(showCelestial, 5_000)
  const globeRef = useRef<GlobeMethods | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [autoRotate, setAutoRotate] = useState(true)
  const [selected, setSelected] = useState<VisibleEvent | null>(null)
  const [selectedSat, setSelectedSat] = useState<Satellite | null>(null)
  const [selectedCelestial, setSelectedCelestial] = useState<CelestialBody | null>(null)

  const satsCapped = useMemo(() => (sats.length > MAX_SATS ? sats.slice(0, MAX_SATS) : sats), [sats])

  /** Sun + Moon as objectsData entries, type-tagged so the lat/lng/alt/object
   *  accessors can dispatch alongside satellites. */
  type GlobeObject =
    | { kind: "sat"; data: Satellite }
    | { kind: "celestial"; data: CelestialBody }

  const globeObjects = useMemo<GlobeObject[]>(() => {
    const out: GlobeObject[] = satsCapped.map((s) => ({ kind: "sat", data: s }))
    if (eph) {
      out.push({ kind: "celestial", data: eph.sun })
      out.push({ kind: "celestial", data: eph.moon })
    }
    return out
  }, [satsCapped, eph])

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

  // Stop auto-rotation the moment the user grabs / pinches / scrolls the globe
  // — without this, satellites and event dots are constantly drifting away
  // from the cursor. Resumes only via the explicit Orbit button.
  useEffect(() => {
    if (size.width === 0) return
    const globe = globeRef.current
    if (!globe) return
    const controls = globe.controls() as unknown as {
      addEventListener: (type: string, fn: () => void) => void
      removeEventListener: (type: string, fn: () => void) => void
    }
    const handleStart = () => setAutoRotate(false)
    controls.addEventListener("start", handleStart)
    return () => controls.removeEventListener("start", handleStart)
  }, [size.width])

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
          objectsData={globeObjects}
          objectLat={(d) => (d as GlobeObject).data.lat}
          objectLng={(d) => (d as GlobeObject).data.lon}
          objectAltitude={(d) => (d as GlobeObject).data.alt}
          objectThreeObject={(d) => {
            const o = d as GlobeObject
            return o.kind === "sat" ? makeSatMesh() : makeCelestialObject(o.data)
          }}
          onObjectClick={(o) => {
            const obj = o as GlobeObject
            if (obj.kind === "sat") setSelectedSat(obj.data)
            else setSelectedCelestial(obj.data)
          }}
          enablePointerInteraction
        />
      )}

      {/* Rotation toggle */}
      <button
        type="button"
        onClick={() => setAutoRotate((r) => !r)}
        aria-label={autoRotate ? "Pause rotation" : "Resume rotation"}
        className={cn(
          "absolute right-14 top-14 z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
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

      {!configured && (
        <PaneStatus
          mode="error"
          message="Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY."
        />
      )}
      {configured && allEvents.length === 0 && <PaneStatus mode="loading" />}
      {configured && allEvents.length > 0 && points.length === 0 && (
        <PaneStatus mode="empty" onReset={() => useStore.getState().reset()} />
      )}

      {/* Floating event card */}
      {selected && (
        <div className="absolute left-1/2 top-4 z-40 -translate-x-1/2">
          <EventDetailCard
            event={selected}
            onSelectCountry={onSelectCountry}
            onClose={() => setSelected(null)}
          />
        </div>
      )}

      {/* Celestial floating card */}
      {selectedCelestial && (
        <div
          className={cn(
            "absolute left-1/2 top-4 z-40 w-64 -translate-x-1/2 rounded-lg border bg-neutral-950/95 p-3 backdrop-blur-md",
            selectedCelestial.name === "Sun" ? "border-amber-700" : "border-neutral-600",
          )}
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: selectedCelestial.name === "Sun" ? "#fde68a" : "#e5e7eb" }}
              />
              <span className="font-mono text-xs uppercase tracking-wider text-neutral-100">
                {selectedCelestial.name}
              </span>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setSelectedCelestial(null)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
            <dt className="text-neutral-500">sub-point</dt>
            <dd className="text-neutral-300">
              {selectedCelestial.lat.toFixed(2)}, {selectedCelestial.lon.toFixed(2)}
            </dd>
            {selectedCelestial.name === "Moon" && (
              <>
                <dt className="text-neutral-500">phase</dt>
                <dd className="text-neutral-300">
                  {moonPhaseLabel(selectedCelestial.phaseAngle)} ({selectedCelestial.phaseAngle.toFixed(0)}°)
                </dd>
                <dt className="text-neutral-500">illuminated</dt>
                <dd className="text-neutral-300">{(selectedCelestial.illumination * 100).toFixed(0)}%</dd>
              </>
            )}
            {selectedCelestial.name === "Sun" && (
              <>
                <dt className="text-neutral-500">overhead</dt>
                <dd className="text-neutral-300">noon at lon {selectedCelestial.lon.toFixed(1)}</dd>
              </>
            )}
          </dl>
        </div>
      )}

      {/* Satellite floating card */}
      {selectedSat && (
        <div className="absolute right-1/2 top-4 z-40 translate-x-1/2">
          <SatelliteDetailCard satellite={selectedSat} onClose={() => setSelectedSat(null)} />
        </div>
      )}

      {showCelestial && <EphemerisChip eph={eph} />}

      <FilterRail pane="globe" side="right" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
