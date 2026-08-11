import { create } from "zustand"
import type { PresenceAircraft } from "@/lib/presence"

/** One live aircraft, opened as the pop-up beside the deck.
 *
 * Presence is still not evidence — nothing here is stored, and the card closes
 * itself the moment the layer stops being live. But a dot a reader cannot
 * question is worse than no dot: what is on the map should always be able to
 * say what it is and who said so.
 *
 * The aircraft is held by value rather than by hex, because the poll replaces
 * the whole list every thirty seconds and a lookup would blink the card out
 * whenever a plane briefly drops from the feed.
 */
interface AircraftDetailState {
  aircraft: PresenceAircraft | null
  /** When the poll that produced this aircraft last heard anything. */
  fetchedAt: string | null
  openAircraft: (aircraft: PresenceAircraft, fetchedAt: string | null) => void
  closeAircraft: () => void
}

export const useAircraftDetailStore = create<AircraftDetailState>((set) => ({
  aircraft: null,
  fetchedAt: null,
  openAircraft: (aircraft, fetchedAt) => set({ aircraft, fetchedAt }),
  closeAircraft: () => set({ aircraft: null, fetchedAt: null }),
}))
