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
import { circlePolygon } from "@/lib/footprints"
import { PRECISION_OPACITY, PRECISION_RADIUS_PX } from "@/lib/precision"
import {
  consensusLocalPlaceName,
  coordinateLabel,
  distanceKm,
  localEventSelections,
  localMapLabel,
  localSelectionBounds,
  localSelectionRadiusKm,
} from "@/lib/localMapSelection"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import { usePlaceStore } from "@/stores/placeStore"
import { useImageryStore } from "@/stores/imageryStore"
import { usePresenceStore } from "@/stores/presenceStore"
import {
  PRESENCE_POLL_MS,
  shouldPoll,
  type PresenceAircraft,
} from "@/lib/presence"
import { fetchPresenceAircraft } from "@/lib/apiClient"
import { imageryDate, imageryLayer, imageryTiles } from "@/lib/imageryLayers"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import {
  hazardColor,
  hazardIcon,
  hazardKind,
  type HazardIcon,
} from "@/lib/hazardSymbols"
import {
  ambientFootprints,
  focusLayerOpacity,
  focusOpacity,
  focusable,
} from "@/lib/mapFocus"
import { hazardFootprintCollections } from "@/lib/mapFootprints"
import {
  eventPointCollection,
  positionsForEvent,
  type PositionedMapEvent,
} from "@/lib/mapPositioning"
import { addMissingStyleImagePlaceholder } from "@/lib/mapStyleImages"
import type { EventRow } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { useMapFocusStore } from "@/stores/mapFocusStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { FilterRail } from "./FilterRail"
import { PaneStatus } from "./PaneStatus"
import { filtersAreNarrowed } from "@/lib/filterExclusions"
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
//: Compared against a parsed hostname, never matched as a substring of a URL.
const MAP_STYLE_HOST = "tiles.openfreemap.org"
const IMAGERY_HOST = "gibs.earthdata.nasa.gov"
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
  /** Phone layout (#942): the two controls docked to the map's own edges —
   *  the filter rail and the time scrubber — stop short of the sheet along
   *  the bottom and grow thumb-sized handles. */
  narrow?: boolean
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onCount: (n: number) => void
  onOpenSelection: () => void
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

interface AreaSnapshot {
  scopeKey: string
  windowLengthMs: number
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
  focusActive,
  isFocused,
}: {
  ev: VisibleEvent
  lat: number
  lon: number
  location?: MarkerLocationContext
  onSelect: (ev: VisibleEvent, location?: MarkerLocationContext) => void
  /** True while some hazard holds the map's focus. */
  focusActive: boolean
  /** True when this marker is the one holding it. */
  isFocused: boolean
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
        style={{
          width: HIT_SIZE,
          height: HIT_SIZE,
          cursor: "pointer",
          opacity: focusOpacity(ev.opacity, focusActive, isFocused),
        }}
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

export function MapPane({
  useStore,
  narrow = false,
  railOpen,
  onRailOpenChange,
  onCount,
  onOpenSelection,
  onSelectEvent,
  selectedEventId,
}: MapPaneProps) {
  const windowLengthMs = useStore((s) => s.windowLengthMs)
  const windowEndOffsetMs = useStore((s) => s.windowEndOffsetMs)
  const playing = useStore((s) => s.playing)
  //: Read only to tell "the map is empty because it was asked to be" from "the
  //: map is empty and nobody asked" — the two look identical on screen.
  const filterSources = useStore((s) => s.sources)
  const filterHazardTypes = useStore((s) => s.hazardTypes)
  const filterSeverity = useStore((s) => s.severity)
  const filtersNarrowed = useMemo(
    () =>
      filtersAreNarrowed({
        sources: filterSources,
        hazardTypes: filterHazardTypes,
        severity: filterSeverity,
      }),
    [filterSources, filterHazardTypes, filterSeverity],
  )
  const [viewport, setViewport] = useState<ViewportBounds | null>(null)
  const [zoom, setZoom] = useState<number>(INITIAL_ZOOM)
  const [viewportSnapshot, setViewportSnapshot] = useState<ViewportSnapshot | null>(null)
  const viewportSnapshotRef = useRef<ViewportSnapshot | null>(null)
  const [viewportErrorKey, setViewportErrorKey] = useState<string | null>(null)
  const [settledWindowOffsetMs, setSettledWindowOffsetMs] = useState(windowEndOffsetMs)

  //: The backdrop's day is the scrubber's day, so the two never disagree.
  const activeImageryId = useImageryStore((s) => s.active)
  const setImageryMissing = useImageryStore((s) => s.setMissing)
  const activeImagery = activeImageryId ? imageryLayer(activeImageryId) : null
  const imageryDay = imageryDate(Date.now() - settledWindowOffsetMs)
  const imageryTileUrls = useMemo(
    () => (activeImageryId ? imageryTiles(activeImageryId, imageryDay) : null),
    [activeImageryId, imageryDay],
  )

  //: A new day, or a different layer, deserves a fresh verdict on whether the
  //: publisher has anything for it. Without this the map keeps reporting a gap
  //: that belonged to the day before.
  useEffect(() => {
    setImageryMissing(false)
  }, [activeImageryId, imageryDay, setImageryMissing])
  const [viewportSyncTick, setViewportSyncTick] = useState(0)
  const [areaSyncTick, setAreaSyncTick] = useState(0)
  const windowEndOffsetRef = useRef(windowEndOffsetMs)
  const viewportRequestRef = useRef<AbortController | null>(null)
  const areaRequestRef = useRef<AbortController | null>(null)
  const selectedArea = useRightPaneModeStore((s) =>
    s.entity?.kind === "area" ? s.entity : null,
  )
  const selectedAreaLat = selectedArea?.lat
  const selectedAreaLon = selectedArea?.lon
  const selectedAreaRadiusKm = selectedArea?.radiusKm
  const areaScopeKey =
    typeof selectedAreaLat === "number" &&
    typeof selectedAreaLon === "number" &&
    typeof selectedAreaRadiusKm === "number"
      ? JSON.stringify([selectedAreaLat, selectedAreaLon, selectedAreaRadiusKm])
      : null
  const [areaSnapshot, setAreaSnapshot] = useState<AreaSnapshot | null>(null)
  const areaSnapshotRef = useRef<AreaSnapshot | null>(null)
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
  const areaSnapshotReady =
    areaScopeKey !== null &&
    areaSnapshot?.scopeKey === areaScopeKey &&
    areaSnapshot.windowLengthMs === windowLengthMs &&
    (areaSnapshot.windowOffsetMs === settledWindowOffsetMs ||
      (playing &&
        Math.abs(areaSnapshot.windowOffsetMs - settledWindowOffsetMs) < windowLengthMs))
  const activeAreaEvents = areaSnapshotReady
    ? areaSnapshot.events
    : EMPTY_VIEWPORT_EVENTS
  const supplementalEvents = useMemo(
    () => mergeEventRows(activeViewportEvents, activeAreaEvents),
    [activeAreaEvents, activeViewportEvents],
  )
  const viewportLoading =
    viewportScopeKey !== null &&
    !snapshotMatchesWindow &&
    viewportErrorKey !== viewportQueryKey
  const viewportFailed = viewportQueryKey !== null && viewportErrorKey === viewportQueryKey
  const { events, windowEnd, total } = useEventsInWindow(useStore, supplementalEvents)
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [styleReloadToken, setStyleReloadToken] = useState(0)
  const retryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const openClusterInPane = useRightPaneModeStore((s) => s.openCluster)
  const openAreaInPane = useRightPaneModeStore((s) => s.openArea)
  const updateAreaSelections = useRightPaneModeStore((s) => s.updateAreaSelections)
  const setAreaDataState = useRightPaneModeStore((s) => s.setAreaDataState)
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
    if (!areaScopeKey) return
    const interval = window.setInterval(() => {
      // Local selections remain live even after the operator zooms or pans
      // away from the detailed viewport that originally opened them.
      if (areaRequestRef.current) return
      setSettledWindowOffsetMs(windowEndOffsetRef.current)
      setAreaSyncTick((tick) => (tick + 1) % 1_000_000)
    }, playing ? PLAYBACK_VIEWPORT_SYNC_MS : IDLE_VIEWPORT_SYNC_MS)
    return () => window.clearInterval(interval)
  }, [areaScopeKey, playing])

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

  // A selected place owns its own complete bbox snapshot. It must not lose
  // events when the operator pans elsewhere and the viewport snapshot changes.
  useEffect(() => {
    if (
      !areaScopeKey ||
      typeof selectedAreaLat !== "number" ||
      typeof selectedAreaLon !== "number" ||
      typeof selectedAreaRadiusKm !== "number"
    ) return

    const requestController = new AbortController()
    areaRequestRef.current = requestController
    const requestStartedAt = new Date().toISOString()
    const selectedWindowEnd = Date.now() - settledWindowOffsetMs
    const selectedWindowStart = selectedWindowEnd - windowLengthMs
    const previous = areaSnapshotRef.current
    const canAppend =
      previous?.scopeKey === areaScopeKey &&
      previous.windowLengthMs === windowLengthMs &&
      previous.windowEnd < selectedWindowEnd &&
      previous.windowEnd >= selectedWindowStart
    const since = canAppend ? previous.windowEnd : selectedWindowStart
    if (!canAppend) setAreaDataState("loading")
    const bounds = localSelectionBounds(
      selectedAreaLat,
      selectedAreaLon,
      selectedAreaRadiusKm,
    )

    const boundedQuery = {
      until: new Date(selectedWindowEnd).toISOString(),
      ...bounds,
      positionedOnly: true,
      exclude: NON_MAP_VIEWPORT_SOURCES,
    }
    void Promise.all([
      fetchAllEventPages(
        { ...boundedQuery, since: new Date(since).toISOString() },
        2000,
        { signal: requestController.signal },
      ),
      previous?.scopeKey === areaScopeKey && previous.windowLengthMs === windowLengthMs
        ? fetchAllUpdatedEventPages(
            { ...boundedQuery, since: new Date(selectedWindowStart).toISOString() },
            previous.revisionSince,
            2000,
            { signal: requestController.signal },
          )
        : Promise.resolve([]),
    ])
      .then(([rows, revisedRows]) => {
        if (requestController.signal.aborted) return
        const incomingRows = mergeEventRows(rows, revisedRows)
        const snapshot: AreaSnapshot = {
          scopeKey: areaScopeKey,
          windowLengthMs,
          windowEnd: selectedWindowEnd,
          windowOffsetMs: settledWindowOffsetMs,
          revisionSince: requestStartedAt,
          events: canAppend
            ? mergeEventRows(previous.events, incomingRows).filter((row) => {
                const occurredAt = new Date(row.occurred_at).getTime()
                return occurredAt >= selectedWindowStart && occurredAt <= selectedWindowEnd
              })
            : incomingRows,
        }
        areaSnapshotRef.current = snapshot
        setAreaSnapshot(snapshot)
      })
      .catch((error) => {
        if (requestController.signal.aborted) return
        if (error instanceof DOMException && error.name === "AbortError") return
        setAreaDataState("error")
      })
      .finally(() => {
        if (areaRequestRef.current === requestController) {
          areaRequestRef.current = null
        }
      })

    return () => {
      requestController.abort()
      if (areaRequestRef.current === requestController) {
        areaRequestRef.current = null
      }
    }
  }, [
    areaScopeKey,
    selectedAreaLat,
    selectedAreaLon,
    selectedAreaRadiusKm,
    settledWindowOffsetMs,
    setAreaDataState,
    areaSyncTick,
    windowLengthMs,
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

  const handleMapError = useCallback(
    (event: unknown) => {
      const e = event as
        | { error?: { message?: string; url?: string }; message?: string }
        | undefined
      //: Which host failed, taken from the request rather than sniffed out of
      //: the message text. A failing tile carries the URL it asked for, and
      //: `new URL().hostname` is an exact answer where `message.includes(host)`
      //: is a guess that any other host can sit either side of.
      const host = (() => {
        const url = e?.error?.url
        if (typeof url !== "string") return null
        try {
          return new URL(url).hostname.toLowerCase()
        } catch {
          return null
        }
      })()

      //: A satellite backdrop with no tiles for the day being shown is not a
      //: broken map (#875). Whole days are genuinely absent from an archive
      //: that otherwise reaches back years, so this is recorded and said out
      //: loud rather than retried — and it must never trigger a style reload,
      //: which would rebuild the whole map because a backdrop had a gap.
      if (host === IMAGERY_HOST) {
        setImageryMissing(true)
        return
      }

      const msg = (e?.error?.message || e?.message || "").toLowerCase()
      // Only a genuine style/tile *load* failure warrants a reload. Missing sprite
      // images (circle-11 / wood-pattern) are NOT load failures — they're handled
      // in-place via styleimagemissing below, so they must never reach here (#407).
      //: `planet/` stays as a message check: it is a path fragment from the
      //: style's own tile references, and some style failures arrive without a
      //: URL to parse.
      const shouldFallback = host === MAP_STYLE_HOST || msg.includes("planet/")

      if (!shouldFallback) return
      scheduleStyleRetry()
    },
    [scheduleStyleRetry, setImageryMissing],
  )

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

  // Country centroids are display fallbacks for otherwise unpositioned
  // non-news rows. They must never become evidence that an event occurred
  // within a selected street, neighbourhood, or building radius.
  const localPositioned = useMemo(
    () => positioned.filter((item) => item.location?.source !== "country-centroid"),
    [positioned],
  )

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

  const selectedAreaFootprint = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features:
        typeof selectedAreaLat === "number" &&
        typeof selectedAreaLon === "number" &&
        typeof selectedAreaRadiusKm === "number"
          ? [
              {
                type: "Feature" as const,
                properties: {},
                geometry: {
                  type: "Polygon" as const,
                  coordinates: [
                    circlePolygon(selectedAreaLon, selectedAreaLat, selectedAreaRadiusKm),
                  ],
                },
              },
            ]
          : [],
    }),
    [selectedAreaLat, selectedAreaLon, selectedAreaRadiusKm],
  )

  // A detailed viewport snapshot can arrive after the click. Keep the local
  // card tied to the complete positioned rows instead of freezing its initial
  // (possibly still loading) contents (#774).
  useEffect(() => {
    if (
      typeof selectedAreaLat !== "number" ||
      typeof selectedAreaLon !== "number" ||
      typeof selectedAreaRadiusKm !== "number"
    ) return
    updateAreaSelections(
      localEventSelections(localPositioned, selectedAreaLat, selectedAreaLon, selectedAreaRadiusKm),
      areaSnapshotReady ? "ready" : undefined,
    )
  }, [
    areaSnapshotReady,
    localPositioned,
    selectedAreaLat,
    selectedAreaLon,
    selectedAreaRadiusKm,
    updateAreaSelections,
  ])

  /** Footprints for all hazards. Non-selected ones are revealed on zoom-in
   *  (opacity ramps 4→6); the SELECTED event's footprint is tagged `selected`
   *  so the paint keeps it full-opacity at every zoom — it must not fade away
   *  while its detail card is open, even fully zoomed out (#218). Cyclones also
   *  expand from track line to full cones when selected. */
  const { ambient: allAmbientHazardFootprints, selected: selectedHazardFootprints } = useMemo(
    () => hazardFootprintCollections(positioned, selectedEventId),
    [positioned, selectedEventId],
  )

  /** Focus mode: clicking a hazard isolates it. Its neighbours keep their
   *  markers — faded, so the reader can still see that they are there — but
   *  drop every contour, ring and extent, which is what was covering the
   *  footprint the reader actually opened. Escape ends it (SplitLayout owns
   *  that key), and the detail card stays open when it does: focus is how the
   *  map is drawn, not what is being read. */
  const focusedEventId = useMapFocusStore((s) => s.focusedEventId)
  const focus = useMapFocusStore((s) => s.focus)
  const clearFocus = useMapFocusStore((s) => s.clearFocus)
  const focusActive = focusedEventId !== null
  const ambientHazardFootprints = useMemo(
    () => ambientFootprints(allAmbientHazardFootprints, focusActive),
    [allAmbientHazardFootprints, focusActive],
  )
  const dimMultiplier = focusLayerOpacity(focusActive)

  //: Closing the card puts the map back. A focused hazard with nothing open
  //: would leave the reader looking at a faded world and no way to read why.
  useEffect(() => {
    if (selectedEventId === null && focusActive) clearFocus()
  }, [clearFocus, focusActive, selectedEventId])

  //: Live aircraft (#873). Presence, not evidence: fetched, drawn, discarded.
  //: Nothing here enters the event counts, the filters, the clustering or the
  //: situation list, because none of it is a claim that anything happened.
  const presenceOn = usePresenceStore((st) => st.aircraft)
  const [presenceAircraft, setPresenceAircraft] = useState<PresenceAircraft[]>([])
  //: When the poll last heard anything, carried into the card so an open card
  //: can go visibly stale instead of quietly.
  const [presenceFetchedAt, setPresenceFetchedAt] = useState<string | null>(null)
  const [presenceVisible, setPresenceVisible] = useState(true)
  const openAircraft = useRightPaneModeStore((st) => st.openAircraft)
  const closeAircraft = useRightPaneModeStore((st) => st.closeAircraft)

  useEffect(() => {
    const onVisibility = () => setPresenceVisible(!document.hidden)
    onVisibility()
    document.addEventListener("visibilitychange", onVisibility)
    return () => document.removeEventListener("visibilitychange", onVisibility)
  }, [])

  //: Off, scrubbed into the past, or in a background tab — all three mean stop
  //: asking. The last one matters because this is a free community service and
  //: a tab nobody is looking at should not be spending its bandwidth.
  const presencePolling = shouldPoll(presenceOn, windowEndOffsetMs, presenceVisible)

  useEffect(() => {
    if (!presencePolling) {
      setPresenceAircraft([])
      setPresenceFetchedAt(null)
      //: The layer going away takes its card with it. A card describing a
      //: position that is no longer drawn is the one thing this layer must
      //: never leave behind.
      closeAircraft()
      return
    }
    let cancelled = false
    const controller = new AbortController()
    const load = async () => {
      try {
        const answer = await fetchPresenceAircraft({ signal: controller.signal })
        if (!cancelled) {
          setPresenceAircraft(answer.aircraft)
          setPresenceFetchedAt(answer.fetched_at)
        }
      } catch {
        //: A refused fetch draws nothing rather than leaving the last known
        //: positions on screen, which would present old locations as current.
        if (!cancelled) {
          setPresenceAircraft([])
          setPresenceFetchedAt(null)
        }
      }
    }
    void load()
    const timer = setInterval(() => void load(), PRESENCE_POLL_MS)
    return () => {
      cancelled = true
      controller.abort()
      clearInterval(timer)
    }
  }, [presencePolling, closeAircraft])

  const hillshadeBeforeId = "waterway"

  const handleSelectMarker = useCallback(
    (ev: VisibleEvent, location?: MarkerLocationContext) => {
      // Bubble up to the shared centred detail overlay (#207); the map no longer
      // renders its own popup. Selecting a cyclone also expands its footprint.
      onSelectEvent(ev, location)
      // A hazard takes the map with it; anything else hands the map back,
      // because a news dot has no footprint to isolate and leaving the last
      // hazard focused would fade the map around a row that did not ask for it.
      if (focusable(ev)) focus(ev.id)
      else clearFocus()
    },
    [clearFocus, focus, onSelectEvent],
  )

  /** Cluster click exposes every unique story without changing camera state.
   * Selection and navigation are separate actions: opening detail must not
   * destroy the operator's spatial context (#776). */
  const handleClusterClick = useCallback(
    (positions: PositionedMapEvent[], lon: number, lat: number) => {
      const byEvent = new Map<VisibleEvent["id"], {
        event: VisibleEvent
        location?: MarkerLocationContext
        distanceKm: number
      }>()
      for (const position of positions) {
        const id = position.ev.id
        const markerDistanceKm = distanceKm(lat, lon, position.lat, position.lon)
        if (!byEvent.has(id)) {
          byEvent.set(id, {
            event: position.ev,
            location: position.location,
            distanceKm: markerDistanceKm,
          })
          continue
        }
        const existing = byEvent.get(id)
        byEvent.set(id, {
          event: position.ev,
          location: {
            name: "Multiple verified places",
            precision: "unknown",
            source: "multiple-marker-cluster",
          },
          distanceKm: Math.min(existing?.distanceKm ?? markerDistanceKm, markerDistanceKm),
        })
      }
      const uniqueSelections = [...byEvent.values()]
      const label = consensusLocalPlaceName(positions) ?? coordinateLabel(lat, lon)
      openClusterInPane(label, uniqueSelections)
      onOpenSelection()
    },
    [onOpenSelection, openClusterInPane],
  )

  const handleAreaClick = useCallback(
    (e: MapLayerMouseEvent) => {
      if (!mapRef) return
      const map = mapRef.getMap()
      const clickedLabel = localMapLabel(map.queryRenderedFeatures(e.point))
      const lat = e.lngLat.lat
      const lon = e.lngLat.lng
      // Area paging is independent of the visible viewport. Keep the camera
      // untouched so selection never masquerades as navigation (#776).
      const localZoom = Math.max(map.getZoom(), COMPLETE_VIEWPORT_ZOOM)
      const labelKind = clickedLabel?.kind ?? "coordinate"
      const radiusKm = localSelectionRadiusKm(localZoom, labelKind)
      openAreaInPane(
        clickedLabel?.name ?? coordinateLabel(lat, lon),
        labelKind,
        lat,
        lon,
        radiusKm,
        localEventSelections(localPositioned, lat, lon, radiusKm),
      )
      onOpenSelection()
    },
    [localPositioned, mapRef, onOpenSelection, openAreaInPane],
  )

  //: Right-click asks what this place *is*; left-click asks what is
  //: *happening* near it (#862). Two questions, two gestures — and the
  //: left-click one is untouched, because the radius selection it builds is
  //: well-worn and this feature does not get to disturb it.
  //:
  //: Registering this handler is also what suppresses the browser's own menu,
  //: and that is worth writing down because nothing here looks like it does
  //: that. MapLibre prevents the native event whenever the map has a
  //: `contextmenu` listener — `this._map.listens("contextmenu") &&
  //: e.preventDefault()` — so the mechanism is the subscription, not anything
  //: this function calls. Move the handler onto a wrapping element and the
  //: menu comes back.
  //:
  //: `e.preventDefault()` was here for that job and never did it: on a
  //: MapMouseEvent it blocks map behaviours only — drag-pan, drag-rotate,
  //: box-zoom, double-click zoom — none of which a right-click raises.
  const openPlace = usePlaceStore((s) => s.openPoint)
  const handleContextMenu = useCallback(
    (e: MapLayerMouseEvent) => {
      openPlace(e.lngLat.lat, e.lngLat.lng)
      onOpenSelection()
    },
    [onOpenSelection, openPlace],
  )

  const handleClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const feature = e.features?.[0]

      if (feature?.layer.id === EVENT_POINT_LAYER_ID) {
        const markerKey = feature.properties?.markerKey
        if (typeof markerKey !== "string") return
        const item = clusteredByKey.get(markerKey)
        if (item) handleSelectMarker(item.ev, item.location)
        return
      }

      if (feature?.layer.id === EVENT_CLUSTER_LAYER_ID && mapRef) {
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

      handleAreaClick(e)
    },
    [clusteredByKey, handleAreaClick, handleClusterClick, handleSelectMarker, mapRef],
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
        ]}
        onClick={handleClick}
        onContextMenu={handleContextMenu}
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
        cursor="pointer"
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
        {/* Satellite backdrop, off unless the operator asks for it (#875).
            Tiles go publisher → browser: nothing is fetched by the API, stored,
            or retained, which is the whole reason it is affordable.

            It follows the time scrubber rather than pinning to today. A map
            reading three weeks ago over a backdrop from last night gives the
            reader no way to tell the two timescales apart, and that is worse
            than no backdrop at all.

            Sits above the hillshade and below `waterway`, so relief still
            shapes it while borders, labels and every marker stay on top. */}
        {imageryTileUrls && activeImagery && (
          <Source
            id={`imagery-${activeImagery.id}-${imageryDay}`}
            key={`imagery-${activeImagery.id}-${imageryDay}`}
            type="raster"
            tiles={imageryTileUrls}
            tileSize={256}
            maxzoom={activeImagery.maxZoom}
          >
            <Layer
              id="imagery"
              type="raster"
              beforeId={hillshadeBeforeId}
              paint={{ "raster-opacity": activeImagery.opacity }}
            />
          </Source>
        )}
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
        <Source id="selected-local-area" type="geojson" data={selectedAreaFootprint}>
          <Layer
            id="selected-local-area-fill"
            type="fill"
            paint={{ "fill-color": "#22d3ee", "fill-opacity": 0.08 }}
          />
          <Layer
            id="selected-local-area-line"
            type="line"
            paint={{
              "line-color": "#67e8f9",
              "line-opacity": 0.9,
              "line-width": 1.5,
              "line-dasharray": [3, 2],
            }}
          />
        </Source>
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
              //: Clusters are news, so they are never the focused hazard —
              //: they only ever recede while one is being read.
              "circle-opacity": dimMultiplier,
              "circle-stroke-opacity": dimMultiplier,
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
              //: The style ships one font and this is it. Left unset,
              //: MapLibre asks for its own default — "Open Sans Regular,
              //: Arial Unicode MS Regular" — which OpenFreeMap does not
              //: serve, so every glyph range 404s and each cluster number is
              //: drawn from a local fallback instead of the map's own type.
              "text-font": ["Noto Sans Regular"],
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
              //: A city centroid is not a surveyed point (#773). Age still
              //: fades a marker; precision decides how solid it ever gets, so
              //: an area claim reads as an area and only a verified location
              //: is drawn solid.
              "circle-opacity": [
                "*",
                //: Focus scales the whole expression rather than replacing it,
                //: so age and precision still say what they said before.
                dimMultiplier,
                ["coalesce", ["get", "opacity"], 1],
                [
                  "match",
                  ["coalesce", ["get", "precision"], "unknown"],
                  "exact",
                  PRECISION_OPACITY.exact,
                  "city",
                  PRECISION_OPACITY.city,
                  "area",
                  PRECISION_OPACITY.area,
                  "country",
                  PRECISION_OPACITY.country,
                  PRECISION_OPACITY.unknown,
                ],
              ],
              "circle-radius": [
                "match",
                ["coalesce", ["get", "precision"], "unknown"],
                "exact",
                PRECISION_RADIUS_PX.exact,
                "city",
                PRECISION_RADIUS_PX.city,
                "area",
                PRECISION_RADIUS_PX.area,
                "country",
                PRECISION_RADIUS_PX.country,
                PRECISION_RADIUS_PX.unknown,
              ],
              "circle-stroke-color": ["get", "color"],
              "circle-stroke-width": 1,
              "circle-stroke-opacity": dimMultiplier,
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
            focusActive={focusActive}
            isFocused={ev.id === focusedEventId}
          />
        ))}
        {typeof selectedAreaLat === "number" && typeof selectedAreaLon === "number" && (
          <Marker longitude={selectedAreaLon} latitude={selectedAreaLat} anchor="center">
            <span className="pointer-events-none block h-3 w-3 rounded-full border-2 border-cyan-200 bg-cyan-400/40 shadow-[0_0_8px_rgba(34,211,238,0.9)]" />
          </Marker>
        )}
        {/*: Live aircraft, and they open. Presence still has no place-screen
            entry and no history — nothing here is stored — but a mark a reader
            cannot question is worse than no mark, so clicking one says what it
            is and who said so. The 16px glyph sits in a 28px target: the arrow
            is small on purpose and a cursor cannot be asked to hit it. */}
        {presenceAircraft.map((a) => (
          <Marker
            key={a.hex ?? `${a.lat},${a.lon}`}
            longitude={a.lon}
            latitude={a.lat}
            anchor="center"
            onClick={(e) => {
              e.originalEvent.stopPropagation()
              openAircraft(a, presenceFetchedAt)
            }}
          >
            <div
              title={[a.callsign, a.type, a.alt_ft ? `${Math.round(a.alt_ft)} ft` : null]
                .filter(Boolean)
                .join(" · ")}
              className="pointer-events-auto grid h-7 w-7 cursor-pointer place-items-center"
            >
              <span
                aria-hidden
                className={
                  a.kind === "distress"
                    ? "block h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-red-400/50"
                    : "block text-[10px] leading-none text-sky-300/80"
                }
                //: No track means no rotation. Pointing north would be a claim
                //: the transponder never made.
                style={
                  a.kind === "distress"
                    ? undefined
                    : { transform: a.track != null ? `rotate(${a.track}deg)` : undefined }
                }
              >
                {a.kind === "distress" ? "" : "\u27A4"}
              </span>
            </div>
          </Marker>
        ))}
      </MapGL>

      {!configured && (
        <PaneStatus
          mode="error"
          message="Local API unreachable — start it at NEXT_PUBLIC_API_URL (default http://localhost:8000)."
        />
      )}
      {/*: The live source-count chips that floated top-left are gone. The
          filter panel prints the same numbers, per layer, next to the switch
          that turns each one off — two places for one count is one place too
          many, and the corner they sat in belongs to the map. */}

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
      {/*: An empty map is only worth interrupting for when nobody asked for it.
          Switch every layer off and the emptiness is the answer, not a fault —
          the panel says what is excluded and offers the way back, so the map
          shows the map. */}
      {configured && allEvents.length > 0 && positioned.length === 0 && !filtersNarrowed && (
        <PaneStatus mode="empty" onReset={() => useStore.getState().reset()} />
      )}

      {/* Source icons/toggles live in the filter rail, docked right — the
       *  left edge belongs to the floating deck and detail panels (#503). */}
      <FilterRail
        side="right"
        useStore={useStore}
        narrow={narrow}
        open={railOpen}
        onOpenChange={onRailOpenChange}
        supplementalEvents={supplementalEvents}
      />
      <TimeScrubber
        useStore={useStore}
        narrow={narrow}
        windowEnd={windowEnd}
        panelOpen={railOpen}
      />
    </div>
  )
}
