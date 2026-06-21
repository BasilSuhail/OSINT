"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import Globe, { type GlobeMethods } from "react-globe.gl"
import {
  Orbit,
  Satellite as SatelliteIcon,
  Sparkles,
  Stars,
  Sunset,
  Target,
  X,
} from "lucide-react"
import * as THREE from "three"
import { useConfigured, useEvents } from "@/app/providers"
import { useEventsInWindow, type VisibleEvent } from "@/lib/queries"
import { colorForEvent } from "@/lib/types"
import { pointAltitude } from "@/lib/markers"
import { useSatellites, type Satellite } from "@/lib/satellites"
import { moonPhaseLabel, useEphemeris, type CelestialBody } from "@/lib/ephemeris"
import { useDriftedNeos, useNeos, type NeoAsteroid } from "@/lib/neos"
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

const ASTEROID_GEOM = new THREE.SphereGeometry(0.5, 6, 6)
const ASTEROID_MAT_SAFE = new THREE.MeshBasicMaterial({
  color: 0xa3a3a3,
  transparent: true,
  opacity: 0.95,
})
const ASTEROID_MAT_HAZARD = new THREE.MeshBasicMaterial({
  color: 0xef4444,
  transparent: true,
  opacity: 0.95,
})

function makeAsteroidMesh(n: NeoAsteroid): THREE.Object3D {
  const mat = n.hazardous ? ASTEROID_MAT_HAZARD : ASTEROID_MAT_SAFE
  const mesh = new THREE.Mesh(ASTEROID_GEOM, mat)
  // Scale by diameter — clamp so very small or very large NEOs still read.
  const s = Math.max(0.6, Math.min(2.4, n.diameterKm * 4))
  mesh.scale.set(s, s, s)
  return mesh
}

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
  const [showAsteroids, setShowAsteroids] = useState(true)
  const [selectedNeo, setSelectedNeo] = useState<NeoAsteroid | null>(null)
  const [showTerminator, setShowTerminator] = useState(true)
  const [showStarfield, setShowStarfield] = useState(true)
  const [followIss, setFollowIss] = useState(false)

  const neosRaw = useNeos(showAsteroids)
  const neos = useDriftedNeos(neosRaw, 1000)

  const satsCapped = useMemo(() => (sats.length > MAX_SATS ? sats.slice(0, MAX_SATS) : sats), [sats])

  /** Sun + Moon + Asteroids as objectsData entries, type-tagged so the
   *  lat/lng/alt/object accessors can dispatch alongside satellites. */
  type GlobeObject =
    | { kind: "sat"; data: Satellite }
    | { kind: "celestial"; data: CelestialBody }
    | { kind: "asteroid"; data: NeoAsteroid }

  const globeObjects = useMemo<GlobeObject[]>(() => {
    const out: GlobeObject[] = satsCapped.map((s) => ({ kind: "sat", data: s }))
    if (eph) {
      out.push({ kind: "celestial", data: eph.sun })
      out.push({ kind: "celestial", data: eph.moon })
    }
    for (const n of neos) out.push({ kind: "asteroid", data: n })
    return out
  }, [satsCapped, eph, neos])

  /** Day/night terminator: the great-circle perpendicular to the sub-solar
   *  vector. Sampled at 72 points so the polyline is smooth at any zoom.
   *  Returns null when ephemeris hasn't loaded yet or the user toggled it off. */
  const terminatorPath = useMemo<[number, number][] | null>(() => {
    if (!showTerminator || !eph) return null
    const lat = (eph.sun.lat * Math.PI) / 180
    const lon = (eph.sun.lon * Math.PI) / 180
    // Sub-solar unit vector S.
    const sx = Math.cos(lat) * Math.cos(lon)
    const sy = Math.cos(lat) * Math.sin(lon)
    const sz = Math.sin(lat)
    // Pick a vector not parallel to S, then orthonormalise to get U, V.
    let ax = 0
    const ay = 0
    let az = 1
    if (Math.abs(sz) > 0.99) {
      ax = 1
      az = 0
    }
    // U = normalize(cross(S, A))
    let ux = sy * az - sz * ay
    let uy = sz * ax - sx * az
    let uz = sx * ay - sy * ax
    const un = Math.hypot(ux, uy, uz)
    ux /= un
    uy /= un
    uz /= un
    // V = cross(S, U)
    const vx = sy * uz - sz * uy
    const vy = sz * ux - sx * uz
    const vz = sx * uy - sy * ux
    const path: [number, number][] = []
    const N = 72
    for (let i = 0; i <= N; i++) {
      const θ = (2 * Math.PI * i) / N
      const px = Math.cos(θ) * ux + Math.sin(θ) * vx
      const py = Math.cos(θ) * uy + Math.sin(θ) * vy
      const pz = Math.cos(θ) * uz + Math.sin(θ) * vz
      const pLat = (Math.asin(pz) * 180) / Math.PI
      const pLon = (Math.atan2(py, px) * 180) / Math.PI
      path.push([pLat, pLon])
    }
    return path
  }, [showTerminator, eph])

  /** Build a one-off starfield scene object the first time the user turns it
   *  on. Three.js Points of ~1500 random unit vectors at distance 6 globe
   *  radii. Static; we don't rotate it because Earth rotation under it gives
   *  the parallax for free. */
  useEffect(() => {
    if (size.width === 0) return
    const globe = globeRef.current
    if (!globe) return
    const scene = globe.scene() as unknown as THREE.Scene
    // Lazily build + cache.
    let starfield = scene.getObjectByName("osint-starfield") as THREE.Points | null
    if (!starfield) {
      const STAR_COUNT = 1500
      const positions = new Float32Array(STAR_COUNT * 3)
      const R = 600
      for (let i = 0; i < STAR_COUNT; i++) {
        // Uniform on the sphere via the standard arccos / 2π trick.
        const u = Math.random()
        const v = Math.random()
        const theta = 2 * Math.PI * u
        const phi = Math.acos(2 * v - 1)
        positions[3 * i + 0] = R * Math.sin(phi) * Math.cos(theta)
        positions[3 * i + 1] = R * Math.sin(phi) * Math.sin(theta)
        positions[3 * i + 2] = R * Math.cos(phi)
      }
      const geom = new THREE.BufferGeometry()
      geom.setAttribute("position", new THREE.BufferAttribute(positions, 3))
      const mat = new THREE.PointsMaterial({
        color: 0xffffff,
        size: 1.2,
        sizeAttenuation: false,
        transparent: true,
        opacity: 0.85,
      })
      starfield = new THREE.Points(geom, mat)
      starfield.name = "osint-starfield"
      scene.add(starfield)
    }
    starfield.visible = showStarfield
  }, [showStarfield, size.width])

  /** Follow ISS: every sat tick, smoothly move the camera onto the ISS sub-
   *  point. Cancelled when the user toggles off; the user can still drag to
   *  reposition mid-follow (the next tick will re-centre, that's the point). */
  useEffect(() => {
    if (!followIss) return
    if (!satsCapped.length) return
    const globe = globeRef.current
    if (!globe) return
    const iss = satsCapped.find((s) => s.noradId === "25544") ?? null
    if (!iss) return
    globe.pointOfView({ lat: iss.lat, lng: iss.lon, altitude: 1.6 }, 800)
  }, [followIss, satsCapped])

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
            if (o.kind === "sat") return makeSatMesh()
            if (o.kind === "asteroid") return makeAsteroidMesh(o.data)
            return makeCelestialObject(o.data)
          }}
          onObjectClick={(o) => {
            const obj = o as GlobeObject
            if (obj.kind === "sat") setSelectedSat(obj.data)
            else if (obj.kind === "asteroid") setSelectedNeo(obj.data)
            else setSelectedCelestial(obj.data)
          }}
          // Day/night terminator: one closed great-circle polyline. Lifted
          // 0.015 globe radii so the camera sees the full visible-hemisphere
          // arc, not just a sliver clipped by the surface. Solid stroke —
          // the dashed march in #117 made it read as a floating yellow stub
          // (issue raised after #117 deployed). See issue #122.
          pathsData={terminatorPath ? [terminatorPath] : []}
          pathPoints={(d) => d as [number, number][]}
          pathPointLat={(p) => (p as [number, number])[0]}
          pathPointLng={(p) => (p as [number, number])[1]}
          pathPointAlt={() => 0.015}
          pathColor={() => ["rgba(253,224,71,0.95)", "rgba(253,224,71,0.95)"]}
          pathStroke={2.5}
          pathTransitionDuration={0}
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

      {/* Terminator toggle */}
      <button
        type="button"
        onClick={() => setShowTerminator((s) => !s)}
        aria-label={showTerminator ? "Hide day/night line" : "Show day/night line"}
        title="Day / night terminator"
        className={cn(
          "absolute right-14 top-24 z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
          showTerminator
            ? "border-amber-700 bg-amber-950/40 text-amber-300"
            : "border-neutral-700 bg-neutral-900/70 text-neutral-300 hover:text-neutral-100",
        )}
      >
        <Sunset className="h-4 w-4" />
      </button>

      {/* Starfield toggle */}
      <button
        type="button"
        onClick={() => setShowStarfield((s) => !s)}
        aria-label={showStarfield ? "Hide starfield" : "Show starfield"}
        title="Starfield background"
        className={cn(
          "absolute right-14 top-[136px] z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
          showStarfield
            ? "border-indigo-700 bg-indigo-950/40 text-indigo-200"
            : "border-neutral-700 bg-neutral-900/70 text-neutral-300 hover:text-neutral-100",
        )}
      >
        <Stars className="h-4 w-4" />
      </button>

      {/* Follow ISS toggle */}
      <button
        type="button"
        onClick={() => setFollowIss((f) => !f)}
        aria-label={followIss ? "Stop following ISS" : "Follow ISS"}
        title="Follow the ISS"
        className={cn(
          "absolute right-14 top-[168px] z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
          followIss
            ? "border-cyan-700 bg-cyan-950/40 text-cyan-200"
            : "border-neutral-700 bg-neutral-900/70 text-neutral-300 hover:text-neutral-100",
        )}
      >
        <Target className="h-4 w-4" />
      </button>

      {/* Asteroid toggle */}
      <button
        type="button"
        onClick={() => setShowAsteroids((s) => !s)}
        aria-label={showAsteroids ? "Hide NEOs" : "Show NEOs"}
        title="Near-Earth asteroids (NASA NeoWS)"
        className={cn(
          "absolute right-14 top-[200px] z-30 grid h-8 w-8 place-items-center rounded-md border backdrop-blur-sm transition-colors",
          showAsteroids
            ? "border-rose-700 bg-rose-950/40 text-rose-300"
            : "border-neutral-700 bg-neutral-900/70 text-neutral-300 hover:text-neutral-100",
        )}
      >
        <Sparkles className="h-4 w-4" />
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

      {/* Asteroid floating card */}
      {selectedNeo && (
        <div className="absolute left-1/2 top-4 z-40 w-72 -translate-x-1/2 rounded-lg border border-rose-900 bg-neutral-950/95 p-3 backdrop-blur-md">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-rose-300" />
              <span className="font-mono text-xs uppercase tracking-wider text-rose-100">
                {selectedNeo.name}
              </span>
            </div>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setSelectedNeo(null)}
              className="text-neutral-500 hover:text-neutral-200"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 font-mono text-[11px]">
            <dt className="text-neutral-500">approach</dt>
            <dd className="text-neutral-300">{selectedNeo.date.toUTCString().slice(0, 22)} UTC</dd>
            <dt className="text-neutral-500">miss</dt>
            <dd className="text-neutral-300">
              {selectedNeo.missKm.toLocaleString(undefined, { maximumFractionDigits: 0 })} km
            </dd>
            <dt className="text-neutral-500">diameter</dt>
            <dd className="text-neutral-300">~{selectedNeo.diameterKm.toFixed(2)} km</dd>
            <dt className="text-neutral-500">hazardous</dt>
            <dd className={cn("text-neutral-300", selectedNeo.hazardous ? "text-rose-300" : "")}>
              {selectedNeo.hazardous ? "yes (PHA)" : "no"}
            </dd>
          </dl>
        </div>
      )}

      {showCelestial && <EphemerisChip eph={eph} />}

      <FilterRail pane="globe" side="right" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
