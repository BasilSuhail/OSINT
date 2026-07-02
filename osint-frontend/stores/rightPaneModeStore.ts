import { create } from "zustand"
import type { VisibleEvent } from "@/lib/queries"

/** The right pane is a swappable multi-window surface (#252).
 *
 *  - `base` is the mode you return to: the ACLED-style world status panel
 *    ("world", the default) or the 3D globe ("globe"). The swap button flips
 *    between them.
 *  - `entity` is a *modal over* whichever base is active: clicking any country
 *    / event locks the pane to that entity until Esc / ×, then it restores the
 *    remembered base. Selecting another entity just replaces the current one.
 */
export type RightPaneBase = "world" | "globe"

export type RightPaneEntity =
  | { kind: "country"; iso: string }
  | { kind: "event"; event: VisibleEvent }
  /** A clicked map cluster / country news pile — a drillable list of events. */
  | { kind: "cluster"; label: string; events: VisibleEvent[] }

export type RightPaneMode = RightPaneBase | "entity"

interface RightPaneModeState {
  base: RightPaneBase
  entity: RightPaneEntity | null
  setBase: (base: RightPaneBase) => void
  swapBase: () => void
  openCountry: (iso: string) => void
  openEvent: (event: VisibleEvent) => void
  openCluster: (label: string, events: VisibleEvent[]) => void
  closeEntity: () => void
}

export const useRightPaneModeStore = create<RightPaneModeState>((set) => ({
  base: "world",
  entity: null,
  setBase: (base) => set({ base }),
  swapBase: () => set((s) => ({ base: s.base === "world" ? "globe" : "world" })),
  openCountry: (iso) => set({ entity: { kind: "country", iso } }),
  openEvent: (event) => set({ entity: { kind: "event", event } }),
  openCluster: (label, events) => set({ entity: { kind: "cluster", label, events } }),
  closeEntity: () => set({ entity: null }),
}))

/** Current resolved mode: entity overrides the base when locked. */
export function rightPaneMode(base: RightPaneBase, entity: RightPaneEntity | null): RightPaneMode {
  return entity ? "entity" : base
}
