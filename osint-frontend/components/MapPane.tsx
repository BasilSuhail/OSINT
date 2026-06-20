"use client"

import "maplibre-gl/dist/maplibre-gl.css"
import { useCallback, useEffect, useMemo, useState } from "react"
import Map, {
  Layer,
  Marker,
  Popup,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre"
import { AnimatePresence, motion } from "framer-motion"
import { formatDistanceToNowStrict } from "date-fns"
import { ExternalLink, X } from "lucide-react"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import { colorForEvent } from "@/lib/types"
import type { FilterStore } from "@/stores/createFilterStore"
import { FilterRail } from "./FilterRail"
import { TimeScrubber } from "./TimeScrubber"

const MAP_STYLE = "https://tiles.openfreemap.org/styles/dark"
const MAX_MARKERS = 700

interface MapPaneProps {
  useStore: FilterStore
  railOpen: boolean
  onRailOpenChange: (open: boolean) => void
  onSelectCountry: (iso: string) => void
  onCount: (n: number) => void
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
  const isNew = ev.age < 0.05

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
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: ev.opacity }}
        exit={{ scale: 0, opacity: 0 }}
        transition={{ duration: 0.2 }}
        style={{ width: style.size, height: style.size, cursor: "pointer" }}
        className="relative grid place-items-center"
      >
        {isNew && (
          <span
            className="absolute inset-0 animate-ping rounded-full"
            style={{
              backgroundColor: style.color,
              opacity: 0.5,
              borderRadius: style.shape === "diamond" ? 0 : "9999px",
              transform: style.shape === "diamond" ? "rotate(45deg)" : undefined,
            }}
          />
        )}
        <span
          className="block"
          style={{
            width: style.size,
            height: style.size,
            backgroundColor: style.color,
            borderRadius: style.shape === "diamond" ? 2 : "9999px",
            transform: style.shape === "diamond" ? "rotate(45deg)" : undefined,
            boxShadow: isNew ? `0 0 8px 2px ${style.color}` : `0 0 3px ${style.color}`,
          }}
        />
      </motion.div>
    </Marker>
  )
}

export function MapPane({ useStore, railOpen, onRailOpenChange, onSelectCountry, onCount }: MapPaneProps) {
  const { events, windowEnd, total } = useEventsInWindow(useStore)
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const [mapRef, setMapRef] = useState<MapRef | null>(null)
  const [selected, setSelected] = useState<{ ev: VisibleEvent; lat: number; lon: number } | null>(null)

  // Report count to the parent status bar.
  useEffect(() => onCount(total), [total, onCount])

  const positioned = useMemo(() => {
    const out: { ev: VisibleEvent; lat: number; lon: number }[] = []
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

  const selectedUrl = selected
    ? ((selected.ev.payload as { source_url?: string; link?: string })?.source_url ??
      (selected.ev.payload as { link?: string })?.link)
    : undefined

  return (
    <div className="relative h-full w-full overflow-hidden bg-neutral-950">
      <Map
        ref={setMapRef}
        mapStyle={MAP_STYLE}
        initialViewState={{ longitude: 10, latitude: 25, zoom: 1.4 }}
        interactiveLayerIds={scoredGeo ? ["country-fill"] : []}
        onClick={handleClick}
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
          {positioned.map(({ ev, lat, lon }) => (
            <EventMarker key={ev.id} ev={ev} lat={lat} lon={lon} onSelect={handleSelectMarker} />
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
            maxWidth="280px"
            className="osint-popup"
          >
            <div className="w-64 rounded-md border border-neutral-700 bg-neutral-950/95 p-3 backdrop-blur-md">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: colorForEvent(selected.ev) }}
                  />
                  <span className="font-mono text-xs uppercase tracking-wider text-neutral-200">
                    {selected.ev.source}
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
                  {formatDistanceToNowStrict(new Date(selected.ev.occurred_at), { addSuffix: true })}
                </dd>
                <dt className="text-neutral-500">category</dt>
                <dd className="text-neutral-300">{selected.ev.category}</dd>
                <dt className="text-neutral-500">severity</dt>
                <dd className="text-neutral-300">{selected.ev.severity.toFixed(2)}</dd>
                {selected.ev.country && (
                  <>
                    <dt className="text-neutral-500">country</dt>
                    <dd className="text-neutral-300">{selected.ev.country}</dd>
                  </>
                )}
              </dl>
              <div className="mt-2 flex items-center gap-3">
                {selected.ev.country && (
                  <button
                    type="button"
                    onClick={() => onSelectCountry(selected.ev.country as string)}
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
          </Popup>
        )}
      </Map>

      {positioned.length === 0 && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <p className="font-mono text-xs uppercase tracking-widest text-neutral-600">
            No events match the current filters
          </p>
        </div>
      )}

      <FilterRail side="left" useStore={useStore} open={railOpen} onOpenChange={onRailOpenChange} />
      <TimeScrubber useStore={useStore} windowEnd={windowEnd} />
    </div>
  )
}
