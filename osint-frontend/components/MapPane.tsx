"use client"

import "maplibre-gl/dist/maplibre-gl.css"
import { useCallback, useEffect, useMemo, useState } from "react"
import MapGL, {
  Layer,
  Marker,
  Popup,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre"
import { AnimatePresence, motion } from "framer-motion"
import { useConfigured, useEvents } from "@/app/providers"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import { colorForEvent } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { EventDetailCard } from "./EventDetailCard"
import { FilterRail } from "./FilterRail"
import { PaneStatus } from "./PaneStatus"
import { TimeScrubber } from "./TimeScrubber"

const MAP_STYLE = "https://tiles.openfreemap.org/styles/dark"
const MAX_MARKERS = 700
const INITIAL_ZOOM = 1.4

interface MapPaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onSelectCountry: (iso: string) => void
  onCount: (n: number) => void
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

export function MapPane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount }: MapPaneProps) {
  const { events, windowEnd, total } = useEventsInWindow(useStore, "map")
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [selected, setSelected] = useState<{ ev: VisibleEvent; lat: number; lon: number } | null>(null)
  const [zoom, setZoom] = useState<number>(INITIAL_ZOOM)
  const [openCluster, setOpenCluster] = useState<ClusterMarker | null>(null)

  useEffect(() => onCount(total), [total, onCount])

  const positioned = useMemo<Positioned[]>(() => {
    const out: Positioned[] = []
    for (const ev of events) {
      let lat = ev.lat
      let lon = ev.lon
      if ((lat == null || lon == null) && ev.country) {
        const c = centroids.get(ev.country)
        if (c) {
          lon = c[0]
          lat = c[1]
        }
      }
      if (lat == null || lon == null) continue
      out.push({ ev, lat, lon })
      if (out.length >= MAX_MARKERS) break
    }
    return out
  }, [events, centroids])

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
      const lat = ev.lat
      const lon = ev.lon
      if (lat == null || lon == null) {
        if (!ev.country) return
        const c = centroids.get(ev.country)
        if (!c) return
        setSelected({ ev, lat: c[1], lon: c[0] })
        return
      }
      setSelected({ ev, lat, lon })
    },
    [centroids],
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
    <div className="relative h-full w-full overflow-hidden bg-neutral-950">
      <MapGL
        ref={setMapRef}
        mapStyle={MAP_STYLE}
        initialViewState={{ longitude: 10, latitude: 25, zoom: INITIAL_ZOOM }}
        interactiveLayerIds={scoredGeo ? ["country-fill"] : []}
        onClick={handleClick}
        onMoveEnd={(e) => setZoom(e.viewState.zoom)}
        attributionControl={false}
        dragRotate={false}
        style={{ position: "absolute", inset: 0 }}
      >
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

        <AnimatePresence>
          {singles.map(({ ev, lat, lon }) => (
            <EventMarker key={ev.id} ev={ev} lat={lat} lon={lon} onSelect={handleSelectMarker} />
          ))}
          {clusters.map((c) => (
            <ClusterChip key={c.key} cluster={c} onClick={handleClusterClick} />
          ))}
        </AnimatePresence>

        {selected && (
          <Popup
            longitude={selected.lon}
            latitude={selected.lat}
            anchor="bottom"
            closeButton={false}
            closeOnClick={false}
            onClose={() => setSelected(null)}
            offset={12}
            maxWidth="360px"
            className="osint-popup"
          >
            <EventDetailCard
              event={selected.ev}
              onSelectCountry={onSelectCountry}
              onClose={() => setSelected(null)}
              embedded
            />
          </Popup>
        )}

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
      </MapGL>

      {!configured && (
        <PaneStatus
          mode="error"
          message="Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY."
        />
      )}
      {configured && allEvents.length === 0 && <PaneStatus mode="loading" />}
      {configured && allEvents.length > 0 && positioned.length === 0 && (
        <PaneStatus mode="empty" onReset={() => useStore.getState().reset()} />
      )}

      <FilterRail pane="map" side="left" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
