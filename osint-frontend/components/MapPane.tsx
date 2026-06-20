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
import { useConfigured, useEvents } from "@/app/providers"
import { useEventsInWindow, useLatestScores, type VisibleEvent } from "@/lib/queries"
import { useCountriesGeo, useScoredGeo } from "@/lib/geo"
import { markerStyle } from "@/lib/markers"
import type { FilterStore } from "@/stores/createFilterStore"
import { EventDetailCard } from "./EventDetailCard"
import { FilterRail } from "./FilterRail"
import { PaneStatus } from "./PaneStatus"
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
  const { events, windowEnd, total } = useEventsInWindow(useStore, "map")
  const { byCountry } = useLatestScores()
  const scoredGeo = useScoredGeo(byCountry)
  const { centroids } = useCountriesGeo()
  const configured = useConfigured()
  const allEvents = useEvents()
  const [, setMapRef] = useState<MapRef | null>(null)
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
      </Map>

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
