import { create } from "zustand"
import type { MarkerLocationContext } from "@/lib/locationProvenance"
import type { VisibleEvent } from "@/lib/queries"

/** One event, opened as the pop-up (#850).
 *
 *  Clicking a row in a screen-3 list used to call the map-selection opener,
 *  which replaced the entity — so the list the reader was reading was
 *  destroyed and no pop-up appeared. The pop-up could only hold a story or the
 *  world tile, so an event had nowhere else to go.
 *
 *  Screen 3 is built by clicking the map, and only by that. Anything opened
 *  from a list lands here instead.
 */
interface EventDetailState {
  event: VisibleEvent | null
  location?: MarkerLocationContext
  /** Bumped on every open, so reopening the same event still moves the deck. */
  opens: number
  openEventDetail: (event: VisibleEvent, location?: MarkerLocationContext) => void
  closeEventDetail: () => void
}

export const useEventDetailStore = create<EventDetailState>((set) => ({
  event: null,
  location: undefined,
  opens: 0,
  openEventDetail: (event, location) =>
    set((state) => ({ event, location, opens: state.opens + 1 })),
  closeEventDetail: () => set({ event: null, location: undefined }),
}))
