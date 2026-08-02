import { create } from "zustand"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import type { VisibleEvent } from "@/lib/queries"

export interface EventSelection {
  event: VisibleEvent
  location?: MarkerLocationContext
}

/** Right-pane entity lock (#252, reshaped by the card deck #328).
 *
 *  The console card shows the ACLED-style world status panel by default;
 *  clicking any country / event locks the card to that entity until Esc / ×.
 *  Selecting another entity just replaces the current one. The 3D globe,
 *  formerly a swappable base mode here, now rides as its own deck card.
 */
export type RightPaneEntity =
  | { kind: "country"; iso: string }
  | { kind: "event"; event: VisibleEvent; location?: MarkerLocationContext }
  /** A clicked map cluster / country news pile — a drillable list of events. */
  | { kind: "cluster"; label: string; selections: EventSelection[] }

interface RightPaneModeState {
  entity: RightPaneEntity | null
  openCountry: (iso: string) => void
  openEvent: (event: VisibleEvent, location?: MarkerLocationContext) => void
  openCluster: (label: string, selections: EventSelection[]) => void
  closeEntity: () => void
}

export const useRightPaneModeStore = create<RightPaneModeState>((set) => ({
  entity: null,
  openCountry: (iso) => set({ entity: { kind: "country", iso } }),
  openEvent: (event, location) => set({ entity: { kind: "event", event, location } }),
  openCluster: (label, selections) => set({ entity: { kind: "cluster", label, selections } }),
  closeEntity: () => set({ entity: null }),
}))
