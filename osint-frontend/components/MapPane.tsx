"use client"

import "maplibre-gl/dist/maplibre-gl.css"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import MapGL, {
  Layer,
  Marker,
  Popup,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre"
import { AnimatePresence, motion } from "framer-motion"
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
import {
  isWorldScopeNews,
  worldNewsAggregates,
  type WorldNewsAggregate,
} from "@/lib/worldNewsAggregates"
import { colorForEvent } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
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
const FALLBACK_MAP_STYLE = {
  version: 8,
  name: "Fallback OSM",
  sources: {
    osm: {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      maxzoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    },
  },
  layers: [
    {
      id: "background",
      type: "background",
      paint: {
        "background-color": "#0b1120",
      },
    },
    {
      id: "osm-tiles",
      type: "raster",
      source: "osm",
    },
  ],
}
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

/** News + GDELT pile up at the same city centroid / city pinpoint. Those are
 *  the only sources we cluster. Earthquakes / fires / hazards / market stay
 *  individual — they're sparse enough that one dot per event reads fine. */
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
  // Force news / GDELT singletons to a small dot — they should never read as
  // "this place is on fire" when they're just one BBC headline.
  const clusterable = isClusterable(ev)
  const size = clusterable ? 4 : style.size
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
      <motion.div
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: ev.opacity }}
        exit={{ scale: 0.6, opacity: 0 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        style={{ width: HIT_SIZE, height: HIT_SIZE, cursor: "pointer" }}
        className="relative grid place-items-center"
      >
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
                  width: 18,
                  height: 18,
                  backgroundColor: color,
                  boxShadow: `0 0 4px ${color}aa`,
                  border: "1px solid rgba(255,255,255,0.5)",
                }}
              >
                <Icon size={12} color="#0a0a0a" strokeWidth={2.5} aria-hidden />
              </span>
            )
          }
          // non-hazard: keep the simple dot/diamond
          return (
            <span
              className="block"
              style={{
                width: size,
                height: size,
                backgroundColor: style.color,
                borderRadius: style.shape === "diamond" ? 2 : "9999px",
                transform: style.shape === "diamond" ? "rotate(45deg)" : undefined,
                boxShadow: `0 0 3px ${style.color}`,
              }}
            />
          )
        })()}
      </motion.div>
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
  // log10 scaling — 2 events → ~18 px, 10 → 22 px, 100 → 28 px. Min 18
  // so a 2-digit value never gets clipped. See #135.
  const size = Math.min(30, 18 + Math.log10(Math.max(2, n)) * 5)
  // Font sized off the chip size so the digit is always optically
  // centred. Cap at 12 px so 3-digit "99+" still fits.
  const fontSize = Math.min(12, Math.max(9, size * 0.45))
  return (
    <Marker longitude={cluster.lon} latitude={cluster.lat} anchor="center">
      <motion.button
        type="button"
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.6, opacity: 0 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
        onClick={(e) => {
          e.stopPropagation()
          onClick(cluster)
        }}
        className="rounded-full font-mono font-semibold tabular-nums text-neutral-950"
        style={{
          width: size,
          height: size,
          backgroundColor: cluster.color,
          boxShadow: `0 0 6px ${cluster.color}`,
          border: "1px solid rgba(255,255,255,0.4)",
          cursor: "pointer",
          // Explicit flex centre + line-height 1 so the digit is dead-centre
          // regardless of font-rendering quirks across browsers.
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          lineHeight: 1,
          padding: 0,
          fontSize: `${fontSize}px`,
        }}
        aria-label={`${n} events clustered`}
      >
        {n < 100 ? n : "99+"}
      </motion.button>
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
  const size = Math.min(34, 18 + Math.log10(Math.max(2, n)) * 6)
  const fontSize = Math.min(12, Math.max(9, size * 0.42))
  return (
    <Marker longitude={aggregate.lon} latitude={aggregate.lat} anchor="center">
      <motion.button
        type="button"
        initial={{ scale: 0.6, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.6, opacity: 0 }}
        transition={{ duration: 0.2, ease: "easeOut" }}
        onClick={(e) => {
          e.stopPropagation()
          onClick(aggregate)
        }}
        className="rounded-md font-mono font-semibold tabular-nums text-neutral-100"
        style={{
          width: size,
          height: size,
          backgroundColor: "rgba(51,65,85,0.9)",
          boxShadow: "0 0 7px rgba(148,163,184,0.65)",
          border: "1px solid rgba(203,213,225,0.55)",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          lineHeight: 1,
          padding: 0,
          fontSize: `${fontSize}px`,
        }}
        aria-label={`${n} world news events in ${aggregate.country}`}
      >
        {n < 100 ? n : "99+"}
      </motion.button>
    </Marker>
  )
}

export function MapPane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount, onSelectEvent, selectedEventId }: MapPaneProps) {
  const { events, windowEnd, total } = useEventsInWindow(useStore, "map")
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [mapStyle, setMapStyle] = useState<string | (typeof FALLBACK_MAP_STYLE)>(MAP_STYLE)
  const [mapStyleError, setMapStyleError] = useState(false)
  const [zoom, setZoom] = useState<number>(INITIAL_ZOOM)
  const [openCluster, setOpenCluster] = useState<ClusterMarker | null>(null)
  const [openWorldAggregate, setOpenWorldAggregate] = useState<WorldNewsAggregate | null>(null)
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

  const handleMapError = useCallback((event: unknown) => {
    const e = event as { error?: { message?: string }; message?: string } | undefined
    const msg = (e?.error?.message || e?.message || "").toLowerCase()
    const shouldFallback =
      msg.includes("tiles.openfreemap.org") ||
      msg.includes("planet/") ||
      msg.includes("circle-11") ||
      msg.includes("wood-pattern")

    if (!mapStyleError && mapStyle === MAP_STYLE && shouldFallback) {
      setMapStyleError(true)
      setMapStyle(FALLBACK_MAP_STYLE)
    }
  }, [mapStyle, mapStyleError])

  useEffect(() => {
    if (!mapRef) return
    const map = mapRef.getMap()

    const onStyleImageMissing = (evt: { id?: string }) => {
      const id = evt?.id ?? ""
      if (mapStyleError) return
      if (id === "circle-11" || id === "wood-pattern") {
        setMapStyleError(true)
        setMapStyle(FALLBACK_MAP_STYLE)
      }
    }

    map.on("styleimagemissing", onStyleImageMissing)
    return () => {
      map.off("styleimagemissing", onStyleImageMissing)
    }
  }, [mapRef, mapStyleError])

  useEffect(() => {
    if (!openCluster && !openWorldAggregate) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return
      if (openCluster) setOpenCluster(null)
      if (openWorldAggregate) setOpenWorldAggregate(null)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [openCluster, openWorldAggregate])

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

  /** Cluster click: zoom in two levels at the centroid. The cell precision
   *  tightens (cellPrecision halves twice) so most clusters break apart
   *  into individual dots — which is the behaviour the user asked for.
   *  Also open a popup listing the first few events so the click feels
   *  like it did something even before the camera arrives. */
  const handleClusterClick = useCallback(
    (c: ClusterMarker) => {
      setOpenCluster(c)
      if (mapRef) {
        const map = mapRef.getMap()
        const target = Math.min(8, map.getZoom() + 2)
        map.flyTo({ center: [c.lon, c.lat], zoom: target, duration: 600 })
      }
    },
    [mapRef],
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
            beforeId="waterway"
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

        <AnimatePresence>
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
              onClick={setOpenWorldAggregate}
            />
          ))}
        </AnimatePresence>


        {openCluster && (
          <Popup
            longitude={openCluster.lon}
            latitude={openCluster.lat}
            anchor="bottom"
            closeButton={false}
            closeOnClick={false}
            onClose={() => setOpenCluster(null)}
            offset={16}
            maxWidth="320px"
            className="osint-popup"
          >
            <div className="w-72 rounded-md border border-neutral-700 bg-neutral-950/95 p-2 backdrop-blur-md">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase tracking-widest text-neutral-400">
                  {openCluster.events.length} events here
                </span>
                <button
                  type="button"
                  aria-label="Close"
                  onClick={() => setOpenCluster(null)}
                  className="font-mono text-[10px] text-neutral-500 hover:text-neutral-200"
                >
                  close
                </button>
              </div>
              <ul className="max-h-56 overflow-y-auto pr-1">
                {openCluster.events.slice(0, 12).map(({ ev }) => {
                  const p = (ev.payload ?? {}) as Record<string, unknown>
                  const title =
                    (typeof p?.title === "string" && p.title) ||
                    (typeof p?.headline === "string" && p.headline) ||
                    ev.source
                  return (
                    <li key={ev.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setOpenCluster(null)
                          handleSelectMarker(ev)
                        }}
                        className="block w-full truncate rounded px-2 py-1 text-left text-[11px] text-neutral-200 hover:bg-neutral-900"
                      >
                        <span className="mr-1 font-mono text-[10px] text-neutral-500">
                          {ev.source.replace(/^rss-/, "")}
                        </span>
                        {title as string}
                      </button>
                    </li>
                  )
                })}
              </ul>
              {openCluster.events.length > 12 && (
                <p className="mt-1 px-2 font-mono text-[10px] text-neutral-600">
                  +{openCluster.events.length - 12} more · zoom in to separate
                </p>
              )}
            </div>
          </Popup>
        )}

        {openWorldAggregate && (
          <Popup
            longitude={openWorldAggregate.lon}
            latitude={openWorldAggregate.lat}
            anchor="bottom"
            closeButton={false}
            closeOnClick={false}
            onClose={() => setOpenWorldAggregate(null)}
            offset={16}
            maxWidth="320px"
            className="osint-popup"
          >
            <div className="w-72 rounded-md border border-slate-700 bg-neutral-950/95 p-2 backdrop-blur-md">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-mono text-[10px] uppercase tracking-widest text-slate-300">
                  {openWorldAggregate.events.length} world news · {openWorldAggregate.country}
                </span>
                <button
                  type="button"
                  aria-label="Close"
                  onClick={() => setOpenWorldAggregate(null)}
                  className="font-mono text-[10px] text-neutral-500 hover:text-neutral-200"
                >
                  close
                </button>
              </div>
              <ul className="max-h-56 overflow-y-auto pr-1">
                {openWorldAggregate.events.slice(0, 12).map((ev) => {
                  const p = (ev.payload ?? {}) as Record<string, unknown>
                  const title =
                    (typeof p?.title === "string" && p.title) ||
                    (typeof p?.headline === "string" && p.headline) ||
                    ev.source
                  return (
                    <li key={ev.id}>
                      <button
                        type="button"
                        onClick={() => {
                          setOpenWorldAggregate(null)
                          handleSelectMarker(ev)
                        }}
                        className="block w-full truncate rounded px-2 py-1 text-left text-[11px] text-neutral-200 hover:bg-neutral-900"
                      >
                        <span className="mr-1 font-mono text-[10px] text-neutral-500">
                          {ev.source.replace(/^rss-/, "")}
                        </span>
                        {title as string}
                      </button>
                    </li>
                  )
                })}
              </ul>
              {openWorldAggregate.events.length > 12 && (
                <p className="mt-1 px-2 font-mono text-[10px] text-neutral-600">
                  +{openWorldAggregate.events.length - 12} more
                </p>
              )}
            </div>
          </Popup>
        )}
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

      {/* The marker legend moved into the left filter rail (icons + colours +
          toggles) so it is interactive, not a static key in the corner. */}

      <FilterRail pane="map" side="left" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
