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
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl"
import { Activity, Droplets, Flame, Snowflake, Sun, Triangle, Wind } from "lucide-react"
import { useConfigured, useEvents } from "@/app/providers"
import { fetchAllEventPages, fetchAllUpdatedEventPages } from "@/lib/apiClient"
import { mergeEventRows } from "@/lib/eventMerge"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import {
  hazardColor,
  hazardIcon,
  hazardKind,
  type HazardIcon,
} from "@/lib/hazardSymbols"
import { hazardFootprintCollections } from "@/lib/mapFootprints"
import {
  eventPointCollection,
  positionsForEvent,
  type PositionedMapEvent,
} from "@/lib/mapPositioning"
import { addMissingStyleImagePlaceholder } from "@/lib/mapStyleImages"
import type { EventRow } from "@/lib/types"
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
const INITIAL_ZOOM = 1.4
const MIN_SCROLL_ZOOM = INITIAL_ZOOM
const COMPLETE_VIEWPORT_ZOOM = 8
const PLAYBACK_VIEWPORT_SYNC_MS = 2_000
const IDLE_VIEWPORT_SYNC_MS = 30_000
const EVENT_SOURCE_ID = "place-backed-events"
const EVENT_CLUSTER_LAYER_ID = "place-event-clusters"
const EVENT_CLUSTER_COUNT_LAYER_ID = "place-event-cluster-count"
const EVENT_POINT_LAYER_ID = "place-event-points"
const EMPTY_VIEWPORT_EVENTS: EventRow[] = []
const NON_MAP_VIEWPORT_SOURCES = ["opensky-adsb", "nasa-firms"]

interface MapPaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onSelectCountry: (iso: string) => void
  onCount: (n: number) => void
  /** Bubble a clicked event up to the shared centred detail overlay. */
  onSelectEvent: (ev: VisibleEvent, location?: MarkerLocationContext) => void
  /** Id of the currently-selected event (drives the expanded cyclone footprint). */
  selectedEventId: VisibleEvent["id"] | null
}

interface ViewportBounds {
  west: number
  south: number
  east: number
  north: number
}

interface ViewportSnapshot {
  key: string
  scopeKey: string
  windowEnd: number
  windowOffsetMs: number
  revisionSince: string
  events: EventRow[]
}

/** Sources dense enough to use MapLibre's lossless clustered GeoJSON layer.
 * Sparse hazards stay independent with their own icon and footprint. NASA
 * FIRMS never reaches this map since #494; its fires are GDACS/EONET alerts. */
function isClusterable(ev: VisibleEvent): boolean {
  const source = (ev.source ?? "").toLowerCase()
  if (ev.category === "news") return true
  if (source.startsWith("rss-")) return true
  if (source === "uk-police") return true
  if (source === "gdelt") return true
  return false
}

function EventMarker({
  ev,
  lat,
  lon,
  location,
  onSelect,
}: {
  ev: VisibleEvent
  lat: number
  lon: number
  location?: MarkerLocationContext
  onSelect: (ev: VisibleEvent, location?: MarkerLocationContext) => void
}) {
  const style = markerStyle(ev)
  const size = style.size
  const HIT_SIZE = 28

  return (
    <Marker
      longitude={lon}
      latitude={lat}
      anchor="center"
      onClick={(e) => {
        e.originalEvent.stopPropagation()
        onSelect(ev, location)
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
          if (iconKey !== "dot" && ev.source !== "nasa-firms") {
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
          // Non-hazard independent rows keep their crisp dot/diamond mark.
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
      </div>
    </Marker>
  )
}

export function MapPane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount, onSelectEvent, selectedEventId }: MapPaneProps) {
  const windowLengthMs = useStore((s) => s.windowLengthMs)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const playing = useStore((s) => s.playing)
  const [viewport, setViewport] = useState<ViewportBounds | null>(null)
  const [zoom, setZoom] = useState<number>(INITIAL_ZOOM)
  const [viewportSnapshot, setViewportSnapshot] = useState<ViewportSnapshot | null>(null)
  const viewportSnapshotRef = useRef<ViewportSnapshot | null>(null)
  const [viewportErrorKey, setViewportErrorKey] = useState<string | null>(null)
  const [settledWindowOffsetMs, setSettledWindowOffsetMs] = useState(windowEndOffsetMs)
  const [viewportSyncTick, setViewportSyncTick] = useState(0)
  const windowEndOffsetRef = useRef(windowEndOffsetMs)
  const viewportRequestRef = useRef<AbortController | null>(null)
  const viewportEnabled = zoom >= COMPLETE_VIEWPORT_ZOOM && viewport !== null
  const viewportScopeKey =
    viewportEnabled && viewport
      ? JSON.stringify([
          viewport.west,
          viewport.south,
          viewport.east,
          viewport.north,
          windowLengthMs,
        ])
      : null
  const viewportQueryKey =
    viewportScopeKey
      ? JSON.stringify([viewportScopeKey, settledWindowOffsetMs, viewportSyncTick])
      : null
  const snapshotMatchesWindow =
    viewportScopeKey !== null &&
    viewportSnapshot?.scopeKey === viewportScopeKey &&
    (viewportSnapshot.windowOffsetMs === settledWindowOffsetMs ||
      (playing &&
        Math.abs(viewportSnapshot.windowOffsetMs - settledWindowOffsetMs) < windowLengthMs))
  const activeViewportEvents =
    snapshotMatchesWindow
      ? viewportSnapshot.events
      : EMPTY_VIEWPORT_EVENTS
  const viewportLoading =
    viewportScopeKey !== null &&
    !snapshotMatchesWindow &&
    viewportErrorKey !== viewportQueryKey
  const viewportFailed = viewportQueryKey !== null && viewportErrorKey === viewportQueryKey
  const { events, windowEnd, total } = useEventsInWindow(useStore, activeViewportEvents)
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [styleReloadToken, setStyleReloadToken] = useState(0)
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const openClusterInPane = useRightPaneModeStore((s) => s.openCluster)
  const consumedMinWheelRef = useRef(false)

  useEffect(() => {
    windowEndOffsetRef.current = windowEndOffsetMs
    if (playing) return
    const timeout = window.setTimeout(() => {
      setSettledWindowOffsetMs(windowEndOffsetMs)
    }, 500)
    return () => window.clearTimeout(timeout)
  }, [playing, windowEndOffsetMs])

  useEffect(() => {
    if (!viewportEnabled) return
    const interval = window.setInterval(() => {
      // Dense viewports can need several pages. Let that snapshot complete;
      // the next tick catches up from the latest raw playback offset.
      if (viewportRequestRef.current) return
      setSettledWindowOffsetMs(windowEndOffsetRef.current)
      setViewportSyncTick((tick) => (tick + 1) % 1_000_000)
    }, playing ? PLAYBACK_VIEWPORT_SYNC_MS : IDLE_VIEWPORT_SYNC_MS)
    return () => window.clearInterval(interval)
  }, [playing, viewportEnabled])

  useEffect(() => {
    if (!viewportEnabled || !viewport || !viewportScopeKey || !viewportQueryKey) return

    const load = async () => {
      const requestController = new AbortController()
      viewportRequestRef.current = requestController
      const requestKey = viewportQueryKey
      const requestStartedAt = new Date().toISOString()
      const windowEnd = Date.now() - settledWindowOffsetMs
      const windowStart = windowEnd - windowLengthMs
      const previous = viewportSnapshotRef.current
      const canAppend =
        previous?.scopeKey === viewportScopeKey &&
        previous.windowEnd < windowEnd &&
        previous.windowEnd >= windowStart
      const since = canAppend ? previous.windowEnd : windowStart
      try {
        const boundedQuery = {
          until: new Date(windowEnd).toISOString(),
          west: viewport.west,
          south: viewport.south,
          east: viewport.east,
          north: viewport.north,
          positionedOnly: true,
          exclude: NON_MAP_VIEWPORT_SOURCES,
        }
        const [rows, revisedRows] = await Promise.all([
          fetchAllEventPages(
            { ...boundedQuery, since: new Date(since).toISOString() },
            2000,
            { signal: requestController.signal },
          ),
          previous?.scopeKey === viewportScopeKey
            ? fetchAllUpdatedEventPages(
                { ...boundedQuery, since: new Date(windowStart).toISOString() },
                previous.revisionSince,
                2000,
                { signal: requestController.signal },
              )
            : Promise.resolve([]),
        ])
        if (requestController.signal.aborted) return
        const incomingRows = mergeEventRows(rows, revisedRows)
        const snapshot: ViewportSnapshot = {
          key: requestKey,
          scopeKey: viewportScopeKey,
          windowEnd,
          windowOffsetMs: settledWindowOffsetMs,
          revisionSince: requestStartedAt,
          events: canAppend
            ? mergeEventRows(previous.events, incomingRows).filter((row) => {
                const occurredAt = new Date(row.occurred_at).getTime()
                return occurredAt >= windowStart && occurredAt <= windowEnd
              })
            : incomingRows,
        }
        viewportSnapshotRef.current = snapshot
        setViewportSnapshot(snapshot)
        setViewportErrorKey(null)
      } catch (error) {
        if (requestController.signal.aborted) return
        if (error instanceof DOMException && error.name === "AbortError") return
        setViewportErrorKey(requestKey)
      } finally {
        if (viewportRequestRef.current === requestController) {
          viewportRequestRef.current = null
        }
      }
    }

    void load()
    return () => {
      const requestController = viewportRequestRef.current
      requestController?.abort()
      if (viewportRequestRef.current === requestController) {
        viewportRequestRef.current = null
      }
    }
  }, [
    viewportEnabled,
    viewport,
    viewportScopeKey,
    windowLengthMs,
    settledWindowOffsetMs,
    viewportQueryKey,
  ])

  const captureViewport = useCallback((map: MapLibreMap) => {
    const bounds = map.getBounds()
    const rounded = (value: number) => Number(value.toFixed(5))
    const normalizedLongitude = (value: number) =>
      ((value + 180) % 360 + 360) % 360 - 180
    setViewport({
      west: rounded(normalizedLongitude(bounds.getWest())),
      south: rounded(Math.max(-90, bounds.getSouth())),
      east: rounded(normalizedLongitude(bounds.getEast())),
      north: rounded(Math.min(90, bounds.getNorth())),
    })
  }, [])

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

  const positioned = useMemo<PositionedMapEvent[]>(() => {
    const out: PositionedMapEvent[] = []
    for (const ev of events) {
      // A news dot is a place; an unplaceable story gets no dot and stays
      // reachable by clicking its country. Hazards keep the country-centroid
      // fallback. See lib/mapPositioning.ts for why (#717).
      for (const at of positionsForEvent(ev, centroids)) {
        out.push({
          ev,
          markerKey: at.key,
          lat: at.lat,
          lon: at.lon,
          place: at.place,
          location: at.location,
        })
      }
    }
    return out
  }, [events, centroids])

  const { independent, clusteredByKey, clusteredData } = useMemo(() => {
    const independentRows: PositionedMapEvent[] = []
    const clusteredRows: PositionedMapEvent[] = []
    const byKey = new Map<string, PositionedMapEvent>()
    for (const item of positioned) {
      if (isClusterable(item.ev)) {
        clusteredRows.push(item)
        byKey.set(item.markerKey, item)
      } else {
        independentRows.push(item)
      }
    }
    return {
      independent: independentRows,
      clusteredByKey: byKey,
      clusteredData: eventPointCollection(clusteredRows),
    }
  }, [positioned])

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

  const handleSelectMarker = useCallback(
    (ev: VisibleEvent, location?: MarkerLocationContext) => {
      // Bubble up to the shared centred detail overlay (#207); the map no longer
      // renders its own popup. Selecting a cyclone also expands its footprint.
      onSelectEvent(ev, location)
    },
    [onSelectEvent],
  )

  /** Cluster click: expose every unique story in the worker-owned cluster and
   *  zoom inward. MapLibre keeps every original coordinate in the source, so
   *  zooming refines the visual grouping instead of selecting another sample. */
  const handleClusterClick = useCallback(
    (positions: PositionedMapEvent[], lon: number, lat: number) => {
      const byEvent = new Map<VisibleEvent["id"], { event: VisibleEvent; location?: MarkerLocationContext }>()
      for (const position of positions) {
        const id = position.ev.id
        if (!byEvent.has(id)) {
          byEvent.set(id, { event: position.ev, location: position.location })
          continue
        }
        byEvent.set(id, {
          event: position.ev,
          location: {
            name: "Multiple verified places",
            precision: "unknown",
            source: "multiple-marker-cluster",
          },
        })
      }
      const uniqueSelections = [...byEvent.values()]
      openClusterInPane(positions[0]?.ev.country ?? "cluster", uniqueSelections)
      if (mapRef) {
        const map = mapRef.getMap()
        // Supercluster emits individual leaves one zoom above clusterMaxZoom.
        // Keep the click path able to reach that level so a dense street or
        // building cluster can always resolve to its exact source points.
        const target = Math.min(21, map.getZoom() + 2)
        map.flyTo({ center: [lon, lat], zoom: target, duration: 600 })
      }
    },
    [mapRef, openClusterInPane],
  )

  const handleClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]
      if (!feature) return

      if (feature.layer.id === EVENT_POINT_LAYER_ID) {
        const markerKey = feature.properties?.markerKey
        if (typeof markerKey !== "string") return
        const item = clusteredByKey.get(markerKey)
        if (item) handleSelectMarker(item.ev, item.location)
        return
      }

      if (feature.layer.id === EVENT_CLUSTER_LAYER_ID && mapRef) {
        const clusterId = Number(feature.properties?.cluster_id)
        const pointCount = Number(feature.properties?.point_count)
        const coordinates = feature.geometry.type === "Point" ? feature.geometry.coordinates : null
        if (!Number.isFinite(clusterId) || !Number.isFinite(pointCount) || !coordinates) return
        const source = mapRef.getMap().getSource(EVENT_SOURCE_ID) as GeoJSONSource | undefined
        if (!source?.getClusterLeaves) return
        void source
          .getClusterLeaves(clusterId, pointCount, 0)
          .then((leaves) => {
            const members: PositionedMapEvent[] = []
            for (const leaf of leaves) {
              const markerKey = leaf.properties?.markerKey
              if (typeof markerKey !== "string") continue
              const item = clusteredByKey.get(markerKey)
              if (item) members.push(item)
            }
            if (members.length > 0) {
              handleClusterClick(members, Number(coordinates[0]), Number(coordinates[1]))
            }
          })
          .catch(() => undefined)
        return
      }

      const iso = feature.properties?.__iso
      if (typeof iso === "string") onSelectCountry(iso)
    },
    [clusteredByKey, handleClusterClick, handleSelectMarker, mapRef, onSelectCountry],
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
        interactiveLayerIds={[
          EVENT_CLUSTER_LAYER_ID,
          EVENT_POINT_LAYER_ID,
          ...(scoredGeo ? ["country-fill"] : []),
        ]}
        onClick={handleClick}
        onLoad={(e) => {
          handleStyleLoad()
          captureViewport(e.target)
        }}
        onMoveEnd={(e) => {
          setZoom(e.viewState.zoom)
          captureViewport(e.target)
        }}
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

        {/* News/GDELT density is handled inside MapLibre's worker. Every valid
            position in the active client event window enters the source;
            clustering changes only presentation, never membership. */}
        <Source
          id={EVENT_SOURCE_ID}
          type="geojson"
          data={clusteredData}
          cluster
          maxzoom={22}
          clusterMaxZoom={20}
          clusterRadius={38}
        >
          <Layer
            id={EVENT_CLUSTER_LAYER_ID}
            type="circle"
            filter={["has", "point_count"]}
            paint={{
              "circle-color": "rgba(96, 165, 250, 0.35)",
              "circle-stroke-color": "rgba(147, 197, 253, 0.9)",
              "circle-stroke-width": 1,
              "circle-radius": [
                "step",
                ["get", "point_count"],
                7,
                10,
                10,
                50,
                14,
                250,
                19,
                1000,
                25,
                5000,
                32,
              ],
            }}
          />
          <Layer
            id={EVENT_CLUSTER_COUNT_LAYER_ID}
            type="symbol"
            filter={["has", "point_count"]}
            layout={{
              "text-field": ["get", "point_count_abbreviated"],
              "text-size": 10,
            }}
            paint={{ "text-color": "#e5f2ff" }}
          />
          <Layer
            id={EVENT_POINT_LAYER_ID}
            type="circle"
            filter={["!", ["has", "point_count"]]}
            paint={{
              "circle-color": ["get", "color"],
              "circle-opacity": ["coalesce", ["get", "opacity"], 1],
              "circle-radius": 4,
              "circle-stroke-color": ["get", "color"],
              "circle-stroke-width": 1,
            }}
          />
        </Source>

        {independent.map(({ ev, markerKey, lat, lon, location }) => (
          <EventMarker
            key={markerKey}
            ev={ev}
            lat={lat}
            lon={lon}
            location={location}
            onSelect={handleSelectMarker}
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
      {configured && viewportLoading && (
        <PaneStatus mode="loading" message="Loading complete viewport…" />
      )}
      {configured && viewportFailed && (
        <PaneStatus
          mode="error"
          message="Viewport refresh failed. Showing last complete snapshot; move map to retry."
        />
      )}
      {configured && allEvents.length > 0 && positioned.length === 0 && (
        <PaneStatus mode="empty" onReset={() => useStore.getState().reset()} />
      )}

      {/* Source icons/toggles live in the filter rail, docked right — the
       *  left edge belongs to the floating deck and detail panels (#503). */}
      <FilterRail
        side="right"
        useStore={useStore}
        open={railOpen}
        onOpenChange={onRailOpenChange}
        supplementalEvents={activeViewportEvents}
      />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
