import { create } from "zustand"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import type { LocalAreaKind } from "@/lib/localMapSelection"
import type { PresenceAircraft } from "@/lib/presence"
import type { PresenceVessel } from "@/lib/vessels"
import type { VisibleEvent } from "@/lib/queries"

export interface EventSelection {
  event: VisibleEvent
  location?: MarkerLocationContext
  distanceKm?: number
}

/** Right-pane entity lock (#252, reshaped by the card deck #328).
 *
 *  The console card shows the ACLED-style world status panel by default;
 *  clicking any event locks the card to that entity until Esc / ×. Selecting
 *  another entity just replaces the current one. The 3D globe, formerly a
 *  swappable base mode here, now rides as its own deck card.
 *
 *  A country is not in this list any more (#862). It is not something a map
 *  click selects — it is its own screen, made by a right-click and holding a
 *  description rather than a selection, so it lives in `placeStore`. What a
 *  left-click can pick is an event, a cluster of them, or an area.
 */
export type RightPaneEntity =
  | { kind: "event"; event: VisibleEvent; location?: MarkerLocationContext }
  /** A live aircraft. Not an event and never stored, but a map click picked it
   *  and a map click's answer belongs on the selection screen with every other
   *  answer — not in the pop-up, which is where a *row in a list* goes. */
  | { kind: "aircraft"; aircraft: PresenceAircraft; fetchedAt: string | null }
  /** A live vessel. Same rule as an aircraft: picked off the map, never
   *  stored, and worth a card because a mark a reader cannot question is
   *  worse than no mark at all. */
  | { kind: "vessel"; vessel: PresenceVessel; fetchedAt: string | null }
  /** A clicked map cluster / country news pile — a drillable list of events. */
  | { kind: "cluster"; label: string; selections: EventSelection[] }
  | {
      kind: "area"
      label: string
      labelKind: LocalAreaKind
      lat: number
      lon: number
      radiusKm: number
      dataState: "loading" | "ready" | "error"
      selections: EventSelection[]
    }

interface RightPaneModeState {
  entity: RightPaneEntity | null
  openEvent: (event: VisibleEvent, location?: MarkerLocationContext) => void
  openAircraft: (aircraft: PresenceAircraft, fetchedAt: string | null) => void
  /** Close only if an aircraft is what is showing: the live layer going away
   *  must take its own card with it and leave every other selection alone. */
  closeAircraft: () => void
  openVessel: (vessel: PresenceVessel, fetchedAt: string | null) => void
  /** Close only if a vessel is what is showing. */
  closeVessel: () => void
  openCluster: (label: string, selections: EventSelection[]) => void
  openArea: (
    label: string,
    labelKind: LocalAreaKind,
    lat: number,
    lon: number,
    radiusKm: number,
    selections: EventSelection[],
  ) => void
  updateAreaSelections: (
    selections: EventSelection[],
    dataState?: "loading" | "ready" | "error",
  ) => void
  setAreaDataState: (dataState: "loading" | "ready" | "error") => void
  closeEntity: () => void
}

export const useRightPaneModeStore = create<RightPaneModeState>((set) => ({
  entity: null,
  openEvent: (event, location) => set({ entity: { kind: "event", event, location } }),
  openAircraft: (aircraft, fetchedAt) => set({ entity: { kind: "aircraft", aircraft, fetchedAt } }),
  closeAircraft: () =>
    set((state) => (state.entity?.kind === "aircraft" ? { entity: null } : state)),
  openVessel: (vessel, fetchedAt) => set({ entity: { kind: "vessel", vessel, fetchedAt } }),
  closeVessel: () =>
    set((state) => (state.entity?.kind === "vessel" ? { entity: null } : state)),
  openCluster: (label, selections) => set({ entity: { kind: "cluster", label, selections } }),
  openArea: (label, labelKind, lat, lon, radiusKm, selections) =>
    set({
      entity: {
        kind: "area",
        label,
        labelKind,
        lat,
        lon,
        radiusKm,
        dataState: "loading",
        selections,
      },
    }),
  updateAreaSelections: (selections, dataState) =>
    set((state) =>
      state.entity?.kind === "area"
        ? {
            entity: {
              ...state.entity,
              selections,
              dataState: dataState ?? state.entity.dataState,
            },
          }
        : state,
    ),
  setAreaDataState: (dataState) =>
    set((state) =>
      state.entity?.kind === "area"
        ? { entity: { ...state.entity, dataState } }
        : state,
    ),
  closeEntity: () => set({ entity: null }),
}))
