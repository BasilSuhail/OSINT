"use client"

import { useEffect } from "react"
import { useRightPaneModeStore } from "@/stores/rightPaneModeStore"
import { ClusterListPanel } from "./ClusterListPanel"
import { CountrySidePanel } from "./CountrySidePanel"
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
  const openCountry = useRightPaneModeStore((s) => s.openCountry)
  const openEvent = useRightPaneModeStore((s) => s.openEvent)

  // Esc closes a locked entity and restores the world status view.
  useEffect(() => {
    if (!entity) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeEntity()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [entity, closeEntity])

  return (
    <div className="relative h-full w-full overflow-hidden bg-neutral-950">
      {entity ? (
        <div className="absolute inset-0 overflow-y-auto bg-neutral-950 p-3">
          {entity.kind === "country" ? (
            <CountrySidePanel country={entity.iso} onClose={closeEntity} />
          ) : entity.kind === "cluster" ? (
            <ClusterListPanel
              label={entity.label}
              events={entity.events}
              onSelectEvent={openEvent}
              onClose={closeEntity}
            />
          ) : (
            <EventDetailCard
              event={entity.event}
              embedded
              onClose={closeEntity}
              onSelectCountry={(iso) => openCountry(iso)}
            />
          )}
        </div>
      ) : (
        <div className="absolute inset-0">
          <WorldStatusPanel />
        </div>
      )}
    </div>
  )
}
