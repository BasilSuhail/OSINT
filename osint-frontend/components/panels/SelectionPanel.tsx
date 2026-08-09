"use client"

import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { ClusterListPanel } from "../ClusterListPanel"
import { CountrySidePanel } from "../CountrySidePanel"
import { EventDetailCard } from "../EventDetailCard"

/**
 * The card that is not there most of the time (#699).
 *
 * Clicking a country, an event or a cluster on the map has always opened a
 * detail view, and Escape has always closed it. It did that by *replacing* the
 * world status panel inside one card, so picking something off the map quietly
 * destroyed the view you were reading.
 *
 * Now it is its own card: it exists while something is selected and the deck
 * moves to it. Nothing is overwritten.
 *
 * Escape does not dismiss it (#844). A page is the reader's place, and a key
 * that removes one is a key that loses it — it closes by its own control, or
 * by being swiped away from.
 *
 * Renders nothing when there is no selection — the deck only mounts it while
 * one exists, and this keeps that true if it is ever mounted otherwise.
 */
export function SelectionPanel() {
  const entity = useRightPaneModeStore((s) => s.entity)
  const closeEntity = useRightPaneModeStore((s) => s.closeEntity)
  const openEvent = useRightPaneModeStore((s) => s.openEvent)
  const openCountry = useRightPaneModeStore((s) => s.openCountry)

  if (!entity) return null

  return (
    <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
      {entity.kind === "country" ? (
        <CountrySidePanel country={entity.iso} onClose={closeEntity} />
      ) : entity.kind === "cluster" ? (
        <ClusterListPanel
          label={entity.label}
          selections={entity.selections}
          onSelectEvent={openEvent}
          onClose={closeEntity}
        />
      ) : entity.kind === "area" ? (
        <ClusterListPanel
          label={entity.label}
          selections={entity.selections}
          area={{
            lat: entity.lat,
            lon: entity.lon,
            radiusKm: entity.radiusKm,
            labelKind: entity.labelKind,
            dataState: entity.dataState,
          }}
          onSelectEvent={openEvent}
          onClose={closeEntity}
        />
      ) : (
        <EventDetailCard
          event={entity.event}
          location={entity.location}
          embedded
          onClose={closeEntity}
          onSelectCountry={(iso) => openCountry(iso)}
        />
      )}
    </div>
  )
}
