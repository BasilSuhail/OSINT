import { create } from "zustand"
import { VESSEL_CATEGORIES, type VesselCategory } from "@/lib/vessels"

/** Which live layers are drawn (#873).
 *
 * Presence is not evidence: these aircraft are where something is right now,
 * never stored and never citable. On by default all the same — every layer the
 * console can draw is drawn until the reader says otherwise, and a layer that
 * arrives switched off is a layer most readers never learn exists. It costs
 * nothing while the tab is hidden or the scrubber has left "now": both stop
 * the poll.
 */
interface PresenceState {
  aircraft: boolean
  toggleAircraft: () => void
  /** Vessels, one switch per transmitted category (#954). Separate switches
   *  because the categories answer different questions — what trade is moving,
   *  what is fishing, what is tied up — and a reader watching one of them
   *  should not have to look through the other six. */
  vessels: Record<VesselCategory, boolean>
  toggleVessel: (key: VesselCategory) => void
  setAllVessels: (on: boolean) => void
  /** Who reported the vessels currently drawn. Held here because the map does
   *  the asking and the rail does the crediting, and the notice has to follow
   *  the data rather than be typed twice. */
  vesselSources: string[]
  setVesselSources: (sources: string[]) => void
  /** How many vessels the last refresh carried, per category. Printed beside
   *  each rail row, so a layer drawing few marks is visibly a quiet sea rather
   *  than a broken layer. */
  vesselCounts: Record<VesselCategory, number>
  setVesselCounts: (counts: Record<VesselCategory, number>) => void
  /** Watched airframes (#954). Its own switch because the two answer different
   *  questions — what is in the air over there, and where is *that* aircraft —
   *  and a reader following one airframe should not have to wade through four
   *  hundred marks to keep sight of it. */
  watchlist: boolean
  toggleWatchlist: () => void
  /** What the last refresh knew about the watchlist: how many airframes are
   *  listed, and how many of them are on the map. Held here because the map
   *  does the asking and the rail does the explaining. */
  watchState: { watching: number; drawn: number; status: "ok" | "default" }
  setWatchState: (state: {
    watching: number
    drawn: number
    status: "ok" | "default"
  }) => void
}

//: On, like every other layer. This shipped switched off, on the reasoning
//: that a thousand hulls in one sea area would be the loudest thing on a world
//: map — which was true and beside the point. A layer nobody switches on is a
//: layer nobody knows exists: it looked broken rather than quiet, and the
//: first question asked of it was where the ships had gone. Seven rows are
//: right there to turn off, which is the reader's decision to make after they
//: have seen what there is.
const VESSELS_ON = Object.fromEntries(
  VESSEL_CATEGORIES.map((c) => [c.key, true]),
) as Record<VesselCategory, boolean>

export const usePresenceStore = create<PresenceState>((set) => ({
  aircraft: true,
  toggleAircraft: () => set((s) => ({ aircraft: !s.aircraft })),
  vessels: VESSELS_ON,
  toggleVessel: (key) =>
    set((s) => ({ vessels: { ...s.vessels, [key]: !s.vessels[key] } })),
  vesselSources: [],
  setVesselSources: (sources) => set(() => ({ vesselSources: sources })),
  vesselCounts: Object.fromEntries(VESSEL_CATEGORIES.map((c) => [c.key, 0])) as Record<
    VesselCategory,
    number
  >,
  setVesselCounts: (counts) => set(() => ({ vesselCounts: counts })),
  setAllVessels: (on) =>
    set(() => ({
      vessels: Object.fromEntries(VESSEL_CATEGORIES.map((c) => [c.key, on])) as Record<
        VesselCategory,
        boolean
      >,
    })),
  watchlist: true,
  toggleWatchlist: () => set((s) => ({ watchlist: !s.watchlist })),
  watchState: { watching: 0, drawn: 0, status: "ok" },
  setWatchState: (state) => set(() => ({ watchState: state })),
}))
