import { create } from "zustand"
import type { VisibleEvent } from "@/lib/queries"

/** Right-pane entity lock (#252, reshaped by the card deck #328).
 *
 *  The console card shows the ACLED-style world status panel by default;
 *  clicking any country / event locks the card to that entity until Esc / ×.
 *  Selecting another entity just replaces the current one. The 3D globe,
 *  formerly a swappable base mode here, now rides as its own deck card.
 */
export type RightPaneEntity =
  | { kind: "country"; iso: string }
  | { kind: "event"; event: VisibleEvent }
  /** A clicked map cluster / country news pile — a drillable list of events. */
  | { kind: "cluster"; label: string; events: VisibleEvent[] }

interface RightPaneModeState {
  entity: RightPaneEntity | null
  openCountry: (iso: string) => void
  openEvent: (event: VisibleEvent) => void
  openCluster: (label: string, events: VisibleEvent[]) => void
  closeEntity: () => void
}

export const useRightPaneModeStore = create<RightPaneModeState>((set) => ({
  entity: null,
  openCountry: (iso) => set({ entity: { kind: "country", iso } }),
  openEvent: (event) => set({ entity: { kind: "event", event } }),
  openCluster: (label, events) => set({ entity: { kind: "cluster", label, events } }),
  closeEntity: () => set({ entity: null }),
}))
