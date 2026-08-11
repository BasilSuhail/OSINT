"use client"

import { useEventDetailStore } from "@/stores/eventDetailStore"
import { usePlaceStore } from "@/stores/placeStore"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { ClusterListPanel } from "./ClusterListPanel"
import { EventDetailCard } from "./EventDetailCard"
import { WorldStatusPanel } from "./WorldStatusPanel"

/** The console card (#252, #328):
 *  - world  → ACLED-style world status panel (default)
 *  - entity → a clicked country / event, locked until Esc / ×
 *
 *  The 3D globe, formerly a swappable base mode here, is now its own card in
 *  the deck (CardDeck), so this surface is just world status + entity lock. */
export function RightPane() {
  const entity = useRightPaneModeStore((s) => s.entity)
  const closeEntity = useRightPaneModeStore((s) => s.closeEntity)
  const openPlace = usePlaceStore((s) => s.openCountry)
  //: A row in these lists opens the pop-up, never the map selection (#850) —
  //: screen three is built by clicking the map and by nothing else.
  const openEventDetail = useEventDetailStore((s) => s.openEventDetail)

  //: Escape no longer closes the locked entity (#842). Doing so removed the
  //: selection *page* from the deck, which is the reader's place rather than a
  //: pop-out over it — so a keypress meant to dismiss a detail card took a
  //: page away instead. The selection closes by its own control, and the way
  //: back from it is to swipe.

  return (
    <div className="relative h-full w-full overflow-hidden bg-neutral-950">
      {entity ? (
        <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
          {entity.kind === "cluster" ? (
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
          ) : entity.kind === "event" ? (
            <EventDetailCard
              event={entity.event}
              location={entity.location}
              embedded
              onClose={closeEntity}
              onSelectCountry={openPlace}
            />
          ) : null}
        </div>
      ) : (
        <div className="absolute inset-0">
          <WorldStatusPanel />
        </div>
      )}
    </div>
  )
}
