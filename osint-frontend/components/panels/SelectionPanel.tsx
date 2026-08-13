"use client"

import { useEventDetailStore } from "@/stores/eventDetailStore"
import { usePlaceStore } from "@/stores/placeStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { AircraftDetailCard } from "./AircraftDetailCard"
import { VesselDetailCard } from "./VesselDetailCard"
import { ClusterListPanel } from "../ClusterListPanel"
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
  //: A row in these lists opens the pop-up (#850). It used to call the
  //: map-selection opener, which replaced this very page — the reader lost
  //: the list they were reading and no pop-up appeared. Screen three is built
  //: by clicking the map and by nothing else.
  const openEventDetail = useEventDetailStore((s) => s.openEventDetail)
  const openPlace = usePlaceStore((s) => s.openCountry)

  if (!entity) return null

  return (
    <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
      {entity.kind === "aircraft" ? (
        <AircraftDetailCard
          aircraft={entity.aircraft}
          fetchedAt={entity.fetchedAt}
          onClose={closeEntity}
        />
      ) : entity.kind === "vessel" ? (
        <VesselDetailCard
          vessel={entity.vessel}
          fetchedAt={entity.fetchedAt}
          onClose={closeEntity}
        />
      ) : entity.kind === "cluster" ? (
        <ClusterListPanel
          label={entity.label}
          selections={entity.selections}
          onSelectEvent={openEventDetail}
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
          onSelectEvent={openEventDetail}
          onClose={closeEntity}
        />
      ) : (
        <EventDetailCard
          event={entity.event}
          location={entity.location}
          embedded
          onClose={closeEntity}
          onSelectCountry={openPlace}
        />
      )}
    </div>
  )
}
