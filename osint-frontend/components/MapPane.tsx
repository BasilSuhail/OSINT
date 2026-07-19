"use client"

import "maplibre-gl/dist/maplibre-gl.css"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import MapGL, {
  Layer,
  Marker,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre"
import { Activity, Droplets, Flame, Snowflake, Sun, Triangle, Wind } from "lucide-react"
import { useConfigured, useEvents } from "@/app/providers"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import {
  hazardColor,
  hazardIcon,
  hazardKind,
  type HazardIcon,
} from "@/lib/hazardSymbols"
import { hazardFootprintCollections } from "@/lib/mapFootprints"
import { addMissingStyleImagePlaceholder } from "@/lib/mapStyleImages"
import {
  isWorldScopeNews,
  worldNewsAggregates,
  type WorldNewsAggregate,
} from "@/lib/worldNewsAggregates"
import { colorForEvent } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { FilterRail } from "./FilterRail"
import { PaneStatus } from "./PaneStatus"
import { TimeScrubber } from "./TimeScrubber"

const HAZARD_ICONS: Record<Exclude<HazardIcon, "dot">, typeof Activity> = {
  activity: Activity,
  flame: Flame,
  wind: Wind,
  droplets: Droplets,
  triangle: Triangle,
  sun: Sun,
  snowflake: Snowflake,
}

const MAP_STYLE = "https://tiles.openfreemap.org/styles/dark"
const MAP_STYLE_RETRY_MS = 1500
const MAX_MARKERS = 700
const INITIAL_ZOOM = 1.4
const MIN_SCROLL_ZOOM = INITIAL_ZOOM

interface MapPaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onSelectCountry: (iso: string) => void
  onCount: (n: number) => void
  /** Bubble a clicked event up to the shared centred detail overlay. */
  onSelectEvent: (ev: VisibleEvent) => void
  /** Id of the currently-selected event (drives the expanded cyclone footprint). */
  selectedEventId: VisibleEvent["id"] | null
}

interface Positioned {
  ev: VisibleEvent
  lat: number
  lon: number
}

interface ClusterMarker {
  key: string
  lat: number
  lon: number
  events: Positioned[]
  color: string
}

/** Sources dense enough that a single dot per event would flood the map, so we
 *  cluster them into proportional circles: news + GDELT pile up at city
 *  centroids. Sparse hazards (quakes, GDACS, EONET) stay individual with their
 *  own icon + footprint. NASA FIRMS (100k+ thermal pixels, no footprint) lives
 *  on the globe, not here — the map's fires are the GDACS/EONET wildfire events. */
function isClusterable(ev: VisibleEvent): boolean {
  const source = (ev.source ?? "").toLowerCase()
  if (ev.category === "news") return true
  if (source.startsWith("rss-")) return true
  if (source === "uk-police") return true
  if (source === "gdelt") return true
  return false
}

/** Zoom → quantisation precision in degrees. Bigger cells when zoomed out,
 *  finer cells when zoomed in. At zoom ~7 the cell is small enough that
 *  city-level pins start to separate again.
 *
 *  Below zoom 3 we floor to 4° so neighbouring 1° cells don't fight for
 *  pixels on the world view (Spain + Italy chips were overlapping at the
 *  default 1.4 zoom — see issue #135). */
function cellPrecision(zoom: number): number {
  if (zoom < 3) return 4
  return Math.max(0.04, 4 / Math.pow(2, zoom))
}

/** ACLED proportional-symbol sizing: area ∝ count → diameter ∝ √count, clamped.
 *  Shared by the cluster/aggregate circles and the size legend so they match. */
function circleSizeForCount(n: number): number {
  return Math.min(58, 9 + Math.sqrt(Math.max(1, n)) * 5)
}

function EventMarker({
  ev,
  lat,
  lon,
  onSelect,
}: {
  ev: VisibleEvent
  lat: number
  lon: number
  onSelect: (ev: VisibleEvent) => void
}) {
  const style = markerStyle(ev)
  // News / GDELT singletons render as a soft, semi-transparent dot — never a
  // glowing "this place is on fire" mark for one BBC headline (#252).
  const clusterable = isClusterable(ev)
  const size = clusterable ? 7 : style.size
  const HIT_SIZE = 28

  return (
    <Marker
      longitude={lon}
      latitude={lat}
      anchor="center"
      onClick={(e) => {
        e.originalEvent.stopPropagation()
        onSelect(ev)
      }}
    >
      <div
        style={{ width: HIT_SIZE, height: HIT_SIZE, cursor: "pointer", opacity: ev.opacity }}
        className="relative grid place-items-center"
        title={ev.ongoing ? "Ongoing — still live in its source feed, older than the window" : undefined}
      >
        {/* Ongoing hazards are the only markers allowed outside the time
         *  window, so they say so rather than passing as current events (#340). */}
        {ev.ongoing && (
          <span
            aria-hidden
            className="pointer-events-none absolute inset-[4px] rounded-full border border-dashed"
            style={{ borderColor: `${hazardColor(ev)}cc` }}
          />
        )}
        {(() => {
          const kind = hazardKind(ev)
          const iconKey = hazardIcon(kind)
          const color = hazardColor(ev)
          if (iconKey !== "dot" && !clusterable && ev.source !== "nasa-firms") {
            const Icon = HAZARD_ICONS[iconKey]
            return (
              <span
                className="grid place-items-center rounded-sm"
                style={{
                  width: 13,
                  height: 13,
                  backgroundColor: color,
                  boxShadow: `0 0 3px ${color}aa`,
                  border: "1px solid rgba(255,255,255,0.5)",
                }}
              >
                <Icon size={9} color="#0a0a0a" strokeWidth={2.5} aria-hidden />
              </span>
            )
          }
          // non-hazard: simple dot/diamond. Clusterable singletons get a soft
          // semi-transparent fill + thin ring (no glow) to match the cluster
          // circles; everything else keeps its crisp glowing mark.
          return (
            <span
              className="block"
              style={{
                width: size,
                height: size,
                backgroundColor: clusterable ? `${style.color}b3` : style.color,
                borderRadius: style.shape === "diamond" ? 2 : "9999px",
                transform: style.shape === "diamond" ? "rotate(45deg)" : undefined,
                border: clusterable ? `1px solid ${style.color}` : undefined,
                boxShadow: clusterable ? "none" : `0 0 3px ${style.color}`,
              }}
            />
          )
        })()}
      </div>
    </Marker>
  )
}

function ClusterChip({
  cluster,
  onClick,
}: {
  cluster: ClusterMarker
  onClick: (c: ClusterMarker) => void
}) {
  const n = cluster.events.length
  // ACLED-style proportional symbol: area ∝ count → radius ∝ √count. No digit
  // — the count/list lives in the right pane (#252). Semi-transparent fill so
  // overlapping piles read as density; clamp so mega-piles don't swallow the map.
  const size = circleSizeForCount(n)
  return (
    <Marker longitude={cluster.lon} latitude={cluster.lat} anchor="center">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onClick(cluster)
        }}
        className="rounded-full"
        style={{
          width: size,
          height: size,
          backgroundColor: `${cluster.color}59`, // ~35% alpha fill
          border: `1px solid ${cluster.color}cc`,
          cursor: "pointer",
          padding: 0,
        }}
        aria-label={`${n} events — open list`}
      />
    </Marker>
  )
}

function WorldAggregateChip({
  aggregate,
  onClick,
}: {
  aggregate: WorldNewsAggregate
  onClick: (aggregate: WorldNewsAggregate) => void
}) {
  const n = aggregate.events.length
  // Proportional symbol, no digit (count in the right pane). Slate fill marks
  // it as world-scope news, distinct from the source-coloured local clusters.
  const size = circleSizeForCount(n)
  return (
    <Marker longitude={aggregate.lon} latitude={aggregate.lat} anchor="center">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          onClick(aggregate)
        }}
        className="rounded-full"
        style={{
          width: size,
          height: size,
          backgroundColor: "rgba(148,163,184,0.28)",
          border: "1px solid rgba(203,213,225,0.7)",
          cursor: "pointer",
          padding: 0,
        }}
        aria-label={`${n} world news in ${aggregate.country} — open list`}
      />
    </Marker>
  )
}

export function MapPane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount, onSelectEvent, selectedEventId }: MapPaneProps) {
  const { events, windowEnd, total } = useEventsInWindow(useStore)
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [styleReloadToken, setStyleReloadToken] = useState(0)
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [zoom, setZoom] = useState<number>(INITIAL_ZOOM)
  const openClusterInPane = useRightPaneModeStore((s) => s.openCluster)
  const consumedMinWheelRef = useRef(false)

  useEffect(() => onCount(total), [total, onCount])

  // Listen for the cross-section "fly to map cell" event the dashboard
  // dispatches when the user clicks a convergence alert (#145). Cheap
  // pub/sub pattern via CustomEvent — no shared store needed.
  useEffect(() => {
    if (!mapRef) return
    const handler = (ev: Event) => {
      const detail = (ev as CustomEvent).detail as
        | { lat?: number; lon?: number; zoom?: number }
        | undefined
      if (!detail || typeof detail.lat !== "number" || typeof detail.lon !== "number") return
      const map = mapRef.getMap()
      const target = typeof detail.zoom === "number" ? detail.zoom : 5
      map.flyTo({ center: [detail.lon, detail.lat], zoom: target, duration: 800 })
    }
    window.addEventListener("osint:flyto", handler)
    return () => window.removeEventListener("osint:flyto", handler)
  }, [mapRef])

  // Lift the country / state borders out of the near-black default so the
  // ground reads against the hillshade. The OpenFreeMap dark style ships them
  // at ~21-23% grey; bump to a legible mid-grey. Runs once the style is ready.
  useEffect(() => {
    if (!mapRef) return
    const map = mapRef.getMap()
    const brightenBorders = () => {
      for (const id of ["boundary_country_z0-4", "boundary_country_z5-"]) {
        if (map.getLayer(id)) map.setPaintProperty(id, "line-color", "hsl(0,0%,55%)")
      }
      if (map.getLayer("boundary_state")) {
        map.setPaintProperty("boundary_state", "line-color", "hsl(0,0%,40%)")
      }
    }
    if (map.isStyleLoaded()) brightenBorders()
    else map.once("load", brightenBorders)
  }, [mapRef])

  useEffect(() => {
    if (zoom > MIN_SCROLL_ZOOM + 0.01) {
      consumedMinWheelRef.current = false
    }
  }, [zoom])

  const mapStyle = useMemo(
    () => `${MAP_STYLE}${styleReloadToken > 0 ? `?v=${styleReloadToken}` : ""}`,
    [styleReloadToken],
  )

  const scheduleStyleRetry = useCallback(() => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current)
    }

    retryTimeoutRef.current = setTimeout(() => {
      setStyleReloadToken((token) => token + 1)
    }, MAP_STYLE_RETRY_MS)
  }, [])

  const handleMapError = useCallback((event: unknown) => {
    const e = event as { error?: { message?: string }; message?: string } | undefined
    const msg = (e?.error?.message || e?.message || "").toLowerCase()
    // Only a genuine style/tile *load* failure warrants a reload. Missing sprite
    // images (circle-11 / wood-pattern) are NOT load failures — they're handled
    // in-place via styleimagemissing below, so they must never reach here (#407).
    const shouldFallback =
      msg.includes("tiles.openfreemap.org") ||
      msg.includes("planet/")

    if (!shouldFallback) return
    scheduleStyleRetry()
  }, [scheduleStyleRetry])

  useEffect(() => {
    if (!mapRef) return
    const map = mapRef.getMap()

    // The dark style references sprite ids its sprite sheet doesn't ship, so
    // maplibre fires styleimagemissing constantly while panning/zooming. Answer
    // with a transparent placeholder — never a style reload (that flashed the
    // map black and looped forever, #407).
    const onStyleImageMissing = (evt: { id?: string }) => {
      addMissingStyleImagePlaceholder(map, evt?.id)
    }

    map.on("styleimagemissing", onStyleImageMissing)
    return () => {
      map.off("styleimagemissing", onStyleImageMissing)
    }
  }, [mapRef])

  const handleStyleLoad = () => {
    if (retryTimeoutRef.current) {
      clearTimeout(retryTimeoutRef.current)
      retryTimeoutRef.current = null
    }
  }

  useEffect(() => {
    return () => {
      if (retryTimeoutRef.current) clearTimeout(retryTimeoutRef.current)
    }
  }, [])

  const positioned = useMemo<Positioned[]>(() => {
    // Two buckets so the MAX_MARKERS budget never drops sparse-but-important
    // hazards. News / GDELT pour in continuously and used to fill the whole 700
    // budget (occurred_at-ordered), starving the handful of GDACS floods /
    // cyclones / quakes — the map showed only fire + quakes. Keep ALL
    // non-clusterable rows (hazards, quakes, market, EONET) and spend the cap
    // only on the clusterable firehose.
    const priority: Positioned[] = []
    const fill: Positioned[] = []
    for (const ev of events) {
      if (isWorldScopeNews(ev)) continue
      let lat = ev.lat
      let lon = ev.lon
      if (lat == null || lon == null) {
        // Skip the country-centroid fallback for clusterable rows whose
        // payload.news_scope is "world" or "unknown" (#166). Dawn / Geo
        // republish world news; stacking those at the PK centroid
        // produced the 92-row blob screenshotted on the issue. Local-only
        // news + non-news rows still get the centroid fallback so quakes /
        // fires / hazards stay visible.
        const p = (ev.payload ?? {}) as Record<string, unknown>
        const scope = typeof p?.news_scope === "string" ? (p.news_scope as string) : null
        const isWorldOrUnknownNews =
          isClusterable(ev) && scope !== "local" && (ev.source ?? "").startsWith("rss-")
        if (isWorldOrUnknownNews) continue
        if (ev.country) {
          const c = centroids.get(ev.country)
          if (c) {
            lon = c[0]
            lat = c[1]
          }
        }
      }
      if (lat == null || lon == null) continue
      ;(isClusterable(ev) ? fill : priority).push({ ev, lat, lon })
    }
    // All priority rows, then clusterable until the total budget is spent.
    return priority.concat(fill.slice(0, Math.max(0, MAX_MARKERS - priority.length)))
  }, [events, centroids])

  const worldAggregates = useMemo(
    () => worldNewsAggregates(events, centroids),
    [events, centroids],
  )

  /** Footprints for all hazards. Non-selected ones are revealed on zoom-in
   *  (opacity ramps 4→6); the SELECTED event's footprint is tagged `selected`
   *  so the paint keeps it full-opacity at every zoom — it must not fade away
   *  while its detail card is open, even fully zoomed out (#218). Cyclones also
   *  expand from track line to full cones when selected. */
  const { ambient: ambientHazardFootprints, selected: selectedHazardFootprints } = useMemo(
    () => hazardFootprintCollections(positioned, selectedEventId),
    [positioned, selectedEventId],
  )

  const hillshadeBeforeId = "waterway"

  /** Split into:
   *  - singles: rendered as individual EventMarker (hazards, market, plus any
   *    news/GDELT singleton in its own cell)
   *  - clusters: 2+ news/GDELT events sharing a quantised cell — rendered as
   *    a single count chip the user can click to expand.
   */
  const { singles, clusters } = useMemo(() => {
    const p = cellPrecision(zoom)
    const cells = new Map<string, Positioned[]>()
    const singlesOut: Positioned[] = []
    for (const item of positioned) {
      if (!isClusterable(item.ev)) {
        singlesOut.push(item)
        continue
      }
      const cellKey = `${Math.round(item.lat / p)}_${Math.round(item.lon / p)}`
      const bucket = cells.get(cellKey)
      if (bucket) bucket.push(item)
      else cells.set(cellKey, [item])
    }
    const clustersOut: ClusterMarker[] = []
    for (const [key, bucket] of cells.entries()) {
      if (bucket.length < 2) {
        // Singleton in the cell — render it as a normal small dot.
        singlesOut.push(bucket[0])
        continue
      }
      // Cluster centroid = mean of member coords; not great-circle accurate
      // but at 0.04-4° cell sizes the visual difference is negligible.
      let latSum = 0
      let lonSum = 0
      for (const it of bucket) {
        latSum += it.lat
        lonSum += it.lon
      }
      clustersOut.push({
        key,
        lat: latSum / bucket.length,
        lon: lonSum / bucket.length,
        events: bucket,
        color: colorForEvent(bucket[0].ev),
      })
    }
    return { singles: singlesOut, clusters: clustersOut }
  }, [positioned, zoom])

  const handleClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]
      const iso = feature?.properties?.__iso as string | undefined
      if (iso) onSelectCountry(iso)
    },
    [onSelectCountry],
  )

  const handleSelectMarker = useCallback(
    (ev: VisibleEvent) => {
      // Bubble up to the shared centred detail overlay (#207); the map no longer
      // renders its own popup. Selecting a cyclone also expands its footprint.
      onSelectEvent(ev)
    },
    [onSelectEvent],
  )

  /** Cluster click: open its event list in the right pane (#252) AND zoom in
   *  two levels at the centroid. The cell precision tightens (cellPrecision
   *  halves twice) so most clusters break apart into individual dots — while
   *  the right pane holds the full list for the ones that stay dense. */
  const handleClusterClick = useCallback(
    (c: ClusterMarker) => {
      openClusterInPane(
        c.events[0]?.ev.country ?? "cluster",
        c.events.map((p) => p.ev),
      )
      if (mapRef) {
        const map = mapRef.getMap()
        const target = Math.min(8, map.getZoom() + 2)
        map.flyTo({ center: [c.lon, c.lat], zoom: target, duration: 600 })
      }
    },
    [mapRef, openClusterInPane],
  )

  /** Country news pile ("world" scope RSS) → its list in the right pane. */
  const handleWorldAggregateClick = useCallback(
    (a: WorldNewsAggregate) => openClusterInPane(a.country, a.events),
    [openClusterInPane],
  )

  return (
    <div
        className="relative h-full w-full overflow-hidden bg-neutral-950"
        onWheelCapture={(e) => {
          const native = e.nativeEvent as WheelEvent
          if (native.cancelable === false) return
          if (e.deltaY < 0 && zoom <= MIN_SCROLL_ZOOM + 0.01) {
            if (!consumedMinWheelRef.current) {
              consumedMinWheelRef.current = true
              native.preventDefault()
              e.stopPropagation()
            }
          } else if (e.deltaY > 0) {
            consumedMinWheelRef.current = false
          }
      }}
    >
      <MapGL
        ref={setMapRef}
        mapStyle={mapStyle}
        initialViewState={{ longitude: 10, latitude: 25, zoom: INITIAL_ZOOM }}
        interactiveLayerIds={scoredGeo ? ["country-fill"] : []}
        onClick={handleClick}
        onLoad={handleStyleLoad}
        onMoveEnd={(e) => setZoom(e.viewState.zoom)}
        onError={handleMapError}
        attributionControl={false}
        dragRotate={false}
        style={{ position: "absolute", inset: 0 }}
      >
        {/* Terrain hillshade so quakes / hazards read against real ground —
            mountains, coastlines, relief — like the GDACS shakemap. Free AWS
            Terrarium DEM (no API key). Inserted before `waterway` (the first
            line layer) so borders + labels stay on top of the relief. */}
        <Source
          id="terrain-dem"
          type="raster-dem"
          tiles={["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"]}
          encoding="terrarium"
          tileSize={256}
          maxzoom={13}
        >
          <Layer
            id="hillshade"
            type="hillshade"
            beforeId={hillshadeBeforeId}
            paint={{
              // Punchy enough to read as real terrain on the near-black theme —
              // ridgelines/coast catch a warm-grey highlight, valleys go black.
              "hillshade-exaggeration": 0.95,
              "hillshade-shadow-color": "#000000",
              "hillshade-highlight-color": "#7a766b",
              "hillshade-accent-color": "#3a3a3a",
              "hillshade-illumination-direction": 315,
            }}
          />
        </Source>
        {/* Hazard footprints — revealed on zoom-in (opacity 0 at zoom 4 → full
            at zoom 6) so the world view stays clean pins. Burn scars / flood
            extent / shake rings / volcano zones; cyclones show only their track
            line (cones are minimised in footprintFeatures). Under the markers. */}
        <Source id="hazard-footprints" type="geojson" data={ambientHazardFootprints}>
          {/* Non-selected footprints — reveal on zoom-in (0 at z4 → full z6).
              Selected footprints use their own source later in the layer stack
              so country fills cannot cover the open detail footprint. */}
          <Layer
            id="hazard-footprint-fill"
            type="fill"
            paint={{
              "fill-color": ["get", "color"],
              "fill-opacity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                4,
                0,
                6,
                ["get", "fillOpacity"],
              ],
            }}
          />
          <Layer
            id="hazard-footprint-line"
            type="line"
            paint={{
              "line-color": ["get", "color"],
              "line-width": 1,
              "line-opacity": ["interpolate", ["linear"], ["zoom"], 4, 0, 6, 0.8],
            }}
          />
        </Source>
        {scoredGeo && (
          <Source id="countries" type="geojson" data={scoredGeo}>
            <Layer
              id="country-fill"
              type="fill"
              paint={{ "fill-color": ["get", "__fill"] }}
            />
            <Layer
              id="country-line"
              type="line"
              paint={{ "line-color": "rgba(120,120,120,0.25)", "line-width": 0.4 }}
            />
          </Source>
        )}
        {/* Selected event — rendered after country fill/lines and before
            markers, so real footprints stay visible while the detail card is
            open instead of being washed out by the choropleth layer. */}
        <Source id="hazard-footprints-selected" type="geojson" data={selectedHazardFootprints}>
          <Layer
            id="hazard-footprint-fill-selected"
            type="fill"
            paint={{
              "fill-color": ["get", "color"],
              "fill-opacity": ["get", "fillOpacity"],
            }}
          />
          <Layer
            id="hazard-footprint-line-selected"
            type="line"
            paint={{
              "line-color": ["get", "color"],
              "line-width": 1.2,
              "line-opacity": 0.85,
            }}
          />
        </Source>

        {singles.map(({ ev, lat, lon }) => (
          <EventMarker key={ev.id} ev={ev} lat={lat} lon={lon} onSelect={handleSelectMarker} />
        ))}
        {clusters.map((c) => (
          <ClusterChip key={c.key} cluster={c} onClick={handleClusterClick} />
        ))}
        {worldAggregates.map((aggregate) => (
          <WorldAggregateChip
            key={aggregate.country}
            aggregate={aggregate}
            onClick={handleWorldAggregateClick}
          />
        ))}
      </MapGL>

      {!configured && (
        <PaneStatus
          mode="error"
          message="Local API unreachable — start it at NEXT_PUBLIC_API_URL (default http://localhost:8000)."
        />
      )}
      {/* Live source-count chips (top-left). Mirror the satellite chip
       *  on the globe pane so the new source-expansion batch is visible
       *  on the map too. */}
      <div className="absolute left-3 top-3 z-30 flex flex-col gap-1">
        {(() => {
          const adsb = events.filter((e) => e.source === "opensky-adsb").length
          const cyber = events.filter((e) => e.source?.startsWith("abuse-ch-")).length
          const poly = events.filter((e) => e.source === "polymarket").length
          const chips: { label: string; n: number; color: string }[] = []
          if (adsb > 0) chips.push({ label: "ADS-B", n: adsb, color: "#06b6d4" })
          if (cyber > 0) chips.push({ label: "cyber", n: cyber, color: "#a855f7" })
          if (poly > 0) chips.push({ label: "markets", n: poly, color: "#10b981" })
          return chips.map((c) => (
            <div
              key={c.label}
              className="flex items-center gap-1.5 rounded-md border bg-neutral-950/80 px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest backdrop-blur-sm"
              style={{ borderColor: `${c.color}55`, color: c.color }}
            >
              <span
                className="inline-block h-1.5 w-1.5 rounded-full"
                style={{ backgroundColor: c.color }}
                aria-hidden="true"
              />
              {c.n.toLocaleString()} {c.label}
            </div>
          ))
        })()}
      </div>

      {configured && allEvents.length === 0 && <PaneStatus mode="loading" />}
      {configured && allEvents.length > 0 && positioned.length === 0 && (
        <PaneStatus mode="empty" onReset={() => useStore.getState().reset()} />
      )}

      {/* Source icons/toggles live in the left filter rail. */}
      <FilterRail side="left" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
